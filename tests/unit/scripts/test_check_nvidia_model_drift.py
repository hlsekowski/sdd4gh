"""Verifies ADR 0010's NVIDIA model-drift check contract."""

import importlib.util
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"


def load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_nvidia_model_drift", SCRIPTS_DIR / "check_nvidia_model_drift.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_nvidia_model_drift"] = module
    spec.loader.exec_module(module)
    return module


def test_load_policy_requires_supported_schema(tmp_path):
    checker = load_checker()
    policy_path = tmp_path / "models_policy.json"
    policy_path.write_text(json.dumps({"schema_version": 2, "nvidia": {}, "functionalities": []}))
    assert checker.load_policy(policy_path)["schema_version"] == 2

    policy_path.write_text(json.dumps({"schema_version": 1, "nvidia": {}, "functionalities": []}))
    try:
        checker.load_policy(policy_path)
    except RuntimeError as error:
        assert "unsupported" in str(error)
    else:
        raise AssertionError("unsupported policy schema accepted")


def test_configured_nvidia_models_are_normalized():
    checker = load_checker()
    config = {
        "providers": {
            "nvidia": {
                "models": {
                    "nvidia/nemotron-3.5": {"name": "Nemotron"},
                    "meta/llama": {"name": "Llama"},
                }
            },
            "ollama": {"models": {"gemma": {}}},
        }
    }
    assert checker.configured_nvidia_models(config) == {
        "nvidia/nemotron-3.5",
        "meta/llama",
    }


def test_policy_matching_supports_includes_and_exclusions():
    checker = load_checker()
    functionality = {"name_patterns": ["*code*", "*nemotron*", "!*-embedding*", "!*vision*"]}
    assert checker.matches_functionality("nvidia/nemotron-code", functionality)
    assert not checker.matches_functionality("nvidia/nemotron-embedding", functionality)
    assert not checker.matches_functionality("nvidia/vision-model", functionality)


def test_catalog_discovery_parses_model_ids():
    checker = load_checker()
    payload = {
        "data": [
            {"id": "nvidia/nemotron-code"},
            {"id": "meta/llama-3"},
            {"name": "missing-id"},
        ]
    }
    assert checker.catalog_model_ids(payload) == {
        "nvidia/nemotron-code",
        "meta/llama-3",
    }


def test_retry_uses_attempt_limit_and_stops_after_success(monkeypatch):
    checker = load_checker()
    attempts = {"count": 0}

    def smoke():
        attempts["count"] += 1
        return attempts["count"] >= 3

    monkeypatch.setattr(checker.time, "sleep", lambda _seconds: None)
    assert checker.smoke_with_retries("nvidia/test", smoke, attempts=5, delay_seconds=0)
    assert attempts["count"] == 3


def test_compare_candidates_never_mutates_input():
    checker = load_checker()
    configured = {"nvidia/kept", "nvidia/removed"}
    discovered = {"nvidia/kept", "nvidia/added"}
    smoke_passed = {"nvidia/kept", "nvidia/added"}

    to_add, to_remove = checker.compare_candidates(configured, discovered, smoke_passed)

    assert to_add == {"nvidia/added"}
    assert to_remove == {"nvidia/removed"}
    assert configured == {"nvidia/kept", "nvidia/removed"}


def test_structured_report_contains_both_candidate_sections(capsys):
    checker = load_checker()
    details = {
        "nvidia/added": {
            "name": "Added model",
            "context": 131072,
            "output": 4096,
        }
    }
    report = checker.format_report({"nvidia/added"}, {"nvidia/removed"}, details)

    assert "CANDIDATES_TO_ADD" in report
    assert "nvidia/added" in report
    assert "CANDIDATES_TO_REMOVE" in report
    assert "nvidia/removed" in report
    assert "Added model" in report
