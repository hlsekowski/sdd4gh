"""Unit tests for the issue-evaluation task service (ADR 0005)."""

import tempfile

import pytest

from sdd4gh.contracts.issue_process import (
    EVALUATION_FAIL,
    EVALUATION_PASS,
    Issue,
    IssueAnalysis,
    IssueClarificationOption,
    IssueClarificationQuestion,
    IssueEvaluation,
    IssueSummaryCheck,
)
from sdd4gh.contracts.task_model import (
    TASK_STATE_QUEUED,
    ExecutionState,
    Task,
    TaskIdentity,
)
from sdd4gh.services.effect_log import EffectAdapter, EffectAdapterError
from sdd4gh.services.execution_state import ExecutionStateService
from sdd4gh.services.issue_evaluation import (
    IssueEvaluationError,
    IssueEvaluationTask,
    IssueEvaluator,
)
from sdd4gh.services.issue_process import create_issue, issue_revision_hash


class FakeEvaluator(IssueEvaluator):
    """Deterministic fake evaluator for tests."""

    def __init__(
        self,
        result: str = EVALUATION_PASS,
        reason: str = "pass",
        analyses: list[IssueAnalysis] | None = None,
    ):
        self.result = result
        self.reason = reason
        self.analyses = analyses or [
            IssueAnalysis(summary_check=IssueSummaryCheck(confidence=0.95))
        ]
        self.called = 0
        self.previous_analyses: list[IssueEvaluation | None] = []

    def evaluate(
        self,
        issue: Issue,
        previous_analysis: IssueEvaluation | None = None,
    ) -> IssueEvaluation:
        self.called += 1
        self.previous_analyses.append(previous_analysis)
        assert issue.description == "A useful description"
        analysis = self.analyses[min(self.called - 1, len(self.analyses) - 1)]
        return IssueEvaluation(
            result=self.result,
            confidence=0.99,
            reason=self.reason,
            clarity_pass=self.result == EVALUATION_PASS,
            consistency_pass=self.result == EVALUATION_PASS,
            change_type="feat",
            analysis=analysis,
        )


class FakeAdapter(EffectAdapter):
    """Fake effect adapter recording calls."""

    def __init__(self):
        self.posted: list[str] = []
        self.pushed: list[str] = []
        self.prs: list[dict] = []
        self.fail_push = False
        self.fail_pr = False

    def post_comment(self, body: str) -> str:
        self.posted.append(body)
        return "comment-1"

    def push_branch(self, branch: str) -> str:
        if self.fail_push:
            raise EffectAdapterError("push failed")
        self.pushed.append(branch)
        return branch

    def create_pull_request(self, title: str, body: str, head: str, base: str) -> str:
        if self.fail_pr:
            raise EffectAdapterError("PR creation failed")
        self.prs.append({"title": title, "body": body, "head": head, "base": base})
        return "42"


def _service():
    return ExecutionStateService(tempfile.mkdtemp())


def _task(
    kind="issue_evaluation",
    work_item="158",
    target="158",
    revision=None,
    not_before=0.0,
):
    issue = _issue()
    return Task(
        identity=TaskIdentity(
            kind=kind,
            work_item=work_item,
            target=target,
            revision=revision or issue_revision_hash(issue.title, issue.description),
        ),
        created_time=1.0,
        not_before_time=not_before,
        event_time=None,
        state=TASK_STATE_QUEUED,
    )


def _issue() -> Issue:
    return create_issue(
        number=158,
        repository="owner/repo",
        title="Issue title",
        description="A useful description",
    )


def _issue_evaluation_task(service=None, adapter=None, evaluator=None, state_name="ie_state"):
    if service is None:
        service = _service()
    if adapter is None:
        adapter = FakeAdapter()
    if evaluator is None:
        evaluator = FakeEvaluator()
    return IssueEvaluationTask(
        service=service,
        state_name=state_name,
        evaluator=evaluator,
        adapter=adapter,
    )


class TestGatePass:
    def test_gate_pass_enqueues_effects(self):
        service = _service()
        adapter = FakeAdapter()
        evaluator = FakeEvaluator(result=EVALUATION_PASS)
        task = _task(not_before=100.0)
        service.save("ie_state", ExecutionState())

        ies = _issue_evaluation_task(service, adapter, evaluator)
        outcome = ies.run(task, _issue())

        assert "accept" in outcome.lower()
        assert adapter.pushed == ["feat/issue-title"]
        assert len(adapter.prs) == 1
        assert "Closes #158" in adapter.prs[0]["body"]
        assert len(adapter.posted) == 1
        assert "**Summary check (95% confidence):**" in adapter.posted[0]
        assert "\n" in adapter.posted[0]
        assert adapter.prs[0]["body"].startswith("<!-- sdd4gh-workflow -->")

    def test_gate_pass_no_second_marker(self):
        service = _service()
        adapter = FakeAdapter()
        evaluator = FakeEvaluator(result=EVALUATION_PASS)
        task = _task(not_before=100.0)
        service.save("ie_state", ExecutionState())

        ies = _issue_evaluation_task(service, adapter, evaluator)
        ies.run(task, _issue())

        # Only one workflow marker in the PR body
        body = adapter.prs[0]["body"]
        assert body.count("<!-- sdd4gh-workflow -->") == 1

    def test_analysis_comment_is_not_duplicated_on_replay(self):
        service = _service()
        adapter = FakeAdapter()
        evaluator = FakeEvaluator(result=EVALUATION_PASS)
        task = _task(not_before=100.0)
        issue = _issue()
        service.save("ie_state", ExecutionState())

        ies = _issue_evaluation_task(service, adapter, evaluator)
        ies.run(task, issue)
        outcome = ies.run(task, issue)

        assert "already opened" in outcome
        assert len(adapter.posted) == 1
        assert len(adapter.prs) == 1


