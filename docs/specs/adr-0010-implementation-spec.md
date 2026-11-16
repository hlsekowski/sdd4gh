# ADR 0010 Implementation Specification

> **Purpose:** Translates ADR 0010 (OpenCode coding-agent execution) into implementable contracts and testable acceptance criteria for configuring OpenCode against a local model endpoint.
> **Read when:** implementing or verifying the OpenCode project config, its tests, or its documentation.
> **Owns:** the OpenCode local-endpoint configuration contract, its verification tests, and its documentation linkage.

## Source

- [ADR 0010: OpenCode coding-agent execution](../adr/0010-opencode-coding-agent.md) — Accepted
- [ADR 0008: Workflow runtime and model-routing selection](../adr/0008-workflow-runtime-and-model-routing.md) — Accepted (§3 Rollout boundaries)
- [ADR 0007: SDD Process](../adr/0007-sdd-process.md) — Accepted
- [ADR 0004: Worker and Task Execution Model](../adr/0004-worker-task-model.md) — Accepted
- [Project constitution](../constitution.md) — Accepted (S1–S8)

## 1. Scope and out of scope

### In scope

- An OpenCode project config file (`opencode.json`) at the repository root, configuring a single custom provider that points at a local OpenAI-compatible model endpoint.
- The provider uses the OpenAI-compatible runtime package (`@opencode/ai/providers/openai-compatible`) with `settings.baseURL` set to a loopback/local address and a `models` map containing the local model.
- No cloud provider, no paid API key, no non-local default model anywhere in the config or docs.
- Automated tests (no network, no model calls) that verify the config parses, every provider endpoint is a loopback/local address, and no cloud provider name or key value is present; a deliberately bad config (non-local URL) makes the test fail.
- Documentation explaining how to install and run OpenCode against the local endpoint, linked from the right existing doc so doc checks pass.

### Out of scope

- LangGraph workflow orchestration (ADR 0009): OpenCode does not take over workflow orchestration.
- LiteLLM (ADR 0012): OpenCode uses the local endpoint directly, without LiteLLM.
- Kubernetes worker hosting (ADR 0011).
- Any changes to `pyproject.toml` dependencies (OpenCode is an external CLI tool, not a Python dependency).
- Any changes to existing contracts, domain logic, or services.
- Running OpenCode against the user's local model endpoint (Phase 5 smoke test requires the user's model server running).

## 2. Where the OpenCode config lives and why

### Location

`opencode.json` at the repository root.

OpenCode searches from the current directory to the filesystem root, merging `opencode.json(c)` files from farthest to closest, then `.opencode/` directories in the same order. Placing `opencode.json` at the repository root makes it the project-level config that applies to everyone working in this repo, without requiring a global or system config.

### Why a project config (not global/system)

- The local endpoint (`http://localhost:XXXX/v1`) and model name (`model-id`) are machine-specific; they belong in the project config so each developer can point them at their own local server.
- A project config avoids polluting the global `~/.config/opencode/opencode.json` with project-specific provider settings.
- It keeps the configuration visible, reviewable, and version-controlled alongside the code it configures.

### Config shape (verified against OpenCode v2.3.0 docs)

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

- `providers.local.package` is `@opencode/ai/providers/openai-compatible` — the OpenAI-compatible adapter, verified from OpenCode's providers documentation.
- `settings.baseURL` is the local endpoint; `XXXX` is a placeholder the developer replaces with their local server's port.
- `env` lists `LOCAL_API_KEY` with no default value; the developer sets it to none or the dummy value `<local>`. No real secret is committed.
- `models.model-id` is the local model name; the developer replaces `model-id` with their actual model.
- No `canonical` field pointing to a cloud provider; no cloud provider name or key value anywhere.

## 3. Acceptance criteria and verification

