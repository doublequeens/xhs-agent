from xml.parsers.expat import model

from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, HashTagOutput
from src.prompts import compose_prompt_for_state, serialize_prompt_value

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
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})
    
    system_prompt = compose_prompt_for_state("hashtag_seo", state)
    template = PromptTemplate(
        input_variables=["hashtag_input", "domain_context", "content_policy"],
        template=(
            "输入参数如下：\n"
            "- hashtag_input:\n{hashtag_input}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "请按 system 规则进行处理。"
        ),
    )
    human_prompt = template.format(
        hashtag_input=serialize_prompt_value(hashtag_input),
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)]

    llm = get_model()
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
