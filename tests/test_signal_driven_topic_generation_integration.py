from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.creator_profile import COMMUTING_BEAUTY_WOMEN_V1
from src.nodes.node_a_02_topic_signal_collector import topic_signal_collector_node
from src.nodes.node_a_03_creative_brief_builder import creative_brief_builder_node
from src.nodes.node_a_04_topic_ideator import topic_ideator_node
from src.nodes.node_a_05_topic_diversity_filter import topic_diversity_filter_node


class FakeModel:
    def __init__(self, state):
        self.state = state

    def execute(self, messages):
        signal = self.state["creative_briefs"][0].signal
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
                    "content_job": "diagnose_and_adjust",
                    "primary_visual_family": "face_zone_map",
                    "primary_visual_subject": "face_map",
                    "proof_mode": "product_texture",
                    "recommended_frame_count": 6,
                },
                "creative_seed": {
                    "signal_type": signal.signal_type,
                    "signal_name": signal.signal_name,
                    "why_now": signal.why_now,
                    "domain_translation": signal.domain_translation,
                    "evergreen_pain": "防晒后上妆容易搓泥。",
                    "timely_framing": "高温天更容易出现脱妆和搓泥问题。",
                },
            }
        ]


def test_signal_driven_topic_generation_offline(monkeypatch):
    monkeypatch.setattr(
        "src.nodes.node_a_02_topic_signal_collector.XHSMemoryManager",
        lambda *a, **k: _EmptyManager(),
    )
    monkeypatch.setattr(
        "src.nodes.node_a_05_topic_diversity_filter.XHSMemoryManager",
        lambda *a, **k: _EmptyManager(),
    )

    state = {
        "creator_profile": COMMUTING_BEAUTY_WOMEN_V1,
        "domain_context": {"domain": "beauty", "subdomain": "skincare"},
        "content_policy": {"risk_level": "low"},
        "memory_context": {},
        "trends_num": 1,
        "_today_for_test": date(2026, 7, 7),
        "_now_for_test": datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
    }

    state.update(topic_signal_collector_node(state))
    state.update(creative_brief_builder_node(state))
    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.get_model", lambda: FakeModel(state)
    )
    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.compose_prompt_for_state",
        lambda task, state: "system prompt",
    )
    state.update(topic_ideator_node(state))
    state.update(topic_diversity_filter_node(state))

    assert state["trends"][0].creative_seed.why_now
    assert state["topic_generation_trace"].filtered_candidates_count == 1


class _EmptyManager:
    """Stand-in XHSMemoryManager: no stored signals, trace capture is a no-op,
    so the chain never touches the real local DB."""

    def __init__(self, *args, **kwargs):
        pass

    def init_db(self, *args, **kwargs):
        pass

    def get_active_trend_signals(self, domain, subdomain, today):
        return []

    def save_topic_generation_trace(self, trace):
        pass


def test_signal_driven_topic_generation_degrades_when_no_signals(monkeypatch, tmp_path):
    """A signal-less day must degrade gracefully through the whole chain
    (evergreen fallback) instead of crashing the graph. Regression for the
    empty-signal crash path."""
    empty_calendar = tmp_path / "trend_calendar.yml"
    empty_calendar.write_text("signals: []\n", encoding="utf-8")
    monkeypatch.setattr(
        "src.nodes.node_a_02_topic_signal_collector.CALENDAR_PATH", empty_calendar
    )
    monkeypatch.setattr(
        "src.nodes.node_a_02_topic_signal_collector.XHSMemoryManager",
        lambda *a, **k: _EmptyManager(),
    )
    monkeypatch.setattr(
        "src.nodes.node_a_05_topic_diversity_filter.XHSMemoryManager",
        lambda *a, **k: _EmptyManager(),
    )

    state = {
        "creator_profile": COMMUTING_BEAUTY_WOMEN_V1,
        "domain_context": {"domain": "beauty", "subdomain": "skincare"},
        "content_policy": {"risk_level": "low"},
        "memory_context": {},
        "trends_num": 1,
        "_today_for_test": date(2026, 5, 7),
        "_now_for_test": datetime(2026, 5, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
    }

    state.update(topic_signal_collector_node(state))
    state.update(creative_brief_builder_node(state))
    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.get_model", lambda: FakeModel(state)
    )
    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.compose_prompt_for_state",
        lambda task, state: "system prompt",
    )
    state.update(topic_ideator_node(state))
    state.update(topic_diversity_filter_node(state))

    assert (
        state["topic_generation_degraded_reason"]
        == "weather_signal_unavailable;no_active_signals"
    )
    assert state["trends"][0].creative_seed.why_now
    assert state["topic_generation_trace"].filtered_candidates_count == 1
