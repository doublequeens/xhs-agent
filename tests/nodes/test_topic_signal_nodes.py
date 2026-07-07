from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.nodes.node_a_02_topic_signal_collector import topic_signal_collector_node
from src.nodes.node_a_03_creative_brief_builder import creative_brief_builder_node


def test_topic_signal_collector_uses_calendar(monkeypatch, tmp_path):
    calendar = tmp_path / "trend_calendar.yml"
    calendar.write_text(
        """
signals:
  - id: summer_heat
    signal_type: seasonal
    signal_name: 高温天
    active_from: 2026-06-15
    active_to: 2026-08-31
    applicable_domains:
      healthy_lifestyle:
        subdomains: [daily_habits]
        angles: [作息安排]
    avoid: []
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "src.nodes.node_a_02_topic_signal_collector.CALENDAR_PATH",
        calendar,
    )

    result = topic_signal_collector_node(
        {
            "domain_context": {"domain": "healthy_lifestyle", "subdomain": "daily_habits"},
            "_today_for_test": date(2026, 7, 7),
            "_now_for_test": datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
        }
    )

    assert result["topic_signals"][0].signal_name == "高温天"


def test_creative_brief_builder_uses_topic_signals():
    result = creative_brief_builder_node(
        {
            "topic_signals": [
                {
                    "signal_id": "sig_001",
                    "source": "calendar",
                    "signal_type": "seasonal",
                    "signal_name": "高温天",
                    "normalized_signal": "高温天",
                    "domain": "healthy_lifestyle",
                    "subdomain": "daily_habits",
                    "why_now": "当前有效。",
                    "domain_translation": "转译为生活习惯。",
                    "risk_level": "low",
                    "avoid_topics": [],
                    "confidence": 0.9,
                    "active_from": "2026-07-01",
                    "expires_at": "2026-07-31",
                    "collected_at": "2026-07-07T00:00:00+08:00",
                    "metadata": {},
                }
            ],
            "trends_num": 3,
            "memory_context": {},
        }
    )

    assert len(result["creative_briefs"]) == 6
