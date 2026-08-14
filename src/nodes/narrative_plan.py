from collections.abc import Iterable

from src.schemas.narrative import NarrativePlan
from src.utils import _get_value


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


# Self-repair reminder for LLM retry loops: the enum constraints that
# validation errors most often trip on. Shared by the nodes whose output
# embeds a narrative_plan, so the listings can never drift apart.
NARRATIVE_ENUM_REMINDER = (
    "narrative_plan.narrative_form 只能是 "
    "cognitive_correction / step_tutorial / checklist_collection / "
    "comparison / diagnostic_qa / scenario_story / story_reversal / "
    "reflective_editorial 之一；"
    "narrative_plan.closing_mode 只能是 "
    "none / boundary / reflection / focused_question / "
    "action_prompt 之一；"
    "narrative beats 的 kind 只能是 "
    "hook / scene / tension / misconception / reveal / principle / "
    "explanation / example / steps / checklist / comparison / "
    "diagnostic / qa / quote / boundary / summary / action 之一，"
    "不要把 closing_mode 的值写到 beat kind，也不要把其它字段的"
    "枚举值串到 narrative_plan"
)
