from types import SimpleNamespace

import pytest

from src.domain import get_topic_metadata
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
                    "domain": "wellness",
                    "subdomain": "sleep",
                    "content_intent": "how_to",
                    "risk_level": "medium",
                    "risk_flags": ["medical-adjacent", "sleep-adjacent"],
                }
            ]

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())

    result = module.trend_scout_node(
        {
            "trends_num": 1,
            "focus_keyword": "改善睡眠",
            "memory_context": {"recent_content": []},
            "domain_context": {"domain": "wellness", "subdomain": "sleep"},
            "content_policy": {"risk_level": "medium", "require_human_review": True},
        }
    )

    human_prompt = captured["messages"][1].content
    assert "domain_context" in human_prompt
    assert "content_policy" in human_prompt
    assert isinstance(result["trends"][0], TopicItem)
    assert result["trends"][0].domain == "wellness"
    assert result["trends"][0].risk_flags == ["medical-adjacent", "sleep-adjacent"]


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
                        "target_group": "上班族",
                        "core_pain": "熬夜后疲惫",
                        "best_cover_copy": "cover",
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
                "target_group": "wrong",
                "core_pain": "wrong",
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
            ),
            "hashtags": SimpleNamespace(hashtags=["#x"]),
            "image_candidates": [],
            "final_images": SimpleNamespace(image_final_choices=[]),
            "trends": [_topic()],
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
    assert publish_package["title"] == "睡眠改善指南"
    assert publish_package["content"] == "body"
