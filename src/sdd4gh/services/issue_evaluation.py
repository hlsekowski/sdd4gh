"""Issue-evaluation task service.

Mirrors docs/adr/0005-issue-process.md and docs/adr/0004-worker-task-model.md.
A worker task kind that calls the existing issue_process domain, not a new
policy. The injected evaluator returns a structured analysis, which is refined
up to the configured attempt limit and posted as one workflow-marked comment.
Only a passing decision proceeds to PR creation.
"""

from __future__ import annotations

from sdd4gh.contracts.constants import WORKFLOW_COMMENT_MARKER
from sdd4gh.contracts.issue_process import (
    ACTION_ACCEPT_AND_SEAL,
    ACTION_REQUEST_CLARIFICATION,
    ISSUE_ANALYSIS_MAX_ATTEMPTS,
    ISSUE_SUMMARY_FIT_THRESHOLD,
    Issue,
    IssueDecision,
    IssueEvaluation,
)
from sdd4gh.contracts.task_model import Task
from sdd4gh.domain.issue_process import decide_issue
from sdd4gh.services.effect_log import EffectAdapter, EffectLog, EffectLogError
from sdd4gh.services.execution_state import ExecutionStateService
from sdd4gh.services.issue_process import issue_revision_hash
from sdd4gh.services.pr_creation import PRCreation


class IssueEvaluationError(Exception):
    """Error during issue evaluation task execution."""


class IssueEvaluator:
    """Injected port for evaluating an issue.

    Tests provide a deterministic fake. Production would call a model.
    """

    def evaluate(
        self,
        issue: Issue,
        previous_analysis: IssueEvaluation | None = None,
    ) -> IssueEvaluation:
        """Evaluate one issue and return the result."""
        raise NotImplementedError


