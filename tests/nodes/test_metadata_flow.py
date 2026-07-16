from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.domain import build_content_policy, get_domain_profile, get_topic_metadata
from src.schemas import CarouselPayload
from src.schemas.decision import DecisionOutput, HashTagInput
from src.schemas.draft import DraftItem
from src.schemas.narrative import NarrativePlan
from src.schemas.topic import TopicItem


def _creative_seed():
    return {
        "signal_type": "evergreen_context",
        "signal_name": "测试默认信号",
        "why_now": "测试中使用稳定 evergreen 信号。",
        "domain_translation": "测试中保持原 domain/subdomain。",
        "evergreen_pain": "测试核心痛点。",
        "timely_framing": "测试时机包装。",
    }


def _content_contract():
    return {
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
    }


def _topic(topic_id="tp_001"):
    return TopicItem(
        topic_id=topic_id,
        topic="睡眠改善",
        target_group="上班族",
        core_pain="熬夜后疲惫",
        hook="别把睡眠问题都怪在晚睡上",
        content_form="教程",
        risk_note="avoid medical claims",
        domain="wellness",
        subdomain="sleep",
        content_intent="how_to",
        risk_level="medium",
        risk_flags=["medical-adjacent", "sleep-adjacent"],
        content_contract=_content_contract(),
        creative_seed=_creative_seed(),
    )


def _domain_context():
    return {
        "domain": "wellness",
        "subdomain": "sleep",
        "classification_source": "explicit",
        "classification_confidence": 1,
        "profile_version": "wellness-v1",
        "risk_level": "medium",
    }


def _content_policy():
    return build_content_policy(get_domain_profile("wellness"), risk_level="medium").model_dump()


def _narrative_plan():
    return NarrativePlan(
        narrative_form="scenario_story",
        beats=[
            {"beat_id": "hook", "kind": "hook", "purpose": "建立阅读承诺"},
            {"beat_id": "scene", "kind": "scene", "purpose": "呈现具体场景"},
            {"beat_id": "reveal", "kind": "reveal", "purpose": "揭示关键发现"},
            {"beat_id": "lesson", "kind": "summary", "purpose": "总结可保存结论"},
        ],
        saveable_beat={
            "beat_id": "lesson",
            "kind": "summary",
            "purpose": "总结可保存结论",
        },
        closing_mode="reflection",
    )


def _hashtag_input(**updates):
    values = {
        "final_title": "睡眠改善指南",
        "final_md": "body",
        "topic_id": "tp_001",
        "topic": "睡眠改善",
        "angle_id": "ag_001",
        "angle": "睡眠策略",
        "domain": "wellness",
        "subdomain": "sleep",
        "content_intent": "how_to",
        "risk_level": "medium",
        "risk_flags": ["medical-adjacent", "sleep-adjacent"],
        "target_group": "上班族",
        "core_pain": "熬夜后疲惫",
        "best_cover_copy": "cover",
        "narrative_plan": _narrative_plan(),
    }
    values.update(updates)
    return HashTagInput.model_validate(values)


def _narrative_metadata():
    narrative_plan = _narrative_plan().model_dump(mode="json")
    return {
        "narrative_plan": narrative_plan,
        "narrative_form": narrative_plan["narrative_form"],
        "closing_mode": narrative_plan["closing_mode"],
    }


def _visual_plan():
    from src.editorial_carousel.strategy import build_visual_plan

    return build_visual_plan(_content_contract(), recent_signatures=[])


def _storyboard_frames():
    frames = []
    for index, item in enumerate(_visual_plan().frame_plan):
        frames.append(
            {
                "frame_id": item.frame_id,
                "role": item.role,
                "layout": item.layout,
                "headline": (
                    _content_contract()["first_screen_promise"]
                    if index == 0
                    else f"第{index + 1}张要点"
                ),
                "kicker": f"第{index + 1}张",
                "content_blocks": [
                    {
                        "block_type": "text",
                        "body": f"第{index + 1}张的单一信息任务",
                    }
                ],
                "emphasis": ["要点"],
                "visual_slots": [
                    {
                        "slot_id": f"{item.frame_id}-visual",
                        "role": item.asset_roles[0],
                        "semantic_tags": ["daily-routine"],
                    }
                ],
                "footer": "按需微调",
            }
        )
    return frames


def _legacy_storyboard_frames():
    common = {"theme": "warm_neutral", "footer": "按需微调"}
    return [
        {
            "frame_id": "frame_001",
            **common,
            "template": "cover_statement",
            "kicker": "封面",
            "headline": _content_contract()["first_screen_promise"],
        },
        {
            "frame_id": "frame_002",
            **common,
            "template": "wrong_vs_right",
            "kicker": "对照",
            "headline": "避免误区",
            "wrong_items": ["立刻执行", "一次加量"],
            "right_items": ["先做记录", "逐步调整"],
        },
        {
            "frame_id": "frame_003",
            **common,
            "template": "step_timeline",
            "kicker": "步骤",
            "headline": "三步执行",
            "steps": [
                {"name": "记录", "hint": "观察现状"},
                {"name": "调整", "hint": "每次一项"},
                {"name": "复盘", "hint": "按周总结"},
            ],
        },
        {
            "frame_id": "frame_004",
            **common,
            "template": "saveable_checklist",
            "kicker": "保存",
            "headline": "执行清单",
            "checklist_items": ["记录现状", "逐项调整", "定期复盘"],
        },
        {
            "frame_id": "frame_005",
            **common,
            "template": "decision_rule",
            "kicker": "判断",
            "headline": "按情况判断",
            "conditions": [
                {"situation": "执行困难", "recommendation": "缩小调整范围"},
                {"situation": "状态稳定", "recommendation": "保持当前节奏"},
            ],
        },
        {
            "frame_id": "frame_006",
            **common,
            "template": "question_closer",
            "kicker": "讨论",
            "headline": "你的下一步",
            "question": "你最想先调整哪一步？",
        },
    ]


