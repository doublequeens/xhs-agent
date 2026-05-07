import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import PromptTemplate
from src.models import get_model
from src.schemas import AgentState
from src.prompts import all_prompts

def storyboards_generator_node(state: AgentState) -> AgentState:
    """
    A node that generates storyboards.

    Args:
        state (AgentState): The current state of the agent containing necessary context for storyboard generation.
    Returns:
        dict: A dictionary containing the generated storyboards.
    """

    
    publish_package = state.get("publish_package", "")

    system_prompt = all_prompts["NODE_O_STORYBOARDS_GENERATOR"]
    template = PromptTemplate(input_variables=["publish_package"], 
                              template="这是 publish_package {publish_package}。按照 system 规则进行处理。")
    human_prompt = template.format(publish_package=publish_package)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    storyboard_json = get_model().execute(messages)
    return {"publish_package": storyboard_json}