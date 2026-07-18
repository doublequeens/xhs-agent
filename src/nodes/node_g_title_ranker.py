import json

from langchain_core.prompts import PromptTemplate
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, TitleWinner
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value
from src.nodes.narrative_plan import (
    find_narrative_plan,
    require_same_narrative_plan,
)


_TITLE_RANKER_MAX_RETRIES = 3


def title_ranker_node(state: AgentState) -> AgentState:
    """
    A node that ranks draft titles using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing draft titles.
    Returns:
        AgentState: Updated agent state with ranked draft titles.
    """
    title_options = state.get("titles_options", [])
    draft_results = state.get("drafts", [])
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})

    system_prompt = compose_prompt_for_state("title_ranker", state)
    template = PromptTemplate(
        input_variables=["draft_results", "title_options", "domain_context", "content_policy"],
        template=(
            "输入参数如下：\n"
            "- draft_results:\n{draft_results}\n"
            "- title_options:\n{title_options}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "请按 system 规则处理。"
        ),
    )
    human_prompt = template.format(
        draft_results=serialize_prompt_value(draft_results),
        title_options=serialize_prompt_value(title_options),
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    llm = get_model()
    winner: TitleWinner | None = None
    title_rank_json: dict | None = None
    last_error: Exception | None = None
    for attempt in range(_TITLE_RANKER_MAX_RETRIES):
        title_rank_json = llm.execute(messages)

        try:
            for draft in title_rank_json["ranking"]:
                print(f"{draft['draft_id']}'s score is {draft['total_score']} with title: {draft['best_title_for_this_draft']}, failed reason is {draft['reason']}")

            print(f"The best title among all drafts is: {title_rank_json['winner']['best_title']}, the core_pain is {title_rank_json['winner']['core_pain']}, the target_group is {title_rank_json['winner']['target_group']}, the angle is {title_rank_json['winner']['angle']}")
            print(f" Why win: {title_rank_json['winner']['why_win']}")
            winner = TitleWinner(**title_rank_json["winner"])
            break
        except Exception as error:
            last_error = error
            print(
                f"[Attempt {attempt + 1}/{_TITLE_RANKER_MAX_RETRIES}] "
                f"格式校验失败，触发大模型自修复机制: {error}"
            )
            if attempt == _TITLE_RANKER_MAX_RETRIES - 1:
                raise RuntimeError(
                    f"Process terminated due to title ranker error "
                    f"after {_TITLE_RANKER_MAX_RETRIES} attempts: {error}"
                ) from error
            messages.append(
                AIMessage(content=json.dumps(title_rank_json, ensure_ascii=False, default=str))
            )
            messages.append(
                HumanMessage(
                    content=(
                        "你的上一次输出触发了以下数据校验错误:\n"
                        f"{error}\n"
                        "请务必严格按照要求的 JSON 结构重新输出，"
                        "不要漏掉必填字段，也不要改变字段层级。注意："
                        "narrative_plan.narrative_form 只能是 "
                        "cognitive_correction / step_tutorial / checklist_collection / "
                        "comparison / diagnostic_qa / scenario_story / story_reversal / "
                        "reflective_editorial 之一；"
                        "narrative_plan.closing_mode 只能是 "
                        "none / boundary / reflection / focused_question / "
                        "action_prompt 之一；"
                        "narrative beats 的 kind 只能是 "
                        "hook / scene / tension / misconception / reveal / principle / "
                        "explanation / example / steps / checklist / comparison / "
                        "diagnostic / qa / quote / boundary / summary / action 之一，"
                        "不要把 closing_mode 的值写到 beat kind，也不要把其它字段的"
                        "枚举值串到 narrative_plan。"
                    )
                )
            )

    if winner is None:
        raise RuntimeError(
            f"title ranker produced no winner: {last_error}"
        )

    expected_plan = find_narrative_plan(
        draft_results,
        topic_id=winner.topic_id,
        angle_id=winner.angle_id,
        stage="title_ranker",
    )
    require_same_narrative_plan(
        winner.narrative_plan,
        expected_plan,
        stage="title_ranker",
    )

    return {"title_winner": winner,
           "selected_narrative_plan": expected_plan,
           "current_node": "TITLE_RANKER"}