def test_trend_scout_includes_domain_context_and_content_policy(monkeypatch):
    from src.nodes import node_a_trend_scout as module

    captured = {}

    class FakeModel:
        def execute(self, messages):
            captured["messages"] = messages
            return [
                {
                    "topic_id": "tp_001",
                    "topic": "睡眠改善",
                    "target_group": "上班族",
                    "core_pain": "熬夜后疲惫",
                    "hook": "别把睡眠问题都怪在晚睡上",
                    "content_form": "教程",
                    "risk_note": "avoid medical claims",
                    "domain": "beauty",
                    "subdomain": "skincare",
                    "content_intent": "how_to",
                    "risk_level": "low",
                    "risk_flags": ["medical-adjacent", "sleep-adjacent"],
                    "content_contract": _content_contract(),
                    "creative_seed": _creative_seed(),
                }
            ]

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())

    result = module.trend_scout_node(
        {
            "trends_num": 1,
            "focus_keyword": "改善睡眠",
            "memory_context": {"recent_content": []},
            "domain_context": _domain_context(),
            "content_policy": _content_policy(),
        }
    )

    human_prompt = captured["messages"][1].content
    assert "domain_context" in human_prompt
    assert "content_policy" in human_prompt
    assert isinstance(result["trends"][0], TopicItem)
    assert result["trends"][0].domain == "wellness"
    assert result["trends"][0].subdomain == "sleep"
    assert result["trends"][0].risk_level == "medium"
    assert result["trends"][0].risk_flags == ["medical-adjacent", "sleep-adjacent"]


def test_trend_scout_normalizes_basic_science_risk_level(monkeypatch):
    from src.nodes import node_a_trend_scout as module

    class FakeModel:
        def execute(self, _messages):
            return [
                {
                    "topic_id": "tp_001",
                    "topic": "睡眠基础科学",
                    "target_group": "上班族",
                    "core_pain": "想知道为什么睡不好",
                    "hook": "别把基础科学说成治疗",
                    "content_form": "科普",
                    "risk_note": "avoid medical claims",
                    "domain": "wellness",
                    "subdomain": "sleep",
                    "content_intent": "basic_science",
                    "risk_level": "low",
                    "risk_flags": ["medical-adjacent"],
                    "content_contract": _content_contract(),
                    "creative_seed": _creative_seed(),
                }
            ]

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())

    result = module.trend_scout_node(
        {
            "trends_num": 1,
            "focus_keyword": "睡眠",
            "memory_context": {},
            "domain_context": _domain_context(),
            "content_policy": _content_policy(),
        }
    )

    assert result["trends"][0].content_intent == "basic_science"
    assert result["trends"][0].risk_level == "medium"


def test_selected_topic_angle_ids_cover_all_decision_sources():
    from src.nodes.node_j_decision_engine import _select_topic_angle_ids

    title_winner = SimpleNamespace(topic_id="tp_title", angle_id="ag_title")
    r1_output = SimpleNamespace(topic_id="tp_r1", angle_id="ag_r1")
    r2_output = SimpleNamespace(
        content_snapshot=SimpleNamespace(topic_id="tp_r2", angle_id="ag_r2")
    )

    assert _select_topic_angle_ids("TITLE_RANKER", title_winner) == ("tp_title", "ag_title")
    assert _select_topic_angle_ids("R1_REFLECTOR", r1_output) == ("tp_r1", "ag_r1")
    assert _select_topic_angle_ids("R2_COMPLIANCE", r2_output) == ("tp_r2", "ag_r2")


def test_extract_selected_content_fields_covers_nested_sources():
    from src.nodes.node_j_decision_engine import _extract_selected_content_fields

    title_winner = SimpleNamespace(
        topic_id="tp_title",
        angle_id="ag_title",
        topic="标题主题",
        angle="标题角度",
        target_group="上班族",
        core_pain="熬夜后疲惫",
        best_cover_copy="copy",
    )
    r1_output = SimpleNamespace(
        content_candidate=SimpleNamespace(
            topic_id="tp_r1",
            angle_id="ag_r1",
            topic="R1主题",
            angle="R1角度",
            target_group="通勤党",
            core_pain="上妆卡粉",
            best_cover_copy="r1-copy",
        )
    )
    r2_output = SimpleNamespace(
        content_snapshot=SimpleNamespace(
            topic_id="tp_r2",
            angle_id="ag_r2",
            topic="R2主题",
            angle="R2角度",
            target_group="学生党",
            core_pain="出油",
            best_cover_copy="r2-copy",
        )
    )

    assert _extract_selected_content_fields("TITLE_RANKER", title_winner) == {
        "topic_id": "tp_title",
        "angle_id": "ag_title",
        "topic": "标题主题",
        "angle": "标题角度",
        "target_group": "上班族",
        "core_pain": "熬夜后疲惫",
        "best_cover_copy": "copy",
    }
    assert _extract_selected_content_fields("R1_REFLECTOR", r1_output) == {
        "topic_id": "tp_r1",
        "angle_id": "ag_r1",
        "topic": "R1主题",
        "angle": "R1角度",
        "target_group": "通勤党",
        "core_pain": "上妆卡粉",
        "best_cover_copy": "r1-copy",
    }
    assert _extract_selected_content_fields("R2_COMPLIANCE", r2_output) == {
        "topic_id": "tp_r2",
        "angle_id": "ag_r2",
        "topic": "R2主题",
        "angle": "R2角度",
        "target_group": "学生党",
        "core_pain": "出油",
        "best_cover_copy": "r2-copy",
    }


