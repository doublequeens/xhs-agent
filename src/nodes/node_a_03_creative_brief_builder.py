from datetime import date, datetime

from src.creator_profile import COMMUTING_BEAUTY_WOMEN_V1
from src.schemas import AgentState
from src.schemas.topic_signal import TopicSignal
from src.topic_signals.briefs import build_creative_briefs


def _as_signal(value):
    if isinstance(value, TopicSignal):
        return value
    payload = dict(value)
    payload["active_from"] = date.fromisoformat(str(payload["active_from"]))
    payload["expires_at"] = date.fromisoformat(str(payload["expires_at"]))
    payload["collected_at"] = datetime.fromisoformat(str(payload["collected_at"]))
    return TopicSignal(**payload)


def creative_brief_builder_node(state: AgentState) -> dict:
    signals = [_as_signal(item) for item in state.get("topic_signals", [])]
    creator_profile = state.get("creator_profile", COMMUTING_BEAUTY_WOMEN_V1)
    briefs = build_creative_briefs(
        signals,
        trends_num=state.get("trends_num") or 10,
        memory_context=state.get("memory_context") or {},
        creator_profile=creator_profile,
        seed=0,
    )
    return {"creative_briefs": briefs}
