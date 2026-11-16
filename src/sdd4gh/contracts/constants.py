"""Shared constants (immutable values published by the framework).

These symbols are the closed vocabularies a consuming application imports
rather than duplicating, so both sides agree on one definition.
"""

from __future__ import annotations

# Decision-gate threshold: model confidence must be strictly above this
# value for an automated judgment to be authorized (ADR 0003 §3).
CONFIDENCE_SHOW_BELOW = 0.95

# Closed set of PR feedback evaluation results (ADR 0006 §1).
EVALUATION_RESULTS = frozenset(
    {"ClearActionable", "Ambiguous", "ScopeChange", "Conflict", "NoAction"}
)

# Prefix every workflow-authored comment carries, so its own comments are
# excluded from feedback and retry detection (ADR 0006 §5).
WORKFLOW_COMMENT_MARKER = "<!-- sdd4gh-workflow -->"


def is_workflow_comment(body: str) -> bool:
    """True when a comment body was authored by the workflow.
    """
    return body.startswith((WORKFLOW_COMMENT_MARKER))


__all__ = [
    "CONFIDENCE_SHOW_BELOW",
    "EVALUATION_RESULTS",
    "WORKFLOW_COMMENT_MARKER",
    "is_workflow_comment",
]
