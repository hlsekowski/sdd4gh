"""Contract tests for structured Issue Process analysis.

Verifies ADR 0005 §3.
"""

from sdd4gh.contracts.issue_process import (
    EVALUATION_FAIL,
    IssueAnalysis,
    IssueClarificationOption,
    IssueClarificationQuestion,
    IssueEvaluation,
    IssueSummaryCheck,
)


def test_issue_analysis_contract_roundtrips_ranked_choices_and_summary():
    analysis = IssueAnalysis(
        summary_check=IssueSummaryCheck(confidence=0.80, suggested_title="A clearer title"),
        clarification_questions=(
            IssueClarificationQuestion(
                question="Which behavior is intended?",
                interpretation_confidence=0.90,
                options=(
                    IssueClarificationOption("Answer A", 0.95),
                    IssueClarificationOption("Answer B", 0.85),
                    IssueClarificationOption("Answer C", 0.60),
                ),
            ),
        ),
    )
    evaluation = IssueEvaluation(
        result=EVALUATION_FAIL,
        confidence=0.90,
        reason="requirements are unclear",
        clarity_pass=False,
        consistency_pass=True,
        analysis=analysis,
        analysis_attempts=3,
    )

    serialized = evaluation.to_dict()

    assert serialized["analysis"]["summary_check"] == {
        "confidence": 0.80,
        "suggested_title": "A clearer title",
    }
    assert [
        option["confidence"]
        for option in serialized["analysis"]["clarification_questions"][0]["options"]
    ] == [
        0.95,
        0.85,
        0.60,
    ]
    assert IssueEvaluation.from_dict(serialized) == evaluation
