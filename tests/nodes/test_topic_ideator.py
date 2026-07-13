from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.creator_profile import COMMUTING_BEAUTY_WOMEN_V1
from src.nodes.node_a_04_topic_ideator import topic_ideator_node
from src.schemas.topic_signal import CreativeBrief, TopicSignal


class FakeModel:
    def execute(self, messages):
        return [
            {
                "topic_id": "tp_001",
                "topic": "高温通勤日，防晒后底妆如何不搓泥",
                "target_group": COMMUTING_BEAUTY_WOMEN_V1.audience,
                "core_pain": "防晒后上妆容易搓泥",
                "hook": "通勤前两步避开防晒搓泥。",
                "content_form": "checklist",
                "risk_note": "不涉及疾病诊断或治疗建议。",
                "domain": "beauty",
                "subdomain": "skincare",
                "content_intent": "checklist",
                "risk_level": "low",
                "risk_flags": [],
                "content_contract": {
                    "audience": COMMUTING_BEAUTY_WOMEN_V1.audience,
                    "trigger_situation": "早八通勤前",
                    "decision_problem": "防晒后是否能立刻上底妆",
                    "first_screen_promise": "通勤前两步避开防晒搓泥",
                    "screenshot_asset": "防晒霜与粉底的上脸对比",
                    "proof_asset": "不同用量的搓泥对比图",
                    "visual_mode": "text_plus_real_proof",
                },
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
        audience=COMMUTING_BEAUTY_WOMEN_V1.audience,
        pain="early commute",
        content_intent="checklist",
        contrast_frame="低门槛",
        historical_pattern_hint=None,
    )


def profile_bound_state(profile=COMMUTING_BEAUTY_WOMEN_V1):
    return {
        "creator_profile": profile,
        "creative_briefs": [_brief()],
        "domain_context": {"domain": "beauty", "subdomain": "skincare"},
        "content_policy": {"risk_level": "low"},
    }


def test_topic_ideator_generates_topic_candidates(monkeypatch):
    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.get_model", lambda: FakeModel()
    )
    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.compose_prompt_for_state",
        lambda task, state: "system prompt",
    )
    result = topic_ideator_node(profile_bound_state())
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
        topic_ideator_node(profile_bound_state())


def test_topic_ideator_rejects_candidate_outside_creator_profile(monkeypatch):
    class OutsideProfileModel:
        def execute(self, messages):
            item = FakeModel().execute(messages)[0]
            item["domain"] = "wellness"
            return [item]

    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.get_model", lambda: OutsideProfileModel()
    )
    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.compose_prompt_for_state",
        lambda task, state: "system prompt",
    )

    with pytest.raises(ValueError, match="outside creator profile scope"):
        topic_ideator_node(profile_bound_state())


def test_topic_ideator_normalizes_model_audience_to_creator_profile(monkeypatch):
    class GenericAudienceModel:
        def execute(self, messages):
            item = FakeModel().execute(messages)[0]
            item["target_group"] = "上班族"
            item["content_contract"]["audience"] = "上班族"
            return [item]

    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.get_model", lambda: GenericAudienceModel()
    )
    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.compose_prompt_for_state",
        lambda task, state: "system prompt",
    )

    candidate = topic_ideator_node(profile_bound_state())["topic_candidates"][0]

    assert candidate.target_group == COMMUTING_BEAUTY_WOMEN_V1.audience
    assert candidate.content_contract.audience == COMMUTING_BEAUTY_WOMEN_V1.audience


def test_topic_ideator_requires_creator_profile(monkeypatch):
    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.get_model", lambda: FakeModel()
    )
    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.compose_prompt_for_state",
        lambda task, state: "system prompt",
    )

    state = profile_bound_state()
    state.pop("creator_profile")

    with pytest.raises(ValueError, match="creator profile is required"):
        topic_ideator_node(state)


@pytest.mark.parametrize(
    ("field", "value", "profile", "message"),
    [
        (
            "content_contract.visual_mode",
            "comparison_table",
            COMMUTING_BEAUTY_WOMEN_V1.model_copy(
                update={"visual_modes": ("text_card",)}
            ),
            "content contract visual mode is not allowed by creator profile",
        ),
    ],
)
def test_topic_ideator_rejects_profile_contract_mismatch(
    monkeypatch, field, value, profile, message
):
    class MismatchedContractModel:
        def execute(self, messages):
            item = FakeModel().execute(messages)[0]
            if field.startswith("content_contract."):
                contract_field = field.removeprefix("content_contract.")
                item["content_contract"][contract_field] = value
            else:
                item[field] = value
            return [item]

    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.get_model",
        lambda: MismatchedContractModel(),
    )
    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.compose_prompt_for_state",
        lambda task, state: "system prompt",
    )

    with pytest.raises(ValueError, match=message):
        topic_ideator_node(profile_bound_state(profile))
