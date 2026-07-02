from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.domain import get_topic_metadata
from src.models import get_model
from src.schemas import AgentState
from src.prompts import all_prompts


def _get_value(payload, key):
    if isinstance(payload, dict):
        return payload.get(key)
    return getattr(payload, key, None)

def assembler_node(state: AgentState) -> AgentState:
    """
    A node that assembles the final content by combining the draft, title, and images based on the visual direction using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing draft content, title options, and final image choices.
    Returns:
        AgentState: Updated agent state with the final assembled content.
    """
    final_content = state.get("final_content", [])
    hashtag_output = state.get("hashtags", [])
    image_final_choices = state.get("final_images", [])

    system_prompt = all_prompts["NODE_O_ASSEMBLER"]
    template = PromptTemplate(
        input_variables=["final_content", "hashtag_output", "image_final_choices"],
        template="这是final_content：{final_content}, 这是hashtag_output：{hashtag_output}, 这是image_final_choices：{image_final_choices}, 请按 system 规则进行处理。"
    )
    human_prompt = template.format(final_content=final_content, hashtag_output=hashtag_output, image_final_choices=image_final_choices)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    llm = get_model()
    publish_package_json = llm.execute(messages)
    final_topic_id = _get_value(final_content, "topic_id")
    if final_topic_id:
        publish_package_json.update(
            {
                "topic_id": final_topic_id,
                "angle_id": _get_value(final_content, "angle_id"),
                **get_topic_metadata(state.get("trends", []), final_topic_id),
            }
        )
    return {
        "publish_package": publish_package_json
    }
