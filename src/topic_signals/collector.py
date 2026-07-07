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

    degraded_reason = ";".join(degraded_reasons) if degraded_reasons else None
    return list(unique.values()), degraded_reason
