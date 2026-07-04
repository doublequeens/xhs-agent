from types import SimpleNamespace

import pytest

from src.graph import next_node
from src.nodes.node_q_human_review import human_review_node
from src.nodes.node_q_01_final_policy_guard import (
    final_policy_guard_node,
    route_after_final_guard,
)
from src.nodes import node_i_r2_compliance as r2_module
from src.nodes import node_j_decision_engine as decision_module
from src.nodes.node_q_human_review import route_after_human_review


def _publish_package(**overrides):
    package = {
        "topic_id": "tp_001",
        "topic": "睡眠改善",
        "angle_id": "ag_001",
        "angle": "作息调整",
        "target_group": "上班族",
        "core_pain": "熬夜后疲惫",
        "title": "经验分享：调整作息的小习惯",
        "content": "先记录晚睡诱因，再逐步调整节奏。",
        "cover_copy": "作息调整记录",
        "hashtags": ["#作息调整", "#睡眠习惯"],
        "storyboards": [],
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


def test_enforce_blocked_r2_decision_preserves_model_tasks_and_adds_deterministic_tasks():
    decision_input = SimpleNamespace(
        content_snapshot=SimpleNamespace(
            draft_id="draft_001",
            revised_title="经验分享",
            revised_md="我写到褪黑素可以稳定提升深睡比例。",
            topic_id="tp_001",
            topic="睡眠改善",
            angle_id="ag_001",
            angle="作息调整",
            target_group="上班族",
            core_pain="熬夜后疲惫",
            best_cover_copy="cover",
        ),
        compliance_audit=SimpleNamespace(
            block_publish=True,
            required_fixes=[],
            suggested_fixes=[],
            matched_policy_rules=["medical_treatment"],
            unresolved_claims=["稳定提升深睡比例"],
        ),
        revision_meta=SimpleNamespace(
            revision_id="rev_001",
            round=2,
            diff_summary=["kept unsafe claim"],
            next_actions=["repair copy"],
        ),
    )
    decision_output_json = {
        "next_node": "R1_REFLECTOR",
        "normalized_input": {
            "r1_input": {
                "content_candidate": {
                    "draft_id": "draft_001",
                    "draft_md": "我写到褪黑素可以稳定提升深睡比例。",
                    "best_title": "经验分享",
                    "best_title_id": None,
                    "safer_title": None,
                    "safer_title_id": None,
                    "why_win": None,
                    "topic_id": "tp_001",
                    "topic": "睡眠改善",
                    "angle_id": "ag_001",
                    "angle": "作息调整",
                    "target_group": "上班族",
                    "core_pain": "熬夜后疲惫",
                    "best_cover_copy": "cover",
                },
                "editorial_tasks": {
                    "mandatory": [
                        {
                            "task_id": "model_task_001",
                            "source": "r2_compliance",
                            "instruction": "Clarify the anecdote.",
                            "severity": "medium",
                            "location_hint": "draft_md",
                            "rationale": "Model-identified clarity issue.",
                            "before": "褪黑素可以稳定提升深睡比例",
                            "after_hint": "Use narrower language.",
                        }
                    ],
                    "optional": [
                        {
                            "task_id": "de_policy_001",
                            "source": "system",
                            "instruction": "Remove or rewrite content that triggers policy rule `medical_treatment`.",
                            "severity": "low",
                            "location_hint": "draft_md",
                            "rationale": "This optional copy must not survive as optional.",
                            "before": None,
                            "after_hint": "Wrong bucket.",
                        }
                    ],
                },
                "revision_meta": {
                    "revision_id": "rev_001",
                    "round": 2,
                    "diff_summary": ["kept unsafe claim"],
                    "next_actions": ["repair copy"],
                },
                "decision_trace": {
                    "source_node": "R2_COMPLIANCE",
                    "why_this_route": ["model already routed back to R1"],
                },
            }
        },
    }

    first = decision_module._enforce_blocked_r2_decision(decision_output_json, decision_input)
    second = decision_module._enforce_blocked_r2_decision(first, decision_input)

    mandatory = first["normalized_input"]["r1_input"]["editorial_tasks"]["mandatory"]
    optional = first["normalized_input"]["r1_input"]["editorial_tasks"]["optional"]

    assert [task["task_id"] for task in mandatory] == [
        "model_task_001",
        "de_policy_001",
        "de_claim_001",
    ]
    assert mandatory[1]["source"] == "system"
    assert mandatory[2]["source"] == "system"
    assert all(task["task_id"] != "de_policy_001" for task in optional)
    assert second["normalized_input"]["r1_input"]["editorial_tasks"]["mandatory"] == mandatory
    assert second["normalized_input"]["r1_input"]["editorial_tasks"]["optional"] == optional


def test_merge_blocked_r2_tasks_removes_stale_deterministic_tasks_and_is_idempotent():
    r1_input = {
        "content_candidate": {
            "draft_id": "draft_001",
            "draft_md": "body",
            "best_title": "title",
            "best_title_id": None,
            "safer_title": None,
            "safer_title_id": None,
            "why_win": None,
            "topic_id": "tp_001",
            "topic": "睡眠改善",
            "angle_id": "ag_001",
            "angle": "作息调整",
            "target_group": "上班族",
            "core_pain": "熬夜后疲惫",
            "best_cover_copy": "cover",
        },
        "editorial_tasks": {
            "mandatory": [
                {
                    "task_id": "model_task_001",
                    "source": "r2_compliance",
                    "instruction": "Keep the calm tone.",
                    "severity": "medium",
                    "location_hint": "draft_md",
                    "rationale": "Model task should survive.",
                    "before": None,
                    "after_hint": None,
                },
                {
                    "task_id": "de_policy_001",
                    "source": "system",
                    "instruction": "Old deterministic task.",
                    "severity": "high",
                    "location_hint": "draft_md",
                    "rationale": "Should be removed when stale.",
                    "before": None,
                    "after_hint": None,
                },
            ],
            "optional": [
                {
                    "task_id": "de_claim_001",
                    "source": "system",
                    "instruction": "Old deterministic optional task.",
                    "severity": "low",
                    "location_hint": "draft_md",
                    "rationale": "Should be removed when stale.",
                    "before": None,
                    "after_hint": None,
                }
            ],
        },
        "revision_meta": {
            "revision_id": "rev_001",
            "round": 2,
            "diff_summary": ["blocked"],
            "next_actions": ["repair"],
        },
        "decision_trace": {
            "source_node": "R2_COMPLIANCE",
            "why_this_route": ["blocked"],
        },
    }
    blocked_tasks = {
        "mandatory": [
            {
                "task_id": "de_claim_002",
                "source": "system",
                "instruction": "Remove unsupported claim.",
                "severity": "high",
                "location_hint": "draft_md",
                "rationale": "Current deterministic task.",
                "before": "unsupported",
                "after_hint": "remove it",
            }
        ],
        "optional": [],
    }

    first = decision_module._merge_blocked_r2_tasks(r1_input, blocked_tasks)
    second = decision_module._merge_blocked_r2_tasks(first, blocked_tasks)

    assert [task["task_id"] for task in first["editorial_tasks"]["mandatory"]] == [
        "model_task_001",
        "de_claim_002",
    ]
    assert first["editorial_tasks"]["optional"] == []
    assert second == first


def test_human_review_patch_merges_visible_text_edit_and_routes_back_to_r2(monkeypatch):
    def fake_interrupt(_payload):
        return {
            "approved": True,
            "edited_publish_package": {
                "title": "更新后的标题",
                "storyboards": [{"frame_title": "新标题", "on_image_copy": "提示", "narration": "说明"}],
            },
            "feedback": "edited",
        }

    monkeypatch.setattr("src.nodes.node_q_human_review.interrupt", fake_interrupt)

    result = human_review_node(
        {
            "publish_package": _publish_package(
                storyboards=[{"frame_title": "旧标题", "on_image_copy": "旧提示", "narration": "旧说明"}]
            ),
            "review_round": 0,
            "final_policy_issues": [{"rule_id": "guaranteed_outcome"}],
            "domain_context": {"profile_version": "wellness-v1"},
            "r2_output": SimpleNamespace(
                content_snapshot=SimpleNamespace(draft_id="draft_001"),
                revision_meta=SimpleNamespace(
                    revision_id="rev_001",
                    round=1,
                    diff_summary=["first pass"],
                    next_actions=["human review"],
                ),
            ),
        }
    )

    assert result["publish_package"]["title"] == "更新后的标题"
    assert result["publish_package"]["topic_id"] == "tp_001"
    assert result["publish_package"]["hashtags"] == ["#作息调整", "#睡眠习惯"]
    assert result["review_status"] == "needs_r2_recheck"
    assert result["final_policy_issues"] == []
    assert route_after_human_review(result) == "r2_compliance"
    assert result["decision_output"].normalized_input.r2_input.content_snapshot.revised_title == "更新后的标题"
    assert result["decision_output"].normalized_input.r2_input.content_snapshot.revised_md == "先记录晚睡诱因，再逐步调整节奏。"
    assert result["decision_output"].normalized_input.r2_input.content_snapshot.model_dump() == {
        "draft_id": "draft_001",
        "revised_title": "更新后的标题",
        "revised_md": "先记录晚睡诱因，再逐步调整节奏。",
        "topic_id": "tp_001",
        "topic": "睡眠改善",
        "angle_id": "ag_001",
        "angle": "作息调整",
        "target_group": "上班族",
        "core_pain": "熬夜后疲惫",
        "best_cover_copy": "作息调整记录",
    }
    assert result["decision_output"].normalized_input.r2_input.revision_meta.round == 2
    assert result["decision_output"].normalized_input.r2_input.decision_trace.source_node == "HUMAN_REVIEW"


def test_human_review_unchanged_approval_routes_to_final_guard(monkeypatch):
    def fake_interrupt(_payload):
        return {
            "approved": True,
            "edited_publish_package": {"domain": "wellness"},
            "feedback": "ok",
        }

    monkeypatch.setattr("src.nodes.node_q_human_review.interrupt", fake_interrupt)

    result = human_review_node(
        {
            "publish_package": _publish_package(),
            "review_round": 0,
            "final_policy_issues": [],
            "domain_context": {"profile_version": "wellness-v1"},
        }
    )

    assert result["review_status"] == "approved"
    assert route_after_human_review(result) == "final_policy_guard"


def test_human_review_remembers_visible_edits_across_unapproved_rounds(monkeypatch):
    responses = iter(
        [
            {
                "approved": False,
                "edited_publish_package": {"content": "更新后的正文"},
                "feedback": "keep reviewing",
            },
            {
                "approved": True,
                "feedback": "approve prior edit",
            },
        ]
    )
    monkeypatch.setattr(
        "src.nodes.node_q_human_review.interrupt",
        lambda _payload: next(responses),
    )

    result = human_review_node(
        {
            "publish_package": _publish_package(),
            "review_round": 0,
            "final_policy_issues": [],
            "domain_context": {"profile_version": "wellness-v1"},
        }
    )

    assert result["publish_package"]["content"] == "更新后的正文"
    assert result["review_status"] == "needs_r2_recheck"
    assert route_after_human_review(result) == "r2_compliance"


def test_route_after_human_review_rejects_non_approved_state():
    with pytest.raises(ValueError, match="approved review"):
        route_after_human_review({"review_status": "pending"})


def test_final_policy_guard_requires_publish_package():
    with pytest.raises(ValueError, match="publish_package"):
        final_policy_guard_node({})


def test_final_policy_guard_routes_empty_publish_package_to_review():
    result = final_policy_guard_node({"publish_package": {}})

    assert route_after_final_guard(result) == "human_review"
    assert [issue["matched_text"] for issue in result["final_policy_issues"]] == [
        "topic_id",
        "topic",
        "angle_id",
        "angle",
        "target_group",
        "core_pain",
        "title",
        "content",
        "hashtags",
    ]


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


def test_final_policy_guard_blocks_missing_required_fields_before_writer():
    result = final_policy_guard_node(
        {
            "publish_package": _publish_package(
                topic_id="",
                title="",
                hashtags=None,
            )
        }
    )

    assert route_after_final_guard(result) == "human_review"
    assert [issue["matched_text"] for issue in result["final_policy_issues"][:3]] == [
        "topic_id",
        "title",
        "hashtags",
    ]


def test_final_policy_guard_blocks_required_fields_with_writer_unsafe_types():
    result = final_policy_guard_node(
        {
            "publish_package": _publish_package(
                topic=["not", "text"],
                hashtags=["#valid", None],
            )
        }
    )

    assert route_after_final_guard(result) == "human_review"
    assert [issue["matched_text"] for issue in result["final_policy_issues"][:2]] == [
        "topic",
        "hashtags",
    ]


def test_final_policy_guard_blocks_empty_required_hashtags():
    result = final_policy_guard_node(
        {"publish_package": _publish_package(hashtags=[])}
    )

    assert route_after_final_guard(result) == "human_review"
    assert result["final_policy_issues"][0]["matched_text"] == "hashtags"


def test_final_policy_guard_scans_storyboard_visible_text():
    result = final_policy_guard_node(
        {
            "publish_package": _publish_package(
                storyboards=[
                    {
                        "frame_title": "治·疗误区",
                        "on_image_copy": "先别停 药",
                        "narration": "每 天 250 毫克就够了",
                    }
                ]
            )
        }
    )

    assert route_after_final_guard(result) == "human_review"
    assert [issue["rule_id"] for issue in result["final_policy_issues"]] == [
        "medical_treatment",
        "medication_advice",
        "supplement_dosage",
    ]


def test_final_policy_guard_does_not_scan_storyboard_urls():
    result = final_policy_guard_node(
        {
            "publish_package": _publish_package(
                storyboards=[
                    {
                        "frame_title": "作息记录",
                        "on_image_copy": "循序渐进",
                        "narration": "分享个人体验",
                        "image_url": "https://example.test/保证治疗/每天250毫克.png",
                    }
                ]
            )
        }
    )

    assert result["final_policy_issues"] == []
    assert route_after_final_guard(result) == "content_writer"


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
