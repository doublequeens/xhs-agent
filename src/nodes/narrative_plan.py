from collections.abc import Iterable

from src.schemas.narrative import NarrativePlan


def _get_value(payload, key):
    if isinstance(payload, dict):
        return payload.get(key)
    return getattr(payload, key, None)


def require_same_narrative_plan(actual, expected, *, stage: str) -> None:
    actual_plan = NarrativePlan.model_validate(actual)
    expected_plan = NarrativePlan.model_validate(expected)
    if actual_plan != expected_plan:
        raise ValueError(f"{stage} must preserve the selected narrative_plan")


def find_narrative_plan(
    candidates: Iterable,
    *,
    topic_id: str,
    angle_id: str,
    stage: str,
) -> NarrativePlan:
    matches = [
        candidate
        for candidate in candidates
        if _get_value(candidate, "topic_id") == topic_id
        and _get_value(candidate, "angle_id") == angle_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"{stage} requires exactly one narrative_plan source for "
            f"topic_id={topic_id}, angle_id={angle_id}; found {len(matches)}"
        )
    return NarrativePlan.model_validate(_get_value(matches[0], "narrative_plan"))
