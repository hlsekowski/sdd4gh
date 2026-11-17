"""Unit tests for the OpenCode project config (ADR 0010).

Verifies that opencode.json configures the OpenCode v2 schema with
providers, agents, and commands. No network, no model calls.
"""

from __future__ import annotations

import ipaddress
import json
import os
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO_ROOT / "opencode.json"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

# Known cloud API key environment variable names that must never appear as
# literal values in the config. File references like {file:...} are allowed.
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


def _load_config() -> dict:
    """Load opencode.json and substitute {env:VAR} placeholders like OpenCode v2.

    OpenCode v2 replaces {env:VARIABLE_NAME} with the environment variable's
    value, or an empty string if unset. {file:...} references are left as-is
    since they cannot be resolved without filesystem access.
    """
    import re as _re

    with open(CONFIG_PATH) as f:
        raw = f.read()

    def _sub(match: _re.Match[str]) -> str:
        var = match.group(1)
        return os.environ.get(var, "")

    resolved = _re.sub(r"\{env:([A-Za-z_][A-Za-z0-9_]*)\}", _sub, raw)
    return json.loads(resolved)


def _is_loopback_host(host: str) -> bool:
    """True when host is a loopback address.

    Uses strict stdlib validation: urllib.parse.urlsplit for URL parsing and
    ipaddress.ip_address for IP address classification. 0.0.0.0 is
    deliberately excluded: it is the unspecified/wildcard bind address, not
    a loopback destination.
    """
    host = host.lower().strip()
    if host == "localhost":
        return True
    if host.startswith("[") and host.endswith("]"):
        inner = host[1:-1]
        try:
            addr = ipaddress.ip_address(inner)
        except ValueError:
            return False
        return addr.is_loopback
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_loopback


def _extract_providers(config: dict) -> dict:
    return config.get("provider", {})


def _extract_agents(config: dict) -> dict:
    return config.get("agent", {})


def _extract_commands(config: dict) -> dict:
    return config.get("command", {})


def _extract_urls(config: dict) -> list[str]:
    urls: list[str] = []
    for provider in _extract_providers(config).values():
        settings = provider.get("options", {}) or provider.get("settings", {})
        base_url = settings.get("baseURL")
        if base_url:
            urls.append(base_url)
    return urls


def _validate_config(config: dict) -> None:
    """Shared validation for the v2 config. Raises AssertionError on failure."""
    assert isinstance(config, dict)
    assert "$schema" in config
    model = config.get("model", "")
    assert isinstance(model, str) and model, "default model must be set"
    provider_name = model.split("/", 1)[0] if "/" in model else ""
    providers = _extract_providers(config)
    assert provider_name in providers, f"default model provider {provider_name!r} not configured"
    # No hardcoded cloud API key values (file references are allowed).
    config_text = json.dumps(config)
    for key in CLOUD_API_KEY_NAMES:
        assert key.lower() not in config_text.lower(), f"cloud API key name found in config: {key}"

    # Ollama baseURL must be a loopback address.
    ollama = providers.get("ollama", {})
    ollama_url = (ollama.get("options") or {}).get("baseURL")
    if ollama_url:
        parsed = urlsplit(ollama_url)
        host = parsed.hostname
        assert host is not None, f"ollama URL has no host: {ollama_url}"
        assert _is_loopback_host(host), f"ollama baseURL is not a loopback address: {ollama_url}"


class TestOpencodeConfigParses:
    def test_config_exists_and_is_valid_json(self):
        config = _load_config()
        assert isinstance(config, dict)
        assert "$schema" in config

    def test_config_has_model(self):
        config = _load_config()
        assert config.get("model") == "ollama/qwen3-8b-16k"

    def test_config_has_providers(self):
        config = _load_config()
        providers = _extract_providers(config)
        assert isinstance(providers, dict)
        assert "ollama" in providers
        assert "nvidia" in providers

    def test_config_has_agents(self):
        config = _load_config()
        agents = _extract_agents(config)
        assert isinstance(agents, dict)
        for name in REQUIRED_AGENTS:
            assert name in agents, f"missing agent: {name}"

    def test_config_has_commands(self):
        config = _load_config()
        commands = _extract_commands(config)
        assert isinstance(commands, dict)
        for name in REQUIRED_COMMANDS:
            assert name in commands, f"missing command: {name}"

    def test_default_model_resolves_to_configured_provider(self):
        config = _load_config()
        model = config["model"]
        provider_name = model.split("/", 1)[0]
        assert provider_name in _extract_providers(config)


