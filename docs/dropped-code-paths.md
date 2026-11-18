> **Purpose:** Catalog intentional removals of code paths and their rationale.
> **Read when:** deciding whether an absent or superseded code path should be restored or reused.
> **Owns:** the record of intentionally dropped code paths and their replacements.

# Dropped Code Paths

## Agent-facing index

Use this concise index to avoid reviving intentionally removed paths. Follow a
details link only when evaluating the removal or its replacement.

| Summary | Details |
|---|---|
| No dropped code paths have been recorded yet. | — |

## Recording a removal

When a change intentionally removes a code path, add one short index summary
that names the removed path and says not to follow it. Link that summary to a
details section below. Keep rationale and historical context out of the index.

Each details section records:

- The removed file, symbol, behavior, or other code path.
- Why it was removed.
- When it was removed, with the relevant issue or pull request.
- Its replacement or migration path, or that none exists.
- Any context needed to reassess the removal.
