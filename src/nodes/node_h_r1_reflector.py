from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, R1Output
from src.prompts import all_prompts

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

    system_prompt = all_prompts["NODE_H_R1_REFLECTOR"]
    template = PromptTemplate(
        input_variables=["r1_input"],
        template="这是r1_input {r1_input}, 请按 system 规则进行处理。"
    )
    human_prompt = template.format(r1_input=r1_input)
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
        exit()

    return {"r1_output": r1_output,
            "current_node": "R1_REFLECTOR"}