def test_decision_engine_overwrites_llm_hashtag_metadata(monkeypatch):
    from src.nodes import node_j_decision_engine as module

    captured = {}
    narrative_plan = _narrative_plan()

    class FakeModel:
        def execute(self, messages):
            captured["messages"] = messages
            return {
                "next_node": "HASHTAG_SEO",
                "normalized_input": {
                    "hashtag_input": {
                        "final_title": "睡眠改善指南",
                        "final_md": "content",
                        "topic_id": "wrong_topic",
                        "angle_id": "wrong_angle",
                        "topic": "wrong",
                        "angle": "wrong",
                        "domain": "beauty",
                        "subdomain": "skincare",
                        "content_intent": "experience",
                        "risk_level": "low",
                        "risk_flags": ["wrong"],
                        "target_group": "wrong-group",
                        "core_pain": "wrong-pain",
                        "best_cover_copy": "wrong-cover",
                        "narrative_plan": narrative_plan.model_dump(mode="json"),
                    }
                },
            }

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())

    result = module.decision_engine_node(
        {
            "current_node": "R2_COMPLIANCE",
            "r2_output": SimpleNamespace(
                content_snapshot=SimpleNamespace(
                    topic_id="tp_001",
                    angle_id="ag_001",
                    topic="睡眠改善",
                    angle="睡眠策略",
                    target_group="上班族",
                    core_pain="熬夜后疲惫",
                    best_cover_copy="cover",
                    narrative_plan=narrative_plan,
                )
            ),
            "scores": [
                SimpleNamespace(
                    topic_id="tp_001",
                    angle_id="ag_001",
                    narrative_plan=narrative_plan,
                )
            ],
            "trends": [_topic()],
            "domain_context": _domain_context(),
            "content_policy": _content_policy(),
        }
    )

    hashtag_input = result["decision_output"].normalized_input.hashtag_input
    assert hashtag_input.topic_id == "tp_001"
    assert hashtag_input.angle_id == "ag_001"
    assert hashtag_input.domain == "wellness"
    assert hashtag_input.subdomain == "sleep"
    assert hashtag_input.content_intent == "how_to"
    assert hashtag_input.risk_level == "medium"
    assert hashtag_input.risk_flags == ["medical-adjacent", "sleep-adjacent"]
    assert hashtag_input.final_title == "睡眠改善指南"
    assert hashtag_input.final_md == "content"
    assert hashtag_input.topic == "睡眠改善"
    assert hashtag_input.angle == "睡眠策略"
    assert hashtag_input.target_group == "上班族"
    assert hashtag_input.core_pain == "熬夜后疲惫"
    assert hashtag_input.best_cover_copy == "cover"
    assert hashtag_input.narrative_plan == narrative_plan


def test_title_ranker_rejects_model_rewritten_narrative_plan(monkeypatch):
    from src.nodes import node_g_title_ranker as module

    authoritative_plan = _narrative_plan()
    rewritten_plan = authoritative_plan.model_copy(
        update={"narrative_form": "cognitive_correction"}
    )

    class FakeModel:
        def execute(self, _messages):
            return {
                "ranking": [
                    {
                        "draft_id": "draft_001",
                        "total_score": 9.2,
                        "best_title_for_this_draft": "睡眠改善指南",
                        "reason": "场景明确",
                    }
                ],
                "winner": {
                    "draft_id": "draft_001",
                    "draft_md": "content",
                    "best_title": "睡眠改善指南",
                    "best_title_id": "title_001",
                    "safer_title": "睡眠习惯参考",
                    "safer_title_id": "title_002",
                    "best_cover_copy": "cover",
                    "why_win": ["场景明确"],
                    "must_fix_if_selected": [],
                    "optional_improvements": [],
                    "topic_id": "tp_001",
                    "topic": "睡眠改善",
                    "angle_id": "ag_001",
                    "angle": "睡眠策略",
                    "target_group": "上班族",
                    "core_pain": "熬夜后疲惫",
                    "narrative_plan": rewritten_plan.model_dump(mode="json"),
                },
            }

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())

    with pytest.raises(ValueError, match="must preserve the selected narrative_plan"):
        module.title_ranker_node(
            {
                "drafts": [
                    DraftItem(
                        draft_id="draft_001",
                        draft_md="content",
                        topic_id="tp_001",
                        topic="睡眠改善",
                        angle_id="ag_001",
                        angle="睡眠策略",
                        target_group="上班族",
                        core_pain="熬夜后疲惫",
                        narrative_plan=authoritative_plan,
                    )
                ],
                "titles_options": [],
                "domain_context": _domain_context(),
                "content_policy": _content_policy(),
            }
        )


