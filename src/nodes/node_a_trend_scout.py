import json
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, TopicItem
from src.prompts import all_prompts

def trend_scout_node(state: AgentState) -> AgentState:
    """
    A node that scouts for trends using Google Gemini models.

    Args:
        no input.
    Returns:
        List[TopicItem]: A list of TopicItem objects representing the scouted trends.
    """
    system_prompt = all_prompts["NODE_A_TREND_SCOUT"]
    template = PromptTemplate(input_variables=["trends_num"], template="根据system规则生成{trends_num}个当前最流行的趋势话题")
    trends_num = state.get("trends_num", None)

    human_prompt = template.format(trends_num=trends_num)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    trend_json = get_model("glm").execute(messages)

    try:
        trend_options = [TopicItem(**trend) for trend in trend_json]
    except Exception as e:
        print(f"Failed to tranform to TopicItem schema, please check the detail: {e}")
        trend_options = []
        exit()

    return {"trends": trend_options}