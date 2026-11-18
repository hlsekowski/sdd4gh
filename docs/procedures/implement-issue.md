# Implement an issue

> **Purpose:** The invocable procedure for implementing one issue of this repository, end to end.
> **Read when:** invoked to implement an issue. Not loaded otherwise.
> **Owns:** nothing — every step links to its owner doc. The workflow itself is owned by [`docs/workflow.md`](../workflow.md).

Implement issue **#N** of this repository. Follow these steps in order. Where a step links to a document, read that document for the details; do not restate them here.

1. **Read the issue and its parent, if linked.** Open #N and any linked parent tracking issue. Note the issue's Tasks, Acceptance criteria and Out of scope sections — they define the scope.
2. **Check blockers.** Every issue listed under "Blocked by" must be closed. If any is open, comment on #N saying which one blocks it and stop.
3. **Apply an issue-specific applicability gate, if present.** If the issue or its accepted parent names a required audit, verify that record and #N's verdict. `APPLICABLE` → continue. `AMEND` → continue using the accepted issue body. `NOT APPLICABLE` → stop and comment. If a stated gate is missing or unresolved, stop and comment; do not guess or infer a gate from issue numbers or source-repository history.
4. **Create the branch.** Per rule D6 (dedicated branches) and the naming convention in [`docs/workflow.md`](../workflow.md): `git checkout -b <type>/<short-description>` from `main`.
5. **Follow the spec-first cycle.** Execute the steps in [`docs/workflow.md`](../workflow.md) in order. If the change alters product behaviour or a data shape, update the spec contract before code.
6. **Implement only the issue's scope.** Do not fix unrelated problems, even ones you notice. If anything is ambiguous, comment on #N with the specific question and stop — do not guess. Record every question and answer verbatim.
7. **Run all checks.** Every command in `AGENTS.md`'s Commands block, including the doc checks. All must pass before opening a PR.
8. **Open the PR.** Reference the issue with "Closes #N". Follow the repository PR template. If a parent tracking issue is linked, tick #N's box there and add a Decision-log line for any deviation from the issue's stated scope.

Stop conditions: a blocker is open, no verdict exists, the scope is ambiguous, or a check fails. In every case, comment on the issue and leave it open — never mark it blocked unilaterally.
