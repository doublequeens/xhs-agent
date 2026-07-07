from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from trend_collector.extractor import extract_trend_titles_from_html, normalize_creator_trends


FIXTURE = Path(__file__).parents[1] / "fixtures" / "trend_collector" / "creator_center_trends.html"


def test_extract_trend_titles_from_html_fixture():
    titles = extract_trend_titles_from_html(FIXTURE.read_text(encoding="utf-8"))

    assert titles == ["高温天通勤补水", "夏日健康生活打卡"]


def test_normalize_creator_trends_to_signals():
    signals = normalize_creator_trends(
        ["高温天通勤补水"],
        domain="healthy_lifestyle",
        subdomain="hydration",
        collected_at=datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert signals[0].source == "creator_center"
    assert signals[0].signal_type == "creator_center"
    assert signals[0].risk_level == "low"
