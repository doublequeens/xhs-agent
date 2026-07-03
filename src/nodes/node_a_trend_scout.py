import json
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, TopicItem
from src.prompts import compose_prompt_for_state, serialize_prompt_value


def _get_value(payload, key):
    if isinstance(payload, dict):
        return payload.get(key)
    return getattr(payload, key, None)


def _normalize_trend_risk_level(trend, domain_context, content_policy):
    content_intent = trend.get("content_intent")
    if content_intent == "basic_science":
        return "medium"
    return _get_value(domain_context, "risk_level") or _get_value(content_policy, "risk_level")

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
    evidence_briefs = state.get("evidence_briefs", {})

    system_prompt = compose_prompt_for_state("trend_scout", state)
    template = PromptTemplate(
        input_variables=[
            "trends_num",
            "memory_context",
            "focus_keyword",
            "domain_context",
            "content_policy",
            "evidence_briefs",
        ],
        template=(
            "输入参数如下：\n"
            "- trends_num:\n{trends_num}\n"
            "- focus_keyword:\n{focus_keyword}\n"
            "- memory_context:\n{memory_context}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "- evidence_briefs:\n{evidence_briefs}\n"
            "请严格按照 system 规则处理。"
        ),
    )
    human_prompt = template.format(
        trends_num=serialize_prompt_value(trends_num),
        memory_context=serialize_prompt_value(memory_context),
        focus_keyword=focus_keyword,
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
        evidence_briefs=serialize_prompt_value(evidence_briefs),
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
            normalized_trend["risk_level"] = _normalize_trend_risk_level(
                normalized_trend,
                domain_context,
                content_policy,
            )
            trend_options.append(TopicItem(**normalized_trend))
    except Exception as e:
        print(f"Failed to tranform to TopicItem schema, please check the detail: {e}")
        trend_options = []
        raise RuntimeError(f"Process terminated due to error: {e}")

    return {"trends": trend_options}
