"""Unit tests for issue process contracts (ADR 0005)."""

import pytest

from sdd4gh.contracts.constants import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM
from sdd4gh.contracts.issue_process import (
    EVALUATION_FAIL,
    EVALUATION_INCONSISTENT,
    EVALUATION_PASS,
    ISSUE_STATE_PENDING,
    ISSUE_STATE_SEALED,
    TERMINAL_ISSUE_STATES,
    DecisionRecord,
    Issue,
    IssueAnalysis,
    IssueClarificationOption,
    IssueClarificationQuestion,
    IssueDecision,
    IssueEvaluation,
    IssueIdentity,
    IssueSummaryCheck,
)


class TestIssueIdentity:
    def test_identity_roundtrip(self):
        identity = IssueIdentity(number=42, repository="hlsekowski/example")
        assert IssueIdentity.from_dict(identity.to_dict()) == identity


class TestIssue:
    def test_issue_roundtrip(self):
        identity = IssueIdentity(number=42, repository="hlsekowski/example")
        issue = Issue(
            identity=identity,
            title="Test issue",
            description="description",
            description_hash="abc123",
            state=ISSUE_STATE_PENDING,
        )
        assert Issue.from_dict(issue.to_dict()) == issue

    def test_is_terminal(self):
        identity = IssueIdentity(number=1, repository="r")
        issue = Issue(identity=identity, title="t", description="d", description_hash="h")
        assert not issue.is_terminal
        issue.state = "Withdrawn"
        assert issue.is_terminal
        issue.state = "Excluded"
        assert issue.is_terminal

    def test_is_sealed(self):
        identity = IssueIdentity(number=1, repository="r")
        issue = Issue(identity=identity, title="t", description="d", description_hash="h")
        assert not issue.is_sealed
        issue.state = ISSUE_STATE_SEALED
        assert issue.is_sealed


class TestIssueEvaluation:
    def test_evaluation_roundtrip(self):
        evaluation = IssueEvaluation(
            result="Pass",
            confidence=0.98,
            reason="clear",
            clarity_pass=True,
            consistency_pass=True,
            change_type="feat",
            has_goal=True,
            has_acceptance_criteria=True,
            has_change_type=True,
            scope_fits_one_pr=True,
            no_contradictions=True,
            consistent_with_constitution=True,
            consistent_with_rules=True,
            consistent_with_spec=True,
            consistent_with_adrs=True,
            input_revision="abc123",
            input_type="description",
        )
        assert IssueEvaluation.from_dict(evaluation.to_dict()) == evaluation

    def test_analysis_roundtrip(self):
        analysis = IssueAnalysis(
            summary_check=IssueSummaryCheck(confidence=0.84, suggested_title="Clear title"),
            clarification_questions=(
                IssueClarificationQuestion(
                    question="Which behavior is intended?",
                    interpretation_confidence=0.90,
                    options=(
                        IssueClarificationOption("Choice A", 0.95),
                        IssueClarificationOption("Choice B", 0.85),
                        IssueClarificationOption("Choice C", 0.60),
                    ),
                ),
            ),
        )
        evaluation = IssueEvaluation(
            result=EVALUATION_FAIL,
            confidence=0.9,
            reason="unclear",
            clarity_pass=False,
            consistency_pass=True,
            analysis=analysis,
            analysis_attempts=5,
        )

        assert IssueEvaluation.from_dict(evaluation.to_dict()) == evaluation

    def test_analysis_refinement_thresholds(self):
        fits = IssueAnalysis(summary_check=IssueSummaryCheck(confidence=CONFIDENCE_MEDIUM))
        needs_refinement = IssueAnalysis(
            summary_check=IssueSummaryCheck(confidence=CONFIDENCE_MEDIUM),
            clarification_questions=(
                IssueClarificationQuestion(
                    question="Which behavior is intended?",
                    interpretation_confidence=0.90,
                    options=(
                        IssueClarificationOption("Choice A", CONFIDENCE_HIGH - 0.01),
                        IssueClarificationOption("Choice B", CONFIDENCE_MEDIUM),
                        IssueClarificationOption("Choice C", 0.60),
                    ),
                ),
            ),
        )

        assert not fits.needs_refinement
        assert needs_refinement.needs_refinement

    def test_analysis_at_shared_confidence_bands_does_not_need_refinement(self):
        analysis = IssueAnalysis(
            summary_check=IssueSummaryCheck(confidence=CONFIDENCE_MEDIUM),
            clarification_questions=(
                IssueClarificationQuestion(
                    question="Which behavior is intended?",
                    interpretation_confidence=0.90,
                    options=(
                        IssueClarificationOption("Choice A", CONFIDENCE_HIGH),
                        IssueClarificationOption("Choice B", CONFIDENCE_MEDIUM),
                        IssueClarificationOption("Choice C", 0.60),
                    ),
                ),
            ),
        )

        assert not analysis.needs_refinement

    def test_summary_mismatch_requires_replacement(self):
        with pytest.raises(ValueError, match="replacement title"):
            IssueAnalysis(summary_check=IssueSummaryCheck(confidence=0.84))

    def test_clarification_question_requires_subthreshold_confidence(self):
        options = (
            IssueClarificationOption("Answer A", CONFIDENCE_HIGH),
            IssueClarificationOption("Answer B", CONFIDENCE_MEDIUM),
            IssueClarificationOption("Answer C", 0.60),
        )

        with pytest.raises(ValueError, match="below 95%"):
            IssueClarificationQuestion(
                question="Which behavior is intended?",
                interpretation_confidence=0.95,
                options=options,
            )

    def test_clarification_question_requires_three_options(self):
        with pytest.raises(ValueError, match="exactly three"):
            IssueClarificationQuestion(
                question="Which behavior is intended?",
                interpretation_confidence=0.90,
                options=(IssueClarificationOption("Only answer", 0.95),),
            )


