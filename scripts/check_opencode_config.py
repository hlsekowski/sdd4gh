#!/usr/bin/env python3
"""Validate the project OpenCode config with the pinned local CLI."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

EXPECTED_VERSION = "opencode v2.3.0"
REQUIRED_AGENTS = frozenset({"ask", "implement", "review", "sentinel", "spec"})
REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "opencode.json"


def run_cli(*args: str) -> str:
    """Run one OpenCode CLI command and return its standard output."""
    command = ["opencode", *args]
    try:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise RuntimeError("OpenCode CLI not found; install v2.3.0 to run this check") from error

    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        raise RuntimeError(f"{' '.join(command)} failed ({result.returncode}): {detail}")
    return result.stdout


def configured_agents(output: str) -> set[str]:
    """Return agent IDs from `opencode debug agents` output."""
    try:
        agents = json.loads(output)
    except json.JSONDecodeError as error:
        raise RuntimeError("opencode debug agents did not return valid JSON") from error

    if not isinstance(agents, list):
        raise RuntimeError("opencode debug agents returned an unexpected JSON shape")

    return {
        agent["id"]
        for agent in agents
        if isinstance(agent, dict) and isinstance(agent.get("id"), str)
    }


def project_configured_agents(output: str) -> set[str]:
    """Return agent IDs from the project config document in `debug config` output."""
    try:
        documents = json.loads(output)
    except json.JSONDecodeError as error:
        raise RuntimeError("opencode debug config did not return valid JSON") from error

    if not isinstance(documents, list):
        raise RuntimeError("opencode debug config returned an unexpected JSON shape")

    for document in documents:
        if not isinstance(document, dict) or document.get("type") != "document":
            continue
        path = document.get("path")
        if not isinstance(path, str):
            continue
        document_path = Path(path)
        if not document_path.is_absolute():
            document_path = REPO_ROOT / document_path
        if document_path.resolve() != CONFIG_PATH.resolve():
            continue

        info = document.get("info")
        if not isinstance(info, dict) or not isinstance(info.get("agents"), dict):
            raise RuntimeError("project opencode.json has no valid agents object")
        return set(info["agents"])

    raise RuntimeError("opencode debug config did not report the project opencode.json")


def project_effective_model(output: str) -> tuple[str, str]:
    """Return the provider and model resolved for the project config."""
    try:
        documents = json.loads(output)
    except json.JSONDecodeError as error:
        raise RuntimeError("opencode debug config did not return valid JSON") from error

    if not isinstance(documents, list):
        raise RuntimeError("opencode debug config returned an unexpected JSON shape")

    for document in documents:
        if not isinstance(document, dict) or document.get("type") != "document":
            continue
        path = document.get("path")
        if not isinstance(path, str):
            continue
        document_path = Path(path)
        if not document_path.is_absolute():
            document_path = REPO_ROOT / document_path
        if document_path.resolve() != CONFIG_PATH.resolve():
            continue

        info = document.get("info")
        if not isinstance(info, dict):
            break
        model = info.get("model")
        if not isinstance(model, dict):
            break
        provider_id = model.get("providerID")
        model_id = model.get("model")
        if isinstance(provider_id, str) and isinstance(model_id, str):
            return provider_id, model_id
        break

    raise RuntimeError("project opencode.json has no resolved effective model")


def listed_models(output: str) -> set[str]:
    """Return model IDs listed by opencode models."""
    return {line.strip() for line in output.splitlines() if line.strip()}


def run_smoke() -> None:
    """Run opt-in, local-only model smoke prompts."""
    prompts = (
        (
            "read",
            "For a read-only runtime smoke test, use the read tool to read "
            "AGENTS.md and report only its first non-empty line. Do not use "
            "GitHub, shell, editing, or delegation tools.",
        ),
        (
            "delegation",
            "Delegate this read-only task to @review: verify that opencode.json "
            "exists, read it, and report one sentence. Do not edit files or use "
            "GitHub or shell mutations.",
        ),
    )
    for name, prompt in prompts:
        print(f"Running local {name} smoke...")
        result = subprocess.run(
            [
                "opencode",
                "run",
                "--model",
                "ollama/gemma4-12b-32k",
                "--agent",
                "sentinel",
                prompt,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
            raise RuntimeError(f"local {name} smoke failed ({result.returncode}): {detail}")
        print(result.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="make opt-in local model calls to Sentinel with Gemma",
    )
    args, _unknown = parser.parse_known_args()

    try:
        version = run_cli("--version").strip()
        if version != EXPECTED_VERSION:
            found = version or "no version output"
            raise RuntimeError(f"Expected {EXPECTED_VERSION}, found {found}")

        project_agents = project_configured_agents(run_cli("debug", "config"))
        missing_project = REQUIRED_AGENTS - project_agents
        if missing_project:
            raise RuntimeError(
                f"project config is missing agents: {', '.join(sorted(missing_project))}"
            )

        discovered = configured_agents(run_cli("debug", "agents"))
        missing = REQUIRED_AGENTS - discovered
        if missing:
            raise RuntimeError(f"missing configured agents: {', '.join(sorted(missing))}")

        effective_output = run_cli("debug", "config")
        provider_id, model_id = project_effective_model(effective_output)
        if (provider_id, model_id) != ("ollama", "gemma4-12b-32k"):
            raise RuntimeError(
                f"resolved project model is {provider_id}/{model_id}, "
                "expected ollama/gemma4-12b-32k"
            )

        available = listed_models(run_cli("models"))
        effective_model = f"{provider_id}/{model_id}"
        if effective_model not in available:
            raise RuntimeError(f"effective project model is not listed: {effective_model}")

        if args.smoke:
            run_smoke()
    except RuntimeError as error:
        print(f"OpenCode config check failed: {error}", file=sys.stderr)
        return 1

    print(f"OpenCode config check passed with {EXPECTED_VERSION}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
