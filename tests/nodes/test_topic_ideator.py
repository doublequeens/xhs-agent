from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.nodes.node_a_04_topic_ideator import topic_ideator_node
from src.schemas.topic_signal import CreativeBrief, TopicSignal


class FakeModel:
    def execute(self, messages):
        return [
            {
                "topic_id": "tp_001",
                "topic": "高温通勤日，上班族的低门槛补水提醒",
                "target_group": "上班族",
                "core_pain": "忙起来忘记喝水",
                "hook": "不是猛灌水，而是把提醒放进通勤和办公节奏里。",
                "content_form": "checklist",
                "risk_note": "不涉及疾病治疗或补剂建议。",
                "domain": "healthy_lifestyle",
                "subdomain": "hydration",
                "content_intent": "checklist",
                "risk_level": "low",
                "risk_flags": [],
                "creative_seed": {
                    "signal_type": "weather",
                    "signal_name": "上海高温天",
                    "why_now": "高温天让补水提醒更有时机感。",
                    "domain_translation": "转译为健康生活方式下的饮水习惯提醒。",
                    "evergreen_pain": "忙起来容易忘记喝水。",
                    "timely_framing": "高温天更容易注意到补水问题。",
                },
            }
        ]


class OffBriefSeedModel:
    def execute(self, messages):
        item = FakeModel().execute(messages)[0]
        item["creative_seed"] = {
            "signal_type": "creator_center",
            "signal_name": "最近爆火话题",
            "why_now": "大家都在讨论。",
            "domain_translation": "随便转译。",
            "evergreen_pain": "怕麻烦。",
            "timely_framing": "最近很火。",
        }
        return [item]


def _brief():
    signal = TopicSignal(
        signal_id="sig_001",
        source="weather",
        signal_type="weather",
        signal_name="上海高温天",
        normalized_signal="上海高温天",
        domain="healthy_lifestyle",
        subdomain="hydration",
        why_now="高温天让补水提醒更有时机感。",
        domain_translation="转译为健康生活方式下的饮水习惯提醒。",
        risk_level="low",
        avoid_topics=[],
        confidence=0.8,
        active_from=date(2026, 7, 7),
        expires_at=date(2026, 7, 9),
        collected_at=datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
        metadata={},
    )
    return CreativeBrief(
        brief_id="br_001",
        signal=signal,
        audience="上班族",
        pain="没时间",
        content_intent="checklist",
        contrast_frame="低门槛",
        historical_pattern_hint=None,
    )


def test_topic_ideator_generates_topic_candidates(monkeypatch):
    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.get_model", lambda: FakeModel()
    )
    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.compose_prompt_for_state",
        lambda task, state: "system prompt",
    )
    result = topic_ideator_node(
        {
            "creative_briefs": [_brief()],
            "domain_context": {
                "domain": "healthy_lifestyle",
                "subdomain": "hydration",
            },
            "content_policy": {"risk_level": "low"},
        }
    )
    assert result["topic_candidates"][0].creative_seed.signal_name == "上海高温天"


def test_topic_ideator_rejects_creative_seed_not_bound_to_input_brief(monkeypatch):
    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.get_model", lambda: OffBriefSeedModel()
    )
    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.compose_prompt_for_state",
        lambda task, state: "system prompt",
    )

    with pytest.raises(RuntimeError, match="creative_seed must match an input brief"):
        topic_ideator_node(
            {
                "creative_briefs": [_brief()],
                "domain_context": {
                    "domain": "healthy_lifestyle",
                    "subdomain": "hydration",
                },
                "content_policy": {"risk_level": "low"},
            }
        )
