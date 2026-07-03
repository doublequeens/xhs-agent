import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import PromptTemplate
from src.models import get_model
from src.schemas import AgentState
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
    merged_publish_package = dict(publish_package)
    merged_publish_package["storyboards"] = storyboard_json.get("storyboards", [])
    return {"publish_package": merged_publish_package}