def test_r1_reflector_rejects_model_rewritten_narrative_plan(monkeypatch):
    from src.nodes import node_h_r1_reflector as module

    authoritative_plan = _narrative_plan()
    rewritten_plan = authoritative_plan.model_copy(
        update={"narrative_form": "cognitive_correction"}
    )
    decision_output = DecisionOutput.model_validate(
        {
            "next_node": "R1_REFLECTOR",
            "normalized_input": {
                "r1_input": {
                    "content_candidate": {
                        "draft_id": "draft_001",
                        "draft_md": "content",
                        "best_title": "睡眠改善指南",
                        "best_title_id": "title_001",
                        "safer_title": "睡眠习惯参考",
                        "safer_title_id": "title_002",
                        "best_cover_copy": "cover",
                        "why_win": ["场景明确"],
                        "topic_id": "tp_001",
                        "topic": "睡眠改善",
                        "angle_id": "ag_001",
                        "angle": "睡眠策略",
                        "target_group": "上班族",
                        "core_pain": "熬夜后疲惫",
                        "narrative_plan": authoritative_plan,
                    },
                    "editorial_tasks": {"mandatory": [], "optional": []},
                    "revision_meta": {
                        "revision_id": "rev_001",
                        "round": 1,
                        "diff_summary": [],
                        "next_actions": [],
                    },
                    "decision_trace": {
                        "source_node": "TITLE_RANKER",
                        "why_this_route": ["需要编辑复核"],
                    },
                }
            },
        }
    )

    class FakeModel:
        def execute(self, _messages):
            return {
                "draft_id": "draft_001",
                "revised_title": "睡眠改善指南",
                "revised_md": "content",
                "topic_id": "tp_001",
                "topic": "睡眠改善",
                "angle_id": "ag_001",
                "angle": "睡眠策略",
                "target_group": "上班族",
                "core_pain": "熬夜后疲惫",
                "best_cover_copy": "cover",
                "narrative_plan": rewritten_plan.model_dump(mode="json"),
                "storyboard_visible_text": [],
                "scores": {
                    "clarity_score": 9,
                    "save_value_score": 9,
                    "readability_score": 9,
                    "authenticity_score": 9,
                    "promise_alignment_score": 9,
                },
                "revision_meta": {
                    "revision_id": "rev_002",
                    "round": 2,
                    "diff_summary": [],
                    "next_actions": ["Ready for R2 compliance review"],
                },
                "task_report": {
                    "completed_task_ids": [],
                    "skipped_task_ids": [],
                    "notes": [],
                },
                "remaining_risks": [],
                "editor_notes": [],
                "should_run_R1_again": False,
            }

    monkeypatch.setattr(module, "get_model", lambda *_args: FakeModel())

    with pytest.raises(ValueError, match="must preserve the selected narrative_plan"):
        module.r1_reflector_node(
            {
                "decision_output": decision_output,
                "domain_context": _domain_context(),
                "content_policy": _content_policy(),
                "evidence_briefs": {},
            }
        )


def test_r2_compliance_rejects_model_rewritten_narrative_plan(monkeypatch):
    from src.nodes import node_i_r2_compliance as module

    authoritative_plan = _narrative_plan()
    rewritten_plan = authoritative_plan.model_copy(
        update={"narrative_form": "cognitive_correction"}
    )
    decision_output = DecisionOutput.model_validate(
        {
            "next_node": "R2_COMPLIANCE",
            "normalized_input": {
                "r2_input": {
                    "content_snapshot": {
                        "draft_id": "draft_001",
                        "revised_title": "睡眠改善指南",
                        "revised_md": "content",
                        "topic_id": "tp_001",
                        "topic": "睡眠改善",
                        "angle_id": "ag_001",
                        "angle": "睡眠策略",
                        "target_group": "上班族",
                        "core_pain": "熬夜后疲惫",
                        "best_cover_copy": "cover",
                        "narrative_plan": authoritative_plan,
                    },
                    "revision_meta": {
                        "revision_id": "rev_001",
                        "round": 1,
                        "diff_summary": [],
                        "next_actions": [],
                    },
                    "decision_trace": {
                        "source_node": "R1_REFLECTOR",
                        "why_this_route": ["编辑完成"],
                    },
                }
            },
        }
    )

    class FakeModel:
        def execute(self, _messages):
            return {
                "content_snapshot": {
                    "draft_id": "draft_001",
                    "revised_title": "睡眠改善指南",
                    "revised_md": "content",
                    "topic_id": "tp_001",
                    "topic": "睡眠改善",
                    "angle_id": "ag_001",
                    "angle": "睡眠策略",
                    "target_group": "上班族",
                    "core_pain": "熬夜后疲惫",
                    "best_cover_copy": "cover",
                    "narrative_plan": rewritten_plan.model_dump(mode="json"),
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
                    "diff_summary": [],
                    "next_actions": [],
                },
            }

    monkeypatch.setattr(module, "get_model", lambda *_args: FakeModel())

    with pytest.raises(ValueError, match="must preserve the selected narrative_plan"):
        module.r2_compliance_node(
            {
                "decision_output": decision_output,
                "domain_context": _domain_context(),
                "content_policy": _content_policy(),
                "evidence_briefs": {},
                "publish_package": {},
            }
        )


