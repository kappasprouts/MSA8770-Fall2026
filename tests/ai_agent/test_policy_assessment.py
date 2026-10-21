import pytest

from ai_agent.summarizing_agent import (
    build_policy_prompt,
    evaluate_test_score_policies,
)


def test_policy_prompt_includes_retrieved_policy_text():
    policy = {
        "policy_id": "POL-002",
        "content": "Evaluate the applicant's unweighted GPA in context.",
    }

    prompt = build_policy_prompt(
        {"app_id": "APP_TEST"}, [policy], {}, [], {}
    )

    assert policy["policy_id"] in prompt
    assert policy["content"] in prompt


@pytest.mark.parametrize(
    "sat,act,sat_alignment,act_alignment",
    [
        (1490, 34, "not_aligned", "aligned"),
        (1500, 33, "aligned", "not_aligned"),
        (1600, 36, "aligned", "aligned"),
        (None, 35, "not_applicable", "aligned"),
        (1550, None, "aligned", "not_applicable"),
    ],
)
def test_test_score_policies_evaluate_sat_and_act_independently(
    sat, act, sat_alignment, act_alignment
):
    policies = [
        {"policy_id": "POL-004", "content": "SAT between 1500 and 1600."},
        {"policy_id": "POL-005", "content": "ACT between 34 and 36."},
    ]

    assessments = evaluate_test_score_policies(
        {"superscored_sat_score": sat, "superscored_act_score": act},
        policies,
    )

    assert [entry["alignment"] for entry in assessments] == [
        sat_alignment, act_alignment
    ]
    assert all(entry["evidence_ids"] == [] for entry in assessments)
    assert all(entry["evidence"] == [] for entry in assessments)


def test_test_score_policies_reject_changed_reference_range():
    with pytest.raises(ValueError, match="Policy range has changed"):
        evaluate_test_score_policies(
            {"superscored_sat_score": 1550},
            [{"policy_id": "POL-004", "content": "SAT between 1400 and 1600."}],
        )
