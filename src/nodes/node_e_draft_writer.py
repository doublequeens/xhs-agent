from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, DraftItem
from src.prompts import all_prompts

def draft_writer_node(state: AgentState) -> AgentState:
    """
    A node that generates content drafts using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing outlines.
    Returns:
        AgentState: Updated agent state with generated drafts.
    """

    outline_results = state.get("outlines", [])
    system_prompt = all_prompts["NODE_E_DRAFT_WRITER"]
    template = PromptTemplate(
        input_variables=["outline_results"],
        template="这是图文大纲 outline_results：{outline_results}。根据system 规则进行处理。"
        )
    human_prompt = template.format(outline_results=outline_results)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]
    llm = get_model("glm")
    draft_json = llm.execute(messages)
    try:
        draft_results = [DraftItem(**draft) for draft in draft_json]
    except Exception as e:
        print(f"Failed to transform to Draft schema, please check the detail: {e}")
        draft_results = []
        exit()
    return {"drafts": draft_results}