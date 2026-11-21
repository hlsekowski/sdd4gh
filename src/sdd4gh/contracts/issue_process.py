"""Issue Process contracts (pure data shapes, no logic).

Mirrors docs/adr/0005-issue-process.md. Defines issue intake, evaluation,
acceptance, sealing, and reopening policies.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

# Issue-analysis limits and thresholds (ADR 0005 §3).
ISSUE_ANALYSIS_MAX_ATTEMPTS = 5
ISSUE_ANSWER_CONFIDENCE_THRESHOLD = 0.95
ISSUE_SUMMARY_FIT_THRESHOLD = 0.85

# --- Issue states (ADR 0005 lifecycle) ---

ISSUE_STATE_PENDING = "Pending"
ISSUE_STATE_EVALUATING = "Evaluating"
ISSUE_STATE_SEALED = "Sealed"
ISSUE_STATE_WITHDRAWN = "Withdrawn"
ISSUE_STATE_EXCLUDED = "Excluded"

ISSUE_STATES = frozenset(
    {
        ISSUE_STATE_PENDING,
        ISSUE_STATE_EVALUATING,
        ISSUE_STATE_SEALED,
        ISSUE_STATE_WITHDRAWN,
        ISSUE_STATE_EXCLUDED,
    }
)

# Terminal states
TERMINAL_ISSUE_STATES = frozenset({ISSUE_STATE_WITHDRAWN, ISSUE_STATE_EXCLUDED})

# --- Evaluation results ---

EVALUATION_PASS = "Pass"
EVALUATION_FAIL = "Fail"
EVALUATION_AMBIGUOUS = "Ambiguous"
EVALUATION_INCONSISTENT = "Inconsistent"

EVALUATION_RESULTS = frozenset(
    {EVALUATION_PASS, EVALUATION_FAIL, EVALUATION_AMBIGUOUS, EVALUATION_INCONSISTENT}
)

# --- Issue template fields ---

ISSUE_TEMPLATE_FIELDS = frozenset({"goal", "acceptance_criteria", "change_type"})

# --- Change types mapping to branch prefixes (docs/workflow.md) ---

CHANGE_TYPE_BRANCH_PREFIX: dict[str, str] = {
    "feat": "feat",
    "fix": "fix",
    "chore": "chore",
    "docs": "docs",
}

BRANCH_PREFIXES = frozenset(CHANGE_TYPE_BRANCH_PREFIX.values())


@dataclass(frozen=True)
class IssueIdentity:
    """The immutable identity of an issue."""

    number: int
    repository: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IssueIdentity:
        return cls(number=int(data["number"]), repository=str(data["repository"]))


@dataclass
class Issue:
    """An issue in the Issue Process (ADR 0005)."""

    identity: IssueIdentity
    title: str
    description: str
    description_hash: str
    state: str = ISSUE_STATE_PENDING
    sealed_description: str | None = None
    sealed_description_hash: str | None = None
    branch_name: str | None = None
    evaluation_count: int = 0
    last_evaluation_result: str | None = None
    last_evaluation_reason: str | None = None
    scheduled_evaluation_at: float | None = None
    is_reopened: bool = False
    is_exception: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "title": self.title,
            "description": self.description,
            "description_hash": self.description_hash,
            "state": self.state,
            "sealed_description": self.sealed_description,
            "sealed_description_hash": self.sealed_description_hash,
            "branch_name": self.branch_name,
            "evaluation_count": self.evaluation_count,
            "last_evaluation_result": self.last_evaluation_result,
            "last_evaluation_reason": self.last_evaluation_reason,
            "scheduled_evaluation_at": self.scheduled_evaluation_at,
            "is_reopened": self.is_reopened,
            "is_exception": self.is_exception,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Issue:
        return cls(
            identity=IssueIdentity.from_dict(data["identity"]),
            title=str(data["title"]),
            description=str(data["description"]),
            description_hash=str(data["description_hash"]),
            state=str(data.get("state", ISSUE_STATE_PENDING)),
            sealed_description=data.get("sealed_description"),
            sealed_description_hash=data.get("sealed_description_hash"),
            branch_name=data.get("branch_name"),
            evaluation_count=int(data.get("evaluation_count", 0)),
            last_evaluation_result=data.get("last_evaluation_result"),
            last_evaluation_reason=data.get("last_evaluation_reason"),
            scheduled_evaluation_at=data.get("scheduled_evaluation_at"),
            is_reopened=bool(data.get("is_reopened", False)),
            is_exception=bool(data.get("is_exception", False)),
        )

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_ISSUE_STATES

    @property
    def is_sealed(self) -> bool:
        return self.state == ISSUE_STATE_SEALED

    @property
    def is_pending(self) -> bool:
        return self.state == ISSUE_STATE_PENDING

    @property
    def is_evaluating(self) -> bool:
        return self.state == ISSUE_STATE_EVALUATING


@dataclass(frozen=True)
class IssueClarificationOption:
    """A candidate answer and its subjective confidence (ADR 0005 §3)."""

    answer: str
    confidence: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("answer confidence must be between 0 and 1")
        if not self.answer.strip():
            raise ValueError("candidate answer must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IssueClarificationOption:
        return cls(answer=str(data["answer"]), confidence=float(data["confidence"]))


@dataclass(frozen=True)
class IssueClarificationQuestion:
    """One unresolved point with three ranked candidate answers."""

    question: str
    interpretation_confidence: float
    options: tuple[IssueClarificationOption, ...]

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("clarification question must not be empty")
        if not 0.0 <= self.interpretation_confidence < ISSUE_ANSWER_CONFIDENCE_THRESHOLD:
            raise ValueError("clarification interpretation confidence must be below 0.95")
        if len(self.options) != 3:
            raise ValueError("each clarification question must have exactly three options")

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "interpretation_confidence": self.interpretation_confidence,
            "options": [option.to_dict() for option in self.options],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IssueClarificationQuestion:
        return cls(
            question=str(data["question"]),
            interpretation_confidence=float(data["interpretation_confidence"]),
            options=tuple(IssueClarificationOption.from_dict(item) for item in data["options"]),
        )


@dataclass(frozen=True)
class IssueSummaryCheck:
    """Confidence that the issue title summarizes its description."""

    confidence: float
    suggested_title: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("summary confidence must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IssueSummaryCheck:
        return cls(
            confidence=float(data["confidence"]),
            suggested_title=data.get("suggested_title"),
        )


@dataclass(frozen=True)
class IssueAnalysis:
    """Structured summary and clarification analysis for an issue."""

    summary_check: IssueSummaryCheck
    clarification_questions: tuple[IssueClarificationQuestion, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.summary_check.confidence < ISSUE_SUMMARY_FIT_THRESHOLD
            and not (self.summary_check.suggested_title or "").strip()
        ):
            raise ValueError("a replacement title is required when the summary does not fit")

    @property
    def needs_refinement(self) -> bool:
        """Whether another analysis attempt may improve a low-confidence result."""
        return self.summary_check.confidence < ISSUE_SUMMARY_FIT_THRESHOLD or any(
            max(option.confidence for option in question.options)
            < ISSUE_ANSWER_CONFIDENCE_THRESHOLD
            for question in self.clarification_questions
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary_check": self.summary_check.to_dict(),
            "clarification_questions": [
                question.to_dict() for question in self.clarification_questions
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IssueAnalysis:
        return cls(
            summary_check=IssueSummaryCheck.from_dict(data["summary_check"]),
            clarification_questions=tuple(
                IssueClarificationQuestion.from_dict(item)
                for item in data.get("clarification_questions", [])
            ),
        )


@dataclass
class IssueEvaluation:
    """The result of evaluating one issue (ADR 0005 §3).

    Includes observable clarity and consistency criteria breakdown
    (ADR 0003 follow-up item 1) and the exact input revision evaluated.
    """

    result: str
    confidence: float
    reason: str
    clarity_pass: bool
    consistency_pass: bool
    change_type: str | None = None

    # Observable clarity criteria (ADR 0003 follow-up item 1)
    has_goal: bool = False
    has_acceptance_criteria: bool = False
    has_change_type: bool = False
    scope_fits_one_pr: bool = False
    no_contradictions: bool = False

    # Observable consistency criteria (ADR 0003 follow-up item 1)
    consistent_with_constitution: bool = True
    consistent_with_rules: bool = True
    consistent_with_spec: bool = True
    consistent_with_adrs: bool = True

    # Exact input revision evaluated (ADR 0003 follow-up item 1)
    input_revision: str | None = None
    input_type: str | None = None  # "description" or "comment"
    analysis: IssueAnalysis | None = None
    analysis_attempts: int = 1

    def __post_init__(self) -> None:
        if not 1 <= self.analysis_attempts <= ISSUE_ANALYSIS_MAX_ATTEMPTS:
            raise ValueError(
                f"analysis_attempts must be between 1 and {ISSUE_ANALYSIS_MAX_ATTEMPTS}"
            )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["analysis"] = self.analysis.to_dict() if self.analysis is not None else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IssueEvaluation:
        return cls(
            result=str(data["result"]),
            confidence=float(data["confidence"]),
            reason=str(data["reason"]),
            clarity_pass=bool(data["clarity_pass"]),
            consistency_pass=bool(data["consistency_pass"]),
            change_type=data.get("change_type"),
            has_goal=bool(data.get("has_goal", False)),
            has_acceptance_criteria=bool(data.get("has_acceptance_criteria", False)),
            has_change_type=bool(data.get("has_change_type", False)),
            scope_fits_one_pr=bool(data.get("scope_fits_one_pr", False)),
            no_contradictions=bool(data.get("no_contradictions", False)),
            consistent_with_constitution=bool(data.get("consistent_with_constitution", True)),
            consistent_with_rules=bool(data.get("consistent_with_rules", True)),
            consistent_with_spec=bool(data.get("consistent_with_spec", True)),
            consistent_with_adrs=bool(data.get("consistent_with_adrs", True)),
            input_revision=data.get("input_revision"),
            input_type=data.get("input_type"),
            analysis=IssueAnalysis.from_dict(data["analysis"])
            if data.get("analysis") is not None
            else None,
            analysis_attempts=int(data.get("analysis_attempts", 1)),
        )


@dataclass
class DecisionRecord:
    """A decision record used before effects (ADR 0003 follow-up item 1).

    Records the exact input evaluated, the decision, confidence, and
    rationale, so that a restart cannot cause the same input to be
    evaluated under an unrecorded or different decision (ADR 0004 §10).
    """

    decision_id: str
    input_revision: str
    input_type: str  # "description" or "comment"
    decision: str  # "accept", "clarify", "reject", "invoke_sdd", etc.
    confidence: float
    reason: str
    clarity_pass: bool
    consistency_pass: bool
    gate_passed: bool
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DecisionRecord:
        return cls(
            decision_id=str(data["decision_id"]),
            input_revision=str(data["input_revision"]),
            input_type=str(data["input_type"]),
            decision=str(data["decision"]),
            confidence=float(data["confidence"]),
            reason=str(data["reason"]),
            clarity_pass=bool(data["clarity_pass"]),
            consistency_pass=bool(data["consistency_pass"]),
            gate_passed=bool(data["gate_passed"]),
            created_at=float(data["created_at"]),
        )


@dataclass
class IssueDecision:
    """What the Issue Process should do about one issue (ADR 0005 §4-§7)."""

    action: str
    reason: str
    seal: bool = False
    create_branch: bool = False
    branch_name: str | None = None
    comment: str | None = None
    scheduled_evaluation_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IssueDecision:
        return cls(
            action=str(data["action"]),
            reason=str(data["reason"]),
            seal=bool(data.get("seal", False)),
            create_branch=bool(data.get("create_branch", False)),
            branch_name=data.get("branch_name"),
            comment=data.get("comment"),
            scheduled_evaluation_at=data.get("scheduled_evaluation_at"),
        )

    @property
    def invokes_sdd(self) -> bool:
        return self.seal and self.create_branch


# Actions the Issue Process can produce.
ACTION_ACCEPT_AND_SEAL = "AcceptAndSeal"
ACTION_REQUEST_CLARIFICATION = "RequestClarification"
ACTION_REPORT_AMBIGUOUS_LINK = "ReportAmbiguousLink"
ACTION_POST_SEALED_EDIT_NOTICE = "PostSealedEditNotice"
ACTION_POST_REOPENED_NOTICE = "PostReopenedNotice"
ACTION_WITHDRAW = "Withdraw"
ACTION_EXCLUDE_REOPENED = "ExcludeReopened"
ACTION_NONE = "None"
