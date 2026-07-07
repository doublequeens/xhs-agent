from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import PromptTemplate

from src.models import get_model
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value
from src.schemas.topic import TopicItem


def topic_ideator_node(state: dict) -> dict:
    creative_briefs = state.get("creative_briefs", [])
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})

    system_prompt = compose_prompt_for_state("topic_ideator", state)
    template = PromptTemplate(
        input_variables=["creative_briefs", "domain_context", "content_policy"],
        template=(
            "输入参数如下：\n"
            "- creative_briefs:\n{creative_briefs}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "请根据 system 规则生成候选主题。"
        ),
    )
    human_prompt = template.format(
        creative_briefs=serialize_prompt_value(creative_briefs),
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
    )

    topic_json = get_model().execute(
        [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]
    )

    try:
        candidates = [TopicItem(**item) for item in topic_json]
    except Exception as error:
        raise RuntimeError(
            f"Process terminated due to topic ideator schema error: {error}"
        ) from error

    return {"topic_candidates": candidates}