class TestOpencodeConfigOllamaProvider:
    def test_ollama_provider_structure(self):
        config = _load_config()
        ollama = config["provider"]["ollama"]
        assert ollama["npm"] == "@ai-sdk/openai-compatible"
        assert ollama["name"] == "Ollama (local)"
        assert ollama["options"]["baseURL"] == "http://localhost:11434/v1"
        assert "qwen3-8b-16k" in ollama["models"]

    def test_ollama_base_url_is_loopback(self):
        config = _load_config()
        url = config["provider"]["ollama"]["options"]["baseURL"]
        parsed = urlsplit(url)
        host = parsed.hostname
        assert host is not None, f"URL has no host: {url}"
        assert _is_loopback_host(host), f"ollama baseURL is not a loopback address: {url}"


class TestOpencodeConfigNvidiaProvider:
    def test_nvidia_provider_structure(self):
        config = _load_config()
        nvidia = config["provider"]["nvidia"]
        assert nvidia["npm"] == "@ai-sdk/openai-compatible"
        assert nvidia["name"] == "NVIDIA NIM"
        assert nvidia["options"]["baseURL"] == "https://integrate.api.nvidia.com/v1"
        assert "apiKey" in nvidia["options"]
        assert "{file:" in nvidia["options"]["apiKey"], (
            "nvidia apiKey must be a file reference, not a literal value"
        )
        for model_id in (
            "nvidia/nemotron-3.5-super-vl-120b-a12b",
            "nvidia/nemotron-3-ultra-550b-a55b",
            "minimaxai/minimax-m3.1-flash",
            "stepfun-ai/step-5-preview",
        ):
            assert model_id in nvidia["models"], f"missing model: {model_id}"


class TestOpencodeConfigNoHardcodedKeys:
    def test_no_cloud_api_key_values(self):
        config = _load_config()
        config_text = json.dumps(config)
        for key in CLOUD_API_KEY_NAMES:
            assert key.lower() not in config_text.lower(), (
                f"cloud API key name found in config: {key}"
            )


class TestOpencodeConfigBadConfigFails:
    def test_non_loopback_ollama_base_url_fails(self, tmp_path):
        """A non-loopback ollama baseURL must fail validation."""
        config = _load_config()
        bad_config = dict(config)
        bad_provider = dict(config["provider"]["ollama"])
        bad_provider["options"] = dict(bad_provider.get("options", {}))
        bad_provider["options"]["baseURL"] = "https://api.example.com/v1"
        bad_config["provider"] = {"ollama": bad_provider}

        bad_path = tmp_path / "opencode.bad.json"
        bad_path.write_text(json.dumps(bad_config))

        with open(bad_path) as f:
            bad = json.load(f)

        try:
            _validate_config(bad)
        except AssertionError:
            return
        raise AssertionError("bad config should fail validation")

    def test_missing_default_model_provider_fails(self, tmp_path):
        """A default model referencing an unconfigured provider must fail."""
        config = _load_config()
        bad_config = dict(config)
        bad_config["model"] = "cloud/unknown-model"
        bad_path = tmp_path / "opencode.bad.json"
        bad_path.write_text(json.dumps(bad_config))

        with open(bad_path) as f:
            bad = json.load(f)

        try:
            _validate_config(bad)
        except AssertionError:
            return
        raise AssertionError("missing provider should fail validation")


class TestPyprojectNoNewDependencies:
    def test_pyproject_dependencies_is_empty(self):
        with open(PYPROJECT_PATH, "rb") as f:
            data = tomllib.load(f)
        deps = data.get("project", {}).get("dependencies", [])
        assert deps == [], f"pyproject.toml dependencies must be empty, got {deps}"
