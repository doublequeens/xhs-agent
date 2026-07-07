from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from memory.memory_manager import XHSMemoryManager
from src.schemas import AgentState
from src.topic_signals.collector import collect_topic_signals


CALENDAR_PATH = Path("config/trend_calendar.yml")


def _get_value(payload, key):
    if isinstance(payload, dict):
        return payload.get(key)
    return getattr(payload, key, None)


def topic_signal_collector_node(state: AgentState) -> dict:
    domain_context = state["domain_context"]
    domain = _get_value(domain_context, "domain")
    subdomain = _get_value(domain_context, "subdomain")
    now = state.get("_now_for_test") or datetime.now(ZoneInfo("Asia/Shanghai"))
    today = state.get("_today_for_test") or now.date()

    manager = XHSMemoryManager("data/xhs_memory.db")
    manager.init_db("memory/schema.sql")
    signals, degraded_reason = collect_topic_signals(
        manager=manager,
        calendar_path=CALENDAR_PATH,
        domain=domain,
        subdomain=subdomain,
        today=today,
        collected_at=now,
        weather_signal=None,
    )

    return {
        "topic_signals": signals,
        "topic_generation_degraded_reason": degraded_reason,
    }
