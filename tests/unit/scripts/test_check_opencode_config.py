"""Verifies the developer-only OpenCode config check (ADR 0010 spec §4)."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"


def load_checker():
    """Load scripts/check_opencode_config.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "check_opencode_config", SCRIPTS_DIR / "check_opencode_config.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_opencode_config"] = module
    spec.loader.exec_module(module)
    return module


def test_main_uses_pinned_cli_and_confirms_project_agents(monkeypatch, capsys):
    checker = load_checker()
    outputs = iter(
        [
            "opencode v2.3.0\n",
            json.dumps(
                [
                    {
                        "type": "document",
                        "path": str(checker.CONFIG_PATH),
                        "info": {"agents": dict.fromkeys(checker.REQUIRED_AGENTS)},
                    }
                ]
            ),
            json.dumps([{"id": agent} for agent in checker.REQUIRED_AGENTS]),
        ]
    )
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout=next(outputs), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert checker.main() == 0
    assert commands == [
        ["opencode", "--version"],
        ["opencode", "debug", "config"],
        ["opencode", "debug", "agents"],
    ]
    assert "OpenCode config check passed" in capsys.readouterr().out


def test_main_rejects_unpinned_cli_before_config_checks(monkeypatch, capsys):
    checker = load_checker()
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="opencode v2.4.0\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert checker.main() == 1
    assert commands == [["opencode", "--version"]]
    assert "Expected opencode v2.3.0" in capsys.readouterr().err


def test_main_fails_when_a_configured_agent_is_missing(monkeypatch, capsys):
    checker = load_checker()
    outputs = iter(
        [
            "opencode v2.3.0\n",
            json.dumps(
                [
                    {
                        "type": "document",
                        "path": str(checker.CONFIG_PATH),
                        "info": {"agents": {"sentinel": {}}},
                    }
                ]
            ),
            json.dumps([{"id": "sentinel"}]),
        ]
    )

    def fake_run(command, **kwargs):
        return SimpleNamespace(returncode=0, stdout=next(outputs), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert checker.main() == 1
    assert "project config is missing agents" in capsys.readouterr().err


def test_main_fails_when_cli_does_not_discover_project_agents(monkeypatch, capsys):
    checker = load_checker()
    outputs = iter(
        [
            "opencode v2.3.0\n",
            json.dumps(
                [
                    {
                        "type": "document",
                        "path": str(checker.CONFIG_PATH),
                        "info": {"agents": dict.fromkeys(checker.REQUIRED_AGENTS)},
                    }
                ]
            ),
            json.dumps([{"id": "sentinel"}]),
        ]
    )

    def fake_run(command, **kwargs):
        return SimpleNamespace(returncode=0, stdout=next(outputs), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert checker.main() == 1
    assert "missing configured agents" in capsys.readouterr().err
