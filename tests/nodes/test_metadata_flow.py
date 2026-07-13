from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.domain import build_content_policy, get_domain_profile, get_topic_metadata
from src.schemas import StoryboardPayload
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


def _storyboard_frame(frame_number: int):
    frames = [
        {"template": "cover_statement"},
        {"template": "wrong_vs_right", "wrong_items": ["立刻上妆", "厚涂粉底"], "right_items": ["等待成膜", "少量点涂"]},
        {"template": "step_timeline", "steps": [{"name": "防晒", "hint": "薄涂全脸"}, {"name": "等待", "hint": "静置三分钟"}, {"name": "底妆", "hint": "少量点涂"}]},
        {"template": "saveable_checklist", "checklist_items": ["薄涂防晒", "等待成膜", "少量点涂"]},
        {"template": "decision_rule", "conditions": [{"situation": "底妆开始搓泥", "recommendation": "减少用量等待"}, {"situation": "时间不足", "recommendation": "先缩减步骤"}]},
        {"template": "question_closer", "question": "你最常在哪步搓泥？"},
    ]
    return {
        "frame_id": f"frame_{frame_number:03d}",
        "theme": "warm_neutral",
        "kicker": f"第{frame_number}张",
        "headline": _content_contract()["first_screen_promise"] if frame_number == 1 else f"第{frame_number}张要点",
        "footer": "按需微调",
        **frames[frame_number - 1],
    }


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
                )
            ),
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


def test_assembler_overwrites_publish_package_metadata(monkeypatch):
    from src.nodes import node_o_assembler as module

    class FakeModel:
        def execute(self, messages):
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
                risk_flags=["medical-adjacent", "sleep-adjacent"],
            ),
            "hashtags": SimpleNamespace(hashtags=["#x"]),
            "image_candidates": [],
            "final_images": SimpleNamespace(image_final_choices=[]),
            "trends": [_topic()],
            "domain_context": _domain_context(),
            "content_policy": _content_policy(),
        }
    )

    publish_package = result["publish_package"]
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
    assert publish_package["title"] == "睡眠改善指南"
    assert publish_package["content"] == "body"
    assert publish_package["profile_version"] == "wellness-v1"
    assert publish_package["content_contract"] == _content_contract()


def test_assembler_enforces_title_max_length_including_punctuation(monkeypatch):
    from src.nodes import node_o_assembler as module

    class FakeModel:
        def execute(self, _messages):
            return {
                "images": [],
                "hashtags": ["#x"],
                "notes": [],
                "storyboard_strategy": "auto",
            }

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())

    result = module.assembler_node(
        {
            "final_content": SimpleNamespace(
                final_title="1234567890123456789！超长标题",
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
                risk_flags=["medical-adjacent"],
            ),
            "hashtags": SimpleNamespace(hashtags=["#x"]),
            "final_images": SimpleNamespace(image_final_choices=[]),
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
                "storyboard_strategy": "generated",
                "hashtags": ["#generated"],
            }

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())

    result = module.assembler_node(
        {
            "final_content": SimpleNamespace(
                final_title="R2 修订后的标题",
                final_md="R2 修订后的正文",
                topic_id="tp_001",
                topic="睡眠改善",
                angle_id="ag_001",
                angle="睡眠策略",
                target_group="上班族",
                core_pain="熬夜后疲惫",
                best_cover_copy="R2 修订后的封面",
                domain="wellness",
                subdomain="sleep",
                content_intent="how_to",
                risk_level="medium",
                risk_flags=["medical-adjacent"],
            ),
            "hashtags": SimpleNamespace(hashtags=["#generated"]),
            "final_images": SimpleNamespace(image_final_choices=[]),
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


def test_storyboards_generator_preserves_full_publish_package_and_text_card_contract(monkeypatch):
    from src.nodes import node_o_storyboards_generator as module

    class FakeModel:
        def execute(self, messages):
            frames = [_storyboard_frame(index) for index in range(1, 7)]
            return {
                "title": "wrong title",
                "content": "wrong content",
                "storyboards": frames,
            }

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
        "storyboard_strategy": "scenario_companion",
        "domain": "wellness",
        "profile_version": "wellness-v1",
        "subdomain": "sleep",
        "content_intent": "how_to",
        "risk_level": "medium",
        "risk_flags": ["medical-adjacent", "sleep-adjacent"],
    }

    result = module.storyboards_generator_node(
        {
            "publish_package": publish_package,
            "trends": [_topic()],
            "domain_context": _domain_context(),
            "content_policy": _content_policy(),
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
    assert merged_package["storyboard_strategy"] == publish_package["storyboard_strategy"]
    assert merged_package["domain"] == publish_package["domain"]
    assert merged_package["profile_version"] == publish_package["profile_version"]
    assert merged_package["subdomain"] == publish_package["subdomain"]
    assert merged_package["content_intent"] == publish_package["content_intent"]
    assert merged_package["risk_level"] == publish_package["risk_level"]
    assert merged_package["risk_flags"] == publish_package["risk_flags"]
    frames = merged_package["storyboards"]
    assert [frame["template"] for frame in frames] == [
        "cover_statement", "wrong_vs_right", "step_timeline",
        "saveable_checklist", "decision_rule", "question_closer",
    ]
    assert {frame["theme"] for frame in frames} == {"warm_neutral"}
    assert frames[0]["headline"] == _content_contract()["first_screen_promise"]
    assert frames[3]["checklist_items"] == ["薄涂防晒", "等待成膜", "少量点涂"]


def test_storyboard_payload_requires_exactly_six_cards():
    with pytest.raises(ValidationError):
        StoryboardPayload.model_validate(
            {"storyboards": [_storyboard_frame(index) for index in range(1, 6)]}
        )

    payload = StoryboardPayload.model_validate(
        {"storyboards": [_storyboard_frame(index) for index in range(1, 7)]}
    )
    assert len(payload.storyboards) == 6


def test_storyboard_generator_leaves_schema_rejection_to_carousel_qa(monkeypatch):
    from src.nodes import node_o_storyboards_generator as module
    from src.nodes.node_p_carousel_qa import carousel_qa_node

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
            "storyboard_strategy": "scenario_companion",
            "domain": "wellness",
            "profile_version": "wellness-v1",
            "subdomain": "sleep",
            "content_intent": "how_to",
            "risk_level": "medium",
            "risk_flags": ["medical-adjacent", "sleep-adjacent"],
        },
        "trends": [_topic()],
        "domain_context": _domain_context(),
        "content_policy": _content_policy(),
    }

    generated = module.storyboards_generator_node(state)
    assert generated["publish_package"]["storyboards"] == [{"template": "not_a_real_card"}]
