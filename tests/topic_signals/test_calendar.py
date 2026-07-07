from datetime import date, datetime
from zoneinfo import ZoneInfo
from src.topic_signals.calendar import load_calendar_signals

def test_loads_active_calendar_signal_for_scope(tmp_path):
    path = tmp_path / "trend_calendar.yml"
    path.write_text("\nsignals:\n  - id: summer_heat\n    signal_type: seasonal\n    signal_name: 高温天\n    active_from: 2026-06-15\n    active_to: 2026-08-31\n    applicable_domains:\n      healthy_lifestyle:\n        subdomains: [hydration, daily_habits]\n        angles: [低门槛补水提醒]\n    avoid: [中暑治疗建议]\n", encoding="utf-8")
    signals = load_calendar_signals(path, today=date(2026, 7, 7), domain="healthy_lifestyle", subdomain="hydration", collected_at=datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")))
    assert len(signals) == 1
    assert signals[0].signal_id == "calendar_summer_heat"
    assert signals[0].avoid_topics == ["中暑治疗建议"]

def test_ignores_inactive_or_wrong_scope_calendar_signal(tmp_path):
    path = tmp_path / "trend_calendar.yml"
    path.write_text("\nsignals:\n  - id: winter_dry\n    signal_type: seasonal\n    signal_name: 冬季干燥\n    active_from: 2026-12-01\n    active_to: 2027-02-28\n    applicable_domains:\n      beauty:\n        subdomains: [skincare]\n        angles: [保湿护理]\n    avoid: []\n", encoding="utf-8")
    signals = load_calendar_signals(path, today=date(2026, 7, 7), domain="healthy_lifestyle", subdomain="hydration", collected_at=datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")))
    assert signals == []
