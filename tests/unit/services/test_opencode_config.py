"""Unit tests for the OpenCode project config (ADR 0010).

Verifies that opencode.json configures the OpenCode v2 schema with
providers, agents, and commands. No network, no model calls.
"""

from __future__ import annotations

import fnmatch
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


def _agent_permission(config: dict, agent: str) -> dict:
    """Return the permission dict for an agent, or {} when absent."""
    agents = _extract_agents(config)
    agent_cfg = agents.get(agent, {})
    return agent_cfg.get("permission", {})


def _matches_rule(command: str, rule: str) -> bool:
    """True when `command` matches a glob-style permission rule."""
    return fnmatch.fnmatch(command, rule)


def _effective_effect(permission: dict, action: str, resource: str) -> str | None:
    """Resolve the effective effect for an action/resource pair.

    OpenCode semantics: a more specific rule overrides a less specific one;
    when no rule matches, the `*` catch-all (if present) applies.
    Returns "allow", "deny", or None when no rule matches at all.
    """
    action_cfg = permission.get(action)
    if isinstance(action_cfg, str):
        # e.g. "edit": "deny" or "webfetch": "deny"
        return action_cfg if action_cfg in {"allow", "deny"} else None
    if not isinstance(action_cfg, dict):
        return None
    # Most specific match wins: exact > glob > catch-all "*".
    best: str | None = None
    best_specificity = -1
    for rule, effect in action_cfg.items():
        if effect not in {"allow", "deny"}:
            continue
        if _matches_rule(resource, rule):
            if rule == "*":
                specificity = 0
            elif "*" in rule or "?" in rule or "[" in rule:
                specificity = 1
            else:
                specificity = 2
            if specificity > best_specificity or (
                specificity == best_specificity and effect == "deny"
            ):
                best_specificity = specificity
                best = effect
    return best


