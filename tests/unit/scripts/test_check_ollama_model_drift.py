"""Verifies the local model-drift contract in ADR 0010."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "ollama"
SPEC = importlib.util.spec_from_file_location(
    "check_ollama_model_drift", SCRIPTS_DIR / "check_ollama_model_drift.py"
)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
sys.modules["check_ollama_model_drift"] = CHECKER
SPEC.loader.exec_module(CHECKER)


def test_loads_shared_schema_v2_policy():
    policy = CHECKER.load_policy()

    assert policy["schema_version"] == 2
    assert {item["id"] for item in policy["functionalities"]} == {
        "coding",
        "cybersecurity",
        "general-purpose",
    }


def test_probe_rejects_unlisted_process_or_system_operations(monkeypatch):
    called = False

    def run(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("a forbidden probe reached subprocess")

    monkeypatch.setattr(CHECKER.subprocess, "run", run)

    forbidden = (
        "kill",
        "signal",
        "renice",
        "sudo",
        "sysctl -w",
        "purge",
        "launchctl",
        "osascript",
        "ollama create",
        "ollama rm",
        "ollama cp",
        "pull",
    )
    for operation in forbidden:
        with pytest.raises(ValueError, match="not allow-listed"):
            CHECKER.probe(operation)

    assert not called


def test_estimator_accepts_reference_anchor_and_rejects_17_gb_weights():
    policy = CHECKER.load_policy()["ollama"]["machine"]
    machine = {"ram_bytes": 16 * CHECKER.GIB}
    info = {
        "block_count": 48,
        "attention.head_count_kv": 2,
        "embedding_length": 256,
        "attention.head_count": 2,
    }
    budget = 12 * CHECKER.GIB

    anchor = CHECKER.estimate_model(
        weights_bytes=7 * CHECKER.GIB,
        model_info=info,
        context=32768,
        machine=machine,
        machine_policy=policy,
        gpu_budget_bytes=budget,
    )
    oversized = CHECKER.estimate_model(
        weights_bytes=17_000_000_000,
        model_info={},
        context=32768,
        machine=machine,
        machine_policy=policy,
        gpu_budget_bytes=budget,
    )

    assert anchor["verdict"] == "candidate"
    assert oversized["verdict"] == "reject"
    assert oversized["reason"] == "weights alone exceed usable memory"


def test_sliding_window_kv_cache_is_bounded_and_unknown_metadata_is_coarse():
    policy = CHECKER.load_policy()["ollama"]["machine"]
    machine = {"ram_bytes": 16 * CHECKER.GIB}
    common = {
        "weights_bytes": 2 * CHECKER.GIB,
        "context": 32768,
        "machine": machine,
        "machine_policy": policy,
        "gpu_budget_bytes": 12 * CHECKER.GIB,
    }
    full_attention = CHECKER.estimate_model(
        **common,
        model_info={
            "block_count": 32,
            "attention.head_count_kv": 4,
            "embedding_length": 1024,
            "attention.head_count": 8,
        },
    )
    sliding = CHECKER.estimate_model(
        **common,
        model_info={
            "block_count": 32,
            "attention.head_count_kv": 4,
            "embedding_length": 1024,
            "attention.head_count": 8,
            "attention.sliding_window": 4096,
        },
    )
    unknown = CHECKER.estimate_model(**common, model_info={})

    assert sliding["kv_cache_bytes"] < full_attention["kv_cache_bytes"]
    assert unknown["precision"] == "coarse"
    assert unknown["kv_cache_bytes"] == 0


def test_reclaimable_memory_includes_only_reclaimable_pages():
    pages = {
        "pages free": 10 * 4096,
        "pages inactive": 20 * 4096,
        "pages speculative": 3 * 4096,
        "pages purgeable": 4 * 4096,
        "pages active": 99 * 4096,
    }

    assert CHECKER.reclaimable_bytes(pages) == 37 * 4096


def test_swapped_memory_parser_converts_units():
    assert CHECKER.swap_used_bytes("total = 4.00G  used = 1.25G  free = 2.75G") == int(
        1.25 * CHECKER.GIB
    )


def test_saved_library_and_registry_fixtures_parse_official_models():
    parser = CHECKER.ModelLinks()
    parser.feed((FIXTURES_DIR / "library_search.html").read_text())
    tags = CHECKER.parse_registry_tags(
        json.loads((FIXTURES_DIR / "registry_tags.json").read_text()),
        "gemma4",
    )
    weight_size, _manifest = CHECKER.parse_registry_manifest(
        json.loads((FIXTURES_DIR / "manifest.json").read_text()),
        "gemma4",
        "12b",
    )

    assert parser.models == {"gemma4", "llama3"}
    assert tags == {"12b", "12b-cloud", "27b"}
    assert weight_size == 7 * CHECKER.GIB


def test_vm_stat_fixture_uses_reported_page_size():
    pages = CHECKER.parse_vm_stat((FIXTURES_DIR / "vm_stat.txt").read_text())

    assert CHECKER.reclaimable_bytes(pages) == 37 * 16384


def test_monitor_thresholds_and_collateral_exit_decisions():
    safety = CHECKER.load_policy()["ollama"]["safety"]

    assert CHECKER.threshold_trip("pressure", 1, safety) is None
    assert CHECKER.threshold_trip("pressure", 4, safety) == (
        "memory_pressure_hard",
        "hard",
    )
    assert CHECKER.threshold_trip("swap_growth_bytes", 1024 * CHECKER.MIB, safety) == (
        "swap_growth",
        "soft",
    )
    assert CHECKER.threshold_trip("timer_lag_ms", 5000, safety) == (
        "system_stall",
        "hard",
    )
    assert not CHECKER.collateral_exit_trip([], 4, 0, safety)
    assert CHECKER.collateral_exit_trip([123], 1, 256 * CHECKER.MIB, safety)


def test_configured_models_are_ordered_before_candidates_by_memory_estimate():
    estimates = {
        "candidate-large": {"estimate_bytes": 4},
        "configured-large": {"estimate_bytes": 3},
        "candidate-small": {"estimate_bytes": 1},
        "configured-small": {"estimate_bytes": 2},
    }

    ordered = CHECKER.order_models(
        ["configured-large", "configured-small", "configured-large"],
        ["candidate-large", "candidate-small"],
        estimates.__getitem__,
    )

    assert ordered == [
        "configured-small",
        "configured-large",
        "candidate-small",
        "candidate-large",
    ]


def test_configured_custom_variant_resolves_base_and_context_from_modelfile(monkeypatch):
    monkeypatch.setattr(
        CHECKER,
        "show_model",
        lambda *_args, **_kwargs: {"modelfile": "FROM library/gemma4:12b\nPARAMETER num_ctx 32768"},
    )

    assert CHECKER.configured_model_details("http://localhost:11434", "gemma4-12b-32k", 1) == {
        "base_model": "gemma4:12b",
        "baked_context": 32768,
        "resolution_verified": True,
    }


def test_retry_keeps_failures_in_place_without_reloading(monkeypatch):
    policy = CHECKER.load_policy()["ollama"]["fit"] | {
        "probe_attempts": 3,
        "cooldown_seconds": 0,
    }
    calls = {"count": 0}
    monitor = type("Monitor", (), {"trip": None})()
    monkeypatch.setattr(CHECKER.time, "sleep", lambda _seconds: None)

    def probe():
        calls["count"] += 1
        if calls["count"] < 3:
            raise RuntimeError("temporary probe failure")
        return {"response": "ok"}

    result = CHECKER.retry_in_place(probe, policy, monitor, require_response=True)

    assert result == {"response": "ok"}
    assert calls["count"] == 3


def test_configured_and_candidate_loads_use_their_required_ollama_endpoints(monkeypatch):
    requests = []

    def fake_http(_base, path, *, payload, **_kwargs):
        requests.append((path, payload))
        return {}

    monkeypatch.setattr(CHECKER, "http_json", fake_http)
    policy = CHECKER.load_policy()["ollama"]

    CHECKER.load_model(
        "http://localhost:11434",
        "configured:latest",
        32768,
        policy,
        [],
        candidate=False,
    )
    CHECKER.load_model(
        "http://localhost:11434",
        "candidate:latest",
        32768,
        policy,
        [],
        candidate=True,
    )

    assert [path for path, _payload in requests] == ["/api/generate", "/api/chat"]
    assert requests[0][1]["prompt"] == ""
    assert requests[1][1]["options"]["num_ctx"] == 32768


def test_journal_round_trip_preserves_started_state(tmp_path):
    path = tmp_path / "crash-journal.json"
    payload = {"started": {"model": "gemma4:12b", "estimate_bytes": 123}}

    CHECKER.write_journal(path, payload)

    assert CHECKER.read_journal(path) == payload


def test_uninstalled_candidate_is_never_pulled_without_allow_pull(monkeypatch, tmp_path):
    report = {
        "machine": {"context": 32768},
        "configured_models": [],
        "candidates": [{"name": "candidate:latest"}],
        "outcomes": {
            "candidate:latest": {
                "weights_bytes": CHECKER.GIB,
                "estimate_bytes": CHECKER.GIB,
            }
        },
    }
    monkeypatch.setattr(CHECKER, "journal_path", lambda: tmp_path / "journal.json")
    monkeypatch.setattr(CHECKER, "installed_models", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        CHECKER,
        "pull_model",
        lambda *_args, **_kwargs: pytest.fail("pull occurred without --allow-pull"),
    )

    verdicts, exit_code = CHECKER.live_verify(
        report,
        CHECKER.load_policy(),
        "http://localhost:11434",
        only=None,
        deep=False,
        allow_pull=False,
    )

    assert exit_code == 0
    assert verdicts[0]["verdict"] == "not_tested"


def test_compare_reports_fit_addition_and_configured_removal():
    plan = {
        "configured_models": [
            {
                "resolved_name": "configured:latest",
                "configured_name": "configured-custom",
                "verdict": "candidate",
                "resolution_verified": True,
            }
        ],
        "candidates": [{"name": "new:latest"}],
    }

    compared = CHECKER.compare_results(
        plan,
        [
            {"model": "new:latest", "verdict": "fits"},
            {"model": "configured:latest", "verdict": "does_not_fit"},
        ],
    )

    assert compared["candidates_to_add"][0]["model"] == "new:latest"
    assert compared["candidates_to_remove"][0]["model"] == "configured:latest"
    assert compared["unverified_candidates"] == []


def test_default_main_never_enters_fit_verification(monkeypatch, capsys, tmp_path):
    policy = CHECKER.load_policy()
    config = {
        "providers": {
            "ollama": {
                "settings": {"baseURL": "http://localhost:11434/v1"},
                "models": {"gemma4-12b-32k": {"limit": {"context": 32768}}},
            }
        }
    }
    monkeypatch.delenv("SDD4GH_ALLOW_MODEL_LOAD", raising=False)
    original_probe = CHECKER.probe
    probe_values = {
        "system_name": "Darwin",
        "arm64": "1",
        "model_load_opt_in": "0",
    }

    def fake_probe(operation):
        return probe_values[operation] if operation in probe_values else original_probe(operation)

    monkeypatch.setattr(CHECKER, "probe", fake_probe)
    monkeypatch.setattr(CHECKER, "load_policy", lambda: policy)
    monkeypatch.setattr(CHECKER, "load_config", lambda: config)
    monkeypatch.setattr(
        CHECKER,
        "http_json",
        lambda _url, path, **_kwargs: {"version": "test"} if path == "/api/version" else {},
    )
    monkeypatch.setattr(
        CHECKER,
        "plan_candidates",
        lambda *_args, **_kwargs: {
            "machine": {
                "chip": "Apple M4",
                "macos": "15",
                "gpu_budget_bytes": 8 * CHECKER.GIB,
                "gpu_budget_source": "test",
                "context": 32768,
            },
            "outcomes": {},
            "unverified_candidates": [],
        },
    )
    monkeypatch.setattr(CHECKER, "save_report", lambda _report: tmp_path / "report.json")
    monkeypatch.setattr(
        CHECKER,
        "live_verify",
        lambda *_args, **_kwargs: pytest.fail("default invocation attempted fit verification"),
    )

    assert CHECKER.main([]) == 2
    assert "No model was loaded" in capsys.readouterr().out
