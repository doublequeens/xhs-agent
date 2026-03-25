from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, DraftTitles
from src.prompts import all_prompts

def title_lab_node(state: AgentState) -> AgentState:
    """
    A node that generates title options using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing drafts.
    Returns:
        AgentState: Updated agent state with generated title options.
    """
    draft_results = state.get("drafts", [])

    system_prompt = all_prompts["NODE_F_TITLE_LAB"]
    template = PromptTemplate(
        input_variables=["draft_results"],
        template="这是初稿列表 draft_results：{draft_results}, 请按 system 规则生成小红书标题与封面钩子文案。 "
    )
    human_prompt = template.format(draft_results=draft_results)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    titles_json = get_model("deepseek").execute(messages)
    try:
        titles_options = [DraftTitles(**titles) for titles in titles_json]
    except Exception as e:
        print(f"Failed to transform to DraftTitles schema, please check the detail: {e}")
        titles_options = []
        exit()

    return {"titles_options": titles_options}