def test_title_ranker_decision_hashtag_preserves_narrative_plan(monkeypatch):
    from src.nodes import node_g_title_ranker as title_ranker_module
    from src.nodes import node_j_decision_engine as decision_module
    from src.nodes import node_k_hashtag_seo as hashtag_module

    authoritative_plan = _narrative_plan()
    contradictory_plan = NarrativePlan(
        narrative_form="cognitive_correction",
        beats=[
            {"beat_id": "hook", "kind": "hook", "purpose": "提出常见误区"},
            {"beat_id": "mistake", "kind": "misconception", "purpose": "展示误区"},
            {"beat_id": "reveal", "kind": "reveal", "purpose": "给出反转"},
            {"beat_id": "action", "kind": "action", "purpose": "给出替代动作"},
        ],
        saveable_beat={
            "beat_id": "action",
            "kind": "action",
            "purpose": "给出替代动作",
        },
        closing_mode="none",
    )

    class TitleRankerModel:
        def execute(self, _messages):
            return {
                "ranking": [
                    {
                        "draft_id": "draft_001",
                        "total_score": 9.2,
                        "best_title_for_this_draft": "睡眠改善指南",
                        "reason": "场景明确",
                    }
                ],
                "winner": {
                    "draft_id": "draft_001",
                    "draft_md": "content",
                    "best_title": "睡眠改善指南",
                    "best_title_id": "title_001",
                    "safer_title": "睡眠习惯参考",
                    "safer_title_id": "title_002",
                    "best_cover_copy": "cover",
                    "why_win": ["场景明确"],
                    "must_fix_if_selected": [],
                    "optional_improvements": [],
                    "topic_id": "tp_001",
                    "topic": "睡眠改善",
                    "angle_id": "ag_001",
                    "angle": "睡眠策略",
                    "target_group": "上班族",
                    "core_pain": "熬夜后疲惫",
                    "narrative_plan": contradictory_plan.model_dump(mode="json"),
                },
            }

    monkeypatch.setattr(title_ranker_module, "get_model", lambda: TitleRankerModel())
    title_ranker_result = title_ranker_module.title_ranker_node(
        {
            "drafts": [
                DraftItem(
                    draft_id="draft_001",
                    draft_md="content",
                    topic_id="tp_001",
                    topic="睡眠改善",
                    angle_id="ag_001",
                    angle="睡眠策略",
                    target_group="上班族",
                    core_pain="熬夜后疲惫",
                    narrative_plan=contradictory_plan,
                )
            ],
            "titles_options": [],
            "domain_context": _domain_context(),
            "content_policy": _content_policy(),
        }
    )

    class DecisionModel:
        def execute(self, _messages):
            return {
                "next_node": "HASHTAG_SEO",
                "normalized_input": {
                    "hashtag_input": {
                        "final_title": "睡眠改善指南",
                        "final_md": "content",
                        "topic_id": "wrong_topic",
                        "angle_id": "wrong_angle",
                        "topic": "wrong",
                        "angle": "wrong",
                        "domain": "wellness",
                        "subdomain": "sleep",
                        "content_intent": "how_to",
                        "risk_level": "medium",
                        "risk_flags": ["medical-adjacent", "sleep-adjacent"],
                        "target_group": "wrong-group",
                        "core_pain": "wrong-pain",
                        "best_cover_copy": "wrong-cover",
                        "narrative_plan": contradictory_plan.model_dump(mode="json"),
                    }
                },
            }

    monkeypatch.setattr(decision_module, "get_model", lambda: DecisionModel())
    decision_result = decision_module.decision_engine_node(
        {
            **title_ranker_result,
            "scores": [
                SimpleNamespace(
                    topic_id="tp_001",
                    angle_id="ag_001",
                    narrative_plan=authoritative_plan,
                )
            ],
            "trends": [_topic()],
            "domain_context": _domain_context(),
            "content_policy": _content_policy(),
        }
    )

    monkeypatch.setattr(
        hashtag_module,
        "get_model",
        lambda: SimpleNamespace(execute=lambda _messages: {"hashtags": ["#睡眠改善"]}),
    )
    result = hashtag_module.hashtag_node(
        {
            **decision_result,
            "domain_context": _domain_context(),
            "content_policy": _content_policy(),
        }
    )

    hashtag_input = decision_result["decision_output"].normalized_input.hashtag_input
    assert hashtag_input.narrative_plan == authoritative_plan
    assert result["final_content"].narrative_plan == authoritative_plan
    assert result["final_content"].narrative_plan != contradictory_plan


def test_decision_engine_raises_before_model_when_topic_missing(monkeypatch):
    from src.nodes import node_j_decision_engine as module

    calls = {"count": 0}

    class FakeModel:
        def execute(self, _messages):
            calls["count"] += 1
            return {}

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())

    with pytest.raises(ValueError, match="Unknown topic_id: tp_missing"):
        module.decision_engine_node(
            {
                "current_node": "R2_COMPLIANCE",
                "r2_output": SimpleNamespace(
                    content_snapshot=SimpleNamespace(
                        topic_id="tp_missing",
                        angle_id="ag_001",
                        topic="睡眠改善",
                        angle="睡眠策略",
                        target_group="上班族",
                        core_pain="熬夜后疲惫",
                        best_cover_copy="cover",
                    )
                ),
                "trends": [_topic()],
                "domain_context": _domain_context(),
                "content_policy": _content_policy(),
            }
        )

    assert calls["count"] == 0


def test_decision_engine_raises_before_model_on_duplicate_topic(monkeypatch):
    from src.nodes import node_j_decision_engine as module

    calls = {"count": 0}

    class FakeModel:
        def execute(self, _messages):
            calls["count"] += 1
            return {}

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())

    duplicate_topics = [_topic(), _topic()]

    with pytest.raises(ValueError, match="Duplicate topic_id: tp_001"):
        module.decision_engine_node(
            {
                "current_node": "R2_COMPLIANCE",
                "r2_output": SimpleNamespace(
                    content_snapshot=SimpleNamespace(
                        topic_id="tp_001",
                        angle_id="ag_001",
                        topic="睡眠改善",
                        angle="睡眠策略",
                        target_group="上班族",
                        core_pain="熬夜后疲惫",
                        best_cover_copy="cover",
                    )
                ),
                "trends": duplicate_topics,
                "domain_context": _domain_context(),
                "content_policy": _content_policy(),
            }
        )

    assert calls["count"] == 0


