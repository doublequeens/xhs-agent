from types import SimpleNamespace

import pytest

from src.domain import build_content_policy, get_domain_profile, get_topic_metadata
from src.schemas.topic import TopicItem


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
    return {
        "frame_id": f"frame_{frame_number:03d}",
        "narrative_role": "封面钩子" if frame_number == 1 else "步骤展开",
        "frame_title": f"画面 {frame_number}",
        "image_orientation": "vertical",
        "aspect_ratio": "3:4",
        "recommended_size": "1080x1440",
        "visual_description": f"粉红小蝾螈画面 {frame_number}",
        "character_action": "抱着水杯发呆",
        "scene_background": "办公桌边",
        "composition": "竖版 3:4 构图，上方留白",
        "text_area": "顶部 20% 留白放标题",
        "on_image_copy": f"提示 {frame_number}",
        "narration": f"第 {frame_number} 张图的说明内容。",
        "image_prompt_cn": "中文提示词",
        "image_prompt_en": "English prompt",
        "negative_prompt": "realistic, horror",
        "continuity_note": "保持同一只粉红小蝾螈",
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


def test_storyboards_generator_preserves_full_publish_package_and_frame_contract(monkeypatch):
    from src.nodes import node_o_storyboards_generator as module

    required_frame_keys = {
        "frame_id",
        "narrative_role",
        "frame_title",
        "image_orientation",
        "aspect_ratio",
        "recommended_size",
        "visual_description",
        "character_action",
        "scene_background",
        "composition",
        "text_area",
        "on_image_copy",
        "narration",
        "image_prompt_cn",
        "image_prompt_en",
        "negative_prompt",
        "continuity_note",
    }

    class FakeModel:
        def execute(self, messages):
            return {
                "title": "wrong title",
                "content": "wrong content",
                "storyboards": [_storyboard_frame(index) for index in range(1, 9)],
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
    assert set(merged_package["storyboards"][0]) == required_frame_keys


@pytest.mark.parametrize(
    ("storyboards", "error_match"),
    [
        ([ _storyboard_frame(index) for index in range(1, 8) ], "storyboards"),
        ([ _storyboard_frame(index) for index in range(1, 12) ], "storyboards"),
        ([ {key: value for key, value in _storyboard_frame(1).items() if key != "negative_prompt"} ] + [_storyboard_frame(index) for index in range(2, 9)], "negative_prompt"),
        ("not-a-list", "storyboards"),
    ],
)
def test_storyboards_generator_rejects_invalid_storyboard_payload(monkeypatch, storyboards, error_match):
    from src.nodes import node_o_storyboards_generator as module

    class FakeModel:
        def execute(self, messages):
            return {"storyboards": storyboards}

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())

    with pytest.raises(RuntimeError, match=error_match):
        module.storyboards_generator_node(
            {
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
                "domain_context": _domain_context(),
                "content_policy": _content_policy(),
            }
        )
