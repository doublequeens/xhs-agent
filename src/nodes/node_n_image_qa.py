from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, FinalImages
from src.prompts import all_prompts

def image_qa_node(state: AgentState) -> AgentState:
    """
    A node that performs quality assurance on sourced images based on visual direction using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing image candidates and visual direction.
    Returns:
        AgentState: Updated agent
    """
    final_content = state.get("final_content", [])
    image_candidates = state.get("image_candidates", [])

    system_prompt = all_prompts["NODE_N_IMAGE_QA"]
    template = PromptTemplate(
        input_variables=["final_content", "image_candidates"],
        template="这是final_content {final_content}， 这是image_candidates 列表：{image_candidates}，请按 system 规则处理"
    )
    human_prompt = template.format(final_content=final_content, image_candidates=image_candidates)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    llm = get_model("glm")
    image_qa_json = llm.execute(messages)

    try:
        image_final_choices = FinalImages(**image_qa_json)
    except Exception as e:
        print(f"Failed to transform to FinalImages schema, please check the detail: {e}")
        image_final_choices = None    
        exit()
    
    return {"final_images": image_final_choices}