def test_assembler_injects_authoritative_narrative_metadata_and_ignores_model_strategy(
    monkeypatch,
):
    from src.nodes import node_o_assembler as module

    captured = {}
    narrative_plan = NarrativePlan.model_validate(
        {
            "narrative_form": "comparison",
            "beats": [
                {"beat_id": "hook", "kind": "hook", "purpose": "建立阅读承诺"},
                {"beat_id": "left", "kind": "comparison", "purpose": "说明常见做法"},
                {"beat_id": "right", "kind": "comparison", "purpose": "说明推荐做法"},
                {"beat_id": "boundary", "kind": "boundary", "purpose": "总结适用边界"},
            ],
            "saveable_beat": {
                "beat_id": "right",
                "kind": "comparison",
                "purpose": "说明推荐做法",
            },
            "closing_mode": "boundary",
        }
    )

    class FakeModel:
        def execute(self, messages):
            captured["human_prompt"] = messages[1].content
            return {
                "title": "睡眠改善指南",
                "content": "body",
                "topic_id": "wrong_topic",
                "topic": "wrong",
                "angle_id": "wrong_angle",
                "angle": "wrong",
                "target_group": "wrong-group",
                "core_pain": "wrong-pain",
                "cover_copy": "cover",
                "images": [],
                "hashtags": ["#x"],
                "notes": [],
                "storyboard_strategy": "auto",
            }

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())

    result = module.assembler_node(
        {
            "focus_keyword": "改善睡眠",
            "focus_keyword_cli_present": True,
            "final_content": _hashtag_input(
                final_title="睡眠改善指南✨",
                final_md="body ✨",
                narrative_plan=narrative_plan,
            ),
            "hashtags": SimpleNamespace(hashtags=["#x"]),
            "trends": [_topic()],
            "domain_context": _domain_context(),
            "content_policy": _content_policy(),
        }
    )

    publish_package = result["publish_package"]
    assert publish_package["focus_keyword"] == "改善睡眠"
    assert publish_package["focus_keyword_cli_present"] is True
    assert publish_package["topic_id"] == "tp_001"
    assert publish_package["angle_id"] == "ag_001"
    assert publish_package["domain"] == "wellness"
    assert publish_package["subdomain"] == "sleep"
    assert publish_package["content_intent"] == "how_to"
    assert publish_package["risk_level"] == "medium"
    assert publish_package["risk_flags"] == ["medical-adjacent", "sleep-adjacent"]
    assert publish_package["topic"] == "睡眠改善"
    assert publish_package["angle"] == "睡眠策略"
    assert publish_package["target_group"] == "上班族"
    assert publish_package["core_pain"] == "熬夜后疲惫"
    assert publish_package["cover_copy"] == "cover"
    assert publish_package["title"] == "睡眠改善指南✨"
    assert publish_package["content"] == "body ✨"
    assert publish_package["profile_version"] == "wellness-v1"
    assert publish_package["content_contract"] == _content_contract()
    assert publish_package["narrative_plan"] == narrative_plan.model_dump(mode="json")
    assert publish_package["narrative_form"] == "comparison"
    assert publish_package["closing_mode"] == "boundary"
    assert "storyboard_strategy" not in publish_package
    assert "image_final_choices" not in captured["human_prompt"]


def test_assembler_rejects_explicit_cli_keyword_that_was_lost(monkeypatch):
    from src.nodes import node_o_assembler as module

    monkeypatch.setattr(
        module,
        "get_model",
        lambda: SimpleNamespace(execute=lambda _messages: {}),
    )

    with pytest.raises(ValueError, match="focus_keyword"):
        module.assembler_node(
            {
                "focus_keyword": "",
                "focus_keyword_cli_present": True,
                "final_content": SimpleNamespace(
                    final_title="睡眠改善指南",
                    final_md="body",
                    topic_id="tp_001",
                    topic="睡眠改善",
                    angle_id="ag_001",
                    angle="睡眠策略",
                    target_group="上班族",
                    core_pain="熬夜后疲惫",
                    best_cover_copy="cover",
                    domain="wellness",
                    subdomain="sleep",
                    content_intent="how_to",
                    risk_level="medium",
                    risk_flags=[],
                ),
                "hashtags": SimpleNamespace(hashtags=["#x"]),
                "trends": [_topic()],
                "domain_context": _domain_context(),
                "content_policy": _content_policy(),
            }
        )


def test_assembler_enforces_title_max_length_including_punctuation(monkeypatch):
    from src.nodes import node_o_assembler as module

    class FakeModel:
        def execute(self, _messages):
            return {
                "images": [],
                "hashtags": ["#x"],
                "notes": [],
            }

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())

    result = module.assembler_node(
        {
            "final_content": _hashtag_input(
                final_title="1234567890123456789！超长标题",
                risk_flags=["medical-adjacent"],
            ),
            "hashtags": SimpleNamespace(hashtags=["#x"]),
            "trends": [_topic()],
            "domain_context": _domain_context(),
            "content_policy": _content_policy(),
        }
    )

    title = result["publish_package"]["title"]
    assert title == "1234567890123456789！"
    assert len(title) == 20


