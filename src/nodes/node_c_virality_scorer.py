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

    # angle_options = state.get("angles", [])
    novelty_check_results = state.get("novelty_check_results", [])
    # trends_options = state.get("trends", [])

    system_prompt = all_prompts["NODE_C_VIRALITY_SCORER"]
    template = PromptTemplate(input_variables=["novelty_check_results"], 
                              template="这是novelty_check_results: {novelty_check_results}， 根据“选题 + 切入角度”的传播潜力，做评估")
    human_prompt = template.format(novelty_check_results=novelty_check_results)

    messages = [SystemMessage(content=system_prompt),
                HumanMessage(content=human_prompt)]
    
    scores_json = get_model().execute(messages)

    try:
        score_options = [ScoreResult(**score) for score in scores_json] 
        for i in range(len(score_options)):
            # score_options[i].angle_id = novelty_check_results[i].angle_id
            # score_options[i].topic_id = novelty_check_results[i].topic_id
            print(f"Score for topic {score_options[i].topic} and angle {score_options[i].angle}: {score_options[i].total_score}")
    except Exception as e:
        print(f"Failed to transform to ScoreResult schema, please check the detail: {e}")
        score_options = []
        raise RuntimeError(f"Process terminated due to error: {e}")
        
    return {"scores": score_options}