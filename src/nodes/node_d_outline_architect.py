from src.models import get_model
from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.schemas import AgentState, OutlineItem
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value

def outline_architect_node(state: AgentState) -> AgentState:
    """
    A node that generates detailed outlines for content pieces using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing scored angles.
    Returns:
        AgentState: Updated agent state with generated outlines.
    """

    score_results = state.get("scores", [])
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})
    evidence_briefs = state.get("evidence_briefs", {})
    system_prompt = compose_prompt_for_state("outline_architect", state)
    template = PromptTemplate(
        input_variables=["score_results", "domain_context", "content_policy", "evidence_briefs"],
        template=(
            "输入参数如下：\n"
            "- score_results:\n{score_results}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "- evidence_briefs:\n{evidence_briefs}\n"
            "请根据 system 规则生成大纲。"
        ),
        )
    human_prompt = template.format(
        score_results=serialize_prompt_value(score_results),
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
        evidence_briefs=serialize_prompt_value(evidence_briefs),
    )
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]
    llm = get_model()
    outline_json = llm.execute(messages)
    try:
        outline_results = [OutlineItem(**outline) for outline in outline_json]
    except Exception as e:
        print(f"Failed to transform to OutlineItem schema, please check the detail: {e}")
        outline_results = []
        raise RuntimeError(f"Process terminated due to error: {e}")
    return {"outlines": outline_results}
        
