from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value


def _get_value(payload, key):
    if isinstance(payload, dict):
        return payload.get(key)
    return getattr(payload, key, None)

def assembler_node(state: AgentState) -> AgentState:
    """
    A node that assembles the final content by combining the draft, title, and images based on the visual direction using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing draft content, title options, and final image choices.
    Returns:
        AgentState: Updated agent state with the final assembled content.
    """
    final_content = state.get("final_content", [])
    hashtag_output = state.get("hashtags", [])
    image_final_choices = state.get("final_images", [])
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})
    evidence_briefs = state.get("evidence_briefs", [])

    system_prompt = compose_prompt_for_state("assembler", state)
    template = PromptTemplate(
        input_variables=[
            "final_content",
            "hashtag_output",
            "image_final_choices",
            "domain_context",
            "content_policy",
            "evidence_briefs",
        ],
        template=(
            "输入参数如下：\n"
            "- final_content:\n{final_content}\n"
            "- hashtag_output:\n{hashtag_output}\n"
            "- image_final_choices:\n{image_final_choices}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "- evidence_briefs:\n{evidence_briefs}\n"
            "请按 system 规则进行处理。"
        ),
    )
    human_prompt = template.format(
        final_content=serialize_prompt_value(final_content),
        hashtag_output=serialize_prompt_value(hashtag_output),
        image_final_choices=serialize_prompt_value(image_final_choices),
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
        evidence_briefs=serialize_prompt_value(evidence_briefs),
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    llm = get_model()
    publish_package_json = llm.execute(messages)
    publish_package_json.update(
        {
            "title": _get_value(final_content, "final_title"),
            "content": _get_value(final_content, "final_md"),
            "topic_id": _get_value(final_content, "topic_id"),
            "topic": _get_value(final_content, "topic"),
            "angle_id": _get_value(final_content, "angle_id"),
            "angle": _get_value(final_content, "angle"),
            "target_group": _get_value(final_content, "target_group"),
            "core_pain": _get_value(final_content, "core_pain"),
            "cover_copy": _get_value(final_content, "best_cover_copy"),
            "domain": _get_value(final_content, "domain"),
            "profile_version": _get_value(domain_context, "profile_version"),
            "subdomain": _get_value(final_content, "subdomain"),
            "content_intent": _get_value(final_content, "content_intent"),
            "risk_level": _get_value(final_content, "risk_level"),
            "risk_flags": list(_get_value(final_content, "risk_flags") or []),
        }
    )
    return {
        "publish_package": publish_package_json
    }
