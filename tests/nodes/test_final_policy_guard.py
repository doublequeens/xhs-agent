import hashlib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.graph import next_node
from src.nodes.node_q_human_review import human_review_node
from src.nodes.node_q_01_final_policy_guard import (
    final_policy_guard_node,
    route_after_final_guard,
)
from src.nodes import node_i_r2_compliance as r2_module
from src.nodes import node_j_decision_engine as decision_module
from src.nodes import node_o_storyboards_generator as storyboard_module
from src.nodes.node_q_human_review import route_after_human_review
from src.nodes.publish_patch import extract_storyboard_visible_text
from src.schemas import R1Output


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
        "content_contract": {
            "audience": "上班族",
            "trigger_situation": "通勤前",
            "decision_problem": "如何安排日常习惯",
            "first_screen_promise": "通勤前快速掌握基础步骤",
            "screenshot_asset": "步骤清单截图",
            "proof_asset": "执行前后对比",
            "visual_mode": "text_card",
            "content_job": "save_and_check",
            "primary_visual_family": "saveable_reference",
            "primary_visual_subject": "checklist",
            "proof_mode": "diagram",
            "recommended_frame_count": 6,
        },
    }
    package.update(overrides)
    return package


def _legacy_guard_state(package):
    return {
        "publish_package": package,
        "legacy_editorial_checkpoint": True,
    }


def _editorial_guard_state(tmp_path: Path):
    active_root = tmp_path / "assets" / "active"
    active_root.mkdir(parents=True)
    asset_path = active_root / "asset.svg"
    asset_path.write_bytes(b"active asset")
    asset_sha = hashlib.sha256(asset_path.read_bytes()).hexdigest()

    image_dir = tmp_path / "images"
    image_dir.mkdir()
    pages = []
    for index in range(5):
        page_path = image_dir / f"{index + 1:02d}-page.png"
        Image.new("RGB", (16, 16), (index * 20, 20, 40)).save(page_path)
        role = "cover" if index == 0 else "detail"
        layout = "editorial_cover" if index == 0 else "texture_baseline"
        pages.append(
            SimpleNamespace(
                frame_id=f"frame-{index + 1}",
                role=role,
                layout=layout,
                path=str(page_path),
                sha256=hashlib.sha256(page_path.read_bytes()).hexdigest(),
                probe=SimpleNamespace(
                    text_results=[
                        SimpleNamespace(role="headline", text=f"Frame {index + 1}")
                    ]
                ),
            )
        )
    contact_sheet = image_dir / "contact-sheet.png"
    Image.new("RGB", (32, 16), "white").save(contact_sheet)

    package = _publish_package(
        rendered_image_paths=[page.path for page in pages],
        storyboards=[
            {
                "frame_id": page.frame_id,
                "role": page.role,
                "layout": page.layout,
                "headline": f"Frame {index + 1}",
                "content_blocks": [],
                "visual_slots": (
                    [{"slot_id": "slot-1", "role": "product_texture"}]
                    if index == 0
                    else []
                ),
            }
            for index, page in enumerate(pages)
        ],
    )
    asset_manifest = SimpleNamespace(
        items=[
            SimpleNamespace(
                slot_id="slot-1",
                role="product_texture",
                layout="editorial_cover",
                status="active",
                path=str(asset_path),
                sha256=asset_sha,
            )
        ]
    )
    render_manifest = SimpleNamespace(
        pages=pages,
        source_asset_sha256={"slot-1": asset_sha},
        contact_sheet_path=str(contact_sheet),
        contact_sheet_sha256=hashlib.sha256(contact_sheet.read_bytes()).hexdigest(),
        contact_sheet_page_sha256=[page.sha256 for page in pages],
    )
    return {
        "publish_package": package,
        "review_status": "approved",
        "visual_plan": SimpleNamespace(
            frame_plan=[
                SimpleNamespace(
                    frame_id=page.frame_id,
                    role=page.role,
                    layout=page.layout,
                )
                for page in pages
            ],
            required_assets=[
                SimpleNamespace(
                    slot_id="slot-1",
                    role="product_texture",
                    layout="editorial_cover",
                )
            ],
        ),
        "asset_manifest": asset_manifest,
        "render_manifest": render_manifest,
        "carousel_qa_result": {"passed": True},
        "render_qa_result": {"passed": True},
    }, active_root


def _storyboard_frame(frame_id, **overrides):
    frame = {
        "frame_id": frame_id,
        "template": "cover_statement",
        "theme": "warm_neutral",
        "kicker": "封面",
        "headline": f"标题 {frame_id}",
        "footer": "按需调整",
    }
    frame.update(overrides)
    return frame


def _modern_storyboard_frame(frame_id="frame_001", **overrides):
    frame = {
        "frame_id": frame_id,
        "role": "cover",
        "layout": "editorial_cover",
        "kicker": "封面",
        "headline": "作息调整",
        "content_blocks": [
            {
                "block_type": "text",
                "heading": "先看诱因",
                "body": "记录每天的作息变化",
                "items": ["项目一", "项目二"],
            }
        ],
        "emphasis": ["作息", "记录"],
        "visual_slots": [
            {
                "slot_id": f"{frame_id}-visual",
                "role": "product_texture",
                "semantic_tags": ["routine"],
                "composition": "right",
                "palette_tags": ["warm"],
            }
        ],
        "footer": "按需调整",
    }
    frame.update(overrides)
    return frame


