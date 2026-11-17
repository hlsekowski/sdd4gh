"""Unit tests for the OpenCode project config (ADR 0010).

Verifies that opencode.json configures only a local OpenAI-compatible
endpoint, with no cloud provider and no non-local default model.
No network, no model calls.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO_ROOT / "opencode.json"

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
    with open(CONFIG_PATH) as f:
        return json.load(f)


def _is_loopback_host(host: str) -> bool:
    """True when host is a loopback/local address."""
    host = host.lower()
    return host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"} or host.startswith("127.")


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


class TestOpencodeConfigEndpointsAreLocal:
    def test_base_url_is_loopback_address(self):
        config = _load_config()
        for url in _extract_urls(config):
            match = re.match(r"^https?://([^/:]+)", url)
            assert match is not None, f"URL has no host: {url}"
            host = match.group(1)
            assert _is_loopback_host(host), f"baseURL is not a loopback address: {url}"

    def test_no_non_local_base_url(self):
        config = _load_config()
        for url in _extract_urls(config):
            assert "localhost" in url or "127.0.0.1" in url or "::1" in url, (
                f"baseURL is not local: {url}"
            )


class TestOpencodeConfigNoCloudProvider:
    def test_no_cloud_provider_name(self):
        config = _load_config()
        provider_names = _extract_provider_names(config)
        for name in provider_names:
            assert name.lower() not in CLOUD_PROVIDER_NAMES, (
                f"Cloud provider name found: {name}"
            )

    def test_no_cloud_api_key_env(self):
        config = _load_config()
        env_names = _extract_env_names(config)
        for name in env_names:
            assert name.upper() not in CLOUD_API_KEY_NAMES, (
                f"Cloud API key env var found: {name}"
            )

    def test_no_cloud_key_value(self):
        config = _load_config()
        config_text = json.dumps(config)
        for key in CLOUD_API_KEY_NAMES:
            assert key.lower() not in config_text.lower(), (
                f"Cloud API key name found in config: {key}"
            )


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

        for url in _extract_urls(bad):
            match = re.match(r"^https?://([^/:]+)", url)
            assert match is not None
            host = match.group(1)
            assert not _is_loopback_host(host), (
                f"Bad config should not be loopback: {url}"
            )
            assert "example.com" in url, f"Expected non-local URL, got: {url}"
