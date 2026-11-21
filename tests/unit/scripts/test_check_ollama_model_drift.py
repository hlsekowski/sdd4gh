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
    assert policy["ollama"]["safety"]["disk_free_percent"] == {"warn": 20, "stop": 15}
    assert {item["id"] for item in policy["functionalities"]} == {
        "coding",
        "cybersecurity",
        "general-purpose",
    }


def test_model_store_path_prefers_policy_then_environment_then_default(monkeypatch, tmp_path):
    policy_path = tmp_path / "policy-models"
    environment_path = tmp_path / "environment-models"
    ollama = {"model_store_path": str(policy_path)}
    monkeypatch.setenv("OLLAMA_MODELS", str(environment_path))

    assert CHECKER.resolve_model_store_path(ollama) == (policy_path, "policy")

    assert CHECKER.resolve_model_store_path({"model_store_path": None}) == (
        environment_path,
        "OLLAMA_MODELS",
    )

    monkeypatch.delenv("OLLAMA_MODELS")
    monkeypatch.setattr(CHECKER.Path, "home", lambda: tmp_path)
    assert CHECKER.resolve_model_store_path({"model_store_path": None}) == (
        tmp_path / ".ollama" / "models",
        "default",
    )


def test_disk_space_probe_uses_available_blocks_and_policy_thresholds(monkeypatch, tmp_path):
    monkeypatch.setattr(
        CHECKER.os,
        "statvfs",
        lambda _path: type(
            "Statvfs",
            (),
            {"f_bavail": 20, "f_frsize": 1, "f_blocks": 100},
        )(),
    )
    safety = CHECKER.load_policy()["ollama"]["safety"]
    status = CHECKER.measure_disk_space(
        {"model_store_path": str(tmp_path)},
        safety,
    )

    assert status["available_bytes"] == 20
    assert status["total_bytes"] == 100
    assert status["available_percent"] == 20
    assert status["action"] == "warn"
    assert CHECKER.disk_space_action(15, safety) == "stop"
    assert CHECKER.disk_space_action(20.1, safety) == "continue"


def test_disk_space_warning_continues_but_measurement_failure_stops(capsys, monkeypatch):
    policy = CHECKER.load_policy()["ollama"]
    disk_checks = []
    monkeypatch.setattr(
        CHECKER,
        "measure_disk_space",
        lambda *_args, **_kwargs: {
            "path": "/models",
            "available_percent": 20,
            "action": "warn",
        },
    )

    assert CHECKER.check_disk_space(policy, disk_checks, "model load") is None
    assert disk_checks[0]["action"] == "warn"
    assert "WARNING:" in capsys.readouterr().out

    def fail_measurement(*_args, **_kwargs):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(CHECKER, "measure_disk_space", fail_measurement)
    reason = CHECKER.check_disk_space(policy, disk_checks, "model load")

    assert reason == "disk space could not be verified before model load: unavailable"
    assert disk_checks[1]["action"] == "stop"
    assert "DISK SPACE SAFETY STOP" in capsys.readouterr().out


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
    tags = CHECKER.ModelTags("gemma4")
    tags.feed((FIXTURES_DIR / "library_tags.html").read_text())
    weight_size, _manifest = CHECKER.parse_registry_manifest(
        json.loads((FIXTURES_DIR / "manifest.json").read_text()),
        "gemma4",
        "12b",
    )

    assert parser.models == {"gemma4", "llama3"}
    assert tags.tags == {"12b", "12b-cloud", "27b"}
    assert weight_size == 9 * CHECKER.GIB


def test_library_tags_uses_official_tags_page_and_rejects_truncation(monkeypatch):
    requested = []
    html = (FIXTURES_DIR / "library_tags.html").read_text()

    def fetch(url, *, timeout, max_redirects):
        requested.append((url, timeout, max_redirects))
        return html

    monkeypatch.setattr(CHECKER, "http_text", fetch)

    tags = CHECKER.library_tags(
        "gemma4",
        timeout=10,
        max_redirects=3,
        max_tags=10,
    )

    assert tags == {"12b", "12b-cloud", "27b"}
    assert requested == [("https://ollama.com/library/gemma4/tags", 10, 3)]

    with pytest.raises(CHECKER.SkipCheck, match="exceeds the policy tag limit"):
        CHECKER.library_tags(
            "gemma4",
            timeout=10,
            max_redirects=3,
            max_tags=2,
        )


