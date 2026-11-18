# Development

> **Purpose:** Developer-only notes: environment setup, checks, and development model configuration.
> **Read when:** setting up the repo, running checks, or using the OpenCode coding agent.
> **Owns:** local setup commands, development model notes, OpenCode setup and changelog update convention. The workflow sequence is owned by [`docs/workflow.md`](workflow.md).

Developer-only notes. End users start at [`README.md`](../README.md).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Changelog

Add a concise entry under `Unreleased` in [`CHANGELOG.md`](../CHANGELOG.md) for
each pull request, as required by the repository's PR template.

Development and testing was done on a Mac Air M4 with 16GB RAM.

## Tests and local validation

```bash
pytest                      # tests (mocked HTTP, no live model)
ruff check . && ruff format --check .
python3 -m mypy src/sdd4gh
python3 scripts/check_traceability.py
python3 scripts/check_doc_defaults.py
python3 scripts/check_doc_links.py
python3 scripts/check_doc_structure.py
```

See [`docs/testing.md`](testing.md) for testing standards. `mypy` is in the `dev` extra. `pre-commit` is not; install it separately or use `pre-commit run --all-files`, which provisions its own environments. The `gitleaks` and `cz` (commitlint) hooks are `language: system` and need those binaries on `PATH`.

## Spec-first change workflow

The workflow sequence is owned by [`docs/workflow.md`](workflow.md). The workflow model and its decision gate are decided in [ADR 0003](adr/0003-local-development-workflow.md). The AI workflow's PR process is defined in [ADR 0006](adr/0006-pr-process.md).

## Models used for development

Not for end users. Used for documentation and local agent tooling.

| Model | Endpoint | Use |
|---|---|---|
| `qwen3.5:4b` | `http://127.0.0.1:11434/v1` (Ollama) | Local model for VS Code Copilot integration; not used to run the framework. |
| `nemotron-3.5-super-vl-120b-a12b` | NVIDIA NIM | Optional non-local model. The project permits it only when its no-charge terms and account safeguards are verified. Allowed under the zero-cost provider policy: genuinely free hosted tier, no paid subscription, no billable usage. |

Standard-use models are listed in [ADR 0012](adr/0012-litellm-model-routing.md).

## OpenCode coding-agent configuration (ADR 0010)

The canonical project configuration is [`opencode.json`](../opencode.json). It uses the native OpenCode V2 keys `providers`, `agents`, and `commands`. All five agents inherit the local default model, `ollama/gemma4-12b-32k`. The NVIDIA provider is optional and is not assigned to an agent by default; its API key is read from `~/.secrets/nvidia_key`, never committed.

OpenCode V2 is required. Install it using the [official instructions](https://opencode.ai/docs/). For local inference, run an OpenAI-compatible model server such as Ollama on the loopback address configured in `opencode.json`.

The repeatable, developer-only configuration check is pinned to OpenCode
`v2.3.0` and uses the CLI's bundled config schema:

```bash
python3 scripts/check_opencode_config.py
```

It runs `opencode debug config` and `opencode debug agents`, verifies the five
project agents, and fails if the CLI version differs. It downloads no schema,
makes no model request, and is not required in offline CI. The config declares
the official schema at `https://opencode.ai/config.json`; its model definitions
reference `https://models.dev/model-schema.json`. The separate schema check
recorded below used `jsonschema 4.26.0`; those URLs are live and are not fetched
by the repeatable local check.

Create the configured local model from [`Modelfile`](../Modelfile):

```bash
ollama create gemma4-12b-32k -f Modelfile
```

Load and inspect the project config without making a model request:

```bash
opencode --version
opencode debug config
opencode debug agents
```

This confirms config loading and agent discovery only. It does not prove model availability, tool-calling quality, delegation, or permission outcomes. Automated tests do not require a live model or provider credentials.

### Runtime evidence

The installed OpenCode CLI successfully loaded the project config and discovered
all five configured agents (`opencode v2.3.0`). `opencode models` listed both
`ollama/gemma4-12b-32k` and the optional
`nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b`.
The config also passed the official `https://opencode.ai/config.json` schema,
including its referenced `https://models.dev/model-schema.json` model schema,
using a temporary `jsonschema 4.26.0` install (no project dependency added).

The current local default was also exercised with a read-only tool call:

| Field | Value |
|---|---|
| OpenCode version | v2.3.0 |
| Model / agent | `ollama/gemma4-12b-32k` / `sentinel` |
| Command | `opencode run --model ollama/gemma4-12b-32k --agent sentinel "For a read-only configuration smoke test, use the read tool to read AGENTS.md and report only its first non-empty line. Do not use GitHub, shell, or editing tools."` |
| Result | The local model called the read tool and returned `# Agent instructions`. |

This verifies a local model request and a read tool call only; delegation and
other permission outcomes have not been independently runtime-tested.

A harmless compound-shell check using the same OpenCode version, model, and
agent attempted `git status --short; printf scanner-smoke`. OpenCode returned
`Error: Permission denied: shell`; no subcommand ran. Edit denial, staging
approval, force-push denial, pipes/redirection, and delegation have not been
independently runtime-tested.

The prior local smoke test also used Qwen before Gemma became the default:

| Field | Value |
|---|---|
| OpenCode version | v2.3.0 |
| Model | `ollama/qwen3-8b-16k` |
| Endpoint | `http://localhost:11434/v1` |
| Command | `OPENCODE_BASE_URL=http://localhost:11434/v1 OPENCODE_MODEL=qwen3-8b-16k opencode run --auto --model ollama/qwen3-8b-16k "Add a docstring to the add function in example.py. Only modify example.py, no other files."` |
| Result | The local model used the write tool to add a docstring in a scratch workspace. |

The environment variables shown are part of the historical command; the current project config does not interpolate them. That result does not verify the current Gemma default, delegated-agent behavior, or permission boundaries. The owner reports successful use of `nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b`; this task does not independently verify a hosted request or any other model. See [ADR 0010](adr/0010-opencode-coding-agent.md) for the zero-cost policy.

## AI / Provider Policy

See [`docs/ai_provider_policy.md`](ai_provider_policy.md) for complete standards on:
- Zero-cost provider policy: local inference as one supported option, not the only permitted option
- Provider configuration (single config source, precedence, validation)
- Standard-use vs development-only models
- Model pinning, reproducibility (temperature, seed)
- Timeouts, retries, structured output validation
- Prompt management (versioned, reviewed like code)
- Privacy & data handling (what leaves local machine)
- Model drift monitoring
- Prompt injection mitigations
- Credential and billing safeguards: free tiers must not depend on a paid subscription or permit accidental metered calls