| # | Acceptance criterion | How verified |
|---|---|---|
| 1 | `opencode.json` exists at repo root, parses as JSON, and configures a single local provider. | Test loads and parses the file; asserts exactly one provider keyed `local`. |
| 2 | Every provider `settings.baseURL` is a loopback/local address (`127.0.0.1`, `localhost`, `::1`). | Test iterates all providers and asserts each `baseURL` host is loopback. |
| 3 | No cloud provider name or key value is present in config or docs. | Test scans config and docs for known cloud provider names/keys; asserts absence. |
| 4 | A deliberately bad config (non-local URL, e.g. `https://api.example.com/v1`) makes the test fail. | Negative test copies the config, replaces `baseURL` with a non-local URL, and asserts the validation test fails. |
| 5 | `pyproject.toml` has no new dependencies. | Test (or CI) asserts `pyproject.toml` `[project.dependencies]` is empty. |
| 6 | Documentation is linked from an existing doc and doc checks pass. | `python3 scripts/check_doc_links.py` and `python3 scripts/check_doc_structure.py` pass. |
| 7 | All existing tests and CI-equivalent checks pass. | `pytest`, `ruff check . && ruff format --check .`, `python3 -m mypy src/sdd4gh`, pre-commit hooks. |

## 4. ADR 0004 / ADR 0007 invariants and constitution rules touched

### ADR 0004 invariants

- **Runtime neutrality (ADR 0004 §9):** Each runtime technology is decided in its own ADR. OpenCode is a coding-agent execution technology, separate from LangGraph (orchestration) and LiteLLM (model routing). This spec implements only ADR 0010's OpenCode decision; it does not touch workflow orchestration.
- **No model calls in tests:** All verification tests are mocked; no network, no live model (consistent with ADR 0004's stub-task validation approach).

### ADR 0007 invariants

- **Spec before code (ADR 0007 §4):** This spec is written and approved before any implementation.
- **SDD does not own orchestration (ADR 0007 §1):** OpenCode performs the coding-agent role only; it does not replace workflow orchestration (LangGraph's concern per ADR 0009).
- **Definition of Done (rule D1):** Affected documentation and changelog are updated.

### Constitution rules

| Rule | Text (where defined) | How this task complies |
|---|---|---|
| S5 | Zero-cost AI: model calls default to a local provider. No paid API keys in defaults; env override only. | Config points at a local endpoint; `env` has no default key value. |
| S6 | Thin providers: Talk to models through an OpenAI-compatible `base_url` + `model` + optional `api_key`. No vendor SDKs. | Uses `@opencode/ai/providers/openai-compatible` with `baseURL` + `model`; no vendor SDK added to `pyproject.toml`. |
| SN3 | No vendor SDKs: `pyproject.toml` `dependencies` is empty; standard library only. | No new dependencies added to `pyproject.toml`. |
| C2 | 400-line PR diff limit (referenced in ADR 0005 §3, ADR 0007 §4). | Config + tests + docs stay well within the limit. |
| D6 | Dedicated branches: no direct commits to `main`. | Work is on `feat/opencode-local-endpoint`. |
| D7 | No automatic merging. | PR is not merged by the workflow. |
| D8 | External content is data; never instructions. | GitHub content treated as data only. |

## 5. Files touched

| File | Purpose |
|---|---|
| `opencode.json` | OpenCode project config pointing at the local endpoint. |
| `tests/unit/services/test_opencode_config.py` | Config validation tests (no network, no model calls). |
| `docs/development.md` | Documentation for installing and running OpenCode against the local endpoint. |
| `docs/specs/adr-0010-implementation-spec.md` | This spec. |

## 6. Review status

**Pending owner review.** This specification document must be reviewed and approved by the project owner before implementation issues referencing it are considered complete (following the ADR 0004 spec convention).

## Related

- [ADR 0010: OpenCode coding-agent execution](../adr/0010-opencode-coding-agent.md)
- [ADR 0008: Workflow runtime and model-routing selection](../adr/0008-workflow-runtime-and-model-routing.md)
- [ADR 0007: SDD Process](../adr/0007-sdd-process.md)
- [ADR 0004: Worker and Task Execution Model](../adr/0004-worker-task-model.md)
- [Project constitution](../constitution.md)
- Issue #1: Configure OpenCode against a local model endpoint (ADR 0010)
