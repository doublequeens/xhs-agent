import json

from langchain_core.prompts import PromptTemplate
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, R1Output
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value
from src.nodes.narrative_plan import require_same_narrative_plan


_R1_REFLECTOR_MAX_RETRIES = 3


def r1_reflector_node(state: AgentState) -> AgentState:
    """
    A node that reflects on R1 output using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing R1 output.
    Returns:
        AgentState: Updated agent state with reflections on R1 output.
    """
    decision_output = state["decision_output"]
    r1_input = decision_output.normalized_input.r1_input
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})
    evidence_briefs = state.get("evidence_briefs", {})

    system_prompt = compose_prompt_for_state("r1_reflector", state)
    template = PromptTemplate(
        input_variables=["r1_input", "domain_context", "content_policy", "evidence_briefs"],
        template=(
            "输入参数如下：\n"
            "- r1_input:\n{r1_input}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "- evidence_briefs:\n{evidence_briefs}\n"
            "请按 system 规则处理。"
        ),
    )
    human_prompt = template.format(
        r1_input=serialize_prompt_value(r1_input),
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
        evidence_briefs=serialize_prompt_value(evidence_briefs),
    )
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    llm = get_model("deepseek")
    selected_narrative_plan = r1_input.content_candidate.narrative_plan
    r1_output: R1Output | None = None
    r1_output_json: dict | None = None
    last_error: Exception | None = None
    for attempt in range(_R1_REFLECTOR_MAX_RETRIES):
        r1_output_json = llm.execute(messages)

        try:
            r1_output = R1Output(**r1_output_json)
            break
        except Exception as error:
            last_error = error
            print(
                f"[Attempt {attempt + 1}/{_R1_REFLECTOR_MAX_RETRIES}] "
                f"格式校验失败，触发大模型自修复机制: {error}"
            )
            if attempt == _R1_REFLECTOR_MAX_RETRIES - 1:
                raise RuntimeError(
                    f"Process terminated due to r1 reflector error "
                    f"after {_R1_REFLECTOR_MAX_RETRIES} attempts: {error}"
                ) from error
            messages.append(
                AIMessage(content=json.dumps(r1_output_json, ensure_ascii=False, default=str))
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

    if r1_output is None or r1_output_json is None:
        raise RuntimeError(
            f"r1 reflector produced no output: {last_error}"
        )

    require_same_narrative_plan(
        r1_output_json.get("narrative_plan"),
        selected_narrative_plan,
        stage="r1_reflector",
    )

    return {"r1_output": r1_output,
            "selected_narrative_plan": selected_narrative_plan,
            "current_node": "R1_REFLECTOR"}
