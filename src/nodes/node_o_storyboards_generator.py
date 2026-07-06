from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import PromptTemplate
from src.models import get_model
from src.schemas import AgentState, StoryboardPayload
from src.nodes.publish_patch import (
    merge_publish_package,
    storyboard_patch_without_visible_text,
)
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value

def storyboards_generator_node(state: AgentState) -> AgentState:
    """
    A node that generates storyboards.

    Args:
        state (AgentState): The current state of the agent containing necessary context for storyboard generation.
    Returns:
        dict: A dictionary containing the generated storyboards.
    """

    
    publish_package = state.get("publish_package", "")
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})
    evidence_briefs = state.get("evidence_briefs", {})

    system_prompt = compose_prompt_for_state("storyboards_generator", state)
    template = PromptTemplate(
        input_variables=["publish_package", "domain_context", "content_policy", "evidence_briefs"],
        template=(
            "输入参数如下：\n"
            "- publish_package:\n{publish_package}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "- evidence_briefs:\n{evidence_briefs}\n"
            "请按照 system 规则进行处理。"
        ),
    )
    human_prompt = template.format(
        publish_package=serialize_prompt_value(publish_package),
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
        evidence_briefs=serialize_prompt_value(evidence_briefs),
    )
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    storyboard_json = get_model().execute(messages)
    try:
        storyboard_payload = StoryboardPayload.model_validate(storyboard_json)
    except Exception as exc:
        raise RuntimeError(f"Storyboard output failed validation: {exc}") from exc

    merged_publish_package = dict(publish_package)
    merged_publish_package["storyboards"] = [
        frame.model_dump() for frame in storyboard_payload.storyboards
    ]

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
        visible_patch = [
            frame.model_dump() if hasattr(frame, "model_dump") else dict(frame)
            for frame in list(visible_text or [])
        ]
        if visible_patch:
            merged_publish_package = merge_publish_package(
                merged_publish_package,
                {"storyboards": visible_patch},
            )

    return {
        "publish_package": merged_publish_package,
        "pending_human_publish_patch": None,
        "pending_human_replace_storyboards": None,
    }
