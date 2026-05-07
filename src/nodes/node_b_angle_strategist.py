from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, AngleStrategy, ContentAngle
from src.prompts import all_prompts

def angle_strategist_node(state: AgentState) -> AgentState:
    """
    A node that generates content angle strategies using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing scouted trends.
    Returns:
        AgentState: Updated agent state with generated angle strategies.
    """
    system_prompt = all_prompts["NODE_B_ANGLE_STRATEGIST"]

    trend_options = state.get("trends", [])
    template = PromptTemplate(
        input_variables=["trends"],
        template="读取候选选题列表: {trends}， 根据system规则生成传播角度"
    )
    human_prompt = template.format(trends=trend_options)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    angle_json = get_model().execute(messages)
    try:
        angle_strategies = [AngleStrategy(**angle) for angle in angle_json]
    except Exception as e:
        print(f"Failed to transform to AngleStrategy schema, please check the detail: {e}")
        angle_strategies = []
        raise RuntimeError(f"Process terminated due to error: {e}")

    return {"angles": angle_strategies}