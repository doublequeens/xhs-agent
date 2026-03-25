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
        template="按照system规则， 针对以下趋势话题，生成每个话题的内容切入角度策略：{trends}"
    )
    human_prompt = template.format(trends=trend_options)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    angle_json = get_model("gemini").execute(messages)
    try:
        angle_strategies = [AngleStrategy(**angle) for angle in angle_json]
    except Exception as e:
        print(f"Failed to transform to AngleStrategy schema, please check the detail: {e}")
        angle_strategies = []
        exit()

    return {"angles": angle_strategies}