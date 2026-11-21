"""Unit tests for the workflow orchestrator service (ADR 0003, ADR 0004, ADR 0005)."""

import tempfile

from sdd4gh.contracts.issue_process import (
    EVALUATION_FAIL,
    EVALUATION_PASS,
    Issue,
    IssueAnalysis,
    IssueEvaluation,
    IssueSummaryCheck,
)
from sdd4gh.contracts.task_model import ExecutionState
from sdd4gh.services.execution_state import ExecutionStateService
from sdd4gh.services.issue_evaluation import IssueEvaluator
from sdd4gh.services.workflow_orchestrator import WorkflowOrchestrator


class FakeEvaluator(IssueEvaluator):
    """Deterministic fake evaluator for tests."""

    def __init__(self, result: str = EVALUATION_PASS, reason: str = "pass"):
        self.result = result
        self.reason = reason
        self.called = 0
        self.descriptions: list[str] = []
        self.titles: list[str] = []

    def evaluate(
        self,
        issue: Issue,
        previous_analysis: IssueEvaluation | None = None,
    ) -> IssueEvaluation:
        self.called += 1
        self.descriptions.append(issue.description)
        self.titles.append(issue.title)
        return IssueEvaluation(
            result=self.result,
            confidence=0.99,
            reason=self.reason,
            clarity_pass=self.result == EVALUATION_PASS,
            consistency_pass=self.result == EVALUATION_PASS,
            change_type="feat",
            analysis=IssueAnalysis(summary_check=IssueSummaryCheck(confidence=0.95)),
        )


class FakeAdapter:
    """Fake effect adapter recording calls."""

    def __init__(self):
        self.posted: list[str] = []
        self.pushed: list[str] = []
        self.prs: list[dict] = []

    def post_comment(self, body: str) -> str:
        self.posted.append(body)
        return "comment-1"

    def push_branch(self, branch: str) -> str:
        self.pushed.append(branch)
        return branch

    def create_pull_request(self, title: str, body: str, head: str, base: str) -> str:
        self.prs.append({"title": title, "body": body, "head": head, "base": base})
        return "42"


def _service():
    return ExecutionStateService(tempfile.mkdtemp())


def _orchestrator(service=None, adapter=None, evaluator=None, state_name="wf_state"):
    if service is None:
        service = _service()
    if adapter is None:
        adapter = FakeAdapter()
    if evaluator is None:
        evaluator = FakeEvaluator()
    return WorkflowOrchestrator(
        service=service,
        state_name=state_name,
        evaluator=evaluator,
        adapter=adapter,
    )


class TestDiscoverAndEvaluate:
    def test_gate_pass_creates_task_and_evaluates(self):
        service = _service()
        adapter = FakeAdapter()
        evaluator = FakeEvaluator(result=EVALUATION_PASS)
        service.save("wf_state", ExecutionState())

        orch = _orchestrator(service, adapter, evaluator)
        outcome = orch.discover_and_evaluate(
            issue_number=42,
            repository="owner/repo",
            title="Add feature",
            description="A new feature",
            now=100.0,
        )

        assert "accept" in outcome.lower()
        assert evaluator.called == 1
        assert evaluator.descriptions == ["A new feature"]
        assert adapter.pushed == ["feat/add-feature"]
        assert len(adapter.prs) == 1
        assert len(adapter.posted) == 1
        assert "**Summary check" in adapter.posted[0]
        assert "Closes #42" in adapter.prs[0]["body"]

    def test_gate_fail_creates_task_and_clarifies(self):
        service = _service()
        adapter = FakeAdapter()
        evaluator = FakeEvaluator(result=EVALUATION_FAIL, reason="unclear goal")
        service.save("wf_state", ExecutionState())

        orch = _orchestrator(service, adapter, evaluator)
        outcome = orch.discover_and_evaluate(
            issue_number=42,
            repository="owner/repo",
            title="Vague issue",
            description="Do something",
            now=100.0,
        )

        assert "clarify" in outcome.lower()
        assert evaluator.called == 1
        assert evaluator.descriptions == ["Do something"]
        assert len(adapter.posted) == 1
        assert adapter.pushed == []
        assert adapter.prs == []

    def test_duplicate_issue_skipped(self):
        service = _service()
        adapter = FakeAdapter()
        evaluator = FakeEvaluator(result=EVALUATION_PASS)
        service.save("wf_state", ExecutionState())

        orch = _orchestrator(service, adapter, evaluator)
        orch.discover_and_evaluate(
            issue_number=42,
            repository="owner/repo",
            title="Add feature",
            description="A new feature",
            now=100.0,
        )
        # Second discovery of same issue should be skipped
        outcome = orch.discover_and_evaluate(
            issue_number=42,
            repository="owner/repo",
            title="Add feature",
            description="A new feature",
            now=200.0,
        )

        assert "skipped" in outcome.lower()

    def test_description_revision_is_part_of_task_identity(self):
        service = _service()
        adapter = FakeAdapter()
        evaluator = FakeEvaluator(result=EVALUATION_FAIL, reason="unclear goal")
        service.save("wf_state", ExecutionState())

        orch = _orchestrator(service, adapter, evaluator)
        first = orch.discover_and_evaluate(
            issue_number=42,
            repository="owner/repo",
            title="Same title",
            description="First description",
            now=100.0,
        )
        second = orch.discover_and_evaluate(
            issue_number=42,
            repository="owner/repo",
            title="Same title",
            description="Updated description",
            now=200.0,
        )

        assert "clarify" in first.lower()
        assert "clarify" in second.lower()
        assert evaluator.descriptions == ["First description", "Updated description"]

    def test_title_revision_is_part_of_task_identity(self):
        service = _service()
        adapter = FakeAdapter()
        evaluator = FakeEvaluator(result=EVALUATION_FAIL, reason="unclear goal")
        service.save("wf_state", ExecutionState())

        orch = _orchestrator(service, adapter, evaluator)
        orch.discover_and_evaluate(
            issue_number=42,
            repository="owner/repo",
            title="First title",
            description="Same description",
            now=100.0,
        )
        outcome = orch.discover_and_evaluate(
            issue_number=42,
            repository="owner/repo",
            title="Updated title",
            description="Same description",
            now=200.0,
        )

        assert "clarify" in outcome.lower()
        assert evaluator.titles == ["First title", "Updated title"]

    def test_state_persisted_after_evaluation(self):
        service = _service()
        adapter = FakeAdapter()
        evaluator = FakeEvaluator(result=EVALUATION_PASS)
        service.save("wf_state", ExecutionState())

        orch = _orchestrator(service, adapter, evaluator)
        orch.discover_and_evaluate(
            issue_number=42,
            repository="owner/repo",
            title="Add feature",
            description="A new feature",
            now=100.0,
        )

        state = orch.get_state()
        assert len(state.tasks) == 1
        task = list(state.tasks.values())[0]
        assert task.state == "Completed"

    def test_get_state(self):
        service = _service()
        adapter = FakeAdapter()
        evaluator = FakeEvaluator()
        service.save("wf_state", ExecutionState())

        orch = _orchestrator(service, adapter, evaluator)
        state = orch.get_state()
        assert isinstance(state, ExecutionState)
