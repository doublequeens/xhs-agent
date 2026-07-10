import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import PromptTemplate

from src.schemas import AgentState, ScoreResult
from src.models import get_model
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value

def virality_scorer_node(state: AgentState) -> AgentState:
    """
    A node that scores content "topic + angles" based on their virality potential.

    Args:
        state (AgentState): The current state of the agent containing angle strategies.
    Returns:
        AgentState: Updated agent state with virality scores for each angle.
    """

    # angle_options = state.get("angles", [])
    novelty_check_results = state.get("novelty_check_results", [])
    trends = state.get("trends", [])
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})
    # trends_options = state.get("trends", [])

    system_prompt = compose_prompt_for_state("virality_scorer", state)
    template = PromptTemplate(
        input_variables=["novelty_check_results", "trends", "domain_context", "content_policy"],
        template=(
            "输入参数如下：\n"
            "- novelty_check_results:\n{novelty_check_results}\n"
            "- trends（每个 topic 的 content_contract 是评分的硬约束）：\n{trends}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "请根据 system 规则评估传播潜力。"
        ),
    )
    human_prompt = template.format(
        novelty_check_results=serialize_prompt_value(novelty_check_results),
        trends=serialize_prompt_value(trends),
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
    )

    messages = [SystemMessage(content=system_prompt),
                HumanMessage(content=human_prompt)]
    
    model = get_model()
    max_retries = 3
    for attempt in range(max_retries):
        scores_json = model.execute(messages)
        try:
            score_options = [ScoreResult(**score) for score in scores_json]
        except Exception as exc:
            print(
                f"[Attempt {attempt + 1}/{max_retries}] "
                f"Virality score schema validation failed: {exc}"
            )
            if attempt == max_retries - 1:
                raise RuntimeError(
                    "Process terminated due to virality score schema errors "
                    f"after {max_retries} attempts: {exc}"
                ) from exc
            messages.append(
                AIMessage(content=json.dumps(scores_json, ensure_ascii=False))
            )
            messages.append(
                HumanMessage(
                    content=(
                        "你的上一次输出触发了以下 JSON schema 校验错误：\n"
                        f"{exc}\n"
                        "请重新输出完整 JSON 数组，保留所有候选并补齐每个必填字段；"
                        "breakdown 评分必须是 0-10 的整数。"
                    )
                )
            )
            continue

        for score in score_options:
            print(
                f"Score for topic {score.topic} and angle {score.angle}: "
                f"{score.total_score}"
            )
        return {"scores": score_options}

    raise AssertionError("unreachable")
