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
        state (AgentState): The current state of the agent containing scouted trends.
    Returns:
        List[TopicItem]: A list of TopicItem objects representing the scouted trends.
    """
    trends_num = state.get("trends_num", None)
    focus_keyword = state.get("focus_keyword", "")
    memory_context = state.get("memory_context", {})

    system_prompt = all_prompts["NODE_A_TREND_SCOUT"]
    template = PromptTemplate(input_variables=["trends_num", "memory_context", "focus_keyword"], 
                              template="这是 memory_context {memory_context}, 这是 trends_num {trends_num}, 这是 focus_keyword {focus_keyword}。按照 system 规则进行处理。")
    human_prompt = template.format(trends_num=trends_num, memory_context=memory_context, focus_keyword=focus_keyword)
    print(f"Prompt for Trend Scout Node: \n{human_prompt}\n")
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    trend_json = get_model().execute(messages)

    try:
        trend_options = [TopicItem(**trend) for trend in trend_json]
    except Exception as e:
        print(f"Failed to tranform to TopicItem schema, please check the detail: {e}")
        trend_options = []
        raise RuntimeError(f"Process terminated due to error: {e}")

    return {"trends": trend_options}