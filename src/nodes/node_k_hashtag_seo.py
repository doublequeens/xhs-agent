from xml.parsers.expat import model

from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, HashTagOutput
from src.prompts import all_prompts

def hashtag_node(state: AgentState) -> AgentState:
    """
    This node generates hashtags based on the input data and the system prompt.

    Args:
        state (AgentState): The current state of the agent, which includes necessary information for generating hashtags.

    Returns:
        AgentState: Updated agent state with the generated hashtags.
    """

    decision_output = state["decision_output"]
    hashtag_input = decision_output.normalized_input.hashtag_input
    
    system_prompt = all_prompts["NODE_K_HASHTAG_SEO"]    
    template = PromptTemplate(
        input_variables=["hashtag_input"],
        template="这是hashtag_input：{hashtag_input}, 请按 system 规则进行处理。")
    human_prompt = template.format(hashtag_input=hashtag_input)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)]

    llm = get_model("glm")
    hashtag_json = llm.execute(messages)
    try:
        hashtag_output = HashTagOutput(**hashtag_json)
    except Exception as e:
        print(f"Failed to transform to HashTagOutput schema, please check the detail: {e}") 
        hashtag_output = None
        raise RuntimeError(f"Process terminated due to error: {e}")

    return {
        "hashtags": hashtag_output,
        "final_content": hashtag_input}