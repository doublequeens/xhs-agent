from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import PromptTemplate

from src.schemas import AgentState, ScoreResult
from src.models import get_model
from src.prompts import all_prompts

def virality_scorer_node(state: AgentState) -> AgentState:
    """
    A node that scores content "topic + angles" based on their virality potential.

    Args:
        state (AgentState): The current state of the agent containing angle strategies.
    Returns:
        AgentState: Updated agent state with virality scores for each angle.
    """

    angle_options = state.get("angles", [])
    trends_options = state.get("trends", [])
    system_prompt = all_prompts["NODE_C_VIRALITY_SCORER"]
    template = PromptTemplate(input_variables=["angles", "trends"], 
                              template="读取候选选题列表: {trends}，以及对应的每个选题的传播切入角度列表{angles}，根据“选题 + 切入角度”的传播潜力，做评估")
    human_prompt = template.format(angles=angle_options, trends=trends_options)

    messages = [SystemMessage(content=system_prompt),
                HumanMessage(content=human_prompt)]
    
    llm = get_model("glm")
    scores_json = llm.execute(messages)

    try:
        score_options = [ScoreResult(**score) for score in scores_json] 
    except Exception as e:
        print(f"Failed to transform to ScoreResult schema, please check the detail: {e}")
        score_options = []
        raise RuntimeError(f"Process terminated due to error: {e}")
        
    return {"scores": score_options}