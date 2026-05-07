from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, TitleWinner
from src.prompts import all_prompts

def title_ranker_node(state: AgentState) -> AgentState:
    """
    A node that ranks draft titles using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing draft titles.
    Returns:
        AgentState: Updated agent state with ranked draft titles.
    """
    title_options = state.get("titles_options", [])
    draft_results = state.get("drafts", [])

    system_prompt = all_prompts["NODE_G_TITLE_RANKER"]
    template = PromptTemplate(
        input_variables=["draft_results", "title_options"],
        template="这是初稿 draft_results：{draft_results}, 这是title_options：{title_options}, 请按 system 规则进行处理。"
    )
    human_prompt = template.format(draft_results=draft_results, title_options=title_options)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    llm = get_model()
    title_rank_json = llm.execute(messages)

    try:
        winner = TitleWinner(**title_rank_json["winner"])
    except Exception as e:
        print(f"Failed to transform to TitleWinner schema, please check the detail: {e}")
        winner = {}
        raise RuntimeError(f"Process terminated due to error: {e}")


    return {"title_winner": winner,
           "current_node": "TITLE_RANKER"}