def test_assembler_reapplies_pending_metadata_without_reviving_r2_managed_copy(monkeypatch):
    from src.nodes import node_o_assembler as module

    class FakeModel:
        def execute(self, _messages):
            return {
                "notes": ["generated note"],
                "hashtags": ["#generated"],
            }

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())

    result = module.assembler_node(
        {
            "final_content": _hashtag_input(
                final_title="R2 修订后的标题",
                final_md="R2 修订后的正文",
                best_cover_copy="R2 修订后的封面",
                risk_flags=["medical-adjacent"],
            ),
            "hashtags": SimpleNamespace(hashtags=["#generated"]),
            "trends": [_topic()],
            "domain_context": _domain_context(),
            "content_policy": _content_policy(),
            "pending_human_publish_patch": {
                "title": "旧人工标题",
                "content": "旧人工正文",
                "cover_copy": "旧人工封面",
                "hashtags": ["#旧人工标签"],
                "notes": ["人工审核备注"],
                "storyboards": [{"frame_id": "frame_001", "image_prompt_cn": "人工提示"}],
            },
        }
    )

    publish_package = result["publish_package"]
    assert publish_package["title"] == "R2 修订后的标题"
    assert publish_package["content"] == "R2 修订后的正文"
    assert publish_package["cover_copy"] == "R2 修订后的封面"
    assert publish_package["hashtags"] == ["#generated"]
    assert publish_package["notes"] == ["人工审核备注"]
    assert "storyboards" not in publish_package


def test_storyboards_generator_preserves_package_and_writes_semantic_carousel(monkeypatch):
    from src.nodes import node_o_storyboards_generator as module

    captured = {}

    class FakeModel:
        def execute(self, messages):
            captured["system_prompt"] = messages[0].content
            return {"storyboards": _storyboard_frames()}

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())

    publish_package = {
        "title": "久坐间隙活动指南",
        "content": "body",
        "topic_id": "tp_001",
        "topic": "睡眠改善",
        "angle_id": "ag_001",
        "angle": "睡眠策略",
        "target_group": "上班族",
        "core_pain": "熬夜后疲惫",
        "cover_copy": "cover",
        "images": [],
        "hashtags": ["#x"],
        "notes": ["note"],
        **_narrative_metadata(),
        "domain": "wellness",
        "profile_version": "wellness-v1",
        "subdomain": "sleep",
        "content_intent": "how_to",
        "risk_level": "medium",
        "risk_flags": ["medical-adjacent", "sleep-adjacent"],
        "content_contract": _content_contract(),
    }

    result = module.storyboards_generator_node(
        {
            "publish_package": publish_package,
            "trends": [_topic()],
            "domain_context": _domain_context(),
            "content_policy": _content_policy(),
            "visual_plan": _visual_plan(),
        }
    )

    merged_package = result["publish_package"]
    assert merged_package["title"] == publish_package["title"]
    assert merged_package["content"] == publish_package["content"]
    assert merged_package["topic_id"] == publish_package["topic_id"]
    assert merged_package["topic"] == publish_package["topic"]
    assert merged_package["angle_id"] == publish_package["angle_id"]
    assert merged_package["angle"] == publish_package["angle"]
    assert merged_package["target_group"] == publish_package["target_group"]
    assert merged_package["core_pain"] == publish_package["core_pain"]
    assert merged_package["cover_copy"] == publish_package["cover_copy"]
    assert merged_package["images"] == publish_package["images"]
    assert merged_package["hashtags"] == publish_package["hashtags"]
    assert merged_package["notes"] == publish_package["notes"]
    assert merged_package["narrative_plan"] == publish_package["narrative_plan"]
    assert merged_package["narrative_form"] == publish_package["narrative_form"]
    assert merged_package["closing_mode"] == publish_package["closing_mode"]
    assert merged_package["domain"] == publish_package["domain"]
    assert merged_package["profile_version"] == publish_package["profile_version"]
    assert merged_package["subdomain"] == publish_package["subdomain"]
    assert merged_package["content_intent"] == publish_package["content_intent"]
    assert merged_package["risk_level"] == publish_package["risk_level"]
    assert merged_package["risk_flags"] == publish_package["risk_flags"]
    frames = merged_package["storyboards"]
    assert [(frame["frame_id"], frame["layout"]) for frame in frames] == [
        (item.frame_id, item.layout) for item in _visual_plan().frame_plan
    ]
    assert frames[0]["headline"] == _content_contract()["first_screen_promise"]
    assert frames[3]["content_blocks"][0]["body"] == "第4张的单一信息任务"
    assert "Semantic Editorial Carousel Storyboard Generator" in captured["system_prompt"]
    assert "Structured Text Card Generator" not in captured["system_prompt"]


def test_storyboard_generator_without_plan_fails_before_model_or_prompt(monkeypatch):
    from src.nodes import node_o_storyboards_generator as module

    monkeypatch.setattr(
        module,
        "get_model",
        lambda: pytest.fail("missing modern plan must fail before model lookup"),
    )

    with pytest.raises(ValueError, match="requires visual_plan"):
        module.storyboards_generator_node(
            {
                "publish_package": {"topic_id": "tp_001"},
                "trends": [_topic()],
                "domain_context": _domain_context(),
                "content_policy": _content_policy(),
            }
        )


def test_semantic_storyboard_uses_final_package_contract_when_trend_is_stale(monkeypatch):
    from src.nodes import node_o_storyboards_generator as module

    captured = {}
    final_contract = _content_contract()
    stale_contract = {
        **final_contract,
        "first_screen_promise": "这是一份已经过期的首屏承诺",
        "content_job": "diagnose_and_adjust",
        "primary_visual_family": "face_zone_map",
        "primary_visual_subject": "face_map",
    }

    class FakeModel:
        def execute(self, messages):
            captured["human_prompt"] = messages[1].content
            return {"storyboards": _storyboard_frames()}

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())

    result = module.storyboards_generator_node(
        {
            "publish_package": {
                "topic_id": "tp_001",
                "content_contract": final_contract,
            },
            "trends": [
                SimpleNamespace(topic_id="tp_001", content_contract=stale_contract)
            ],
            "domain_context": _domain_context(),
            "content_policy": _content_policy(),
            "visual_plan": _visual_plan(),
        }
    )

    assert result["publish_package"]["content_contract"] == final_contract
    assert '"content_job": "save_and_check"' in captured["human_prompt"]
    assert stale_contract["first_screen_promise"] not in captured["human_prompt"]


