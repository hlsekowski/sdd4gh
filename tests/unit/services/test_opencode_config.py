"""Unit tests for the native OpenCode V2 project config.

Verifies docs/adr/0010-opencode-coding-agent.md.
"""

from __future__ import annotations

import ipaddress
import json
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO_ROOT / "opencode.json"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

CLOUD_API_KEY_NAMES = {
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "AZURE_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "COHERE_API_KEY",
    "MISTRAL_API_KEY",
    "TOGETHER_API_KEY",
    "PERPLEXITY_API_KEY",
    "GROQ_API_KEY",
    "DEEPINFRA_API_KEY",
    "FIREWORKS_API_KEY",
    "BASETEN_API_KEY",
    "CEREBRAS_API_KEY",
}

REQUIRED_AGENTS = ("ask", "sentinel", "spec", "implement", "review")
REQUIRED_COMMANDS = ("work", "spec", "review")
OPTIONAL_NVIDIA_MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"


def _load_config() -> dict:
    with CONFIG_PATH.open() as config_file:
        return json.load(config_file)


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _validate_config(config: dict) -> None:
    assert isinstance(config, dict)
    assert config.get("$schema") == "https://opencode.ai/config.json"
    model = config.get("model", "")
    assert isinstance(model, str) and model
    provider_id, separator, model_id = model.partition("/")
    assert separator and model_id
    providers = config.get("providers", {})
    assert provider_id in providers, f"default provider {provider_id!r} is not configured"
    assert model_id in providers[provider_id].get("models", {}), (
        f"default model {model_id!r} is not configured"
    )

    ollama_url = providers.get("ollama", {}).get("settings", {}).get("baseURL")
    if ollama_url:
        host = urlsplit(ollama_url).hostname
        assert host is not None and _is_loopback_host(host), (
            f"ollama baseURL is not a loopback address: {ollama_url}"
        )


def _agent_rules(config: dict, agent: str) -> list[dict]:
    return config["agents"][agent]["permissions"]


def _rules_for(config: dict, agent: str, action: str) -> list[dict]:
    return [rule for rule in _agent_rules(config, agent) if rule["action"] == action]


class TestOpencodeConfigParses:
    def test_config_exists_and_is_valid_json(self):
        config = _load_config()
        assert isinstance(config, dict)
        _validate_config(config)

    def test_uses_native_v2_top_level_keys(self):
        config = _load_config()
        for key in ("provider", "agent", "command", "permission", "tools"):
            assert key not in config
        assert {"providers", "agents", "commands"} <= config.keys()

    def test_config_has_required_agents_and_commands(self):
        config = _load_config()
        assert set(REQUIRED_AGENTS) <= config["agents"].keys()
        assert set(REQUIRED_COMMANDS) <= config["commands"].keys()
        assert config["default_agent"] == "sentinel"

    def test_default_and_agent_models_resolve_to_configured_models(self):
        config = _load_config()
        for model in (
            config["model"],
            *(agent["model"] for agent in config["agents"].values() if "model" in agent),
        ):
            provider_id, model_id = model.split("/", 1)
            assert model_id in config["providers"][provider_id]["models"]
        assert config["model"] == "ollama/gemma4-12b-32k"
        assert all("model" not in agent for agent in config["agents"].values())

    def test_agents_use_native_system_and_permission_fields(self):
        config = _load_config()
        actions = set()
        for agent in config["agents"].values():
            assert isinstance(agent.get("system"), str) and agent["system"]
            for legacy_field in ("prompt", "permission", "tools", "temperature", "maxSteps"):
                assert legacy_field not in agent
            assert isinstance(agent["permissions"], list)
            actions.update(rule["action"] for rule in agent["permissions"])
            assert agent["permissions"][0] == {
                "action": "*",
                "resource": "*",
                "effect": "deny",
            }
        assert not actions.intersection({"bash", "task", "write", "patch"})
        assert "maxSteps" not in json.dumps(config)

    def test_commands_use_native_subagent_field(self):
        config = _load_config()
        for command in config["commands"].values():
            assert "subtask" not in command
        assert config["commands"]["spec"]["subagent"] is True
        assert config["commands"]["review"]["subagent"] is True