class TestGateFail:
    def test_gate_fail_enqueues_clarification_only(self):
        service = _service()
        adapter = FakeAdapter()
        evaluator = FakeEvaluator(result=EVALUATION_FAIL, reason="unclear goal")
        task = _task(not_before=100.0)
        service.save("ie_state", ExecutionState())

        ies = _issue_evaluation_task(service, adapter, evaluator)
        outcome = ies.run(task, _issue())

        assert "clarify" in outcome.lower()
        assert len(adapter.posted) == 1
        assert adapter.posted[0].startswith("<!-- sdd4gh-workflow -->")
        assert "No clarification questions were generated." in adapter.posted[0]
        assert adapter.pushed == []
        assert adapter.prs == []

    def test_gate_fail_no_branch_created(self):
        service = _service()
        adapter = FakeAdapter()
        evaluator = FakeEvaluator(result=EVALUATION_FAIL, reason="unclear goal")
        task = _task(not_before=100.0)
        service.save("ie_state", ExecutionState())

        ies = _issue_evaluation_task(service, adapter, evaluator)
        ies.run(task, _issue())

        assert adapter.pushed == []
        assert adapter.prs == []


class TestNoModelCalls:
    def test_no_openai_call(self):
        service = _service()
        adapter = FakeAdapter()
        evaluator = FakeEvaluator(result=EVALUATION_PASS)
        task = _task(not_before=100.0)
        service.save("ie_state", ExecutionState())

        ies = _issue_evaluation_task(service, adapter, evaluator)
        ies.run(task, _issue())

        # FakeEvaluator is deterministic; no model involved
        assert evaluator.called == 1
        assert adapter.prs[0]["body"].startswith("<!-- sdd4gh-workflow -->")


class TestAnalysisRefinement:
    def test_refines_with_previous_result_until_confident(self):
        low_confidence = IssueAnalysis(
            summary_check=IssueSummaryCheck(confidence=0.84, suggested_title="Clearer title"),
        )
        confident = IssueAnalysis(summary_check=IssueSummaryCheck(confidence=0.85))
        evaluator = FakeEvaluator(analyses=[low_confidence, confident])
        service = _service()
        adapter = FakeAdapter()
        service.save("ie_state", ExecutionState())

        outcome = _issue_evaluation_task(service, adapter, evaluator).run(_task(), _issue())

        assert "accept" in outcome.lower()
        assert evaluator.called == 2
        assert evaluator.previous_analyses[0] is None
        assert evaluator.previous_analyses[1] is not None
        assert "Analysis attempts:** 2/5" in adapter.posted[0]

    def test_stops_after_five_attempts_and_reports_best_analysis(self):
        low_confidence = IssueAnalysis(
            summary_check=IssueSummaryCheck(confidence=0.84, suggested_title="Clearer title"),
        )
        evaluator = FakeEvaluator(
            result=EVALUATION_FAIL,
            reason="unclear requirements",
            analyses=[low_confidence],
        )
        service = _service()
        adapter = FakeAdapter()
        service.save("ie_state", ExecutionState())

        outcome = _issue_evaluation_task(service, adapter, evaluator).run(_task(), _issue())

        assert "clarify" in outcome.lower()
        assert evaluator.called == 5
        assert "Analysis attempts:** 5/5" in adapter.posted[0]
        assert "**Suggested title:** Clearer title" in adapter.posted[0]

    def test_questions_are_ranked_with_freeform_option(self):
        question = IssueClarificationQuestion(
            question="Which behavior should apply?",
            interpretation_confidence=0.90,
            options=(
                IssueClarificationOption("Least likely", 0.60),
                IssueClarificationOption("Most likely", 0.95),
                IssueClarificationOption("Middle choice", 0.85),
            ),
        )
        analysis = IssueAnalysis(
            summary_check=IssueSummaryCheck(confidence=0.95),
            clarification_questions=(question,),
        )
        evaluator = FakeEvaluator(result=EVALUATION_FAIL, analyses=[analysis])
        service = _service()
        adapter = FakeAdapter()
        service.save("ie_state", ExecutionState())

        outcome = _issue_evaluation_task(service, adapter, evaluator).run(_task(), _issue())

        assert "clarify" in outcome.lower()
        comment = adapter.posted[0]
        assert "**Question (90% interpretation confidence):**" in comment
        assert "**A.** Most likely (95% confidence)" in comment
        assert "**B.** Middle choice (85% confidence)" in comment
        assert "**C.** Least likely (60% confidence)" in comment
        assert "**D.** Describe another option." in comment
        assert "### Clarifications" in comment

    def test_task_rejects_mismatched_issue_revision(self):
        service = _service()
        service.save("ie_state", ExecutionState())
        ies = _issue_evaluation_task(service, evaluator=FakeEvaluator())

        with pytest.raises(IssueEvaluationError, match="does not match"):
            ies.run(_task(revision="wrong-revision"), _issue())

    def test_missing_structured_analysis_fails_closed(self):
        class IncompleteEvaluator(IssueEvaluator):
            def evaluate(
                self,
                issue: Issue,
                previous_analysis: IssueEvaluation | None = None,
            ) -> IssueEvaluation:
                return IssueEvaluation(
                    result=EVALUATION_PASS,
                    confidence=0.99,
                    reason="pass",
                    clarity_pass=True,
                    consistency_pass=True,
                    change_type="feat",
                )

        service = _service()
        service.save("ie_state", ExecutionState())
        ies = _issue_evaluation_task(service, evaluator=IncompleteEvaluator())

        with pytest.raises(IssueEvaluationError, match="did not return an analysis"):
            ies.run(_task(), _issue())
