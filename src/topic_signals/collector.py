from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from src.schemas.topic_signal import TopicSignal
from src.topic_signals.calendar import load_calendar_signals


def _signal_from_mapping(row: dict[str, object]) -> TopicSignal:
    payload = dict(row)
    payload["active_from"] = date.fromisoformat(str(payload["active_from"]))
    payload["expires_at"] = date.fromisoformat(str(payload["expires_at"]))
    payload["collected_at"] = datetime.fromisoformat(str(payload["collected_at"]))
    return TopicSignal(**payload)


def _evergreen_fallback_signal(
    domain: str, subdomain: str, today: date, collected_at: datetime
) -> TopicSignal:
    """When no timely signal is active, fall back to an evergreen pain signal
    so the pipeline degrades gracefully instead of crashing. The degradation
    is still surfaced via the returned ``degraded_reason``."""
    return TopicSignal(
        signal_id="evergreen_fallback",
        source="fallback",
        signal_type="evergreen_context",
        signal_name="通用生活场景",
        normalized_signal="通用生活场景",
        domain=domain,
        subdomain=subdomain,
        why_now="当前无活跃时机信号（日历/天气/创作者中心均无），回退到 evergreen 痛点切入。",
        domain_translation="转译为该领域下低风险、长期有效的生活习惯场景。",
        risk_level="low",
        avoid_topics=["疾病诊断", "治疗建议", "药物建议"],
        confidence=0.5,
        active_from=today,
        expires_at=today,
        collected_at=collected_at,
        metadata={"fallback": True},
    )


def collect_topic_signals(
    *,
    manager,
    calendar_path: Path,
    domain: str,
    subdomain: str,
    today: date,
    collected_at: datetime,
    weather_signal: TopicSignal | None,
) -> tuple[list[TopicSignal], str | None]:
    signals: list[TopicSignal] = []
    degraded_reasons: list[str] = []

    calendar_signals = load_calendar_signals(
        calendar_path,
        today=today,
        domain=domain,
        subdomain=subdomain,
        collected_at=collected_at,
    )
    signals.extend(calendar_signals)

    if weather_signal is not None:
        signals.append(weather_signal)

    stored_rows = manager.get_active_trend_signals(
        domain=domain,
        subdomain=subdomain,
        today=today.isoformat(),
    )
    signals.extend(_signal_from_mapping(row) for row in stored_rows)

    if not signals:
        degraded_reasons.append("no_active_signals")

    unique: dict[str, TopicSignal] = {}
    for signal in signals:
        unique.setdefault(signal.signal_id, signal)

    if not unique:
        # No timely signal is active today: degrade to an evergreen fallback so
        # downstream brief building / ideation still have a signal to work
        # with. The "no_active_signals" reason recorded above surfaces it.
        unique["evergreen_fallback"] = _evergreen_fallback_signal(
            domain, subdomain, today, collected_at
        )

    degraded_reason = ";".join(degraded_reasons) if degraded_reasons else None
    return list(unique.values()), degraded_reason
