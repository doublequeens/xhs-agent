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
