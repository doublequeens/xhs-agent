from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal, Protocol

from src.schemas.topic_signal import TopicSignal

WeatherType = Literal["high_heat", "cold_wave", "rainy", "humid", "dry", "windy", "normal"]

@dataclass(frozen=True)
class WeatherSnapshot:
    city: str
    date: date
    weather_type: WeatherType
    temperature_high: int | None
    temperature_low: int | None
    humidity_bucket: str
    source: str

class WeatherProvider(Protocol):
    def get_weather(self, city: str, today: date) -> WeatherSnapshot: ...

def weather_signal_from_snapshot(
    snapshot: WeatherSnapshot,
    *,
    domain: str,
    subdomain: str,
    collected_at: datetime,
) -> TopicSignal | None:
    if snapshot.weather_type == "normal":
        return None
    name_by_type = {
        "high_heat": f"{snapshot.city}高温天",
        "cold_wave": f"{snapshot.city}降温天",
        "rainy": f"{snapshot.city}连续阴雨",
        "humid": f"{snapshot.city}潮湿天",
        "dry": f"{snapshot.city}空气干燥",
        "windy": f"{snapshot.city}大风天",
    }
    translation_by_type = {
        "high_heat": "转译为补水、低门槛活动和通勤节奏提醒。",
        "cold_wave": "转译为保暖、作息和室内活动提醒。",
        "rainy": "转译为通勤、居家活动和睡眠环境提醒。",
        "humid": "转译为潮闷环境下的生活习惯提醒。",
        "dry": "转译为饮水、皮肤护理和室内环境提醒。",
        "windy": "转译为通勤防护和低风险生活提醒。",
    }
    signal_name = name_by_type[snapshot.weather_type]
    return TopicSignal(
        signal_id=f"weather_{snapshot.city}_{snapshot.date.isoformat()}_{snapshot.weather_type}",
        source="weather",
        signal_type="weather",
        signal_name=signal_name,
        normalized_signal=signal_name,
        domain=domain,
        subdomain=subdomain,
        why_now=f"{snapshot.city}当前天气为{signal_name}，适合做泛化生活场景切入。",
        domain_translation=translation_by_type[snapshot.weather_type],
        risk_level="low",
        avoid_topics=["疾病诊断", "治疗建议", "药物建议"],
        confidence=0.8,
        active_from=snapshot.date,
        expires_at=snapshot.date + timedelta(days=2),
        collected_at=collected_at,
        metadata={"city": snapshot.city, "temperature_high": snapshot.temperature_high, "temperature_low": snapshot.temperature_low, "humidity_bucket": snapshot.humidity_bucket, "source": snapshot.source},
    )