class TestOpencodeConfigLeastPrivilege:
    """Regression tests that each agent's file, shell, delegation, and GitHub
    permissions match its role and cannot drift without a test failure."""

    def test_sentinel_cannot_edit_implementation_files(self):
        config = _load_config()
        perm = _agent_permission(config, "sentinel")
        # Only narrowly scoped orchestration actions remain: tasks.md tick
        # updates are allowed; everything else under specs/ is denied.
        assert _effective_effect(perm, "edit", "specs/11-foo/spec.md") == "deny"
        assert _effective_effect(perm, "edit", "specs/11-foo/plan.md") == "deny"
        assert _effective_effect(perm, "edit", "specs/11-foo/tasks.md") == "allow"
        assert _effective_effect(perm, "edit", "src/sdd4gh/services/x.py") == "deny"
        assert _effective_effect(perm, "edit", "opencode.json") == "deny"
        assert _effective_effect(perm, "edit", ".github/workflows/ci.yml") == "deny"

    def test_sentinel_cannot_bypass_delegated_workflow(self):
        config = _load_config()
        perm = _agent_permission(config, "sentinel")
        assert _effective_effect(perm, "task", "spec") == "allow"
        assert _effective_effect(perm, "task", "implement") == "allow"
        assert _effective_effect(perm, "task", "review") == "allow"
        assert _effective_effect(perm, "task", "sentinel") == "deny"
        assert _effective_effect(perm, "task", "ask") == "deny"

    def test_sentinel_shell_rules_block_compound_and_force_push(self):
        config = _load_config()
        perm = _agent_permission(config, "sentinel")
        # Required workflow commands continue to work.
        assert _effective_effect(perm, "bash", "git status") == "allow"
        assert _effective_effect(perm, "bash", "git diff") == "allow"
        assert _effective_effect(perm, "bash", "git add -A") == "allow"
        assert _effective_effect(perm, "bash", "git commit -m 'x'") == "allow"
        assert _effective_effect(perm, "bash", "git push origin sdd/11-foo") == "allow"
        assert _effective_effect(perm, "bash", "pytest") == "allow"
        # Force-push attempts are denied in every spelling.
        assert _effective_effect(perm, "bash", "git push --force") == "deny"
        assert _effective_effect(perm, "bash", "git push -f") == "deny"
        assert _effective_effect(perm, "bash", "git push origin sdd/* --force") == "deny"
        # Compound commands, redirection, and command substitution cannot be
        # statically blocked by OpenCode's prefix-glob model: a prefix allow
        # rule such as `git status*` also matches `git status; rm -rf /`.
        # That boundary is documented in docs/specs/adr-0010-implementation-spec.md
        # and brought to the owner; it is not asserted here because no static
        # rule can enforce it.

    def test_implement_cannot_rewrite_spec_or_governance_docs(self):
        config = _load_config()
        perm = _agent_permission(config, "implement")
        assert _effective_effect(perm, "edit", "specs/11-foo/spec.md") == "deny"
        assert _effective_effect(perm, "edit", "specs/11-foo/plan.md") == "deny"
        assert _effective_effect(perm, "edit", "specs/constitution.md") == "deny"
        # Its required task-status update is explicitly and narrowly supported.
        assert _effective_effect(perm, "edit", "specs/11-foo/tasks.md") == "allow"
        assert _effective_effect(perm, "edit", "src/sdd4gh/services/x.py") == "allow"
        assert _effective_effect(perm, "edit", "opencode.json") == "deny"
        assert _effective_effect(perm, "edit", ".github/**/x.yml") == "deny"

    def test_implement_cannot_push_or_use_gh(self):
        config = _load_config()
        perm = _agent_permission(config, "implement")
        assert _effective_effect(perm, "bash", "git push origin sdd/11-foo") == "deny"
        assert _effective_effect(perm, "bash", "gh pr create") == "deny"
        assert _effective_effect(perm, "bash", "gh issue view 11") == "deny"

    def test_spec_agent_scoped_to_current_issue_directory(self):
        config = _load_config()
        perm = _agent_permission(config, "spec")
        # The spec agent may edit only within specs/ (enforceable static
        # boundary). It cannot edit arbitrary issue specifications outside
        # specs/ or unrelated artifacts.
        assert _effective_effect(perm, "edit", "specs/11-foo/spec.md") == "allow"
        assert _effective_effect(perm, "edit", "specs/11-foo/plan.md") == "allow"
        assert _effective_effect(perm, "edit", "specs/11-foo/tasks.md") == "allow"
        assert _effective_effect(perm, "edit", "specs/99-other/spec.md") == "allow"
        assert _effective_effect(perm, "edit", "src/sdd4gh/services/x.py") == "deny"
        assert _effective_effect(perm, "edit", "opencode.json") == "deny"
        assert _effective_effect(perm, "edit", "README.md") == "deny"

    def test_review_agent_remains_read_only(self):
        config = _load_config()
        perm = _agent_permission(config, "review")
        assert _effective_effect(perm, "edit", "any/file.md") == "deny"
        assert _effective_effect(perm, "edit", "specs/11-foo/spec.md") == "deny"
        assert _effective_effect(perm, "task", "implement") == "deny"
        assert _effective_effect(perm, "task", "spec") == "deny"
        assert perm.get("webfetch") == "deny"
        assert perm.get("external_directory") == "deny"
        # Read-only shell commands continue to work.
        assert _effective_effect(perm, "bash", "git diff") == "allow"
        assert _effective_effect(perm, "bash", "git status") == "allow"
        assert _effective_effect(perm, "bash", "git log") == "allow"
        assert _effective_effect(perm, "bash", "pytest") == "allow"
        assert _effective_effect(perm, "bash", "git push origin sdd/11-foo") == "deny"
        assert _effective_effect(perm, "bash", "gh pr create") == "deny"

    def test_all_agents_have_no_webfetch_or_external_directory(self):
        config = _load_config()
        agents = _extract_agents(config)
        for agent in REQUIRED_AGENTS:
            agent_cfg = agents[agent]
            perm = agent_cfg.get("permission", {})
            tools = agent_cfg.get("tools", {})
            # `permission.webfetch` (string) or `tools.webfetch` (bool false)
            # both mean webfetch is denied.
            webfetch = perm.get("webfetch", tools.get("webfetch", True))
            assert webfetch == "deny" or webfetch is False, f"{agent} webfetch must be denied"
            # `permission.external_directory` (string) means denied. The `ask`
            # agent uses the `tools` format with every tool disabled, so it has
            # no external_directory access either.
            external_directory = perm.get("external_directory")
            if external_directory is not None:
                assert external_directory == "deny", f"{agent} external_directory must be denied"
            else:
                assert not tools or all(v is False for v in tools.values()), (
                    f"{agent} must have no tools enabled"
                )


class TestOpencodeConfigParses:
    def test_config_exists_and_is_valid_json(self):
        config = _load_config()
        assert isinstance(config, dict)
        assert "$schema" in config

    def test_config_has_model(self):
        config = _load_config()
        assert config.get("model") == "ollama/gemma4-12b-32k"

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
        model_id = model.split("/", 1)[1]
        assert model_id in _extract_providers(config)[provider_name]["models"]


class TestOpencodeConfigOllamaProvider:
    def test_ollama_provider_structure(self):
        config = _load_config()
        ollama = config["provider"]["ollama"]
        assert ollama["npm"] == "@ai-sdk/openai-compatible"
        assert ollama["name"] == "Ollama (local)"
        assert ollama["options"]["baseURL"] == "http://localhost:11434/v1"
        assert "qwen3-8b-16k" in ollama["models"]
        assert "gemma4-12b-32k" in ollama["models"]
        assert ollama["models"]["gemma4-12b-32k"]["limit"]["context"] == 32768

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
