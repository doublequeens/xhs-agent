from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, DraftItem
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value

def draft_writer_node(state: AgentState) -> AgentState:
    """
    A node that generates content drafts using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing outlines.
    Returns:
        AgentState: Updated agent state with generated drafts.
    """

    outline_results = state.get("outlines", [])
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})
    evidence_briefs = state.get("evidence_briefs", {})
    system_prompt = compose_prompt_for_state("draft_writer", state)
    template = PromptTemplate(
        input_variables=["outline_results", "domain_context", "content_policy", "evidence_briefs"],
        template=(
            "输入参数如下：\n"
            "- outline_results:\n{outline_results}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "- evidence_briefs:\n{evidence_briefs}\n"
            "请根据 system 规则生成正文。"
        ),
        )
    human_prompt = template.format(
        outline_results=serialize_prompt_value(outline_results),
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
        evidence_briefs=serialize_prompt_value(evidence_briefs),
    )
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]
    llm = get_model()
    draft_json = llm.execute(messages)
    try:
        draft_results = [DraftItem(**draft) for draft in draft_json]
    except Exception as e:
        print(f"Failed to transform to Draft schema, please check the detail: {e}")
        draft_results = []
        raise RuntimeError(f"Process terminated due to error: {e}")
    return {"drafts": draft_results}
