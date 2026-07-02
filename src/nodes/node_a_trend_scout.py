import json
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, TopicItem
from src.prompts import all_prompts


def _get_value(payload, key):
    if isinstance(payload, dict):
        return payload.get(key)
    return getattr(payload, key, None)

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
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})

    system_prompt = all_prompts["NODE_A_TREND_SCOUT"]
    template = PromptTemplate(
        input_variables=["trends_num", "memory_context", "focus_keyword", "domain_context", "content_policy"],
        template=(
            "这是 memory_context {memory_context}, 这是 trends_num {trends_num}, "
            "这是 focus_keyword {focus_keyword}, 这是 domain_context {domain_context}, "
            "这是 content_policy {content_policy}。按照 system 规则进行处理。"
        ),
    )
    human_prompt = template.format(
        trends_num=trends_num,
        memory_context=memory_context,
        focus_keyword=focus_keyword,
        domain_context=domain_context,
        content_policy=content_policy,
    )
    print(f"Prompt for Trend Scout Node: \n{human_prompt}\n")
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    trend_json = get_model().execute(messages)

    try:
        trend_options = []
        for trend in trend_json:
            normalized_trend = dict(trend)
            if domain_context:
                normalized_trend["domain"] = _get_value(domain_context, "domain")
                normalized_trend["subdomain"] = _get_value(domain_context, "subdomain")
            if normalized_trend.get("content_intent") == "basic_science":
                normalized_trend["risk_level"] = "medium"
            trend_options.append(TopicItem(**normalized_trend))
    except Exception as e:
        print(f"Failed to tranform to TopicItem schema, please check the detail: {e}")
        trend_options = []
        raise RuntimeError(f"Process terminated due to error: {e}")

    return {"trends": trend_options}
