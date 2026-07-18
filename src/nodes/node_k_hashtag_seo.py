import json

from langchain_core.prompts import PromptTemplate
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, HashTagOutput
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value


_HASHTAG_SEO_MAX_RETRIES = 3


def hashtag_node(state: AgentState) -> AgentState:
    """
    This node generates hashtags based on the input data and the system prompt.

    Args:
        state (AgentState): The current state of the agent, which includes necessary information for generating hashtags.

    Returns:
        AgentState: Updated agent state with the generated hashtags.
    """

    decision_output = state["decision_output"]
    hashtag_input = decision_output.normalized_input.hashtag_input
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})
    
    system_prompt = compose_prompt_for_state("hashtag_seo", state)
    template = PromptTemplate(
        input_variables=["hashtag_input", "domain_context", "content_policy"],
        template=(
            "输入参数如下：\n"
            "- hashtag_input:\n{hashtag_input}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "请按 system 规则进行处理。"
        ),
    )
    human_prompt = template.format(
        hashtag_input=serialize_prompt_value(hashtag_input),
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)]

    llm = get_model()
    hashtag_output: HashTagOutput | None = None
    last_error: Exception | None = None
    for attempt in range(_HASHTAG_SEO_MAX_RETRIES):
        hashtag_json = llm.execute(messages)
        try:
            hashtag_output = HashTagOutput(**hashtag_json)
            return {
                "hashtags": hashtag_output,
                "final_content": hashtag_input}
        except Exception as error:
            last_error = error
            print(
                f"[Attempt {attempt + 1}/{_HASHTAG_SEO_MAX_RETRIES}] "
                f"格式校验失败，触发大模型自修复机制: {error}"
            )
            if attempt == _HASHTAG_SEO_MAX_RETRIES - 1:
                raise RuntimeError(
                    f"Process terminated due to hashtag seo error "
                    f"after {_HASHTAG_SEO_MAX_RETRIES} attempts: {error}"
                ) from error
            messages.append(
                AIMessage(content=json.dumps(hashtag_json, ensure_ascii=False, default=str))
            )
            messages.append(
                HumanMessage(
                    content=(
                        "你的上一次输出触发了以下数据校验错误:\n"
                        f"{error}\n"
                        "请务必严格按照要求的 JSON 结构重新输出，"
                        "不要漏掉必填字段，也不要改变字段层级；"
                        "hashtags 必须是字符串数组，不要写成 null 或单个字符串。"
                    )
                )
            )

    raise RuntimeError(
        f"hashtag seo produced no output: {last_error}"
    )
