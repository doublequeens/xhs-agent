import json

from langchain_core.prompts import PromptTemplate
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, DraftTitles
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value


_TITLE_LAB_MAX_RETRIES = 3


def title_lab_node(state: AgentState) -> AgentState:
    """
    A node that generates title options using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing drafts.
    Returns:
        AgentState: Updated agent state with generated title options.
    """
    draft_results = state.get("drafts", [])
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})

    system_prompt = compose_prompt_for_state("title_lab", state)
    template = PromptTemplate(
        input_variables=["draft_results", "domain_context", "content_policy"],
        template=(
            "输入参数如下：\n"
            "- draft_results:\n{draft_results}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "请按 system 规则处理。"
        ),
    )
    human_prompt = template.format(
        draft_results=serialize_prompt_value(draft_results),
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    titles_options: list[DraftTitles] | None = None
    last_error: Exception | None = None
    for attempt in range(_TITLE_LAB_MAX_RETRIES):
        titles_json = get_model().execute(messages)
        try:
            titles_options = [DraftTitles(**titles) for titles in titles_json]
            return {"titles_options": titles_options}
        except Exception as error:
            last_error = error
            print(
                f"[Attempt {attempt + 1}/{_TITLE_LAB_MAX_RETRIES}] "
                f"格式校验失败，触发大模型自修复机制: {error}"
            )
            if attempt == _TITLE_LAB_MAX_RETRIES - 1:
                raise RuntimeError(
                    f"Process terminated due to title lab error "
                    f"after {_TITLE_LAB_MAX_RETRIES} attempts: {error}"
                ) from error
            messages.append(
                AIMessage(content=json.dumps(titles_json, ensure_ascii=False, default=str))
            )
            messages.append(
                HumanMessage(
                    content=(
                        "你的上一次输出触发了以下数据校验错误:\n"
                        f"{error}\n"
                        "请务必严格按照要求的 JSON 数组结构重新输出，"
                        "不要漏掉必填字段，也不要改变字段层级；"
                        "每个 draft 的 titles 与 cover_copies 必须是数组，"
                        "且数组元素结构必须符合 Title schema。"
                    )
                )
            )

    raise RuntimeError(
        f"title lab produced no titles: {last_error}"
    )