class TestOpencodeConfigPermissions:
    def test_ask_agent_denies_all_tools(self):
        assert _agent_rules(_load_config(), "ask") == [
            {"action": "*", "resource": "*", "effect": "deny"}
        ]

    def test_sentinel_only_delegates_to_workflow_agents(self):
        config = _load_config()
        assert _rules_for(config, "sentinel", "subagent") == [
            {"action": "subagent", "resource": "*", "effect": "deny"},
            {"action": "subagent", "resource": "spec", "effect": "allow"},
            {"action": "subagent", "resource": "implement", "effect": "allow"},
            {"action": "subagent", "resource": "review", "effect": "allow"},
        ]

    def test_sentinel_requires_approval_to_edit_task_status_files(self):
        config = _load_config()
        assert _rules_for(config, "sentinel", "edit") == [
            {
                "action": "edit",
                "resource": "specs/**/tasks.md",
                "effect": "ask",
            }
        ]

    def test_spec_edits_require_approval(self):
        config = _load_config()
        assert _rules_for(config, "spec", "edit") == [
            {"action": "edit", "resource": "specs/**", "effect": "ask"}
        ]

    def test_implement_edits_only_source_and_tests(self):
        config = _load_config()
        assert _rules_for(config, "implement", "edit") == [
            {"action": "edit", "resource": "src/**", "effect": "allow"},
            {"action": "edit", "resource": "tests/**", "effect": "allow"},
        ]
        assert not any(
            rule["effect"] == "allow" for rule in _rules_for(config, "implement", "subagent")
        )
        assert not any(
            rule["effect"] == "allow"
            and (rule["resource"].startswith("git push") or rule["resource"].startswith("gh "))
            for rule in _rules_for(config, "implement", "shell")
        )

    def test_review_has_no_mutation_or_delegation_permissions(self):
        config = _load_config()
        assert _rules_for(config, "review", "edit") == [
            {"action": "edit", "resource": "*", "effect": "deny"}
        ]
        assert _rules_for(config, "review", "subagent") == [
            {"action": "subagent", "resource": "*", "effect": "deny"}
        ]
        shell_allows = [
            rule["resource"]
            for rule in _rules_for(config, "review", "shell")
            if rule["effect"] == "allow"
        ]
        assert shell_allows
        assert all(
            not command.startswith(("git push", "git add", "git commit", "gh "))
            for command in shell_allows
        )

    def test_sentinel_mutations_require_approval_and_force_push_is_denied(self):
        config = _load_config()
        rules = _rules_for(config, "sentinel", "shell")
        for command in ("git add *", "git commit *", "git push *"):
            assert {"action": "shell", "resource": command, "effect": "ask"} in rules
        deny_force_push = [
            rule
            for rule in rules
            if rule["effect"] == "deny" and rule["resource"].startswith("git push")
        ]
        assert deny_force_push
        assert max(rules.index(rule) for rule in deny_force_push) > rules.index(
            {"action": "shell", "resource": "git push *", "effect": "ask"}
        )
        assert not any(
            rule["effect"] == "allow"
            and rule["resource"].startswith(("git add", "git commit", "git push"))
            for rule in rules
        )

    def test_every_agent_denies_external_paths_and_network_tools(self):
        config = _load_config()
        for agent in REQUIRED_AGENTS:
            rules = _agent_rules(config, agent)
            assert rules[0] == {
                "action": "*",
                "resource": "*",
                "effect": "deny",
            }
            for action in ("external_directory", "webfetch", "websearch"):
                assert not any(
                    rule["action"] == action and rule["effect"] == "allow" for rule in rules
                )


class TestOpencodeConfigProviders:
    def test_ollama_provider_uses_native_shape_and_loopback(self):
        config = _load_config()
        ollama = config["providers"]["ollama"]
        assert ollama["package"] == "aisdk:@ai-sdk/openai-compatible"
        assert ollama["name"] == "Ollama (local)"
        assert ollama["settings"]["baseURL"] == "http://localhost:11434/v1"
        assert "npm" not in ollama
        assert "options" not in ollama
        assert {"gemma4-12b-32k"} <= ollama["models"].keys()
        assert ollama["models"]["gemma4-12b-32k"]["limit"] == {
            "context": 32768,
            "output": 8192,
        }
        for model in ollama["models"].values():
            assert model["capabilities"]["tools"] is True
            for legacy_field in ("tool_call", "attachment", "modalities", "temperature"):
                assert legacy_field not in model

    def test_nvidia_provider_is_optional_and_has_only_owner_verified_model(self):
        config = _load_config()
        nvidia = config["providers"]["nvidia"]
        assert nvidia["package"] == "aisdk:@ai-sdk/openai-compatible"
        assert nvidia["settings"]["baseURL"] == "https://integrate.api.nvidia.com/v1"
        assert nvidia["settings"]["apiKey"] == "{file:~/.secrets/nvidia_key}"
        assert set(nvidia["models"]) == {OPTIONAL_NVIDIA_MODEL}
        assert all("model" not in agent for agent in config["agents"].values())

    def test_no_cloud_api_key_name_is_committed(self):
        config_text = json.dumps(_load_config())
        for key in CLOUD_API_KEY_NAMES:
            assert key.lower() not in config_text.lower()

    def test_no_new_python_runtime_dependencies(self):
        with PYPROJECT_PATH.open("rb") as pyproject_file:
            data = tomllib.load(pyproject_file)
        assert data.get("project", {}).get("dependencies", []) == []


class TestOpencodeConfigBadConfigFails:
    def test_non_loopback_ollama_base_url_fails(self):
        config = _load_config()
        bad_config = json.loads(json.dumps(config))
        bad_config["providers"]["ollama"]["settings"]["baseURL"] = "https://api.example.com/v1"
        with pytest.raises(AssertionError, match="loopback"):
            _validate_config(bad_config)

    def test_missing_default_model_provider_fails(self):
        config = _load_config()
        bad_config = json.loads(json.dumps(config))
        bad_config["model"] = "cloud/unknown-model"
        with pytest.raises(AssertionError, match="provider"):
            _validate_config(bad_config)

    def test_missing_default_model_id_fails(self):
        config = _load_config()
        bad_config = json.loads(json.dumps(config))
        bad_config["model"] = "ollama/not-configured"
        with pytest.raises(AssertionError, match="model"):
            _validate_config(bad_config)
