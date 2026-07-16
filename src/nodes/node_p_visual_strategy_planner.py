from collections.abc import Mapping
from typing import Any

from src.editorial_carousel.planner import build_visual_plan
from src.editorial_carousel.legacy import modern_editorial_transition_updates
from src.schemas import AgentState


def _recent_visual_signatures(state: AgentState) -> list[Any]:
    memory_context = state.get("memory_context") or {}
    signatures = list(
        memory_context.get("recent_frame_plan_signatures")
        or memory_context.get("frame_plan_signatures")
        or []
    )
    recent_content = (
        memory_context.get("recent_content")
        or memory_context.get("same_subdomain_recent")
        or []
    )
    for item in recent_content:
        if not isinstance(item, Mapping):
            continue
        signature = item.get("visual_signature")
        if signature is None and item.get("template_family") is not None:
            signature = item
        if signature is None:
            signature = item.get("frame_plan_signature")
        if signature is None:
            visual_plan = item.get("visual_plan")
            if isinstance(visual_plan, Mapping):
                frame_plan = visual_plan.get("frame_plan")
                if isinstance(frame_plan, list):
                    signature = {
                        "narrative_form": visual_plan.get("narrative_form"),
                        "template_family": visual_plan.get("template_family"),
                        "frame_plan_signature": frame_plan,
                        "frame_count": len(frame_plan),
                    }
        if signature is not None:
            signatures.append(signature)
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
