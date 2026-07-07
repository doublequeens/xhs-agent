from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from memory.memory_manager import XHSMemoryManager
from src.schemas.topic_signal import TopicGenerationTrace
from src.topic_signals.diversity import filter_topic_candidates


def _get_value(payload, key):
    if isinstance(payload, dict):
        return payload.get(key)
    return getattr(payload, key, None)


def topic_diversity_filter_node(state: dict) -> dict:
    candidates = state.get("topic_candidates", [])
    trends_num = state.get("trends_num") or 10

    selected, metrics = filter_topic_candidates(candidates, trends_num=trends_num)

    domain_context = state["domain_context"]
    now = state.get("_now_for_test") or datetime.now(ZoneInfo("Asia/Shanghai"))

    trace = TopicGenerationTrace(
        run_id=f"tg_{uuid4().hex[:12]}",
        domain=_get_value(domain_context, "domain"),
        subdomain=_get_value(domain_context, "subdomain"),
        trends_num=trends_num,
        signals_used=[
            signal.signal_id for signal in state.get("topic_signals", [])
        ],
        creative_briefs_sampled=[
            brief.brief_id for brief in state.get("creative_briefs", [])
        ],
        generated_candidates_count=len(candidates),
        filtered_candidates_count=len(selected),
        final_trends=[item.topic_id for item in selected],
        diversity_metrics=metrics,
        degraded_reason=state.get("topic_generation_degraded_reason"),
        created_at=now,
    )

    manager = XHSMemoryManager("data/xhs_memory.db")
    manager.init_db("memory/schema.sql")
    manager.save_topic_generation_trace(trace)

    return {"trends": selected, "topic_generation_trace": trace}
