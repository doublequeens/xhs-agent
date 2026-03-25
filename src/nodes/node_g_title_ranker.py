from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, TitleRankResult, R1Input
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
        template="这是初稿 draft_results：{draft_results}, 这是title_options：{title_options}, 请按 system 规则进行评审并选择最佳。"
    )
    human_prompt = template.format(draft_results=draft_results, title_options=title_options)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    title_rank_json = get_model("gemini").execute(messages)

    try:
        title_rank_results = TitleRankResult(**title_rank_json)
        title_winner = title_rank_results.winner
        winner_score = [r.scores for r in title_rank_results.ranking if r.draft_id == title_winner.draft_id ][0]

    except Exception as e:
        print(f"Failed to transform to TitleRankResult schema, please check the detail: {e}")
        title_rank_results = []
        exit()

    try:
        r1_input_data = {
            "winner": title_winner,
            "winner_scores": winner_score
        }
        r1_input = R1Input(**r1_input_data)
    except Exception as e:
        print(f"Failed to transform to R1Input schema, please check the detail: {e}")
        r1_input = []
        exit()


    return {"title_winner": r1_input}