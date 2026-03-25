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
    system_prompt = all_prompts["NODE_C_VIRALITY_SCORER"]
    template = PromptTemplate(input_variables=["angles"], 
                              template="根据system 规则， 对下面angle_options {angle_options} 进行评估")
    human_prompt = template.format(angles=angle_options)
    messages = [SystemMessage(content=system_prompt),
                HumanMessage(content=human_prompt)]
    
    llm = get_model("gemini")
    scores_json = llm.execute(messages)

    try:
        score_options = [ScoreResult(**score) for score in scores_json]
    except Exception as e:
        print(f"Failed to transform to ScoreResult schema, please check the detail: {e}")
        score_options = []
        exit()
        
    return {"scores": score_options}