def _structured_storyboards():
    common = {"theme": "warm_neutral", "footer": "按需调整"}
    return [
        {"frame_id": "frame_001", **common, "template": "cover_statement", "kicker": "封面", "headline": "作息调整"},
        {"frame_id": "frame_002", **common, "template": "wrong_vs_right", "kicker": "对照", "headline": "避免误区", "wrong_items": ["熬夜硬扛", "随意加量"], "right_items": ["记录诱因", "逐步调整"]},
        {"frame_id": "frame_003", **common, "template": "step_timeline", "kicker": "步骤", "headline": "逐步调整", "steps": [{"name": "记录", "hint": "观察诱因"}, {"name": "调整", "hint": "每次一项"}, {"name": "复盘", "hint": "每周总结"}]},
        {"frame_id": "frame_004", **common, "template": "saveable_checklist", "kicker": "保存", "headline": "睡前检查", "checklist_items": ["记录睡眠", "每天250毫克", "减少屏幕"]},
        {"frame_id": "frame_005", **common, "template": "decision_rule", "kicker": "判断", "headline": "先小步调整", "conditions": [{"situation": "连续疲惫", "recommendation": "优先规律作息"}, {"situation": "难以坚持", "recommendation": "缩小调整范围"}]},
        {"frame_id": "frame_006", **common, "template": "question_closer", "kicker": "讨论", "headline": "你会怎么做", "question": "你最想调整哪一步？"},
    ]


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


def test_r2_compliance_node_does_not_block_clean_fully_compliant_safety_rules(monkeypatch):
    class FakeModel:
        def execute(self, messages):
            return {
                "content_snapshot": {
                    "draft_id": "draft_001",
                    "revised_title": "作息记录",
                    "revised_md": "分享我的作息调整记录。",
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
                    "block_publish": True,
                    "matched_policy_rules": [
                        "no_prohibited_topics",
                        "no_prohibited_claims",
                        "disclaimer_included",
                    ],
                    "unresolved_claims": [],
                },
                "revision_meta": {
                    "revision_id": "rev_001",
                    "round": 1,
                    "diff_summary": ["clean"],
                    "next_actions": ["publish"],
                },
            }

    monkeypatch.setattr(r2_module, "get_model", lambda *_args, **_kwargs: FakeModel())

    result = r2_module.r2_compliance_node(
        _r2_state(title="作息记录", body="分享我的作息调整记录。")
    )

    audit = result["r2_output"].compliance_audit

    assert audit.block_publish is False
    assert audit.matched_policy_rules == [
        "no_prohibited_topics",
        "no_prohibited_claims",
        "disclaimer_included",
    ]


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


def test_deterministic_policy_task_keeps_title_location():
    r2_output = SimpleNamespace(
        content_snapshot=SimpleNamespace(
            revised_title="保证立即见效",
            revised_md="分享个人作息记录。",
        ),
        compliance_audit=SimpleNamespace(
            required_fixes=[],
            suggested_fixes=[],
            matched_policy_rules=["guaranteed_outcome"],
            unresolved_claims=[],
        ),
    )

    tasks = decision_module._build_blocked_r2_tasks(r2_output)

    assert tasks["mandatory"][0]["location_hint"] == "title"


