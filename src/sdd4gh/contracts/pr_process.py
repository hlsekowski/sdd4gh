"""PR Process contract module.

Mirrors docs/adr/0006-pr-process.md §1–§5. Pure data shapes and closed
vocabularies; no orchestration logic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from qnagym.contracts.constants import (
    EVALUATION_RESULTS,
    WORKFLOW_COMMENT_MARKER,
)

# --- PR Process vocabularies (from docs/adr/0006-pr-process.md) ---

# Feedback event surfaces (ADR 0006 §1)
FEEDBACK_EVENT_TYPES = frozenset({"ConversationComment", "Review", "InlineComment", "Reply"})

# PR check statuses (ADR 0006 §2)
CHECK_STATUSES = frozenset(
    {
        "Passing",
        "Pending",
        "Running",
        "Failed",
        "Cancelled",
        "Skipped",
        "InfrastructureFailed",
        "ExternallyBlocked",
    }
)

# Check statuses that are not development failures and do not spend a
# correction attempt (ADR 0006 §2; docs/workflow.md step 8)
NON_FAILURE_CHECK_STATUSES = frozenset(
    {"Passing", "Pending", "Running", "Cancelled", "Skipped", "InfrastructureFailed"}
)

# Correction attempt steps (ADR 0006 §2)
CORRECTION_ATTEMPT_STEPS = frozenset({"Diagnosis", "Fix", "LocalVerification", "Push", "Observe"})

# Correction attempts allowed per batch (ADR 0006 §2)
MAX_CORRECTION_ATTEMPTS_PER_BATCH = 5

# PR lifecycle states (ADR 0006 §3)
PR_LIFECYCLE_STATES = frozenset(
    {
        "Monitoring",
        "ChecksPassClear",
        "ChecksPassPending",
        "ClosedAnomaly",
        "Merged",
        "PostMerge",
        "PostMergeBlocked",
        "Done",
    }
)

# PR lifecycle events (ADR 0006 §3)
PR_LIFECYCLE_EVENTS = frozenset(
    {
        "CheckResult",
        "Feedback",
        "PRClosed",
        "PRReopened",
        "IssueClosed",
        "PRMerged",
        "PostMergeStepResult",
    }
)

# Message routing targets (ADR 0006 §4)
MESSAGE_ROUTING_TARGETS = frozenset({"IssueComment", "PRComment", "ScopeChangeNotice"})

# PR feedback evaluation prompt (see docs/adr/0006-pr-process.md §1)
PR_FEEDBACK_SYSTEM = (
    "Return JSON only. Evaluate one PR feedback item against the accepted "
    "requirements. Decide whether a development change is needed, whether it "
    "conflicts with a non-negotiable rule, and whether it is an explicit scope "
    "change. Self-reported confidence 0-1. "
    '{"result":"ClearActionable|Ambiguous|ScopeChange|Conflict|NoAction",'
    '"confidence":0,"reason":"..."}.'
)

__all__ = [
    "CHECK_STATUSES",
    "CORRECTION_ATTEMPT_STEPS",
    "EVALUATION_RESULTS",
    "FEEDBACK_EVENT_TYPES",
    "MAX_CORRECTION_ATTEMPTS_PER_BATCH",
    "MESSAGE_ROUTING_TARGETS",
    "NON_FAILURE_CHECK_STATUSES",
    "PR_LIFECYCLE_EVENTS",
    "PR_LIFECYCLE_STATES",
    "WORKFLOW_COMMENT_MARKER",
    "FeedbackEvent",
    "EvaluationResult",
    "CheckResult",
    "CorrectionAttempt",
    "PRMessage",
    "PR_FEEDBACK_SYSTEM",
    "build_pr_feedback_messages",
    "parse_pr_feedback_response",
]


@dataclass
class FeedbackEvent:
    """A feedback item observed on a PR (ADR 0006 §1)."""

    event_type: str
    author: str
    body: str
    comment_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeedbackEvent:
        return cls(
            event_type=str(data.get("event_type", "")),
            author=str(data.get("author", "")),
            body=str(data.get("body", "")),
            comment_id=str(data.get("comment_id", "")),
        )


@dataclass
class EvaluationResult:
    """The outcome of evaluating one feedback item (ADR 0006 §1)."""

    result: str
    confidence: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvaluationResult:
        return cls(
            result=str(data.get("result", "")),
            confidence=float(data.get("confidence", 0.0)),
            reason=str(data.get("reason", "")),
        )


@dataclass
class CheckResult:
    """A PR check result event (ADR 0006 §2)."""

    name: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CheckResult:
        return cls(name=str(data.get("name", "")), status=str(data.get("status", "")))


@dataclass
class CorrectionAttempt:
    """One bounded correction attempt within a batch (ADR 0006 §2)."""

    step: str
    batch: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CorrectionAttempt:
        return cls(step=str(data.get("step", "")), batch=int(data.get("batch", 0)))


@dataclass
class PRMessage:
    """A workflow-authored message and where it is routed (ADR 0006 §4)."""

    target: str
    what_happened: str
    evidence: str
    decision: str
    completed: str
    pending: str
    automation_state: str
    user_next_step: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PRMessage:
        return cls(
            target=str(data.get("target", "")),
            what_happened=str(data.get("what_happened", "")),
            evidence=str(data.get("evidence", "")),
            decision=str(data.get("decision", "")),
            completed=str(data.get("completed", "")),
            pending=str(data.get("pending", "")),
            automation_state=str(data.get("automation_state", "")),
            user_next_step=str(data.get("user_next_step", "")),
        )


def build_pr_feedback_messages(
    event: FeedbackEvent,
    accepted_requirements: str,
) -> list[dict[str, str]]:
    """Build messages to evaluate one PR feedback item (ADR 0006 §1)."""
    return [
        {"role": "system", "content": PR_FEEDBACK_SYSTEM},
        {
            "role": "user",
            "content": (
                "Evaluate this feedback against the accepted requirements.\n"
                f"Surface: {event.event_type}\n"
                f"Author: {event.author}\n"
                f"Feedback: {event.body}\n"
                f"Accepted requirements: {accepted_requirements}"
            ),
        },
    ]


def parse_pr_feedback_response(response: dict[str, object]) -> EvaluationResult:
    """Parse a model response into an EvaluationResult (ADR 0006 §1)."""
    result = str(response.get("result", ""))
    if result not in EVALUATION_RESULTS:
        raise ValueError(f"Unknown evaluation result: {result!r}")
    return EvaluationResult(
        result=result,
        confidence=float(response.get("confidence", 0)),  # type: ignore[arg-type]
        reason=str(response.get("reason", "")),
    )
