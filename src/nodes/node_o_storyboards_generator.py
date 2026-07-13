from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import PromptTemplate
from src.editorial_carousel.strategy import build_visual_plan
from src.models import get_model
from src.schemas import AgentState, CarouselPayload, VisualPlan
from src.nodes.publish_patch import (
    apply_storyboard_visible_text_patch,
    extract_storyboard_visible_text,
    merge_storyboard_visible_text,
    merge_publish_package,
    storyboard_patch_without_visible_text,
)
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value


def _get_value(payload, key):
    if isinstance(payload, dict):
        return payload.get(key)
    return getattr(payload, key, None)


def _selected_content_contract(state: AgentState, publish_package: dict) -> dict:
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


def storyboards_generator_node(state: AgentState) -> AgentState:
    """
    A node that generates storyboards.

    Args:
        state (AgentState): The current state of the agent containing necessary context for storyboard generation.
    Returns:
        dict: A dictionary containing the generated storyboards.
    """

    
    publish_package = state.get("publish_package", {})
    content_contract = _selected_content_contract(state, publish_package)
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})
    evidence_briefs = state.get("evidence_briefs", {})
    visual_plan_value = state.get("visual_plan")
    semantic_storyboard_contract = visual_plan_value is not None
    visual_plan = (
        VisualPlan.model_validate(visual_plan_value)
        if semantic_storyboard_contract
        else build_visual_plan(content_contract, recent_signatures=[])
    )

    system_prompt = compose_prompt_for_state("storyboards_generator", state)
    template = PromptTemplate(
        input_variables=["publish_package", "content_contract", "visual_plan", "domain_context", "content_policy", "evidence_briefs"],
        template=(
            "输入参数如下：\n"
            "- publish_package:\n{publish_package}\n"
            "- content_contract:\n{content_contract}\n"
            "- visual_plan:\n{visual_plan}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "- evidence_briefs:\n{evidence_briefs}\n"
            "请按照 system 规则进行处理。"
        ),
    )
    human_prompt = template.format(
        publish_package=serialize_prompt_value(publish_package),
        content_contract=serialize_prompt_value(content_contract),
        visual_plan=serialize_prompt_value(visual_plan),
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
        evidence_briefs=serialize_prompt_value(evidence_briefs),
    )
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    storyboard_json = get_model().execute(messages)
    expected = [
        (item.frame_id, item.layout) for item in visual_plan.frame_plan
    ]
    if semantic_storyboard_contract:
        payload = CarouselPayload.model_validate(storyboard_json)
        actual = [(item.frame_id, item.layout) for item in payload.storyboards]
        if actual != expected:
            raise ValueError(
                "storyboard frames must exactly match visual_plan frame order and layouts"
            )
        generated_storyboards = payload.model_dump(mode="json")["storyboards"]
    else:
        # Pre-migration checkpoints can resume before the planner node has
        # written visual_plan. Keep their existing cards intact; all new graph
        # executions provide visual_plan and take the strict branch above.
        generated_storyboards = (
            storyboard_json.get("storyboards")
            if isinstance(storyboard_json, dict)
            else None
        )

    merged_publish_package = dict(publish_package)
    merged_publish_package["content_contract"] = content_contract
    merged_publish_package["storyboards"] = generated_storyboards

    pending_patch = state.get("pending_human_publish_patch")
    if pending_patch:
        merged_publish_package = merge_publish_package(
            merged_publish_package,
            storyboard_patch_without_visible_text(pending_patch),
            replace_storyboards=bool(state.get("pending_human_replace_storyboards")),
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
            merged_publish_package["storyboards"] = apply_storyboard_visible_text_patch(
                merged_publish_package.get("storyboards"), visible_patch
            )

    if semantic_storyboard_contract:
        final_payload = CarouselPayload.model_validate(
            {"storyboards": merged_publish_package.get("storyboards")}
        )
        final_actual = [
            (item.frame_id, item.layout) for item in final_payload.storyboards
        ]
        if final_actual != expected:
            raise ValueError(
                "storyboard frames must exactly match visual_plan frame order and layouts"
            )
        merged_publish_package["storyboards"] = final_payload.model_dump(
            mode="json"
        )["storyboards"]

    return {
        "publish_package": merged_publish_package,
        "pending_human_publish_patch": None,
        "pending_human_replace_storyboards": None,
    }
