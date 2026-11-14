# Agent instructions

sdd4gh is the spec-driven development framework extracted from qnagym. It owns the Issue, SDD and PR process contracts, the worker/task model and the workflow orchestration. The product spec for the consuming CLI lives in qnagym.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"     # setup
pytest                      # tests (mocked HTTP, no live model)
ruff check . && ruff format --check .   # lint
python3 -m mypy src/sdd4gh              # type-check
python3 scripts/check_doc_links.py
python3 scripts/check_doc_structure.py
```

## Routing

| When | Read |
|---|---|
| opening any file under `docs/` for the first time | [`docs/documentation.md`](docs/documentation.md) |
| changing a process contract or data shape | the ADR in [`docs/adr/`](docs/adr/) |
| adding or changing a rule or threshold | the ADR that owns it, then [`docs/rules.md`](https://github.com/hlsekowski/qnagym/blob/main/docs/rules.md) |
| starting any change (branch, spec-first order, PR) | [`docs/development.md`](docs/development.md) |
| implementing an issue end to end | [`docs/procedures/implement-issue.md`](docs/procedures/implement-issue.md) |
| implementing ADR 0004 follow-up items | [`docs/specs/adr-0004-implementation-spec.md`](docs/specs/adr-0004-implementation-spec.md) |
| writing or reviewing tests | [`docs/testing.md`](docs/testing.md) |
| asking why a decision was made | the ADR in [`docs/adr/`](docs/adr/) |

Non-negotiable principles C1–C10 live in qnagym's [`docs/constitution.md`](https://github.com/hlsekowski/qnagym/blob/main/docs/constitution.md) and apply to every change here.