def test_model_discovery_uses_library_tags_and_registry_weight_manifests(
    monkeypatch,
):
    policy = CHECKER.load_policy()
    tag_page = (FIXTURES_DIR / "library_tags.html").read_text()
    manifest = json.loads((FIXTURES_DIR / "manifest.json").read_text())
    manifest_requests = []

    def fetch(url, *, timeout, max_redirects):
        assert timeout == policy["ollama"]["discovery"]["timeout_seconds"]
        assert max_redirects == policy["ollama"]["discovery"]["max_redirects"]
        if "/search?" in url:
            return '<a href="/library/gemma4">gemma4</a>'
        if url == "https://ollama.com/library/gemma4/tags":
            return tag_page
        return "<html></html>"

    def get_manifest(_registry_url, model, tag, _timeout):
        manifest_requests.append((model, tag))
        return CHECKER.GIB, manifest

    monkeypatch.setattr(CHECKER, "http_text", fetch)
    monkeypatch.setattr(CHECKER, "registry_manifest", get_manifest)
    monkeypatch.setattr(CHECKER, "registry_config", lambda *_args, **_kwargs: {})

    candidates = CHECKER.discover_models(policy["ollama"], policy["functionalities"])

    assert set(candidates) == {"gemma4:12b", "gemma4:27b"}
    assert manifest_requests == [("gemma4", "12b"), ("gemma4", "27b")]


def test_model_discovery_skips_cloud_and_mlx_tags_before_registry_lookup(monkeypatch):
    policy = CHECKER.load_policy()
    gemma_tags = (FIXTURES_DIR / "library_tags.html").read_text()
    search_html = (
        '<a href="/library/deepseek-v4.1-flash">deepseek-v4.1-flash</a>'
        '<a href="/library/flint">flint</a>'
        '<a href="/library/gemma4">gemma4</a>'
    )
    manifest = json.loads((FIXTURES_DIR / "manifest.json").read_text())
    manifest_requests = []

    def fetch(url, *, timeout, max_redirects):
        if "/search?" in url:
            return search_html if "page=1" in url else "<html></html>"
        if url == "https://ollama.com/library/deepseek-v4.1-flash/tags":
            return '<a href="/library/deepseek-v4.1-flash:cloud">cloud</a>'
        if url == "https://ollama.com/library/flint/tags":
            return '<a href="/library/flint:40b-a2b-mlx-bf16">40b-a2b-mlx-bf16</a>'
        if url == "https://ollama.com/library/gemma4/tags":
            return gemma_tags
        raise AssertionError(f"unexpected catalog URL: {url}")

    def get_manifest(_registry_url, model, tag, _timeout):
        manifest_requests.append((model, tag))
        if tag == "cloud" or "mlx" in tag.split("-"):
            raise AssertionError("excluded tags must not request registry manifests")
        return CHECKER.GIB, manifest

    monkeypatch.setattr(CHECKER, "http_text", fetch)
    monkeypatch.setattr(CHECKER, "registry_manifest", get_manifest)
    monkeypatch.setattr(CHECKER, "registry_config", lambda *_args, **_kwargs: {})

    candidates = CHECKER.discover_models(policy["ollama"], policy["functionalities"])

    assert set(candidates) == {"gemma4:12b", "gemma4:27b"}
    assert manifest_requests == [("gemma4", "12b"), ("gemma4", "27b")]


