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
