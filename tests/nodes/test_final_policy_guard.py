from types import SimpleNamespace

import pytest

from src.graph import next_node
from src.nodes.node_q_human_review import human_review_node
from src.nodes.node_q_01_final_policy_guard import (
    final_policy_guard_node,
    route_after_final_guard,
)
from src.nodes import node_i_r2_compliance as r2_module


def _publish_package(**overrides):
    package = {
        "title": "经验分享：调整作息的小习惯",
        "content": "先记录晚睡诱因，再逐步调整节奏。",
        "cover_copy": "作息调整记录",
        "hashtags": ["#作息调整", "#睡眠习惯"],
        "domain": "wellness",
        "subdomain": "sleep",
        "content_intent": "how_to",
        "risk_level": "medium",
        "risk_flags": ["medical-adjacent"],
        "profile_version": "wellness-v1",
    }
    package.update(overrides)
    return package


def _r2_input(title="经验分享", body="分享我的作息调整记录。"):
    return SimpleNamespace(
        content_snapshot=SimpleNamespace(
            draft_id="draft_001",
            revised_title=title,
            revised_md=body,
            topic_id="tp_001",
            topic="睡眠改善",
            angle_id="ag_001",
            angle="作息调整",
            target_group="上班族",
            core_pain="熬夜后疲惫",
            best_cover_copy="cover",
        ),
        revision_meta=SimpleNamespace(
            revision_id="rev_001",
            round=1,
            diff_summary=["title refined"],
            next_actions=["run compliance audit"],
        ),
        decision_trace=SimpleNamespace(
            source_node="R1_REFLECTOR",
            why_this_route=["need compliance audit"],
        ),
    )


def _r2_state(title="经验分享", body="分享我的作息调整记录。", *, unsupported_claims=None):
    evidence_brief = SimpleNamespace(unsupported_claims=unsupported_claims or [])
    return {
        "decision_output": SimpleNamespace(normalized_input=SimpleNamespace(r2_input=_r2_input(title, body))),
        "domain_context": {"domain": "wellness", "profile_version": "wellness-v1"},
        "content_policy": {"risk_level": "medium"},
        "evidence_briefs": {"tp_001": evidence_brief},
    }


def test_r2_compliance_node_blocks_publish_when_deterministic_guard_finds_issues(monkeypatch):
    captured = {}

    class FakeModel:
        def execute(self, messages):
            captured["messages"] = messages
            return {
                "content_snapshot": {
                    "draft_id": "draft_001",
                    "revised_title": "保证立即见效",
                    "revised_md": "这个方法可以治疗失眠。",
                    "topic_id": "tp_001",
                    "topic": "睡眠改善",
                    "angle_id": "ag_001",
                    "angle": "作息调整",
                    "target_group": "上班族",
                    "core_pain": "熬夜后疲惫",
                    "best_cover_copy": "cover",
                },
                "compliance_audit": {
                    "compliance_status": "fully_compliant",
                    "issues": [],
                    "required_fixes": [],
                    "suggested_fixes": [],
                    "block_publish": False,
                    "matched_policy_rules": [],
                    "unresolved_claims": [],
                },
                "revision_meta": {
                    "revision_id": "rev_001",
                    "round": 1,
                    "diff_summary": ["title refined"],
                    "next_actions": ["publish"],
                },
            }

    monkeypatch.setattr(r2_module, "get_model", lambda *_args, **_kwargs: FakeModel())

    result = r2_module.r2_compliance_node(
        _r2_state(title="保证立即见效", body="这个方法可以治疗失眠。")
    )

    audit = result["r2_output"].compliance_audit
    prompt_text = captured["messages"][1].content

    assert audit.block_publish is True
    assert audit.matched_policy_rules == ["medical_treatment", "guaranteed_outcome"]
    assert "deterministic_policy_issues" in prompt_text
    assert "medical_treatment" in prompt_text
    assert "guaranteed_outcome" in prompt_text


