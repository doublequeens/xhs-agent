from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, ImageScriptList
from src.prompts import all_prompts

def visual_director_node(state: AgentState) -> AgentState:
    """
    A node that generates visual direction for content creation using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing drafts and title options.
    Returns:
        AgentState: Updated agent state with visual direction output.
    """

    final_content = state.get("final_content", [])
    hashtag_output = state.get("hashtags", [])

    system_prompt = all_prompts["NODE_L_VISUAL_DIRECTOR"]
    template = PromptTemplate(
        input_variables=["final_content", "hashtag_output"],
        template="这是final_content：{final_content}, 这是hashtag_output：{hashtag_output}, 请按 system 规则进行处理。"
    )
    human_prompt = template.format(final_content=final_content, hashtag_output=hashtag_output)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]
    llm = get_model()
    visual_director_json = llm.execute(messages)
    
    try:
        image_scripts = ImageScriptList(**visual_director_json)
    except Exception as e:
        print(f"Failed to transform to ImageScriptList schema, please check the detail: {e}")
        image_scripts = None    
        raise RuntimeError(f"Process terminated due to error: {e}")

    return {"image_scripts": image_scripts}