from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.nodes.node_a_02_topic_signal_collector import topic_signal_collector_node
from src.nodes.node_a_03_creative_brief_builder import creative_brief_builder_node
from src.nodes.node_a_04_topic_ideator import topic_ideator_node
from src.nodes.node_a_05_topic_diversity_filter import topic_diversity_filter_node


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
                "subdomain": "daily_habits",
                "content_intent": "checklist",
                "risk_level": "low",
                "risk_flags": [],
                "creative_seed": {
                    "signal_type": "seasonal",
                    "signal_name": "高温天",
                    "why_now": "高温天让补水提醒更有时机感。",
                    "domain_translation": "转译为健康生活方式下的饮水习惯提醒。",
                    "evergreen_pain": "忙起来容易忘记喝水。",
                    "timely_framing": "高温天更容易注意到补水问题。",
                },
            }
        ]


def test_signal_driven_topic_generation_offline(monkeypatch):
    monkeypatch.setattr("src.nodes.node_a_04_topic_ideator.get_model", lambda: FakeModel())
    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.compose_prompt_for_state",
        lambda task, state: "system prompt",
    )

    state = {
        "domain_context": {"domain": "healthy_lifestyle", "subdomain": "daily_habits"},
        "content_policy": {"risk_level": "low"},
        "memory_context": {},
        "trends_num": 1,
        "_today_for_test": date(2026, 7, 7),
        "_now_for_test": datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
    }

    state.update(topic_signal_collector_node(state))
    state.update(creative_brief_builder_node(state))
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
    monkeypatch.setattr("src.nodes.node_a_04_topic_ideator.get_model", lambda: FakeModel())
    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.compose_prompt_for_state",
        lambda task, state: "system prompt",
    )

    state = {
        "domain_context": {"domain": "healthy_lifestyle", "subdomain": "daily_habits"},
        "content_policy": {"risk_level": "low"},
        "memory_context": {},
        "trends_num": 1,
        "_today_for_test": date(2026, 7, 7),
        "_now_for_test": datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
    }

    state.update(topic_signal_collector_node(state))
    state.update(creative_brief_builder_node(state))
    state.update(topic_ideator_node(state))
    state.update(topic_diversity_filter_node(state))

    assert state["topic_generation_degraded_reason"] == "no_active_signals"
    assert state["trends"][0].creative_seed.why_now
    assert state["topic_generation_trace"].filtered_candidates_count == 1