def test_r2_compliance_node_blocks_publish_for_unresolved_claims(monkeypatch):
    captured = {}

    class FakeModel:
        def execute(self, messages):
            captured["messages"] = messages
            return {
                "content_snapshot": {
                    "draft_id": "draft_001",
                    "revised_title": "经验分享",
                    "revised_md": "我写到褪黑素可以稳定提升深睡比例。",
                    "topic_id": "tp_001",
                    "topic": "睡眠改善",
                    "angle_id": "ag_001",
                    "angle": "作息调整",
                    "target_group": "上班族",
                    "core_pain": "熬夜后疲惫",
                    "best_cover_copy": "cover",
                },
                "compliance_audit": {
                    "compliance_status": "fully_compliant",
                    "issues": [],
                    "required_fixes": [],
                    "suggested_fixes": [],
                    "block_publish": False,
                    "matched_policy_rules": [],
                    "unresolved_claims": [],
                },
                "revision_meta": {
                    "revision_id": "rev_001",
                    "round": 1,
                    "diff_summary": ["body refined"],
                    "next_actions": ["publish"],
                },
            }

    monkeypatch.setattr(r2_module, "get_model", lambda *_args, **_kwargs: FakeModel())

    result = r2_module.r2_compliance_node(
        _r2_state(
            body="我写到褪黑素可以稳定提升深睡比例。",
            unsupported_claims=["稳定提升深睡比例"],
        )
    )

    audit = result["r2_output"].compliance_audit
    prompt_text = captured["messages"][1].content

    assert audit.block_publish is True
    assert audit.unresolved_claims == ["稳定提升深睡比例"]
    assert "unresolved_claims" in prompt_text
    assert "稳定提升深睡比例" in prompt_text


def test_next_node_forces_r1_when_r2_audit_is_blocked():
    state = {
        "current_node": "R2_COMPLIANCE",
        "decision_output": SimpleNamespace(next_node="HASHTAG_SEO"),
        "r2_output": SimpleNamespace(
            compliance_audit=SimpleNamespace(
                block_publish=True,
                matched_policy_rules=["medical_treatment"],
                unresolved_claims=[],
            )
        ),
    }

    assert next_node(state) == "R1_REFLECTOR"


def test_final_policy_guard_requires_publish_package():
    with pytest.raises(ValueError, match="publish_package"):
        final_policy_guard_node({})


def test_final_policy_guard_routes_unsafe_package_back_to_human_review():
    result = final_policy_guard_node(
        {
            "publish_package": _publish_package(
                title="保证立即见效",
                content="这种方案可以治疗失眠。",
            )
        }
    )

    assert route_after_final_guard(result) == "human_review"
    assert [issue["rule_id"] for issue in result["final_policy_issues"]] == [
        "medical_treatment",
        "guaranteed_outcome",
    ]


def test_final_policy_guard_routes_clean_package_to_content_writer():
    result = final_policy_guard_node({"publish_package": _publish_package()})

    assert result["final_policy_issues"] == []
    assert route_after_final_guard(result) == "content_writer"


def test_edited_unsafe_package_loops_until_clean(monkeypatch):
    calls = []
    responses = iter(
        [
            {
                "approved": True,
                "edited_publish_package": _publish_package(
                    title="保证立即见效",
                    content="这种方案可以治疗失眠。",
                ),
                "feedback": "first pass",
            },
            {
                "approved": True,
                "edited_publish_package": _publish_package(
                    title="经验分享：调整作息的小习惯",
                    content="先记录晚睡诱因，再逐步调整节奏。",
                ),
                "feedback": "second pass",
            },
        ]
    )

    def fake_interrupt(payload):
        calls.append(payload)
        return next(responses)

    monkeypatch.setattr("src.nodes.node_q_human_review.interrupt", fake_interrupt)

    first_review = human_review_node(
        {
            "publish_package": _publish_package(),
            "review_round": 0,
            "final_policy_issues": [],
            "domain_context": {"profile_version": "wellness-v1"},
        }
    )
    first_guard = final_policy_guard_node(first_review)

    assert route_after_final_guard(first_guard) == "human_review"

    second_review = human_review_node(
        {
            **first_review,
            "final_policy_issues": first_guard["final_policy_issues"],
            "review_round": first_review["review_round"],
            "domain_context": {"profile_version": "wellness-v1"},
        }
    )
    second_guard = final_policy_guard_node(second_review)

    assert calls[1]["final_policy_issues"] == first_guard["final_policy_issues"]
    assert route_after_final_guard(second_guard) == "content_writer"
