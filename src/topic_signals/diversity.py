from __future__ import annotations

from difflib import SequenceMatcher

from metrics_collector.matcher import normalize_title
from src.schemas.topic import TopicItem


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(
        None, normalize_title(left), normalize_title(right)
    ).ratio()


def _average_pairwise_similarity(items: list[TopicItem]) -> float:
    if len(items) < 2:
        return 0.0
    scores = []
    for index, left in enumerate(items):
        for right in items[index + 1 :]:
            scores.append(_similarity(left.topic, right.topic))
    return sum(scores) / len(scores)


def _ratio(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 4)


def filter_topic_candidates(
    candidates: list[TopicItem],
    *,
    trends_num: int,
    duplicate_threshold: float = 0.72,
) -> tuple[list[TopicItem], dict[str, object]]:
    if trends_num <= 0:
        raise ValueError("trends_num must be positive")

    selected: list[TopicItem] = []
    signal_counts: dict[str, int] = {}

    for candidate in candidates:
        seed = candidate.creative_seed
        if not seed.why_now or not seed.domain_translation:
            continue
        if any(
            _similarity(candidate.topic, item.topic) >= duplicate_threshold
            for item in selected
        ):
            continue
        if signal_counts.get(seed.signal_name, 0) >= max(1, trends_num // 3):
            continue

        selected.append(candidate)
        signal_counts[seed.signal_name] = signal_counts.get(seed.signal_name, 0) + 1
        if len(selected) == trends_num:
            break

    selected_count = len(selected)
    timely_count = sum(
        1
        for item in selected
        if item.creative_seed.signal_type != "evergreen_context"
    )
    evergreen_pain_count = sum(
        1 for item in selected if item.creative_seed.evergreen_pain.strip()
    )
    metrics = {
        "unique_signal_count": len(
            {item.creative_seed.signal_name for item in selected}
        ),
        "unique_target_group_count": len({item.target_group for item in selected}),
        "unique_core_pain_count": len({item.core_pain for item in selected}),
        "unique_content_intent_count": len({item.content_intent for item in selected}),
        "average_pairwise_title_similarity": round(
            _average_pairwise_similarity(selected), 4
        ),
        "timely_signal_ratio": _ratio(timely_count, selected_count),
        "evergreen_pain_ratio": _ratio(evergreen_pain_count, selected_count),
    }

    return selected, metrics