def test_semantic_storyboard_rejects_package_contract_that_disagrees_with_plan(monkeypatch):
    from src.nodes import node_o_storyboards_generator as module

    mismatched_contract = {
        **_content_contract(),
        "content_job": "diagnose_and_adjust",
        "primary_visual_family": "face_zone_map",
        "primary_visual_subject": "face_map",
    }
    calls = {"count": 0}

    class FakeModel:
        def execute(self, _messages):
            calls["count"] += 1
            return {"storyboards": _storyboard_frames()}

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())

    with pytest.raises(
        ValueError,
        match="publish_package.content_contract must match visual_plan",
    ):
        module.storyboards_generator_node(
            {
                "publish_package": {
                    "topic_id": "tp_001",
                    "content_contract": mismatched_contract,
                },
                "trends": [_topic()],
                "domain_context": _domain_context(),
                "content_policy": _content_policy(),
                "visual_plan": _visual_plan(),
            }
        )
    assert calls["count"] == 0


def test_carousel_payload_accepts_the_visual_plan_frame_count():
    with pytest.raises(ValidationError):
        CarouselPayload.model_validate(
            {"storyboards": _storyboard_frames()[:4]}
        )

    payload = CarouselPayload.model_validate(
        {"storyboards": _storyboard_frames()}
    )
    assert len(payload.storyboards) == len(_visual_plan().frame_plan)


def test_storyboard_generator_rejects_invalid_payload_before_state_write(monkeypatch):
    from src.nodes import node_o_storyboards_generator as module

    class FakeModel:
        def execute(self, _messages):
            return {"storyboards": [{"template": "not_a_real_card"}]}

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())

    state = {
        "publish_package": {
            "title": "久坐间隙活动指南",
            "content": "body",
            "topic_id": "tp_001",
            "topic": "睡眠改善",
            "angle_id": "ag_001",
            "angle": "睡眠策略",
            "target_group": "上班族",
            "core_pain": "熬夜后疲惫",
            "cover_copy": "cover",
            "images": [],
            "hashtags": ["#x"],
            "notes": ["note"],
            **_narrative_metadata(),
            "domain": "wellness",
            "profile_version": "wellness-v1",
            "subdomain": "sleep",
            "content_intent": "how_to",
            "risk_level": "medium",
            "risk_flags": ["medical-adjacent", "sleep-adjacent"],
            "content_contract": _content_contract(),
        },
        "trends": [_topic()],
        "domain_context": _domain_context(),
        "content_policy": _content_policy(),
        "visual_plan": _visual_plan(),
    }

    with pytest.raises(ValidationError):
        module.storyboards_generator_node(state)
    assert "storyboards" not in state["publish_package"]


def test_semantic_storyboard_rejects_cover_promise_mismatch_before_state_write(monkeypatch):
    from src.nodes import node_o_storyboards_generator as module

    frames = _storyboard_frames()
    frames[0]["headline"] = "错误的首屏承诺"

    class FakeModel:
        def execute(self, _messages):
            return {"storyboards": frames}

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())
    state = {
        "publish_package": {
            "topic_id": "tp_001",
            "content_contract": _content_contract(),
        },
        "trends": [_topic()],
        "domain_context": _domain_context(),
        "content_policy": _content_policy(),
        "visual_plan": _visual_plan(),
    }

    with pytest.raises(
        ValueError,
        match="cover headline must exactly equal content_contract.first_screen_promise",
    ):
        module.storyboards_generator_node(state)
    assert "storyboards" not in state["publish_package"]


def test_semantic_storyboard_rejects_cover_promise_mismatch_after_r2_patch(monkeypatch):
    from src.nodes import node_o_storyboards_generator as module

    class FakeModel:
        def execute(self, _messages):
            return {"storyboards": _storyboard_frames()}

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())

    with pytest.raises(
        ValueError,
        match="cover headline must exactly equal content_contract.first_screen_promise",
    ):
        module.storyboards_generator_node(
            {
                "publish_package": {
                    "topic_id": "tp_001",
                    "content_contract": _content_contract(),
                    "storyboards": _storyboard_frames(),
                },
                "trends": [_topic()],
                "domain_context": _domain_context(),
                "content_policy": _content_policy(),
                "visual_plan": _visual_plan(),
                "r2_output": SimpleNamespace(
                    content_snapshot=SimpleNamespace(
                        storyboard_visible_text=[
                            {
                                "frame_id": "cover",
                                "text_blocks": {"headline": "补丁改坏的首屏承诺"},
                            }
                        ]
                    )
                ),
            }
        )


def test_storyboard_generator_rejects_frame_order_or_layout_drift(monkeypatch):
    from src.nodes import node_o_storyboards_generator as module

    frames = _storyboard_frames()
    frames[1]["layout"] = "decision_tree"

    class FakeModel:
        def execute(self, _messages):
            return {"storyboards": frames}

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())

    with pytest.raises(
        ValueError,
        match="storyboard frames must exactly match visual_plan frame order and layouts",
    ):
        module.storyboards_generator_node(
            {
                "publish_package": {
                    "topic_id": "tp_001",
                    "content_contract": _content_contract(),
                },
                "trends": [_topic()],
                "domain_context": _domain_context(),
                "content_policy": _content_policy(),
                "visual_plan": _visual_plan(),
            }
        )
