from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, TitleWinner
from src.prompts import compose_prompt_for_state, serialize_prompt_value

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
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})

    system_prompt = compose_prompt_for_state("title_ranker", state)
    template = PromptTemplate(
        input_variables=["draft_results", "title_options", "domain_context", "content_policy"],
        template=(
            "输入参数如下：\n"
            "- draft_results:\n{draft_results}\n"
            "- title_options:\n{title_options}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "请按 system 规则处理。"
        ),
    )
    human_prompt = template.format(
        draft_results=serialize_prompt_value(draft_results),
        title_options=serialize_prompt_value(title_options),
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    llm = get_model()
    title_rank_json = llm.execute(messages)

    try:
        for draft in title_rank_json["ranking"]:
            print(f"{draft['draft_id']}'s score is {draft['total_score']} with title: {draft['best_title_for_this_draft']}, failed reason is {draft['reason']}")

        print(f"The best title among all drafts is: {title_rank_json['winner']['best_title']}, the core_pain is {title_rank_json['winner']['core_pain']}, the target_group is {title_rank_json['winner']['target_group']}, the angle is {title_rank_json['winner']['angle']}")
        print(f" Why win: {title_rank_json['winner']['why_win']}")
        winner = TitleWinner(**title_rank_json["winner"])
    except Exception as e:
        print(f"Failed to transform to TitleWinner schema, please check the detail: {e}")
        winner = {}
        raise RuntimeError(f"Process terminated due to error: {e}")


    return {"title_winner": winner,
           "current_node": "TITLE_RANKER"}
