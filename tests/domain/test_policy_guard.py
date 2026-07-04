import pytest

from src.domain.policy_guard import find_policy_violations


def test_find_policy_violations_returns_empty_for_blank_text():
    assert find_policy_violations("   ") == []


def test_find_policy_violations_rejects_non_string():
    with pytest.raises(TypeError, match="text must be a string"):
        find_policy_violations(None)


def test_find_policy_violations_allows_general_language():
    issues = find_policy_violations("这篇内容只是在分享作息调整和放松习惯，没有医疗建议。")

    assert issues == []


def test_find_policy_violations_dedupes_rules_and_reports_multiple_categories():
    issues = find_policy_violations(
        "这种方法可以治疗和治愈问题，服用感冒药前别停药。"
        "化验结果代表身体状态，每天250毫克或每日2粒，保证百分百立即见效。"
    )

    assert [issue.rule_id for issue in issues] == [
        "medical_treatment",
        "medication_advice",
        "test_interpretation",
        "supplement_dosage",
        "guaranteed_outcome",
    ]
    assert issues[0].matched_text == "治疗"
    assert issues[1].matched_text == "服用感冒药"
    assert issues[2].matched_text == "化验结果代表"
    assert issues[3].matched_text == "每天250毫克"
    assert issues[4].matched_text == "保证"
    assert all(issue.location is None for issue in issues)


def test_find_policy_violations_matches_obfuscated_terms_after_normalization():
    issues = find_policy_violations(
        "这种说法能治·疗问题，建议停 药，"
        "每 天 250 毫克就够了，还能百分 百见效。"
    )

    assert [issue.rule_id for issue in issues] == [
        "medical_treatment",
        "medication_advice",
        "supplement_dosage",
        "guaranteed_outcome",
    ]


def test_find_policy_violations_avoids_benign_guarantee_and_generic_indicator_text():
    issues = find_policy_violations("保证睡够很重要，这只是普通活动的指标说明。")

    assert issues == []


def test_find_policy_violations_does_not_join_indicator_context_across_sentences():
    issues = find_policy_violations("这项指标用于记录活动完成度。说明身体感受时请保持客观。")

    assert issues == []
