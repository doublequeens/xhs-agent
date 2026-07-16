from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, AngleStrategy, ContentAngle
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value

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

    angle_json = get_model().execute(messages)
    try:
        angle_strategies = [AngleStrategy(**angle) for angle in angle_json]
    except Exception as e:
        print(f"Failed to transform to AngleStrategy schema, please check the detail: {e}")
        angle_strategies = []
        raise RuntimeError(f"Process terminated due to error: {e}")

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
