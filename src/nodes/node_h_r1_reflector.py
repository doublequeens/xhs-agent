from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, R1Output
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value

def r1_reflector_node(state: AgentState) -> AgentState:
    """
    A node that reflects on R1 output using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing R1 output.
    Returns:
        AgentState: Updated agent state with reflections on R1 output.
    """
    decision_output = state["decision_output"]
    r1_input = decision_output.normalized_input.r1_input
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})
    evidence_briefs = state.get("evidence_briefs", {})

    system_prompt = compose_prompt_for_state("r1_reflector", state)
    template = PromptTemplate(
        input_variables=["r1_input", "domain_context", "content_policy", "evidence_briefs"],
        template=(
            "输入参数如下：\n"
            "- r1_input:\n{r1_input}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "- evidence_briefs:\n{evidence_briefs}\n"
            "请按 system 规则处理。"
        ),
    )
    human_prompt = template.format(
        r1_input=serialize_prompt_value(r1_input),
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
        evidence_briefs=serialize_prompt_value(evidence_briefs),
    )
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    llm = get_model("deepseek")
    r1_output_json = llm.execute(messages)

    try:
        r1_output = R1Output(**r1_output_json)
    except Exception as e:
        print(f"Failed to extract reflection from model output, please check the detail: {e}")
        r1_output = None
        raise RuntimeError(f"Process terminated due to error: {e}")

    return {"r1_output": r1_output,
            "current_node": "R1_REFLECTOR"}
