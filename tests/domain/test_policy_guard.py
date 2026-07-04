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
