from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from src.models import get_model
from src.nodes.publish_patch import (
    apply_storyboard_visible_text_patch,
    extract_storyboard_visible_text,
    merge_publish_package,
    merge_storyboard_visible_text,
    storyboard_patch_without_visible_text,
)
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value
from src.schemas import AgentState, CarouselPayload, VisualPlan
from src.schemas.content_contract import ContentContract


def _get_value(payload, key):
    if isinstance(payload, dict):
        return payload.get(key)
    return getattr(payload, key, None)


def _selected_content_contract(state: AgentState, publish_package: dict) -> dict:
    """Read the topic contract for a pre-visual-plan checkpoint."""

    topic_id = publish_package.get("topic_id")
    matches = [
        topic
        for topic in state.get("trends") or []
        if _get_value(topic, "topic_id") == topic_id
    ]
    if not matches:
        raise ValueError(f"Unknown topic_id: {topic_id}")
    if len(matches) > 1:
        raise ValueError(f"Duplicate topic_id: {topic_id}")

    content_contract = _get_value(matches[0], "content_contract")
    if content_contract is None:
        raise ValueError(f"Selected topic {topic_id} requires content_contract")
    if hasattr(content_contract, "model_dump"):
        return content_contract.model_dump(mode="json")
    return dict(content_contract)


def _final_content_contract(
    publish_package: dict,
    visual_plan: VisualPlan,
) -> ContentContract:
    raw_contract = publish_package.get("content_contract")
    if raw_contract is None:
        raise ValueError(
            "semantic storyboard generation requires "
            "publish_package.content_contract"
        )
    contract = ContentContract.model_validate(raw_contract)
    if (
        contract.content_job != visual_plan.content_job
        or contract.primary_visual_family != visual_plan.primary_visual_family
    ):
        raise ValueError(
            "publish_package.content_contract must match visual_plan "
            "content_job and primary_visual_family"
        )
    return contract


def _semantic_payload(
    raw_payload: Any,
    visual_plan: VisualPlan,
    content_contract: ContentContract,
) -> CarouselPayload:
    payload = CarouselPayload.model_validate(raw_payload)
    expected = [
        (item.frame_id, item.layout) for item in visual_plan.frame_plan
    ]
    actual = [(item.frame_id, item.layout) for item in payload.storyboards]
    if actual != expected:
        raise ValueError(
            "storyboard frames must exactly match visual_plan frame order and layouts"
        )
    if payload.storyboards[0].headline != content_contract.first_screen_promise:
        raise ValueError(
            "storyboard cover headline must exactly equal "
            "content_contract.first_screen_promise"
        )
    return payload


def _human_prompt(
    *,
    publish_package: dict,
    content_contract: dict,
    visual_plan: VisualPlan | None,
    domain_context,
    content_policy,
    evidence_briefs,
) -> str:
    sections = [
        "输入参数如下：",
        f"- publish_package:\n{serialize_prompt_value(publish_package)}",
        f"- content_contract:\n{serialize_prompt_value(content_contract)}",
    ]
    if visual_plan is not None:
        sections.append(f"- visual_plan:\n{serialize_prompt_value(visual_plan)}")
    sections.extend(
        [
            f"- domain_context:\n{serialize_prompt_value(domain_context)}",
            f"- content_policy:\n{serialize_prompt_value(content_policy)}",
            f"- evidence_briefs:\n{serialize_prompt_value(evidence_briefs)}",
            "请按照 system 规则进行处理。",
        ]
    )
    return "\n".join(sections)


def storyboards_generator_node(state: AgentState) -> AgentState:
    """Generate a strict semantic carousel from the persisted modern plan."""

    publish_package = state.get("publish_package", {})
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})
    evidence_briefs = state.get("evidence_briefs", {})
    visual_plan_value = state.get("visual_plan")
    if visual_plan_value is None:
        raise ValueError("storyboards_generator_node requires visual_plan")
    visual_plan = VisualPlan.model_validate(visual_plan_value)
    validated_contract = _final_content_contract(
        publish_package,
        visual_plan,
    )
    content_contract = validated_contract.model_dump(mode="json")

    messages = [
        SystemMessage(
            content=compose_prompt_for_state("storyboards_generator", state)
        ),
        HumanMessage(
            content=_human_prompt(
                publish_package=publish_package,
                content_contract=content_contract,
                visual_plan=visual_plan,
                domain_context=domain_context,
                content_policy=content_policy,
                evidence_briefs=evidence_briefs,
            )
        ),
    ]

    storyboard_json = get_model().execute(messages)
    payload = _semantic_payload(
        storyboard_json,
        visual_plan,
        validated_contract,
    )
    generated_storyboards = payload.model_dump(mode="json")["storyboards"]

    merged_publish_package = dict(publish_package)
    merged_publish_package["content_contract"] = content_contract
    merged_publish_package["storyboards"] = generated_storyboards

    pending_patch = state.get("pending_human_publish_patch")
    if pending_patch:
        merged_publish_package = merge_publish_package(
            merged_publish_package,
            storyboard_patch_without_visible_text(pending_patch),
            replace_storyboards=bool(
                state.get("pending_human_replace_storyboards")
            ),
        )

    r2_output = state.get("r2_output")
    content_snapshot = getattr(r2_output, "content_snapshot", None)
    if content_snapshot is None and isinstance(r2_output, dict):
        content_snapshot = r2_output.get("content_snapshot")
    visible_text = getattr(content_snapshot, "storyboard_visible_text", None)
    if visible_text is None and isinstance(content_snapshot, dict):
        visible_text = content_snapshot.get("storyboard_visible_text")
    if visible_text is not None:
        visible_patch = merge_storyboard_visible_text(
            extract_storyboard_visible_text(publish_package.get("storyboards")),
            visible_text,
        )
        if visible_patch:
            merged_publish_package["storyboards"] = (
                apply_storyboard_visible_text_patch(
                    merged_publish_package.get("storyboards"),
                    visible_patch,
                )
            )

    final_payload = _semantic_payload(
        {"storyboards": merged_publish_package.get("storyboards")},
        visual_plan,
        validated_contract,
    )
    merged_publish_package["storyboards"] = final_payload.model_dump(
        mode="json"
    )["storyboards"]

    return {
        "publish_package": merged_publish_package,
        "pending_human_publish_patch": None,
        "pending_human_replace_storyboards": None,
    }
