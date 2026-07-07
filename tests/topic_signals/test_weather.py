from datetime import date, datetime
from zoneinfo import ZoneInfo
from src.topic_signals.weather import (
    DEFAULT_WEATHER_CITY,
    ShanghaiGeneralizedWeatherProvider,
    WeatherSnapshot,
    weather_signal_from_snapshot,
)


def test_shanghai_generalized_weather_provider_returns_summer_heat_signal_source():
    provider = ShanghaiGeneralizedWeatherProvider()

    snapshot = provider.get_weather(DEFAULT_WEATHER_CITY, date(2026, 7, 7))
    signal = weather_signal_from_snapshot(
        snapshot,
        domain="healthy_lifestyle",
        subdomain="hydration",
        collected_at=datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert snapshot.city == "上海"
    assert snapshot.weather_type == "high_heat"
    assert snapshot.source == "generalized_shanghai_weather"
    assert signal is not None
    assert signal.signal_name == "上海高温天"

def test_high_heat_weather_creates_shanghai_signal():
    snapshot = WeatherSnapshot(city="上海", date=date(2026, 7, 7), weather_type="high_heat", temperature_high=36, temperature_low=28, humidity_bucket="humid", source="fake")
    signal = weather_signal_from_snapshot(snapshot, domain="healthy_lifestyle", subdomain="hydration", collected_at=datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")))
    assert signal is not None
    assert signal.signal_type == "weather"
    assert signal.signal_name == "上海高温天"
    assert "高温" in signal.why_now

def test_normal_weather_returns_none():
    snapshot = WeatherSnapshot(city="上海", date=date(2026, 7, 7), weather_type="normal", temperature_high=28, temperature_low=22, humidity_bucket="normal", source="fake")
    assert weather_signal_from_snapshot(snapshot, domain="healthy_lifestyle", subdomain="daily_habits", collected_at=datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai"))) is None
