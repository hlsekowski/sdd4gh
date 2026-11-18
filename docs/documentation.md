# Documentation

> **Purpose:** Governs how documents under `docs/` are structured, so a reader can decide whether to open a file from its first lines.
> **Read when:** adding a document under `docs/`, or changing any document's header.
> **Owns:** the document header convention (Purpose / Read when / Owns) and the list of banned "Read when" phrases.

## Header convention

Every document under `docs/` opens with a blockquote header of at most three lines:

```
> **Purpose:** <one line: what this document is>
> **Read when:** <concrete trigger>
> **Owns:** <facts or rules this document is the source of truth for, or "nothing — index only">
```

- **Purpose** states what the document is, not what it contains.
- **Read when** names a concrete trigger a reader can match against their current task. Banned phrases: `when needed`, `as reference`, `for context`, `general guidance`, `overview`, `background`.
- **Owns** matches the owners chosen in the single-source-of-truth work: a document owns a fact only if it is the one place that fact is defined. Everything else links to the owner.

ADRs keep their existing template and `Status` field; the header is added above `## Status` without changing the status or decision text.

## Exclusions

- `AGENTS.md` and `README.md` are entry files and keep their own format.

## Documentation quality policy (DQ1–DQ5)

These principles govern every document under `docs/`, `AGENTS.md`, and `README.md`.

### DQ1 — Minimum sufficient information

Every document contains the information necessary for its intended purpose and audience. Remove:

- Repeated explanations.
- Redundant introductions and conclusions.
- Information that adds no practical value.
- Generic advice that does not influence project behavior.
- Obsolete instructions.

Do not remove information solely to reduce length.

### DQ2 — Information density

Prefer precise, actionable statements; clear headings; structured information where appropriate; examples that clarify non-obvious behavior; and explicit conditions, exceptions, and consequences. Avoid unnecessarily verbose explanations, ambiguous instructions, repeating the same concept in multiple forms, and excessive nested structures.

### DQ3 — Single source of truth

Each project rule, requirement, or decision has one authoritative location. Other documents reference that location rather than reproduce its content. Distinguish between normative rules, explanatory material, and references to other documents.

### DQ4 — Audience and context

Apply different standards to different document types:

| Document | Standard |
|---|---|
| `AGENTS.md` | Minimal, actionable, always-relevant agent instructions |
| `README.md` | Project introduction and onboarding |
| Procedures | Sufficient detail for reliable execution |
| ADRs | Complete decision rationale, alternatives, and consequences |
| Specifications | Complete requirements, constraints, and acceptance criteria |
| Historical documentation | Preserve useful historical context and decisions |

Do not introduce universal word-count or line-count limits for all Markdown files. Retain existing justified limits (AGENTS.md: 40 lines, README.md: 80 lines).

### DQ5 — Preserve decision integrity

Never simplify documentation by removing:

- Explicit requirements.
- Architectural decisions.
- Decision rationale.
- Important alternatives and trade-offs.
- Acceptance criteria.
- Constraints and assumptions.
- Security requirements.
- Exceptions.
- Dependencies and consequences.

Never change an accepted ADR decision or status as part of documentation optimization.

## Enforcement

Blocking rules are validated mechanically by the documentation checkers under `scripts/` and run on every commit through pre-commit and CI. Advisory rules (semantic quality such as unnecessary explanations or duplicated meaning) require human or AI-agent review and are not enforced by pre-commit.

Intentional removals of code paths are recorded in the
[dropped code paths catalog](dropped-code-paths.md).

## Reference integrity

`python3 scripts/check_doc_links.py` checks every tracked and unignored
untracked Markdown file in the repository, including prompts and GitHub
templates. It verifies local Markdown links and heading fragments,
backticked repository-file paths, repository-owned branch-specific `blob/`
URLs, and explicit ADR file/section references.

External URLs and GitHub issue, pull request, commit, symbol, and contextual
claims still need review before a PR. The checker cannot establish that an
external page is reachable or that any target supports the surrounding claim;
record evidence and exact corrections for findings that need manual review.
The inventory and evidence from the issue #19 audit are recorded in
[`audits/reference-audit-issue-19.md`](audits/reference-audit-issue-19.md).
