# sdd4gh

Always-on SDD sentinel for GitHub: from issue to merged PR.

Spec-driven development framework extracted from
[qnagym](https://github.com/hlsekowski/qnagym). It owns the Issue, SDD and
PR process contracts, the worker/task model, and the workflow
orchestration. No third-party runtime dependencies — standard library only.

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

`CONFIDENCE_SHOW_BELOW`, `EVALUATION_RESULTS`, `WORKFLOW_COMMENT_MARKER`
and `ModelClientProtocol` are owned here and imported by qnagym, so the
framework stays installable on its own.

## Checks

```bash
pytest                                     # 491 tests
ruff check . && ruff format --check .
python3 -m mypy src/sdd4gh
python3 scripts/check_doc_links.py
python3 scripts/check_doc_structure.py
```

Agent instructions live in [`AGENTS.md`](AGENTS.md).
