"""Unit tests for the OpenCode project config (ADR 0010).

Verifies that opencode.json configures only a local OpenAI-compatible
endpoint, with no cloud provider and no non-local default model.
No network, no model calls.
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

# Set env vars so {env:VAR} placeholders in opencode.json resolve to real
# values for testing. These are test-only values; the committed config uses
# placeholders that developers replace with their own local endpoint/model.
os.environ.setdefault("OPENCODE_MODEL", "local/model-id")
os.environ.setdefault("OPENCODE_BASE_URL", "http://localhost:11434/v1")

# Known cloud provider names/keys that must never appear in config or docs.
CLOUD_PROVIDER_NAMES = {
    "openai",
    "anthropic",
    "google",
    "azure",
    "aws",
    "bedrock",
    "cohere",
    "mistral",
    "vertex",
    "gemini",
    "claude",
    "gpt",
    "dall-e",
    "whisper",
    "together",
    "perplexity",
    "groq",
    "deepinfra",
    "fireworks",
    "baseten",
    "cerebras",
    "cloudflare",
    "nvidia",
    "build.nvidia.com",
}

# Known cloud API key environment variable names that must never appear.
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


def _load_config() -> dict:
    """Load opencode.json and substitute {env:VAR} placeholders like OpenCode v2.

    OpenCode v2 replaces {env:VARIABLE_NAME} with the environment variable's
    value, or an empty string if unset (verified at
    https://opencode.ai/docs/config, "Variables" section).
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
    a loopback destination. A client cannot connect to 0.0.0.0 as a
    destination, and accepting it would let a non-loopback endpoint slip
    through validation.

    Hostnames such as "localhost.attacker.example" or IP literals such as
    "127.0.0.1.attacker.example" are rejected because they are not exact
    loopback addresses.
    """
    host = host.lower().strip()
    # Exact hostname match for localhost.
    if host == "localhost":
        return True
    # Bracketed IPv6 literal, e.g. "[::1]".
    if host.startswith("[") and host.endswith("]"):
        inner = host[1:-1]
        try:
            addr = ipaddress.ip_address(inner)
        except ValueError:
            return False
        return addr.is_loopback
    # Bare IP literal.
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_loopback


def _extract_urls(config: dict) -> list[str]:
    urls: list[str] = []
    for provider in config.get("providers", {}).values():
        settings = provider.get("settings", {})
        base_url = settings.get("baseURL")
        if base_url:
            urls.append(base_url)
    return urls


def _extract_env_names(config: dict) -> list[str]:
    names: list[str] = []
    for provider in config.get("providers", {}).values():
        for name in provider.get("env", []):
            names.append(name)
    return names


def _extract_provider_names(config: dict) -> list[str]:
    return list(config.get("providers", {}).keys())


def _extract_provider_display_names(config: dict) -> list[str]:
    names: list[str] = []
    for provider in config.get("providers", {}).values():
        name = provider.get("name")
        if name:
            names.append(name)
    return names


def _extract_model_ids(config: dict) -> list[str]:
    ids: list[str] = []
    for provider in config.get("providers", {}).values():
        for model_id in provider.get("models", {}):
            ids.append(model_id)
    return ids


def _validate_config(config: dict) -> None:
    """Validate that config uses only local endpoints and no cloud providers.

    Raises AssertionError if any check fails. This is the shared validation
    function used by both positive and negative tests.
    """
    # Exactly one provider, keyed "local".
    providers = config.get("providers", {})
    assert len(providers) == 1, f"expected exactly one provider, got {len(providers)}"
    assert "local" in providers, 'expected a "local" provider'

    # Every baseURL is a loopback address.
    for url in _extract_urls(config):
        parsed = urlsplit(url)
        assert parsed.scheme in {"http", "https"}, f"unsupported scheme: {url}"
        host = parsed.hostname
        assert host is not None, f"URL has no host: {url}"
        assert _is_loopback_host(host), f"baseURL is not a loopback address: {url}"

    # No cloud provider name anywhere: provider keys, display names, or model IDs.
    for name in _extract_provider_names(config):
        is_cloud = name.lower() in CLOUD_PROVIDER_NAMES
        assert not is_cloud, f"cloud provider name found: {name}"
    for name in _extract_provider_display_names(config):
        is_cloud = name.lower() in CLOUD_PROVIDER_NAMES
        assert not is_cloud, f"cloud provider display name found: {name}"
    for model_id in _extract_model_ids(config):
        is_cloud = model_id.lower() in CLOUD_PROVIDER_NAMES
        assert not is_cloud, f"cloud provider model ID found: {model_id}"

    # No cloud API key env var names.
    for name in _extract_env_names(config):
        is_cloud_key = name.upper() in CLOUD_API_KEY_NAMES
        assert not is_cloud_key, f"cloud API key env var found: {name}"

    # Default model resolves to the local provider.
    model = config.get("model", "")
    assert isinstance(model, str) and model, "default model must be set"
    assert model.startswith("local/"), f"default model must resolve to local provider: {model}"
    local_models = providers["local"].get("models", {})
    model_key = model.split("/", 1)[1] if "/" in model else model
    assert model_key in local_models, f"default model {model_key!r} not in local models"


class TestOpencodeConfigParses:
    def test_config_exists_and_is_valid_json(self):
        config = _load_config()
        assert isinstance(config, dict)
        assert "$schema" in config

    def test_config_has_exactly_one_provider(self):
        config = _load_config()
        providers = config.get("providers", {})
        assert len(providers) == 1
        assert "local" in providers

    def test_provider_uses_openai_compatible_package(self):
        config = _load_config()
        provider = config["providers"]["local"]
        assert provider["package"] == "@opencode/ai/providers/openai-compatible"

    def test_provider_has_models_map(self):
        config = _load_config()
        provider = config["providers"]["local"]
        assert isinstance(provider.get("models"), dict)
        assert len(provider["models"]) >= 1

    def test_default_model_resolves_to_local_provider(self):
        config = _load_config()
        model = config.get("model", "")
        assert model.startswith("local/"), f"default model must resolve to local: {model}"
        model_key = model.split("/", 1)[1]
        local_models = config["providers"]["local"].get("models", {})
        assert model_key in local_models, f"default model {model_key!r} not in local models"

    def test_local_provider_has_base_url(self):
        config = _load_config()
        provider = config["providers"]["local"]
        base_url = provider.get("settings", {}).get("baseURL")
        assert base_url, "local provider must have a non-empty baseURL"


class TestOpencodeConfigEndpointsAreLocal:
    def test_base_url_is_loopback_address(self):
        config = _load_config()
        for url in _extract_urls(config):
            parsed = urlsplit(url)
            host = parsed.hostname
            assert host is not None, f"URL has no host: {url}"
            assert _is_loopback_host(host), f"baseURL is not a loopback address: {url}"

    def test_rejects_remote_hostname_disguised_as_loopback(self):
        """Hostnames like localhost.attacker.example must be rejected."""
        assert not _is_loopback_host("localhost.attacker.example")
        assert not _is_loopback_host("127.0.0.1.attacker.example")
        assert not _is_loopback_host("LOCALHOST.ATTACKER.EXAMPLE")

    def test_rejects_0_0_0_0(self):
        """0.0.0.0 is the unspecified address, not loopback."""
        assert not _is_loopback_host("0.0.0.0")

    def test_accepts_bracketed_ipv6_loopback(self):
        """[::1] is a valid loopback destination."""
        assert _is_loopback_host("[::1]")

    def test_rejects_non_loopback_ipv6(self):
        assert not _is_loopback_host("[2001:db8::1]")


class TestOpencodeConfigNoCloudProvider:
    def test_no_cloud_provider_name(self):
        config = _load_config()
        for name in _extract_provider_names(config):
            assert name.lower() not in CLOUD_PROVIDER_NAMES, f"cloud provider name found: {name}"

    def test_no_cloud_provider_display_name(self):
        config = _load_config()
        for name in _extract_provider_display_names(config):
            is_cloud = name.lower() in CLOUD_PROVIDER_NAMES
            assert not is_cloud, f"cloud provider display name found: {name}"

    def test_no_cloud_model_id(self):
        config = _load_config()
        for model_id in _extract_model_ids(config):
            is_cloud = model_id.lower() in CLOUD_PROVIDER_NAMES
            assert not is_cloud, f"cloud provider model ID found: {model_id}"

    def test_no_cloud_api_key_env(self):
        config = _load_config()
        env_names = _extract_env_names(config)
        for name in env_names:
            assert name.upper() not in CLOUD_API_KEY_NAMES, f"cloud API key env var found: {name}"

    def test_no_cloud_key_value(self):
        config = _load_config()
        config_text = json.dumps(config)
        for key in CLOUD_API_KEY_NAMES:
            is_cloud_key = key.lower() in config_text.lower()
            assert not is_cloud_key, f"cloud API key name found in config: {key}"


class TestOpencodeConfigBadConfigFails:
    def test_non_local_base_url_fails_validation(self, tmp_path):
        """A deliberately bad config (non-local URL) must make the test fail."""
        config = _load_config()
        bad_config = dict(config)
        bad_provider = dict(config["providers"]["local"])
        bad_provider["settings"] = dict(bad_provider.get("settings", {}))
        bad_provider["settings"]["baseURL"] = "https://api.example.com/v1"
        bad_config["providers"] = {"local": bad_provider}

        bad_path = tmp_path / "opencode.bad.json"
        bad_path.write_text(json.dumps(bad_config))

        with open(bad_path) as f:
            bad = json.load(f)

        try:
            _validate_config(bad)
        except AssertionError:
            return
        raise AssertionError("bad config should fail validation")

    def test_unexpected_provider_key_fails(self, tmp_path):
        """An unexpected top-level provider key (e.g. the v1 "provider" key) must fail."""
        config = _load_config()
        bad_config = dict(config)
        bad_config["providers"]["provider"] = {
            "name": "Unexpected provider",
            "package": "@opencode/ai/providers/openai-compatible",
            "settings": {"baseURL": "http://127.0.0.1:11434/v1"},
            "models": {"model-id": {"name": "Model"}},
        }
        bad_path = tmp_path / "opencode.bad.json"
        bad_path.write_text(json.dumps(bad_config))

        with open(bad_path) as f:
            bad = json.load(f)

        try:
            _validate_config(bad)
        except AssertionError:
            return
        raise AssertionError("unexpected provider key should fail validation")


class TestPyprojectNoNewDependencies:
    def test_pyproject_dependencies_is_empty(self):
        with open(PYPROJECT_PATH, "rb") as f:
            data = tomllib.load(f)
        deps = data.get("project", {}).get("dependencies", [])
        assert deps == [], f"pyproject.toml dependencies must be empty, got {deps}"
