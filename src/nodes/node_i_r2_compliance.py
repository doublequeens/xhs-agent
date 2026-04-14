from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, R2Output
from src.prompts import all_prompts

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

    system_prompt = all_prompts["NODE_I_R2_COMPLIANCE"]
    template = PromptTemplate(
        input_variables=["r2_input"],
        template="这是输入数据 r2_input：{r2_input}, 请按 system 规则进行处理。")
    human_prompt = template.format(r2_input=r2_input)

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
        exit()

    return {
        "r2_output": r2_output,
        "current_node": "R2_COMPLIANCE"}