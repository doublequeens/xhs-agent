from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import yaml

from src.schemas.topic_signal import TopicSignal


def load_calendar_signals(
    path: Path,
    *,
    today: date,
    domain: str,
    subdomain: str,
    collected_at: datetime,
) -> list[TopicSignal]:
    if not path.exists():
        return []
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    signals = payload.get("signals") or []
    result: list[TopicSignal] = []
    for item in signals:
        active_from = date.fromisoformat(str(item["active_from"]))
        expires_at = date.fromisoformat(str(item["active_to"]))
        if not active_from <= today <= expires_at:
            continue
        domain_config = (item.get("applicable_domains") or {}).get(domain)
        if not domain_config:
            continue
        if subdomain not in list(domain_config.get("subdomains") or []):
            continue
        signal_name = str(item["signal_name"])
        angles = list(domain_config.get("angles") or [])
        result.append(
            TopicSignal(
                signal_id=f"calendar_{item['id']}",
                source="calendar",
                signal_type=item["signal_type"],
                signal_name=signal_name,
                normalized_signal=signal_name,
                domain=domain,
                subdomain=subdomain,
                why_now=f"{signal_name}处于当前内容时机窗口。",
                domain_translation="；".join(angles) if angles else signal_name,
                risk_level="low",
                avoid_topics=list(item.get("avoid") or []),
                confidence=0.9,
                active_from=active_from,
                expires_at=expires_at,
                collected_at=collected_at,
                metadata={"angles": angles},
            )
        )
    return result
