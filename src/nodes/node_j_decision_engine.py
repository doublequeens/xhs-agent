import json
from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from src.domain import get_topic_metadata
from src.models import get_model
from src.schemas import AgentState
from src.prompts import all_prompts
from src.schemas import DecisionOutput


def _get_value(payload, key):
    if isinstance(payload, dict):
        return payload.get(key)
    return getattr(payload, key, None)


def _select_topic_angle_ids(source, decision_input):
    if source in {"TITLE_RANKER", "R1_REFLECTOR"}:
        topic_id = _get_value(decision_input, "topic_id")
        angle_id = _get_value(decision_input, "angle_id")
    elif source == "R2_COMPLIANCE":
        content_snapshot = _get_value(decision_input, "content_snapshot")
        topic_id = _get_value(content_snapshot, "topic_id")
        angle_id = _get_value(content_snapshot, "angle_id")
    else:
        raise ValueError(f"Unsupported decision source: {source}")

    if not topic_id or not angle_id:
        raise ValueError(f"Missing topic_id or angle_id for source {source}")

    return topic_id, angle_id

def decision_engine_node(state: AgentState) -> AgentState:
    """
    A node that makes decisions based on the outputs of previous nodes. It evaluates the outputs from the title ranker, R1 reflector, and R2 compliance nodes to determine the best course of action for content creation.
    R2 compliance node and decides where to route the workflow next, such as whether to proceed to R2 compliance check, or to go back to R1 reflection for further refinement. And the output format of the decision engine will
    be differ based on the target node, the output format of R1, R2 and hashtag will be different.
    Args:
        state (AgentState): The current state of the agent.
    Returns:
        AgentState: Updated agent state with the decision output.
    """

    current_node = state.get("current_node", None)
    if "TITLE_RANKER" == current_node:
        source = "TITLE_RANKER"
        decision_input = state["title_winner"]
    elif "R1_REFLECTOR" == current_node:
        source = "R1_REFLECTOR"
        decision_input = state["r1_output"]
    else:
        source = "R2_COMPLIANCE"
        decision_input = state["r2_output"]
    
    system_prompt = all_prompts["NODE_J_DECISION_ENGINE"]
    template = PromptTemplate(
        input_variables=["source", "decision_input"],
        template="这是source：{source}, 这是decision_input：{decision_input}, 请按 system 规则进行处理。 "
    )
    human_prompt = template.format(source=source, decision_input=decision_input)

    messages8 = [
        SystemMessage(content=system_prompt), 
        HumanMessage(content=human_prompt)
    ]

    model = get_model()

    # 引入自修复重试机制 (Self-Correction Loop)
    max_retries = 3
    for attempt in range(max_retries):
        decision_output_json = model.execute(messages8)

        try:
            normalized_input = decision_output_json.get("normalized_input", {})
            hashtag_input = normalized_input.get("hashtag_input") if isinstance(normalized_input, dict) else None
            if hashtag_input is not None:
                topic_id, angle_id = _select_topic_angle_ids(source, decision_input)
                hashtag_input.update({
                    "topic_id": topic_id,
                    "angle_id": angle_id,
                    **get_topic_metadata(state.get("trends", []), topic_id),
                })
            decision_output = DecisionOutput(**decision_output_json)
            # 解析成功，跳出循环并返回
            return {"decision_output": decision_output}
        except Exception as e:
            print(f"[Attempt {attempt + 1}/{max_retries}] 格式校验失败，触发大模型自修复机制: {e}")
            if attempt == max_retries - 1:
                # 如果最后一次重试仍然失败，才抛出异常
                raise RuntimeError(f"Process terminated due to error after {max_retries} attempts: {e}")
            
            # 将错误的输出和报错信息喂给大模型，让它自己修正
            messages8.append(AIMessage(content=json.dumps(decision_output_json, ensure_ascii=False)))
            messages8.append(HumanMessage(content=f"你的上一次输出触发了以下数据校验错误:\n{e}\n请务必严格按照要求的 JSON 结构重新输出，不要漏掉必填字段，也不要改变字段层级。"))
