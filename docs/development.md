# Development

> **Purpose:** Developer-only notes: environment setup, the commands to run, and the development-only model list.
> **Read when:** setting up the repo, running checks, or choosing a development model.
> **Owns:** the local setup commands, the development-only model list, and the pointer to the AI provider policy. The workflow sequence is owned by [`docs/workflow.md`](workflow.md).

Developer-only notes. End users start at [`README.md`](../README.md).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Development and testing was done on a Mac Air M4 with 16GB RAM.

## Tests

```bash
pytest   # mocked HTTP; no live model
```

See [`docs/testing.md`](testing.md) for complete testing standards (organization, mocking, coverage, naming, failure paths).

## Local validation

Run every check before opening a PR. The full list lives in `AGENTS.md`'s Commands block:

```bash
pytest                      # tests (mocked HTTP, no live model)
ruff check . && ruff format --check .   # lint
python3 -m mypy src/sdd4gh              # type-check
python3 scripts/check_traceability.py   # doc checks
python3 scripts/check_doc_defaults.py
python3 scripts/check_doc_links.py
python3 scripts/check_doc_structure.py
```

`mypy` is in the `dev` extra, so `pip install -e ".[dev]"` provides every Python check above. `pre-commit` is not; install it separately or use `pre-commit run --all-files`, which provisions its own environments. The `gitleaks` and `cz` (commitlint) hooks are `language: system` and need those binaries on `PATH`.

### Documentation quality policy (DQ1–DQ5)

Markdown documentation is governed by the quality policy in [`docs/documentation.md`](documentation.md):

- **DQ1** — Minimum sufficient information: remove repetition, redundancy, and obsolete content.
- **DQ2** — Information density: prefer precise, actionable statements and clear headings.
- **DQ3** — Single source of truth: each rule or decision has one authoritative location.
- **DQ4** — Audience and context: different standards for AGENTS.md, README, procedures, ADRs, and specs.
- **DQ5** — Preserve decision integrity: never remove requirements, rationale, or acceptance criteria.

Blocking rules are enforced mechanically by the documentation checkers under `scripts/` and run on every commit through pre-commit and CI. Advisory rules (semantic quality such as unnecessary explanations or duplicated meaning) require human or AI-agent review and are not enforced by pre-commit.

### Pre-commit hooks

Install the Git hook once after cloning:

```bash
pre-commit install
```

The hook runs the documentation checkers (`check-doc-links`, `check-doc-structure`, `check-doc-defaults`, `check-traceability`) plus lint, type-check, and secret scanning on every commit. Run manually at any time with:

```bash
pre-commit run --all-files --hook-stage pre-commit
```

CI independently enforces the same blocking rules through the `pre-commit` job and the individual `doc-*` jobs in `.github/workflows/ci.yml`.

## Spec-first change workflow

The spec-first workflow sequence is owned by the workflow hub: [`docs/workflow.md`](workflow.md).

The workflow model and its decision gate are decided in [ADR 0003](adr/0003-local-development-workflow.md). The AI workflow's PR Process (feedback evaluation, check monitoring, corrections, lifecycle) is defined in [ADR 0006](adr/0006-pr-process.md).

## Models used for development

Not for end users. Used to write and review these docs and for local agent tooling.

| Model | Endpoint | Use |
|---|---|---|
| `qwen3.5:4b` | `http://127.0.0.1:11434/v1` (Ollama) | Local model for VS Code Copilot integration; fast, low resource. Used for development only; **not used to run the framework**. |
| `nemotron-3.5-super-vl-120b-a12b` | `https://build.nvidia.com/nvidia/nemotron-3.5-super-vl-120b-a12b` | **Recommended** for documentation review: handles larger codebases reliably. Free-tier cloud alternative for development. |

Standard-use models are listed in [`docs/adr/0012-litellm-model-routing.md`](adr/0012-litellm-model-routing.md).

### OpenCode coding-agent configuration (ADR 0010)

OpenCode is configured as the SDD coding agent via a project-level
`opencode.json` at the repository root. It connects to a local
OpenAI-compatible model endpoint; no cloud provider, no paid API key, and
no non-local default model are configured.

OpenCode v2 is required. OpenCode v1 uses a different config schema and
would silently ignore this `opencode.json`.

### Prerequisites

- Install OpenCode v2: see the official install docs at
  https://opencode.ai/docs/ (for example `brew install anomalyco/tap/opencode-v2` on macOS).
- Run a local OpenAI-compatible model server (Ollama, llama.cpp, or vLLM)
  on your machine's loopback address.

### Config

The project config (`opencode.json`) defines a single `local` provider
using the OpenAI-compatible adapter. It uses OpenCode v2 variable
substitution (`{env:VARIABLE_NAME}`) so no tracked file needs editing for
machine-specific values:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "{env:OPENCODE_MODEL}",
  "policies": [
    { "action": "provider.use", "resource": "*", "effect": "deny" },
    { "action": "provider.use", "resource": "local", "effect": "allow" }
  ],
  "providers": {
    "local": {
      "name": "Local model endpoint",
      "env": ["LOCAL_API_KEY"],
      "package": "@opencode/ai/providers/openai-compatible",
      "settings": {
        "baseURL": "{env:OPENCODE_BASE_URL}"
      },
      "models": {
        "model-id": {
          "name": "Local model"
        }
      }
    }
  }
}
```

Before running OpenCode, set these environment variables in your shell:

- `OPENCODE_BASE_URL` — your local endpoint, e.g. `http://localhost:11434/v1` for Ollama.
- `OPENCODE_MODEL` — your local model name, e.g. `qwen2.5:7b`.
- `LOCAL_API_KEY` — set to none or the dummy value `<local>`; never commit a real secret.

The `policies` section denies all providers by default and allows only
`local`, so OpenCode cannot offer hosted/free models or any provider whose
API key happens to be in the environment.

### Running OpenCode against the local endpoint

```bash
OPENCODE_BASE_URL=http://localhost:11434/v1 \
  OPENCODE_MODEL=qwen2.5:7b \
  opencode run "your task"
```

OpenCode resolves `local/qwen2.5:7b` through the `local` provider and sends
requests to `http://localhost:11434/v1`. No cloud provider is involved.

### Smoke test results (ADR 0010 validation)

OpenCode was configured and tested against a local model endpoint as ADR 0010
requires:

| Field | Value |
|---|---|
| OpenCode version | v2.3.0 |
| Model | `qwen2.5:7b` (Ollama) |
| Endpoint | `http://localhost:11434/v1` |
| Command | `OPENCODE_BASE_URL=http://localhost:11434/v1 OPENCODE_MODEL=qwen2.5:7b opencode run --auto --model local/qwen2.5:7b "Add a docstring to the add function in example.py. Only modify example.py, no other files."` |
| Tool calling | ✅ Worked — `write` tool used to modify `example.py` |
| Result | ✅ Docstring added to `add` function |

The smoke test ran in a scratch workspace (not on the feature branch). OpenCode
successfully connected to the local Ollama endpoint, used tool calling, and
added `"""Add two numbers."""` to the `add` function.

## AI / Provider Policy

Provider configuration, standard-use vs development-only models, model
pinning, privacy, and zero-cost provider constraints are governed by the
constitution ([`docs/constitution.md`](constitution.md)) and ADR 0012
([`docs/adr/0012-litellm-model-routing.md`](adr/0012-litellm-model-routing.md)).