class IssueEvaluationTask:
    """Executes one issue-evaluation task attempt.

    Calls the issue_process domain to evaluate, then enqueues effects
    based on the decision. Never calls a model directly; the evaluator
    is injected.
    """

    def __init__(
        self,
        service: ExecutionStateService,
        state_name: str,
        evaluator: IssueEvaluator,
        adapter: EffectAdapter,
    ):
        self.service = service
        self.state_name = state_name
        self.evaluator = evaluator
        self.adapter = adapter
        self.effect_log = EffectLog(service, state_name, adapter)
        self.pr_creation = PRCreation(service, state_name, adapter)

    def run(self, task: Task, issue: Issue) -> str:
        """Run one issue-evaluation task attempt.

        Args:
            task: The task to execute.
            issue: The current issue revision supplied by the observer.

        Returns:
            An outcome string describing what happened.
        """
        self.service.load(self.state_name)

        if (
            not task.identity.target.isdigit()
            or int(task.identity.target) != issue.identity.number
            or task.identity.revision != issue_revision_hash(issue.title, issue.description)
        ):
            raise IssueEvaluationError("Task identity does not match the supplied issue revision")

        evaluation: IssueEvaluation | None = None
        for attempt in range(1, ISSUE_ANALYSIS_MAX_ATTEMPTS + 1):
            evaluation = self.evaluator.evaluate(issue, evaluation)
            if evaluation.analysis is None:
                raise IssueEvaluationError("Issue evaluator did not return an analysis")
            evaluation.analysis_attempts = attempt
            if not evaluation.analysis.needs_refinement:
                break

        if evaluation is None:
            raise IssueEvaluationError("Issue evaluator produced no result")

        # Decide using the issue_process domain
        decision = decide_issue(
            issue=issue,
            evaluation=evaluation,
            now=task.not_before_time,
        )

        if decision.action in {ACTION_ACCEPT_AND_SEAL, ACTION_REQUEST_CLARIFICATION}:
            self._post_analysis_comment(issue, evaluation, decision, task)

        # Enqueue effects based on the decision
        if decision.action == ACTION_ACCEPT_AND_SEAL:
            return self._handle_accept(issue, evaluation, decision, task)
        if decision.action == ACTION_REQUEST_CLARIFICATION:
            return f"clarify: {decision.reason}"
        return f"no action: {decision.reason}"

    def _task_key(self, task: Task) -> str:
        """Stable key for a task identity."""
        return (
            f"{task.identity.kind}|{task.identity.work_item or ''}|"
            f"{task.identity.target}|{task.identity.revision}|{task.identity.generation}"
        )

    def _post_analysis_comment(
        self,
        issue: Issue,
        evaluation: IssueEvaluation,
        decision: IssueDecision,
        task: Task,
    ) -> None:
        """Post the structured analysis once for this issue revision."""
        effect_id = f"issue_eval:{self._task_key(task)}:analysis"
        body = self._format_analysis_comment(issue, evaluation, decision)
        try:
            self.effect_log.dispatch_if_needed(
                effect_id=effect_id,
                task_identity_key=self._task_key(task),
                effect_step="post_analysis",
                body=body,
            )
        except EffectLogError as exc:
            raise IssueEvaluationError(f"Issue analysis comment failed: {exc}") from exc

    @staticmethod
    def _format_analysis_comment(
        issue: Issue,
        evaluation: IssueEvaluation,
        decision: IssueDecision,
    ) -> str:
        """Render title assessment and ranked clarification choices."""
        analysis = evaluation.analysis
        if analysis is None:
            raise IssueEvaluationError("Issue evaluator did not return an analysis")

        summary_check = analysis.summary_check
        summary_fits = summary_check.confidence >= ISSUE_SUMMARY_FIT_THRESHOLD
        lines = [
            WORKFLOW_COMMENT_MARKER,
            "## Issue analysis",
            "",
            (
                f"**Summary check ({summary_check.confidence:.0%} confidence):** "
                f"the title {issue.title!r} {'fits' if summary_fits else 'does not fit'} "
                "the description."
            ),
            (f"**Evaluation confidence:** {evaluation.confidence:.0%}. {evaluation.reason}"),
        ]
        if not summary_fits:
            if not summary_check.suggested_title:
                raise IssueEvaluationError(
                    "Issue evaluator did not propose a replacement for a mismatched title"
                )
            lines.append(f"**Suggested title:** {summary_check.suggested_title}")

        lines.extend(
            [
                "",
                (
                    f"**Analysis attempts:** {evaluation.analysis_attempts}/"
                    f"{ISSUE_ANALYSIS_MAX_ATTEMPTS}."
                ),
            ]
        )
        if analysis.clarification_questions:
            lines.extend(["", "### Clarifications"])
            for index, question in enumerate(analysis.clarification_questions, start=1):
                lines.extend(
                    [
                        "",
                        (
                            f"{index}. **Question ({question.interpretation_confidence:.0%} "
                            f"interpretation confidence):** {question.question}"
                        ),
                    ]
                )
                ranked_options = sorted(
                    enumerate(question.options),
                    key=lambda item: (-item[1].confidence, item[0]),
                )
                for label_index, (_, option) in enumerate(ranked_options):
                    label = chr(ord("A") + label_index)
                    lines.append(
                        f"   - **{label}.** {option.answer} ({option.confidence:.0%} confidence)"
                    )
                lines.append("   - **D.** Describe another option.")
        else:
            lines.extend(["", "No clarification questions were generated."])

        lines.extend(
            [
                "",
                (
                    "Confidence estimates are evidence-based subjective judgments, "
                    "not calibrated probabilities."
                ),
                f"**Decision:** {decision.action} — {decision.reason}.",
            ]
        )
        return "\n".join(lines)

    def _handle_accept(
        self,
        issue: Issue,
        evaluation: IssueEvaluation,
        decision: IssueDecision,
        task: Task,
    ) -> str:
        """Handle gate pass: enqueue sealing comment, branch, PR."""
        effect_id = f"issue_eval:{self._task_key(task)}:accept"

        # Build PR body with workflow marker
        body = (
            f"{WORKFLOW_COMMENT_MARKER}\n"
            f"**What happened:** Issue #{issue.identity.number} evaluated and accepted\n"
            f"**Evidence:** {evaluation.reason}\n"
            f"**Decision:** accept and seal\n"
            f"**Completed:** evaluation passed\n"
            f"**Pending:** branch creation and PR\n"
            f"**Automation state:** issue-evaluation task\n"
            f"**Next step for you:** review the PR"
        )

        pr_number = self.pr_creation.push_and_open_pr(
            effect_id=effect_id,
            task_identity_key=self._task_key(task),
            branch=decision.branch_name or "main",
            title=f"Evaluate issue #{issue.identity.number}",
            body=body,
            closes_issue=issue.identity.number,
        )

        if pr_number is None:
            return "accept: PR already opened (replay)"

        return f"accept: PR #{pr_number} opened"
