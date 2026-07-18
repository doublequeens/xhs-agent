import json
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, TopicItem
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value


_TREND_SCOUT_MAX_RETRIES = 3


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

    trend_options: list[TopicItem] | None = None
    last_error: Exception | None = None
    for attempt in range(_TREND_SCOUT_MAX_RETRIES):
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
            return {"trends": trend_options}
        except Exception as error:
            last_error = error
            print(
                f"[Attempt {attempt + 1}/{_TREND_SCOUT_MAX_RETRIES}] "
                f"格式校验失败，触发大模型自修复机制: {error}"
            )
            if attempt == _TREND_SCOUT_MAX_RETRIES - 1:
                raise RuntimeError(
                    f"Process terminated due to trend scout error "
                    f"after {_TREND_SCOUT_MAX_RETRIES} attempts: {error}"
                ) from error
            messages.append(
                AIMessage(content=json.dumps(trend_json, ensure_ascii=False, default=str))
            )
            messages.append(
                HumanMessage(
                    content=(
                        "你的上一次输出触发了以下数据校验错误:\n"
                        f"{error}\n"
                        "请务必严格按照要求的 JSON 数组结构重新输出，"
                        "不要漏掉必填字段，也不要改变字段层级。注意："
                        "content_contract.primary_visual_subject 只能是 "
                        "face_map / serum_texture / product_cutout / skin_macro / "
                        "checklist / process 之一；"
                        "content_contract.proof_mode 只能是 "
                        "diagram / real_photo / product_texture / comparison / none 之一；"
                        "content_intent / risk_level / visual_mode 等 enum 字段必须"
                        "使用各自允许的取值，不要把一个枚举的值写到另一个字段；"
                        "risk_flags / creative_seed 等必填字段不能写成 null。"
                    )
                )
            )

    raise RuntimeError(
        f"trend scout produced no trends: {last_error}"
    )
