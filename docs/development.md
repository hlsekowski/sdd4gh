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

## Spec-first change workflow

The spec-first workflow sequence is owned by the workflow hub: [`docs/workflow.md`](workflow.md).

The workflow model and its decision gate are decided in [ADR 0003](adr/0003-local-development-workflow.md). The AI workflow's PR Process (feedback evaluation, check monitoring, corrections, lifecycle) is defined in [ADR 0006](adr/0006-pr-process.md).

## Models used for development

Not for end users. Used to write and review these docs and for local agent tooling.

| Model | Endpoint | Use |
|---|---|---|
| `qwen3.5:4b` | See [`DEFAULT_BASE_URL`](../src/sdd4gh/contracts/constants.py) (Ollama) | Local model for VS Code Copilot integration; fast, low resource. Used for development only; **not used to run the framework**. |
| `nemotron-3.5-super-vl-120b-a12b` | `https://build.nvidia.com/nvidia/nemotron-3.5-super-vl-120b-a12b` | **Recommended** for documentation review: handles larger codebases reliably. Free-tier cloud alternative for development. |

Standard-use models are listed in `docs/spec/prompts.md`.

## OpenCode coding-agent configuration (ADR 0010)

OpenCode is configured as the SDD coding agent via a project-level
`opencode.json` at the repository root. It connects to a local
OpenAI-compatible model endpoint; no cloud provider, no paid API key, and
no non-local default model are configured.

### Prerequisites

- Install OpenCode: `brew install anomalyco/tap/opencode-v2` (or see
  https://opencode.ai/docs/).
- Run a local OpenAI-compatible model server (Ollama, llama.cpp, or vLLM)
  on `http://localhost:XXXX/v1`, where `XXXX` is your server's port.

### Config

The project config (`opencode.json`) defines a single `local` provider
using the OpenAI-compatible adapter:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "local/model-id",
  "providers": {
    "local": {
      "name": "Local model endpoint",
      "env": ["LOCAL_API_KEY"],
      "package": "@opencode/ai/providers/openai-compatible",
      "settings": {
        "baseURL": "http://localhost:XXXX/v1"
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

Replace `XXXX` with your local server's port and `model-id` with your
model's name. Set `LOCAL_API_KEY` to none or the dummy value `<local>`;
never commit a real secret.

### Running OpenCode against the local endpoint

```bash
opencode run "your task"
```

OpenCode resolves `local/model-id` through the `local` provider and sends
requests to `http://localhost:XXXX/v1`. No cloud provider is involved.

## AI / Provider Policy

See `docs/ai_provider_policy.md` for complete standards on:
- Provider configuration (single config source, precedence, validation)
- Standard-use vs development-only models
- Model pinning, reproducibility (temperature, seed)
- Timeouts, retries, structured output validation
- Prompt management (versioned, reviewed like code)
- Privacy & data handling (what leaves local machine)
- Model drift monitoring
- Prompt injection mitigations
