"""Tests for the OpenCode task-report contract.

Verifies docs/adr/0010-opencode-coding-agent.md.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_implementer_report_contract_is_verifiable():
    config = json.loads((REPO_ROOT / "opencode.json").read_text())
    implement_system = config["agents"]["implement"]["system"].lower()
    sentinel_prompt = " ".join((REPO_ROOT / "prompts" / "sentinel.md").read_text().lower().split())

    for field in (
        "task id",
        "requirements addressed",
        "changed files",
        "exact test commands and results",
        "commit hash",
        "deviations",
    ):
        assert field in implement_system
        assert field in sentinel_prompt
    assert "independently verify" in sentinel_prompt
