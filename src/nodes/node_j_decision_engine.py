from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState
from src.prompts import all_prompts

def decision_engine_node(state: AgentState) -> AgentState:
    """
    A node that makes decisions based on R2 compliance audit results using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing R2 compliance audit results.
    Returns:
        AgentState: Updated agent state with decisions based on R2 compliance audit results.
    """
    r2_compliance_audit = state.get("r2_compliance_audit", None)

    system_prompt = all_prompts["NODE_J_DECISION_ENGINE"]
    template = PromptTemplate(
        input_variables=["r2_compliance_audit"],
        template="这是R2的合规审查结果 r2_compliance_audit：{r2_compliance_audit}, 请按 system 规则进行决策"
    )
    human_prompt = template.format(r2_compliance_audit=r2_compliance_audit)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    decision_json = get_model("gemini").execute(messages)

    return {"r2_decision": decision_json}