def test_catalog_get_follows_same_host_303_redirect(monkeypatch):
    class Response:
        def __init__(self, status, body=b"", location=None):
            self.status = status
            self.body = body
            self.location = location

        def getheader(self, name):
            return self.location if name == "Location" else None

        def read(self):
            return self.body

    responses = [
        Response(303, location="/search?c=tools"),
        Response(200, b"<html>catalog</html>"),
    ]
    requests = []

    class Connection:
        def __init__(self, host, port, timeout):
            assert host == "ollama.com"
            assert port is None
            assert timeout == 10

        def request(self, method, path):
            requests.append((method, path))

        def getresponse(self):
            return responses.pop(0)

        def close(self):
            pass

    monkeypatch.setattr(CHECKER, "HTTPSConnection", Connection)

    result = CHECKER.http_text(
        "https://ollama.com/search?c=tools&page=1",
        timeout=10,
        max_redirects=3,
    )

    assert result == "<html>catalog</html>"
    assert requests == [
        ("GET", "/search?c=tools&page=1"),
        ("GET", "/search?c=tools"),
    ]


def test_catalog_get_rejects_cross_host_redirect(monkeypatch):
    class Response:
        status = 303

        def getheader(self, _name):
            return "https://example.com/search"

    connections = []

    class Connection:
        def __init__(self, host, _port, **_kwargs):
            connections.append(host)

        def request(self, _method, _path):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(CHECKER, "HTTPSConnection", Connection)

    with pytest.raises(RuntimeError, match="redirect left the official Ollama host"):
        CHECKER.http_text(
            "https://ollama.com/search?c=tools&page=1",
            timeout=10,
            max_redirects=3,
        )

    assert connections == ["ollama.com"]


def test_discovery_passes_policy_redirect_limit(monkeypatch):
    policy = CHECKER.load_policy()
    limits = []

    def fetch(_url, *, timeout, max_redirects):
        assert timeout == policy["ollama"]["discovery"]["timeout_seconds"]
        limits.append(max_redirects)
        return "<html></html>"

    monkeypatch.setattr(CHECKER, "http_text", fetch)

    with pytest.raises(CHECKER.SkipCheck, match="returned no models"):
        CHECKER.discover_models(policy["ollama"], policy["functionalities"])

    assert limits == [policy["ollama"]["discovery"]["max_redirects"]]


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


