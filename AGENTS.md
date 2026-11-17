# Agent instructions

sdd4gh is a spec-driven development framework. It owns the Issue, SDD and PR process contracts, the worker/task model and the workflow orchestration.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"     # setup
pytest                      # tests (mocked HTTP, no live model)
ruff check . && ruff format --check .   # lint
python3 -m mypy src/sdd4gh              # type-check
python3 scripts/check_doc_links.py
python3 scripts/check_doc_structure.py
python3 scripts/check_traceability.py
python3 scripts/check_doc_defaults.py
```

## Routing

| When | Read |
|---|---|
| opening any file under `docs/` for the first time | [`docs/documentation.md`](docs/documentation.md) |
| changing a process contract or data shape | the ADR in [`docs/adr/`](docs/adr/), starting with [0002](docs/adr/0002-architecture-dependency-model.md) for layering |
| adding or changing a rule or threshold | the ADR that owns it, then [`docs/constitution.md`](docs/constitution.md) |
| starting any change (branch, spec-first order, PR) | [`docs/development.md`](docs/development.md) |
| implementing an issue end to end | [`docs/procedures/implement-issue.md`](docs/procedures/implement-issue.md) |
| implementing ADR 0004 follow-up items | [`docs/specs/adr-0004-implementation-spec.md`](docs/specs/adr-0004-implementation-spec.md) |
| implementing ADR 0010 (OpenCode coding-agent) | [`docs/specs/adr-0010-implementation-spec.md`](docs/specs/adr-0010-implementation-spec.md) |
| writing or reviewing tests | [`docs/testing.md`](docs/testing.md) |
| asking why a decision was made | the ADR in [`docs/adr/`](docs/adr/) |

Non-negotiable principles S1–S8 live in [`docs/constitution.md`](docs/constitution.md) and apply to every change here.
