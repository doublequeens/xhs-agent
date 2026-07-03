from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, R2Output
from src.prompts import compose_prompt_for_state, serialize_prompt_value

def r2_compliance_node(state: AgentState) -> AgentState:
    """
    A node that reflects on R2 output using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing R2 output.
    Returns:
        AgentState: Updated agent state with reflections on R2 output.
    """

    decision_output = state["decision_output"]
    r2_input = decision_output.normalized_input.r2_input
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})
    evidence_briefs = state.get("evidence_briefs", {})

    system_prompt = compose_prompt_for_state("r2_compliance", state)
    template = PromptTemplate(
        input_variables=["r2_input", "domain_context", "content_policy", "evidence_briefs"],
        template=(
            "输入参数如下：\n"
            "- r2_input:\n{r2_input}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "- evidence_briefs:\n{evidence_briefs}\n"
            "请按 system 规则进行处理。"
        ),
    )
    human_prompt = template.format(
        r2_input=serialize_prompt_value(r2_input),
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
        evidence_briefs=serialize_prompt_value(evidence_briefs),
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]
    
    llm = get_model("deepseek")
    r2_complianced_json = llm.execute(messages)
    
    try:
        r2_output = R2Output(**r2_complianced_json)
    except Exception as e:
        print(f"Failed to transform to R2Output schema, please check the detail: {e}")
        r2_output = None    
        raise RuntimeError(f"Process terminated due to error: {e}")

    return {
        "r2_output": r2_output,
        "current_node": "R2_COMPLIANCE"}
