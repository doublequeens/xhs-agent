from collections.abc import Mapping
from typing import Any

from src.editorial_carousel.planner import build_visual_plan
from src.editorial_carousel.legacy import modern_editorial_transition_updates
from src.schemas import AgentState
from src.schemas.visual_plan import VisualPlan


def _recent_visual_signatures(state: AgentState) -> list[Any]:
    memory_context = state.get("memory_context") or {}
    direct = memory_context.get("recent_visual_signatures")
    if isinstance(direct, list):
        return list(direct)
    signatures = []
    recent_content = (
        memory_context.get("recent_content")
        or memory_context.get("same_subdomain_recent")
        or []
    )
    for item in recent_content:
        if not isinstance(item, Mapping):
            continue
        visual_plan = item.get("visual_plan")
        if not isinstance(visual_plan, Mapping):
            continue
        try:
            validated_plan = VisualPlan.model_validate(visual_plan)
        except ValueError:
            continue
        signatures.append(
            {
                "narrative_form": validated_plan.narrative_form,
                "template_family": validated_plan.template_family,
                "frame_plan_signature": [
                    frame.page_archetype
                    for frame in validated_plan.frame_plan
                ],
                "frame_count": len(validated_plan.frame_plan),
            }
        )
    return signatures


def visual_strategy_planner_node(state: AgentState) -> AgentState:
    publish_package = state.get("publish_package") or {}
    content_contract = publish_package.get("content_contract")
    if content_contract is None:
        raise ValueError(
            "visual_strategy_planner_node requires "
            "publish_package.content_contract"
        )
    narrative_plan = publish_package.get("narrative_plan")
    if narrative_plan is None:
        raise ValueError(
            "visual_strategy_planner_node requires "
            "publish_package.narrative_plan"
        )

    return {
        **modern_editorial_transition_updates(),
        "visual_plan": build_visual_plan(
            content_contract,
            narrative_plan,
            publish_package,
            recent_signatures=_recent_visual_signatures(state),
        ),
    }
