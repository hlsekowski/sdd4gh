"""Shared constants (immutable values published by the framework).

These symbols are the closed vocabularies a consuming application imports
rather than duplicating, so both sides agree on one definition.
"""

from __future__ import annotations

# Shared confidence bands. The decision gate requires confidence strictly
# above CONFIDENCE_HIGH (ADR 0003 §3); CONFIDENCE_MEDIUM is used for
# non-authorizing assessments such as title-summary fit (ADR 0005 §3).
CONFIDENCE_HIGH = 0.95
CONFIDENCE_MEDIUM = 0.85

# Backwards-compatible name for the decision-gate threshold.
CONFIDENCE_SHOW_BELOW = CONFIDENCE_HIGH

# Closed set of PR feedback evaluation results (ADR 0006 §1).
EVALUATION_RESULTS = frozenset(
    {"ClearActionable", "Ambiguous", "ScopeChange", "Conflict", "NoAction"}
)

# Prefix every workflow-authored comment carries, so its own comments are
# excluded from feedback and retry detection (ADR 0006 §5).
WORKFLOW_COMMENT_MARKER = "<!-- sdd4gh-workflow -->"


def is_workflow_comment(body: str) -> bool:
    """True when a comment body was authored by the workflow."""
    return body.startswith(WORKFLOW_COMMENT_MARKER)


__all__ = [
    "CONFIDENCE_HIGH",
    "CONFIDENCE_MEDIUM",
    "CONFIDENCE_SHOW_BELOW",
    "EVALUATION_RESULTS",
    "WORKFLOW_COMMENT_MARKER",
    "is_workflow_comment",
]