def test_disk_stop_preserves_completed_models_and_skips_later_loads(monkeypatch, tmp_path):
    report = {
        "machine": {"context": 4096},
        "configured_models": [
            {
                "resolved_name": "configured-small",
                "configured_name": "configured-small",
                "verdict": "candidate",
                "resolution_verified": True,
                "estimate_bytes": 1,
                "usable_bytes": 100,
            },
            {
                "resolved_name": "configured-large",
                "configured_name": "configured-large",
                "verdict": "candidate",
                "resolution_verified": True,
                "estimate_bytes": 2,
                "usable_bytes": 100,
            },
        ],
        "candidates": [],
        "outcomes": {},
    }
    disk_statuses = iter(
        [
            {"path": "/models", "available_percent": 30, "action": "continue"},
            {"path": "/models", "available_percent": 15, "action": "stop"},
        ]
    )
    loaded_models = [
        {
            "name": name,
            "size": 100,
            "size_vram": 100,
            "context_length": 4096,
        }
        for name in ("configured-small", "configured-large")
    ]
    loaded = []

    class Monitor:
        def __init__(self, *, model_loaded, **_kwargs):
            self.trip = None
            self.model_loaded = model_loaded

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(CHECKER, "journal_path", lambda: tmp_path / "journal.json")
    monkeypatch.setattr(CHECKER, "write_journal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        CHECKER,
        "installed_models",
        lambda *_args, **_kwargs: {"configured-small": {}, "configured-large": {}},
    )
    monkeypatch.setattr(
        CHECKER, "measure_disk_space", lambda *_args, **_kwargs: next(disk_statuses)
    )
    monkeypatch.setattr(
        CHECKER,
        "normal_preflight",
        lambda *_args, **_kwargs: ({"baseline_swap_bytes": 0}, {}),
    )
    monkeypatch.setattr(CHECKER, "admission_check", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(CHECKER, "FitMonitor", Monitor)
    monkeypatch.setattr(
        CHECKER,
        "load_model",
        lambda _base, model, *_args, **_kwargs: loaded.append(model),
    )
    monkeypatch.setattr(CHECKER, "unload_own_model", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(CHECKER, "functionality_prompts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(CHECKER, "retry_in_place", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(CHECKER, "timeline_summary", lambda *_args, **_kwargs: {"warnings": []})
    monkeypatch.setattr(CHECKER, "monitor_until_baseline", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        CHECKER,
        "http_json",
        lambda *_args, **_kwargs: {"models": loaded_models},
    )

    verdicts, exit_code = CHECKER.live_verify(
        report,
        CHECKER.load_policy(),
        "http://localhost:11434",
        only=None,
        deep=False,
        allow_pull=False,
    )

    assert exit_code == 3
    assert loaded == ["configured-small"]
    assert verdicts[0]["verdict"] == "fits_degraded"
    assert verdicts[1]["verdict"] == "not_tested"
    assert verdicts[1]["disk_space_checks"][0]["available_percent"] == 15


def test_disk_stop_prevents_model_pull(monkeypatch, tmp_path):
    report = {
        "machine": {"context": 4096},
        "configured_models": [],
        "candidates": [{"name": "candidate:latest"}],
        "outcomes": {"candidate:latest": {"weights_bytes": CHECKER.GIB}},
    }
    monkeypatch.setattr(CHECKER, "journal_path", lambda: tmp_path / "journal.json")
    monkeypatch.setattr(CHECKER, "installed_models", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        CHECKER,
        "measure_disk_space",
        lambda *_args, **_kwargs: {
            "path": "/models",
            "available_percent": 15,
            "action": "stop",
        },
    )
    monkeypatch.setattr(
        CHECKER,
        "pull_model",
        lambda *_args, **_kwargs: pytest.fail("pull occurred below the disk stop threshold"),
    )

    verdicts, exit_code = CHECKER.live_verify(
        report,
        CHECKER.load_policy(),
        "http://localhost:11434",
        only=None,
        deep=False,
        allow_pull=True,
    )

    assert exit_code == 3
    assert verdicts[0]["verdict"] == "not_tested"
    assert verdicts[0]["disk_space_checks"][0]["stage"] == "model pull"


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


def test_safety_stop_prints_partial_results_if_report_cannot_be_saved(monkeypatch, capsys):
    policy = CHECKER.load_policy()
    config = {
        "providers": {
            "ollama": {
                "settings": {"baseURL": "http://localhost:11434/v1"},
                "models": {},
            }
        }
    }
    plan = {
        "machine": {
            "chip": "Apple M4",
            "macos": "15",
            "gpu_budget_bytes": 8 * CHECKER.GIB,
            "gpu_budget_source": "test",
            "context": 4096,
        },
        "outcomes": {},
        "configured_models": [],
        "candidates": [],
        "unverified_candidates": [],
    }
    verdicts = [
        {"model": "completed", "verdict": "fits_degraded"},
        {"model": "unrun", "verdict": "not_tested"},
    ]
    monkeypatch.setattr(CHECKER, "load_policy", lambda: policy)
    monkeypatch.setattr(CHECKER, "load_config", lambda: config)
    monkeypatch.setattr(
        CHECKER,
        "probe",
        lambda operation, **_kwargs: {
            "system_name": "Darwin",
            "arm64": "1",
            "termination_handlers": "",
        }[operation],
    )
    monkeypatch.setattr(
        CHECKER,
        "http_json",
        lambda *_args, **_kwargs: {"version": "test"},
    )
    monkeypatch.setattr(CHECKER, "plan_candidates", lambda *_args, **_kwargs: plan)
    monkeypatch.setattr(CHECKER, "live_verify", lambda *_args, **_kwargs: (verdicts, 3))
    monkeypatch.setattr(CHECKER.time, "sleep", lambda _seconds: None)

    def fail_saving(_report):
        raise RuntimeError("disk is full")

    monkeypatch.setattr(CHECKER, "save_report", fail_saving)

    assert CHECKER.main(["--verify-fit"]) == 3
    captured = capsys.readouterr()
    assert "Partial fit results:" in captured.out
    assert '"model": "completed"' in captured.out
    assert "Evidence report could not be saved: disk is full" in captured.err
