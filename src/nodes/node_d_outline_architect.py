import json

from src.models import get_model
from langchain_core.prompts import PromptTemplate
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from src.schemas import AgentState, OutlineItem
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value
from src.nodes.narrative_plan import (
    find_narrative_plan,
    require_same_narrative_plan,
)


_OUTLINE_ARCHITECT_MAX_RETRIES = 3


def outline_architect_node(state: AgentState) -> AgentState:
    """
    A node that generates detailed outlines for content pieces using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing scored angles.
    Returns:
        AgentState: Updated agent state with generated outlines.
    """

    score_results = state.get("scores", [])
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})
    evidence_briefs = state.get("evidence_briefs", {})
    system_prompt = compose_prompt_for_state("outline_architect", state)
    template = PromptTemplate(
        input_variables=["score_results", "domain_context", "content_policy", "evidence_briefs"],
        template=(
            "输入参数如下：\n"
            "- score_results:\n{score_results}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "- evidence_briefs:\n{evidence_briefs}\n"
            "请根据 system 规则生成大纲。"
        ),
        )
    human_prompt = template.format(
        score_results=serialize_prompt_value(score_results),
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
        evidence_briefs=serialize_prompt_value(evidence_briefs),
    )
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]
    llm = get_model()
    outline_results: list[OutlineItem] | None = None
    last_error: Exception | None = None
    for attempt in range(_OUTLINE_ARCHITECT_MAX_RETRIES):
        outline_json = llm.execute(messages)
        try:
            outline_results = [OutlineItem(**outline) for outline in outline_json]
            break
        except Exception as error:
            last_error = error
            print(
                f"[Attempt {attempt + 1}/{_OUTLINE_ARCHITECT_MAX_RETRIES}] "
                f"格式校验失败，触发大模型自修复机制: {error}"
            )
            if attempt == _OUTLINE_ARCHITECT_MAX_RETRIES - 1:
                raise RuntimeError(
                    f"Process terminated due to outline architect error "
                    f"after {_OUTLINE_ARCHITECT_MAX_RETRIES} attempts: {error}"
                ) from error
            messages.append(
                AIMessage(content=json.dumps(outline_json, ensure_ascii=False, default=str))
            )
            messages.append(
                HumanMessage(
                    content=(
                        "你的上一次输出触发了以下数据校验错误:\n"
                        f"{error}\n"
                        "请务必严格按照要求的 JSON 数组结构重新输出，"
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

    if outline_results is None:
        raise RuntimeError(
            f"outline architect produced no outlines: {last_error}"
        )

    for outline in outline_results:
        expected_plan = find_narrative_plan(
            score_results,
            topic_id=outline.topic_id,
            angle_id=outline.angle_id,
            stage="outline_architect",
        )
        require_same_narrative_plan(
            outline.narrative_plan,
            expected_plan,
            stage="outline_architect",
        )
    return {"outlines": outline_results}
        