def test_human_review_patch_merges_visible_text_edit_and_routes_back_to_r2(monkeypatch):
    def fake_interrupt(_payload):
        return {
            "approved": True,
            "edited_publish_package": {
                "title": "更新后的标题",
                "storyboards": [{"frame_id": "frame_001", "headline": "新标题"}],
            },
            "feedback": "edited",
        }

    monkeypatch.setattr("src.nodes.node_q_human_review.interrupt", fake_interrupt)

    result = human_review_node(
        {
            "publish_package": _publish_package(
                storyboards=[
                    {
                        "frame_id": "frame_001",
                        "template": "cover_statement",
                        "theme": "warm_neutral",
                        "kicker": "旧标签",
                        "headline": "旧标题",
                        "footer": "旧页脚",
                    }
                ]
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
        "storyboard_visible_text": [
                {
                    "frame_id": "frame_001",
                    "template": "cover_statement",
                    "text_blocks": {
                        "kicker": "旧标签",
                        "headline": "新标题",
                        "footer": "旧页脚",
                    },
            }
        ],
    }
    assert result["decision_output"].normalized_input.r2_input.revision_meta.round == 2
    assert result["decision_output"].normalized_input.r2_input.decision_trace.source_node == "HUMAN_REVIEW"


@pytest.mark.parametrize(
    "storyboard_patch",
    [
        {
            "frame_id": "frame_001",
            "content_blocks": [
                {
                    "block_type": "text",
                    "heading": "先看诱因",
                    "body": "人工改过的正文",
                    "items": ["项目一", "项目二"],
                }
            ],
        },
        {"frame_id": "frame_001", "layout": "decision_tree"},
        {
            "frame_id": "frame_001",
            "visual_slots": [
                {
                    "slot_id": "frame_001-new-visual",
                    "role": "comparison",
                    "semantic_tags": ["routine"],
                }
            ],
        },
    ],
    ids=("content-block", "layout", "asset-slot-structure"),
)
def test_human_review_modern_storyboard_edit_invalidates_downstream_artifacts(
    monkeypatch,
    storyboard_patch,
):
    monkeypatch.setattr(
        "src.nodes.node_q_human_review.interrupt",
        lambda _payload: {
            "approved": True,
            "edited_publish_package": {"storyboards": [storyboard_patch]},
        },
    )

    result = human_review_node(
        {
            "publish_package": _publish_package(
                storyboards=[_modern_storyboard_frame()]
            ),
            "review_round": 0,
            "final_policy_issues": [],
            "visual_plan": object(),
            "asset_manifest": {"items": []},
            "carousel_qa_result": {"passed": True},
            "render_manifest": {"pages": []},
            "render_qa_result": {"passed": True},
        }
    )

    assert result["review_status"] == "needs_r2_recheck"
    assert route_after_human_review(result) == "r2_compliance"
    assert result["visual_plan"] is None
    assert result["asset_manifest"] is None
    assert result["carousel_qa_result"] is None
    assert result["render_manifest"] is None
    assert result["render_qa_result"] is None


def test_human_review_enforces_title_max_length_including_punctuation(monkeypatch):
    def fake_interrupt(_payload):
        return {
            "approved": True,
            "edited_publish_package": {"title": "1234567890123456789！超长标题"},
            "feedback": "edited",
        }

    monkeypatch.setattr("src.nodes.node_q_human_review.interrupt", fake_interrupt)

    result = human_review_node(
        {
            "publish_package": _publish_package(),
            "review_round": 0,
            "final_policy_issues": [],
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

    title = result["publish_package"]["title"]
    assert title == "1234567890123456789！"
    assert len(title) == 20
    assert (
        result["decision_output"].normalized_input.r2_input.content_snapshot.revised_title
        == title
    )


def test_human_review_storyboard_patch_without_frame_id_merges_by_index(monkeypatch):
    monkeypatch.setattr(
        "src.nodes.node_q_human_review.interrupt",
        lambda _payload: {
            "approved": True,
            "edited_publish_package": {
                "storyboards": [{"theme": "cool_sage"}],
            },
        },
    )
    original_frames = [_storyboard_frame("frame_001"), _storyboard_frame("frame_002")]

    result = human_review_node(
        {
            "publish_package": _publish_package(storyboards=original_frames),
            "review_round": 0,
            "final_policy_issues": [],
        }
    )

    merged_frames = result["publish_package"]["storyboards"]
    assert merged_frames[0] == {
        **original_frames[0],
        "theme": "cool_sage",
    }
    assert merged_frames[1] == original_frames[1]


def test_human_review_storyboard_patch_merges_by_frame_id_and_appends_new_frame(monkeypatch):
    monkeypatch.setattr(
        "src.nodes.node_q_human_review.interrupt",
        lambda _payload: {
            "approved": True,
            "edited_publish_package": {
                "storyboards": [
                    {"frame_id": "frame_002", "theme": "cool_sage"},
                    _storyboard_frame("frame_003"),
                ],
            },
        },
    )
    original_frames = [_storyboard_frame("frame_001"), _storyboard_frame("frame_002")]

    result = human_review_node(
        {
            "publish_package": _publish_package(storyboards=original_frames),
            "review_round": 0,
            "final_policy_issues": [],
        }
    )

    merged_frames = result["publish_package"]["storyboards"]
    assert [frame["frame_id"] for frame in merged_frames] == [
        "frame_001",
        "frame_002",
        "frame_003",
    ]
    assert merged_frames[1] == {
        **original_frames[1],
        "theme": "cool_sage",
    }


def test_human_review_can_explicitly_replace_storyboards(monkeypatch):
    replacement = [_storyboard_frame("replacement")]
    monkeypatch.setattr(
        "src.nodes.node_q_human_review.interrupt",
        lambda _payload: {
            "approved": True,
            "replace_storyboards": True,
            "edited_publish_package": {"storyboards": replacement},
        },
    )

    result = human_review_node(
        {
            "publish_package": _publish_package(
                storyboards=[_storyboard_frame("frame_001"), _storyboard_frame("frame_002")]
            ),
            "review_round": 0,
            "final_policy_issues": [],
        }
    )

    assert result["publish_package"]["storyboards"] == replacement


def test_checklist_policy_task_uses_precise_location_and_patch_updates_card():
    storyboards = _structured_storyboards()
    snapshot = SimpleNamespace(
        revised_title="作息记录",
        revised_md="分享个人体验",
        storyboard_visible_text=extract_storyboard_visible_text(storyboards),
    )
    r2_output = SimpleNamespace(
        content_snapshot=snapshot,
        compliance_audit=SimpleNamespace(
            required_fixes=[], suggested_fixes=[], matched_policy_rules=["supplement_dosage"], unresolved_claims=[]
        ),
    )

    task = decision_module._build_blocked_r2_tasks(r2_output)["mandatory"][0]
    assert task["location_hint"] == "storyboard_visible_text[3].text_blocks.checklist_items[1]"

    patched = storyboard_module.apply_storyboard_visible_text_patch(
        storyboards,
        [{"frame_id": "frame_004", "template": "saveable_checklist", "text_blocks": {"checklist_items[1]": "咨询专业人士"}}],
    )
    assert patched[3]["checklist_items"][1] == "咨询专业人士"


def test_decision_condition_visible_atoms_are_extracted_and_reapplied_by_frame_id():
    storyboards = _structured_storyboards()
    visible = extract_storyboard_visible_text(storyboards)

    assert visible[4]["text_blocks"]["conditions[1].situation"] == "难以坚持"
    assert visible[4]["text_blocks"]["conditions[1].recommendation"] == "缩小调整范围"

    patched = storyboard_module.apply_storyboard_visible_text_patch(
        storyboards,
        [{"frame_id": "frame_005", "template": "decision_rule", "text_blocks": {
            "conditions[1].recommendation": "改成更小目标"
        }}],
    )

    assert patched[4]["conditions"][1]["recommendation"] == "改成更小目标"


def test_modern_content_blocks_and_emphasis_are_visible_text_atoms_and_reapplied():
    storyboards = [_modern_storyboard_frame()]

    visible = extract_storyboard_visible_text(storyboards)

    assert visible[0]["text_blocks"] == {
        "kicker": "封面",
        "headline": "作息调整",
        "footer": "按需调整",
        "content_blocks[0].heading": "先看诱因",
        "content_blocks[0].body": "记录每天的作息变化",
        "content_blocks[0].items[0]": "项目一",
        "content_blocks[0].items[1]": "项目二",
        "emphasis[0]": "作息",
        "emphasis[1]": "记录",
    }

    revised = deepcopy(visible)
    revised[0]["text_blocks"]["content_blocks[0].body"] = "先记录再调整"
    revised[0]["text_blocks"]["content_blocks[0].items[1]"] = "新的项目"
    revised[0]["text_blocks"]["emphasis[1]"] = "调整"

    patched = storyboard_module.apply_storyboard_visible_text_patch(
        storyboards,
        revised,
    )

    assert patched[0]["content_blocks"][0]["body"] == "先记录再调整"
    assert patched[0]["content_blocks"][0]["items"][1] == "新的项目"
    assert patched[0]["emphasis"][1] == "调整"


def test_visible_text_patch_rejects_unknown_nonempty_frame_id():
    with pytest.raises(ValueError, match="unknown frame_id"):
        storyboard_module.apply_storyboard_visible_text_patch(
            _structured_storyboards(),
            [{"frame_id": "stale_frame", "template": "cover_statement", "text_blocks": {"headline": "错误目标"}}],
        )


def test_blocked_storyboard_tasks_carry_visible_text_into_r1_candidate():
    storyboard_visible_text = [
        {
            "frame_id": "frame_001",
            "template": "cover_statement",
            "text_blocks": {"headline": "保证立即见效"},
        }
    ]
    r2_output = SimpleNamespace(
        content_snapshot=SimpleNamespace(
            draft_id="draft_001",
            revised_title="作息记录",
            revised_md="正文",
            topic_id="tp_001",
            topic="睡眠改善",
            angle_id="ag_001",
            angle="作息调整",
            target_group="上班族",
            core_pain="熬夜后疲惫",
            best_cover_copy="cover",
            storyboard_visible_text=storyboard_visible_text,
        ),
        revision_meta=SimpleNamespace(
            revision_id="rev_001",
            round=2,
            diff_summary=["blocked"],
            next_actions=["repair"],
        ),
        compliance_audit=SimpleNamespace(
            block_publish=True,
            required_fixes=[],
            suggested_fixes=[],
            matched_policy_rules=["guaranteed_outcome"],
            unresolved_claims=[],
        ),
    )

    enforced = decision_module._enforce_blocked_r2_decision(
        {"next_node": "HASHTAG_SEO", "normalized_input": {}},
        r2_output,
    )

    assert (
        enforced["normalized_input"]["r1_input"]["content_candidate"][
            "storyboard_visible_text"
        ]
        == storyboard_visible_text
    )


def test_r1_output_schema_retains_revised_storyboard_visible_text():
    storyboard_visible_text = [
        {
            "frame_id": "frame_001",
            "template": "cover_statement",
            "text_blocks": {"headline": "作息调整记录"},
        }
    ]

    output = R1Output(
        draft_id="draft_001",
        revised_title="作息记录",
        revised_md="正文",
        topic_id="tp_001",
        topic="睡眠改善",
        angle_id="ag_001",
        angle="作息调整",
        target_group="上班族",
        core_pain="熬夜后疲惫",
        best_cover_copy="cover",
        storyboard_visible_text=storyboard_visible_text,
        scores={
            "clarity_score": 1,
            "save_value_score": 1,
            "readability_score": 1,
            "authenticity_score": 1,
            "promise_alignment_score": 1,
        },
        revision_meta={
            "revision_id": "rev_002",
            "round": 3,
            "diff_summary": ["revised storyboard"],
            "next_actions": ["R2"],
        },
        task_report={
            "completed_task_ids": ["de_policy_guaranteed_outcome"],
            "skipped_task_ids": [],
            "notes": [],
        },
        remaining_risks=[],
        editor_notes=[],
        should_run_R1_again=False,
    )

    assert output.storyboard_visible_text[0].text_blocks["headline"] == "作息调整记录"


def test_decision_engine_propagates_r1_storyboard_text_into_r2_input():
    storyboard_visible_text = [
        {
            "frame_id": "frame_001",
            "template": "cover_statement",
            "text_blocks": {"headline": "作息调整记录"},
        }
    ]
    decision_json = {
        "next_node": "R2_COMPLIANCE",
        "normalized_input": {
            "r2_input": {
                "content_snapshot": {
                    "draft_id": "draft_001",
                    "revised_title": "作息记录",
                    "revised_md": "正文",
                    "topic_id": "tp_001",
                    "topic": "睡眠改善",
                    "angle_id": "ag_001",
                    "angle": "作息调整",
                    "target_group": "上班族",
                    "core_pain": "熬夜后疲惫",
                    "best_cover_copy": "cover",
                },
                "revision_meta": {
                    "revision_id": "rev_002",
                    "round": 3,
                    "diff_summary": ["revised storyboard"],
                    "next_actions": ["R2"],
                },
                "decision_trace": {
                    "source_node": "R1_REFLECTOR",
                    "why_this_route": ["recheck"],
                },
            }
        },
    }
    r1_output = SimpleNamespace(storyboard_visible_text=storyboard_visible_text)

    propagated = decision_module._propagate_storyboard_visible_text(
        decision_json,
        r1_output,
    )

    assert (
        propagated["normalized_input"]["r2_input"]["content_snapshot"][
            "storyboard_visible_text"
        ]
        == storyboard_visible_text
    )


def test_regenerated_storyboards_reapply_visible_text_patch(monkeypatch):
    frames = _structured_storyboards()
    frames[3]["checklist_items"][0] = "生成器的新清单"

    class FakeStoryboardModel:
        def execute(self, _messages):
            return {"storyboards": frames}

    monkeypatch.setattr(storyboard_module, "get_model", lambda: FakeStoryboardModel())
    regenerated = storyboard_module.storyboards_generator_node(
        {
            "publish_package": _publish_package(storyboards=_structured_storyboards()),
            "pending_human_publish_patch": {"storyboards": [{"frame_id": "frame_001", "theme": "cool_sage", "headline": "stale"}]},
            "pending_human_replace_storyboards": False,
            "r2_output": SimpleNamespace(content_snapshot=SimpleNamespace(storyboard_visible_text=[
                {"frame_id": "frame_001", "template": "cover_statement", "text_blocks": {"headline": "R2修订标题"}}
            ])),
            "trends": [SimpleNamespace(topic_id="tp_001", content_contract=_publish_package()["content_contract"])],
        }
    )

    first_frame = regenerated["publish_package"]["storyboards"][0]
    assert first_frame["theme"] == "cool_sage"
    assert first_frame["headline"] == "R2修订标题"
    assert first_frame["footer"] == "按需调整"
    assert regenerated["publish_package"]["storyboards"][3]["checklist_items"] == [
        "记录睡眠", "每天250毫克", "减少屏幕"
    ]


def test_regenerated_storyboards_apply_complete_r2_visible_text_without_human_patch(monkeypatch):
    generated_frames = _structured_storyboards()
    generated_frames[0]["headline"] = "生成器的新标题"
    generated_frames[3]["checklist_items"][1] = "生成器的新清单"
    r2_visible_text = extract_storyboard_visible_text(_structured_storyboards())
    r2_visible_text[0]["text_blocks"]["headline"] = "R2修订标题"
    r2_visible_text[3]["text_blocks"]["checklist_items[1]"] = "咨询专业人士"

    class FakeStoryboardModel:
        def execute(self, _messages):
            return {"storyboards": generated_frames}

    monkeypatch.setattr(storyboard_module, "get_model", lambda: FakeStoryboardModel())
    regenerated = storyboard_module.storyboards_generator_node(
        {
            "publish_package": _publish_package(storyboards=_structured_storyboards()),
            "r2_output": SimpleNamespace(
                content_snapshot=SimpleNamespace(storyboard_visible_text=r2_visible_text)
            ),
            "trends": [
                SimpleNamespace(
                    topic_id="tp_001",
                    content_contract=_publish_package()["content_contract"],
                )
            ],
        }
    )

    assert (
        extract_storyboard_visible_text(regenerated["publish_package"]["storyboards"])
        == r2_visible_text
    )


def test_visible_text_merge_rejects_unknown_frame_id_and_ignores_empty_frame_id():
    prior_visible_text = extract_storyboard_visible_text(_structured_storyboards())

    with pytest.raises(ValueError, match="unknown frame_id"):
        storyboard_module.merge_storyboard_visible_text(
            prior_visible_text,
            [
                {
                    "frame_id": "stale_frame",
                    "template": "cover_statement",
                    "text_blocks": {"headline": "错误目标"},
                }
            ],
        )

    assert storyboard_module.merge_storyboard_visible_text(
        prior_visible_text,
        [{"frame_id": "", "text_blocks": {"headline": "忽略"}}],
    ) == prior_visible_text


def test_r2_merges_partial_visible_text_with_all_cards_before_policy_scan(monkeypatch):
    class FakeModel:
        def execute(self, _messages):
            return {
                "content_snapshot": {
                    "draft_id": "draft_001",
                    "revised_title": "经验分享",
                    "revised_md": "分享我的作息调整记录。",
                    "topic_id": "tp_001",
                    "topic": "睡眠改善",
                    "angle_id": "ag_001",
                    "angle": "作息调整",
                    "target_group": "上班族",
                    "core_pain": "熬夜后疲惫",
                    "best_cover_copy": "cover",
                    "storyboard_visible_text": [
                        {"frame_id": "frame_001", "template": "cover_statement", "text_blocks": {"headline": "R2标题"}}
                    ],
                },
                "compliance_audit": {"compliance_status": "fully_compliant"},
                "revision_meta": {"revision_id": "rev_001", "round": 1, "diff_summary": [], "next_actions": []},
            }

    monkeypatch.setattr(r2_module, "get_model", lambda *_args, **_kwargs: FakeModel())
    state = _r2_state()
    state["publish_package"] = _publish_package(storyboards=_structured_storyboards())

    result = r2_module.r2_compliance_node(state)

    visible_text = result["r2_output"].content_snapshot.storyboard_visible_text
    assert len(visible_text) == 6
    assert visible_text[0].text_blocks["headline"] == "R2标题"
    assert visible_text[3].text_blocks["checklist_items[1]"] == "每天250毫克"
    assert "supplement_dosage" in result["r2_output"].compliance_audit.matched_policy_rules


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
    result = final_policy_guard_node(_legacy_guard_state({}))

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
        _legacy_guard_state(
            _publish_package(
                title="保证立即见效",
                content="这种方案可以治疗失眠。",
            )
        )
    )

    assert route_after_final_guard(result) == "human_review"
    assert [issue["rule_id"] for issue in result["final_policy_issues"]] == [
        "medical_treatment",
        "guaranteed_outcome",
    ]


def test_final_policy_guard_blocks_missing_required_fields_before_writer():
    result = final_policy_guard_node(
        _legacy_guard_state(
            _publish_package(
                topic_id="",
                title="",
                hashtags=None,
            )
        )
    )

    assert route_after_final_guard(result) == "human_review"
    assert [issue["matched_text"] for issue in result["final_policy_issues"][:3]] == [
        "topic_id",
        "title",
        "hashtags",
    ]


def test_final_policy_guard_blocks_required_fields_with_writer_unsafe_types():
    result = final_policy_guard_node(
        _legacy_guard_state(
            _publish_package(
                topic=["not", "text"],
                hashtags=["#valid", None],
            )
        )
    )

    assert route_after_final_guard(result) == "human_review"
    assert [issue["matched_text"] for issue in result["final_policy_issues"][:2]] == [
        "topic",
        "hashtags",
    ]


def test_final_policy_guard_blocks_empty_required_hashtags():
    result = final_policy_guard_node(_legacy_guard_state(_publish_package(hashtags=[])))

    assert route_after_final_guard(result) == "human_review"
    assert result["final_policy_issues"][0]["matched_text"] == "hashtags"


def test_final_policy_guard_scans_storyboard_visible_text():
    result = final_policy_guard_node(
        _legacy_guard_state(
            _publish_package(
                storyboards=[
                    {
                        "frame_id": "frame_004",
                        "template": "saveable_checklist",
                        "theme": "warm_neutral",
                        "kicker": "保存",
                        "headline": "治·疗误区",
                        "footer": "按需调整",
                        "checklist_items": ["记录变化", "先别停 药", "每 天 250 毫克就够了"],
                    }
                ]
            )
        )
    )

    assert route_after_final_guard(result) == "human_review"
    assert [issue["rule_id"] for issue in result["final_policy_issues"]] == [
        "medical_treatment",
        "medication_advice",
        "supplement_dosage",
    ]


@pytest.mark.parametrize(
    "content_blocks,expected_rule",
    [
        (
            [{"block_type": "text", "body": "这种方案可以治·疗失眠"}],
            "medical_treatment",
        ),
        (
            [{"block_type": "checklist", "items": ["先记录", "保证立即见效"]}],
            "guaranteed_outcome",
        ),
    ],
    ids=("body", "item"),
)
def test_final_policy_guard_scans_modern_content_block_visible_text(
    content_blocks,
    expected_rule,
):
    result = final_policy_guard_node(
        _legacy_guard_state(
            _publish_package(
                storyboards=[
                    _modern_storyboard_frame(content_blocks=content_blocks)
                ]
            )
        )
    )

    assert expected_rule in {
        issue["rule_id"] for issue in result["final_policy_issues"]
    }


def test_final_policy_guard_does_not_scan_storyboard_urls():
    result = final_policy_guard_node(
        _legacy_guard_state(
            _publish_package(
                storyboards=[
                    {
                        "frame_title": "作息记录",
                        "on_image_copy": "循序渐进",
                        "narration": "分享个人体验",
                        "image_url": "https://example.test/保证治疗/每天250毫克.png",
                    }
                ]
            )
        )
    )

    assert result["final_policy_issues"] == []
    assert route_after_final_guard(result) == "content_writer"


def test_final_policy_guard_routes_clean_package_to_content_writer():
    result = final_policy_guard_node(_legacy_guard_state(_publish_package()))

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
    first_guard = final_policy_guard_node(
        {**first_review, "legacy_editorial_checkpoint": True}
    )

    assert route_after_final_guard(first_guard) == "human_review"

    second_review = human_review_node(
        {
            **first_review,
            "final_policy_issues": first_guard["final_policy_issues"],
            "review_round": first_review["review_round"],
            "domain_context": {"profile_version": "wellness-v1"},
        }
    )
    second_guard = final_policy_guard_node(
        {**second_review, "legacy_editorial_checkpoint": True}
    )

    assert calls[1]["final_policy_issues"] == first_guard["final_policy_issues"]
    assert route_after_final_guard(second_guard) == "content_writer"


def test_final_policy_guard_accepts_complete_approved_editorial_artifacts(
    monkeypatch, tmp_path
):
    module = __import__(
        "src.nodes.node_q_01_final_policy_guard", fromlist=["unused"]
    )
    state, active_root = _editorial_guard_state(tmp_path)
    monkeypatch.setattr(module, "ASSET_ACTIVE_ROOT", active_root)
    monkeypatch.setattr(module, "RENDER_OUTPUT_ROOT", tmp_path)

    result = final_policy_guard_node(state)

    assert result["final_policy_issues"] == []
    assert route_after_final_guard(result) == "content_writer"


@pytest.mark.parametrize(
    "mutation,expected_rule",
    [
        (
            lambda state: setattr(
                state["asset_manifest"].items[0], "status", "pending_external"
            ),
            "pending_asset_not_approved",
        ),
        (
            lambda state: state["asset_manifest"].items[0].path
            and Path(state["asset_manifest"].items[0].path).write_bytes(b"tampered"),
            "asset_file_hash_mismatch",
        ),
        (
            lambda state: state["render_manifest"].pages[0].path
            and Path(state["render_manifest"].pages[0].path).write_bytes(b"tampered"),
            "rendered_page_missing",
        ),
        (
            lambda state: state["publish_package"].update(
                {"rendered_image_paths": state["publish_package"]["rendered_image_paths"][:-1]}
            ),
            "rendered_image_paths_incomplete",
        ),
        (
            lambda state: (
                setattr(
                    state["render_manifest"],
                    "pages",
                    list(reversed(state["render_manifest"].pages)),
                ),
                setattr(
                    state["render_manifest"],
                    "contact_sheet_page_sha256",
                    list(
                        reversed(
                            state["render_manifest"].contact_sheet_page_sha256
                        )
                    ),
                ),
                state["publish_package"].update(
                    {
                        "rendered_image_paths": list(
                            reversed(
                                state["publish_package"]["rendered_image_paths"]
                            )
                        )
                    }
                ),
            ),
            "rendered_page_order_mismatch",
        ),
        (
            lambda state: state.update({"render_qa_result": {"passed": False}}),
            "render_qa_not_passed",
        ),
    ],
)
def test_final_policy_guard_blocks_pending_tampered_or_incomplete_artifacts(
    monkeypatch, tmp_path, mutation, expected_rule
):
    module = __import__(
        "src.nodes.node_q_01_final_policy_guard", fromlist=["unused"]
    )
    state, active_root = _editorial_guard_state(tmp_path)
    monkeypatch.setattr(module, "ASSET_ACTIVE_ROOT", active_root)
    monkeypatch.setattr(module, "RENDER_OUTPUT_ROOT", tmp_path)
    mutation(state)

    result = final_policy_guard_node(state)

    assert expected_rule in {
        issue["rule_id"] for issue in result["final_policy_issues"]
    }
    assert route_after_final_guard(result) == "human_review"


def test_final_policy_guard_requires_distinct_complete_rendered_page_paths(
    monkeypatch, tmp_path
):
    module = __import__(
        "src.nodes.node_q_01_final_policy_guard", fromlist=["unused"]
    )
    state, active_root = _editorial_guard_state(tmp_path)
    monkeypatch.setattr(module, "ASSET_ACTIVE_ROOT", active_root)
    monkeypatch.setattr(module, "RENDER_OUTPUT_ROOT", tmp_path)
    pages = state["render_manifest"].pages
    pages[1].path = pages[0].path
    pages[1].sha256 = pages[0].sha256
    state["publish_package"]["rendered_image_paths"][1] = pages[0].path
    state["render_manifest"].contact_sheet_page_sha256[1] = pages[0].sha256

    result = final_policy_guard_node(state)

    assert "rendered_image_paths_incomplete" in {
        issue["rule_id"] for issue in result["final_policy_issues"]
    }
    assert "rendered_page_path_alias" in {
        issue["rule_id"] for issue in result["final_policy_issues"]
    }
    assert route_after_final_guard(result) == "human_review"


@pytest.mark.parametrize("path_kind", ["symlink", "hardlink", "outside"])
def test_final_policy_guard_rejects_untrusted_or_aliased_render_paths(
    monkeypatch,
    tmp_path,
    path_kind,
):
    module = __import__(
        "src.nodes.node_q_01_final_policy_guard", fromlist=["unused"]
    )
    state, active_root = _editorial_guard_state(tmp_path)
    monkeypatch.setattr(module, "ASSET_ACTIVE_ROOT", active_root)
    trusted_root = tmp_path / "images"
    monkeypatch.setattr(module, "RENDER_OUTPUT_ROOT", trusted_root)
    pages = state["render_manifest"].pages
    target = Path(pages[1].path)
    target.unlink()
    if path_kind == "symlink":
        target.symlink_to(Path(pages[0].path))
    elif path_kind == "hardlink":
        target.hardlink_to(Path(pages[0].path))
    else:
        target = tmp_path / "outside.png"
        Image.new("RGB", (16, 16), "red").save(target)
    pages[1].path = str(target)
    pages[1].sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
    state["publish_package"]["rendered_image_paths"][1] = str(target)
    state["render_manifest"].contact_sheet_page_sha256[1] = pages[1].sha256

    result = final_policy_guard_node(state)
    rules = {issue["rule_id"] for issue in result["final_policy_issues"]}

    assert (
        "rendered_page_missing" in rules
        if path_kind in {"symlink", "outside"}
        else "rendered_page_path_alias" in rules
    )


def test_final_policy_guard_binds_role_layout_visible_text_and_unique_slots(
    monkeypatch,
    tmp_path,
):
    module = __import__(
        "src.nodes.node_q_01_final_policy_guard", fromlist=["unused"]
    )
    state, active_root = _editorial_guard_state(tmp_path)
    monkeypatch.setattr(module, "ASSET_ACTIVE_ROOT", active_root)
    monkeypatch.setattr(module, "RENDER_OUTPUT_ROOT", tmp_path)
    state["render_manifest"].pages[1].role = "wrong-role"
    state["publish_package"]["storyboards"][0]["headline"] = "stale edit"
    duplicate = deepcopy(state["asset_manifest"].items[0])
    state["asset_manifest"].items.append(duplicate)

    result = final_policy_guard_node(state)
    rules = {issue["rule_id"] for issue in result["final_policy_issues"]}

    assert "rendered_page_order_mismatch" in rules
    assert "rendered_visible_text_binding_mismatch" in rules
    assert "duplicate_asset_slot_id" in rules
    assert "asset_slot_binding_mismatch" in rules


def test_final_policy_guard_rejects_path_replacement_during_single_open_snapshot(
    monkeypatch,
    tmp_path,
):
    module = __import__(
        "src.nodes.node_q_01_final_policy_guard", fromlist=["unused"]
    )
    state, active_root = _editorial_guard_state(tmp_path)
    monkeypatch.setattr(module, "ASSET_ACTIVE_ROOT", active_root)
    monkeypatch.setattr(module, "RENDER_OUTPUT_ROOT", tmp_path)
    target = Path(state["render_manifest"].pages[0].path)
    replacement = tmp_path / "replacement.png"
    Image.new("RGB", (16, 16), "blue").save(replacement)
    original_open = module.os.open
    original_read = module.os.read
    replaced = False
    target_descriptor = None

    def tracking_open(path, flags):
        nonlocal target_descriptor
        descriptor = original_open(path, flags)
        if Path(path) == target:
            target_descriptor = descriptor
        return descriptor

    def replacing_read(descriptor, size):
        nonlocal replaced
        chunk = original_read(descriptor, size)
        if chunk and descriptor == target_descriptor and not replaced:
            replaced = True
            replacement.replace(target)
        return chunk

    monkeypatch.setattr(module.os, "open", tracking_open)
    monkeypatch.setattr(module.os, "read", replacing_read)

    result = final_policy_guard_node(state)

    assert "rendered_page_missing" in {
        issue["rule_id"] for issue in result["final_policy_issues"]
    }


def test_final_policy_guard_rejects_symlinked_active_asset(
    monkeypatch,
    tmp_path,
):
    module = __import__(
        "src.nodes.node_q_01_final_policy_guard", fromlist=["unused"]
    )
    state, active_root = _editorial_guard_state(tmp_path)
    monkeypatch.setattr(module, "ASSET_ACTIVE_ROOT", active_root)
    monkeypatch.setattr(module, "RENDER_OUTPUT_ROOT", tmp_path)
    asset_path = Path(state["asset_manifest"].items[0].path)
    outside = tmp_path / "outside-asset.svg"
    asset_path.replace(outside)
    asset_path.symlink_to(outside)

    result = final_policy_guard_node(state)

    assert "asset_file_missing" in {
        issue["rule_id"] for issue in result["final_policy_issues"]
    }
