# ADR 0001: Spec-Driven Development

> **Purpose:** The decision to adopt spec-driven development as the framework's architecture.
> **Read when:** checking why the spec-first sequence exists, or what SDD commits this repository to.
> **Owns:** the decision to adopt SDD and its rationale. The executable sequence is owned by [`docs/workflow.md`](../workflow.md).

## Status

Accepted

## Context

sdd4gh is the spec-driven development framework extracted from
[qnagym](https://github.com/hlsekowski/qnagym). It owns the Issue, SDD and PR
process contracts, the worker/task model, and the workflow orchestration.

The framework was written against qnagym's SDD discipline from the start: every
module in `src/sdd4gh/` mirrors a decision recorded in `docs/adr/`, and every
decision names the code and tests that implement it. Extracting the framework
into its own repository would break that discipline if the decisions did not
come with it.

This ADR records the adoption of SDD for sdd4gh on its own terms. It is adapted
from qnagym's
[ADR 0001](https://github.com/hlsekowski/qnagym/blob/main/docs/adr/0001-spec-driven-development.md);
the decision is the same, the artifacts are this repository's.

## Decision

Adopt spec-driven development (SDD) as the framework's architectural decision:

1. **Decompose the framework into decision records** under [`docs/adr/`](.). Each ADR has an explicit **Decision** section that code and tests must conform to. ADR numbers are contiguous and never reused.
2. **Add a contracts layer in code** under `src/sdd4gh/contracts/`. Each module mirrors an ADR and defines the canonical data shapes, closed vocabularies and ports that framework code must conform to.
3. **Organize tests by decision traceability** under `tests/contracts/`, `tests/unit/` and `tests/integration/`. Each test file header cites the ADR it verifies.
4. **Keep the ADR set self-describing.** An ADR that depends on another states the dependency in its Context section, and links it in its Related Files section.

## Consequences

- Every code change starts from a decision record (constitution S2).
- A change with no covering ADR is either a bug fix inside an existing decision, or a new ADR.
- The ADR set is the specification. There is no separate `docs/spec/` tree here; qnagym owns the product spec.
- Cross-repository decisions (qnagym's constitution, its ADR 0001 and 0002) are linked by absolute URL, because a relative link cannot leave the repository.

## Alternatives Considered

- **Keep the decisions in qnagym and treat sdd4gh as unversioned code.** Rejected: the framework's ADRs 0003–0007 already cite ADR 0001 and 0002 as their basis, so the citations would dangle.
- **Write a fresh, unrelated decision set.** Rejected: it would discard the rationale that ADRs 0003–0007 depend on, and invite two competing methodologies (see ADR 0003).

## Related Files

- [`docs/workflow.md`](../workflow.md) — the executable change sequence
- [`docs/constitution.md`](../constitution.md) — principles S1–S8
- [ADR 0002](0002-architecture-dependency-model.md) — the layering decision this one implies
- [ADR 0003](0003-local-development-workflow.md) — the workflow model and its decision gate
- qnagym's [ADR 0001](https://github.com/hlsekowski/qnagym/blob/main/docs/adr/0001-spec-driven-development.md) — the decision this adapts