from src.models import get_model
from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.schemas import AgentState, OutlineItem
from src.prompts import all_prompts

def outline_architect_node(state: AgentState) -> AgentState:
    """
    A node that generates detailed outlines for content pieces using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing scored angles.
    Returns:
        AgentState: Updated agent state with generated outlines.
    """

    score_results = state.get("scores", [])
    system_prompt = all_prompts["NODE_D_OUTLINE_ARCHITECT"]
    template = PromptTemplate(
        input_variables=["score_results"],
        template="这是score_results：{score_results}。根据system 规则进行处理。"
        )
    human_prompt = template.format(score_results=score_results)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]
    llm = get_model("glm")
    outline_json = llm.execute(messages)
    try:
        outline_results = [OutlineItem(**outline) for outline in outline_json]
    except Exception as e:
        print(f"Failed to transform to OutlineItem schema, please check the detail: {e}")
        outline_results = []
        raise RuntimeError(f"Process terminated due to error: {e}")
    return {"outlines": outline_results}
        
