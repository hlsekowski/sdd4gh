"""Shared constants (immutable values used across the framework boundary).

These symbols are consumed by both sdd4gh and qnagym. sdd4gh owns them
because the framework must be installable without qnagym; qnagym imports
them from here rather than duplicating the values (rules A1, A3).
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
WORKFLOW_COMMENT_MARKER = "<!-- qnagym-workflow -->"

__all__ = [
    "CONFIDENCE_SHOW_BELOW",
    "EVALUATION_RESULTS",
    "WORKFLOW_COMMENT_MARKER",
]
