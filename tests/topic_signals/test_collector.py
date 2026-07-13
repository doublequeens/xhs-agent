from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.schemas.topic_signal import TopicSignal
from src.topic_signals.collector import collect_topic_signals


class FakeManager:
    def get_active_trend_signals(self, domain, subdomain, today):
        return [
            {
                "signal_id": "sig_db",
                "source": "creator_center",
                "signal_type": "creator_center",
                "signal_name": "活动话题",
                "normalized_signal": "活动话题",
                "domain": domain,
                "subdomain": subdomain,
                "why_now": "创作中心当前展示。",
                "domain_translation": "转译为生活习惯场景。",
                "risk_level": "low",
                "avoid_topics": [],
                "confidence": 0.8,
                "active_from": "2026-07-01",
                "expires_at": "2026-07-10",
                "collected_at": "2026-07-07T10:00:00+08:00",
                "metadata": {},
                "source_url": None,
                "raw_title": None,
            }
        ]


def test_collect_topic_signals_merges_sources(tmp_path):
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

    signals, degraded = collect_topic_signals(
        manager=FakeManager(),
        calendar_path=calendar,
        domain="healthy_lifestyle",
        subdomain="daily_habits",
        today=date(2026, 7, 7),
        collected_at=datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
        weather_signal=None,
    )

    assert degraded == "weather_signal_unavailable"
    assert [signal.signal_id for signal in signals] == [
        "calendar_summer_heat",
        "sig_db",
    ]


def test_collect_topic_signals_falls_back_to_evergreen_when_empty(tmp_path):
    """When no source yields a signal, the collector degrades to an evergreen
    fallback signal (instead of leaving downstream to crash) and records the
    degradation reason."""
    calendar = tmp_path / "trend_calendar.yml"
    calendar.write_text("signals: []\n", encoding="utf-8")

    class EmptyManager:
        def get_active_trend_signals(self, domain, subdomain, today):
            return []

    signals, degraded = collect_topic_signals(
        manager=EmptyManager(),
        calendar_path=calendar,
        domain="healthy_lifestyle",
        subdomain="daily_habits",
        today=date(2026, 7, 7),
        collected_at=datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
        weather_signal=None,
    )

    assert degraded == "weather_signal_unavailable;no_active_signals"
    assert [signal.signal_id for signal in signals] == ["evergreen_fallback"]
    fallback = signals[0]
    assert fallback.signal_type == "evergreen_context"
    assert fallback.metadata == {"fallback": True}
