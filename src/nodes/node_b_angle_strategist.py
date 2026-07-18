import json

from langchain_core.prompts import PromptTemplate
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, AngleStrategy, ContentAngle
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value


_ANGLE_STRATEGIST_MAX_RETRIES = 3


def angle_strategist_node(state: AgentState) -> AgentState:
    """
    A node that generates content angle strategies using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing scouted trends.
    Returns:
        AgentState: Updated agent state with generated angle strategies.
    """
    trend_options = state.get("trends", [])
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})
    system_prompt = compose_prompt_for_state("angle_strategist", state)
    template = PromptTemplate(
        input_variables=["trends", "domain_context", "content_policy"],
        template=(
            "输入参数如下：\n"
            "- trend_options:\n{trends}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "请根据 system 规则生成传播角度。"
        ),
    )
    human_prompt = template.format(
        trends=serialize_prompt_value(trend_options),
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    angle_strategies: list[AngleStrategy] | None = None
    last_error: Exception | None = None
    for attempt in range(_ANGLE_STRATEGIST_MAX_RETRIES):
        angle_json = get_model().execute(messages)
        try:
            angle_strategies = [AngleStrategy(**angle) for angle in angle_json]
            break
        except Exception as error:
            last_error = error
            print(
                f"[Attempt {attempt + 1}/{_ANGLE_STRATEGIST_MAX_RETRIES}] "
                f"格式校验失败，触发大模型自修复机制: {error}"
            )
            if attempt == _ANGLE_STRATEGIST_MAX_RETRIES - 1:
                raise RuntimeError(
                    f"Process terminated due to angle strategist error "
                    f"after {_ANGLE_STRATEGIST_MAX_RETRIES} attempts: {error}"
                ) from error
            messages.append(
                AIMessage(content=json.dumps(angle_json, ensure_ascii=False, default=str))
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

    if angle_strategies is None:
        raise RuntimeError(
            f"angle strategist produced no strategies: {last_error}"
        )

    for strategy in angle_strategies:
        narrative_forms = {
            angle.narrative_plan.narrative_form for angle in strategy.angles
        }
        if len(narrative_forms) < 2:
            raise ValueError(
                "angle_strategist requires at least two distinct narrative forms "
                "across each three-angle strategy"
            )

    return {"angles": angle_strategies}
