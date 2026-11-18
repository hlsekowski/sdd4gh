# sdd4gh

Always-on SDD sentinel for GitHub: from issue to merged PR.

Spec-driven development framework. It owns the Issue, SDD and PR process
contracts, the worker/task model, and the workflow orchestration. No
third-party runtime dependencies — standard library only.

## Install

```bash
pip install -e ".[dev]"
```

## Quickstart

```python
from sdd4gh.services.workflow_orchestrator import WorkflowOrchestrator
```

## Layout

| Path | Owns |
|---|---|
| `src/sdd4gh/contracts/` | Process contracts and closed vocabularies (ADR 0003–0007) |
| `src/sdd4gh/domain/` | Pure decision logic: issue gate, PR feedback, checks, lifecycle, trust, task queue |
| `src/sdd4gh/services/` | Orchestration: task runner, effect log, GitHub observation, model routing |
| `docs/adr/` | The architecture decisions this code implements |
| `tests/` | Contract, unit and ADR-invariant tests |

## Shared symbols

[`CONFIDENCE_SHOW_BELOW`](src/sdd4gh/contracts/constants.py),
[`EVALUATION_RESULTS`](src/sdd4gh/contracts/constants.py),
[`WORKFLOW_COMMENT_MARKER`](src/sdd4gh/contracts/constants.py) and
[`ModelClientProtocol`](src/sdd4gh/contracts/ports.py) are published for a
consuming application to import, so both sides agree on one definition.

## Checks

```bash
pytest                                     # mocked HTTP, no live model
ruff check . && ruff format --check .
python3 -m mypy src/sdd4gh
python3 scripts/check_doc_links.py
python3 scripts/check_doc_structure.py
python3 scripts/check_traceability.py
python3 scripts/check_doc_defaults.py
```

Agent instructions live in [`AGENTS.md`](AGENTS.md).