class TestDecisionRecord:
    def test_decision_record_roundtrip(self):
        record = DecisionRecord(
            decision_id="dr-1",
            input_revision="abc123",
            input_type="description",
            decision="accept",
            confidence=0.98,
            reason="clear and consistent",
            clarity_pass=True,
            consistency_pass=True,
            gate_passed=True,
            created_at=100.0,
        )
        assert DecisionRecord.from_dict(record.to_dict()) == record

    def test_decision_record_defaults(self):
        record = DecisionRecord(
            decision_id="dr-1",
            input_revision="abc123",
            input_type="description",
            decision="clarify",
            confidence=0.5,
            reason="unclear",
            clarity_pass=False,
            consistency_pass=True,
            gate_passed=False,
            created_at=100.0,
        )
        assert record.decision_id == "dr-1"
        assert record.input_type == "description"
        assert not record.gate_passed


class TestIssueDecision:
    def test_decision_roundtrip(self):
        decision = IssueDecision(
            action="AcceptAndSeal",
            reason="accepted",
            seal=True,
            create_branch=True,
            branch_name="feat/test",
            comment="sealed",
        )
        d = IssueDecision.from_dict(decision.to_dict())
        assert d.action == "AcceptAndSeal"
        assert d.invokes_sdd

    def test_invokes_sdd(self):
        decision = IssueDecision(action="x", reason="y", seal=True, create_branch=True)
        assert decision.invokes_sdd

        decision = IssueDecision(action="x", reason="y", seal=True, create_branch=False)
        assert not decision.invokes_sdd

        decision = IssueDecision(action="x", reason="y", seal=False, create_branch=True)
        assert not decision.invokes_sdd


class TestConstants:
    def test_terminal_states(self):
        assert "Withdrawn" in TERMINAL_ISSUE_STATES
        assert "Excluded" in TERMINAL_ISSUE_STATES
        assert ISSUE_STATE_PENDING not in TERMINAL_ISSUE_STATES

    def test_evaluation_results(self):
        assert EVALUATION_PASS == "Pass"
        assert EVALUATION_FAIL == "Fail"
        assert EVALUATION_INCONSISTENT == "Inconsistent"
