from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from langchain.agents import create_agent
import json
from src.models import get_model
from src.schemas import AgentState, ImageCandidates
from src.prompts import all_prompts
from src.tools.pexels_search import pexels_search

def image_sourcing_node(state: AgentState) -> AgentState:
    """
    A node that sources images based on visual direction using the Pexels API.

    Args:
        state (AgentState): The current state of the agent containing visual direction output.
    Returns:
        AgentState: Updated agent state with sourced images.
    """

    image_scripts = state.get("image_scripts", None)

    system_prompt = all_prompts["NODE_M_IMAGE_SOURCING"]
    template = PromptTemplate(
        input_variables=["image_scripts"],
        template="这是image_scripts：{image_scripts}, 请按 system 规则进行处理."
    )
    human_prompt = template.format(image_scripts=image_scripts)

    llm = get_model("glm", tools=[pexels_search])  
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]
    
    image_candidates_json = llm.execute(messages)

    try:
        image_candidates = ImageCandidates(**image_candidates_json)
    except Exception as e:
        print(f"Failed to transform to ImageCandidates schema, please check the detail: {e}")
        image_candidates = None    
        raise RuntimeError(f"Process terminated due to error: {e}")

    return {
        "image_candidates": image_candidates
    }