from __future__ import annotations

import random

from src.domain.models import ContentIntent
from src.schemas.topic_signal import CreativeBrief, TopicSignal


AUDIENCES = ["上班族", "学生党", "久坐人群", "健身新手", "生活习惯新手"]
PAINS = ["没时间", "懒得做", "做了没效果", "怕麻烦", "不知道对错"]
INTENTS: list[ContentIntent] = ["how_to", "checklist", "myth_busting", "experience"]
CONTRAST_FRAMES = ["低门槛", "误区纠偏", "场景清单", "3分钟行动", "反常识"]


def _historical_hint(memory_context: dict, index: int) -> str | None:
    patterns = list(memory_context.get("high_performing_patterns") or [])
    if not patterns:
        return None
    pattern = patterns[index % len(patterns)]
    return str(pattern.get("topic") or pattern.get("title") or "参考高表现结构")


def build_creative_briefs(
    signals: list[TopicSignal],
    *,
    trends_num: int,
    memory_context: dict,
    seed: int = 0,
) -> list[CreativeBrief]:
    if trends_num <= 0:
        raise ValueError("trends_num must be positive")
    if not signals:
        raise ValueError("signals must not be empty")

    rng = random.Random(seed)
    target_count = trends_num * 2
    sorted_signals = sorted(
        signals,
        key=lambda item: (-item.confidence, item.signal_id),
    )
    briefs: list[CreativeBrief] = []
    signal_counts: dict[str, int] = {}

    attempt = 0
    while len(briefs) < target_count and attempt < target_count * 20:
        attempt += 1
        signal_pool = sorted(
            sorted_signals,
            key=lambda item: (signal_counts.get(item.signal_id, 0), -item.confidence, item.signal_id),
        )
        signal = signal_pool[0]
        signal_counts[signal.signal_id] = signal_counts.get(signal.signal_id, 0) + 1
        index = len(briefs)
        briefs.append(
            CreativeBrief(
                brief_id=f"br_{index + 1:03d}",
                signal=signal,
                audience=AUDIENCES[index % len(AUDIENCES)],
                pain=PAINS[(index + rng.randrange(len(PAINS))) % len(PAINS)],
                content_intent=INTENTS[index % len(INTENTS)],
                contrast_frame=CONTRAST_FRAMES[index % len(CONTRAST_FRAMES)],
                historical_pattern_hint=_historical_hint(memory_context, index),
            )
        )

    return briefs
