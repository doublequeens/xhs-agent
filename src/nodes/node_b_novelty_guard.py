from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.prompts import PromptTemplate
from typing import List, Mapping

from memory import vector_memory
from src.models import get_model
from src.schemas import AgentState, AngleStrategy, NoveltyCheckResults, NoveltyMatches
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value
from memory.vector_memory import XHSVectorMemory
from memory.embedding import build_embedding_text


def _require_domain_scope(domain_context) -> tuple[str, str]:
    if isinstance(domain_context, Mapping):
        domain = domain_context.get("domain")
        subdomain = domain_context.get("subdomain")
    else:
        domain = getattr(domain_context, "domain", None)
        subdomain = getattr(domain_context, "subdomain", None)

    if not domain or not subdomain:
        raise ValueError("novelty_guard_node requires state.domain_context with domain and subdomain")

    return domain, subdomain


def get_memory_matches(angle_options: List[AngleStrategy], domain_context) -> List[NoveltyMatches]:
    """
    A helper function to retrieve relevant past content from memory based on topic-angle pairs.
    Args:
        angle_options (List[AngleStrategy]): the result of node angle strategist
    Returns:
        topic_angles_memory_matches: List of memory records that are relevant to the given topic-angle pairs, including their embedding similarity scores.
    """
    domain, subdomain = _require_domain_scope(domain_context)
    memory_matches = []
    vector_memory = XHSVectorMemory("data/chroma")

    for topic in angle_options:
        for angle in topic.angles:
            query_text = build_embedding_text(
                topic=topic.topic,
                angle=angle.angle,
                title="",
                target_group=topic.target_group,
                core_pain=topic.core_pain,
            )

            similar_items = vector_memory.query_similar(
                query_text=query_text,
                n_results=3,
                domain=domain,
                subdomain=subdomain,
            )

            memory_matches.append({
                "topic_id": topic.topic_id,
                "angle_id": angle.angle_id,

                "matches": [
                    {
                        "content_id": item["content_id"],
                        "topic": item["metadata"].get("topic", ""),
                        "angle": item["metadata"].get("angle", ""),
                        "title": item["metadata"].get("title", ""),
                        "created_at": item["metadata"].get("created_at", ""),
                        "published_at": item["metadata"].get("published_at", ""),
                        "similarity": item["similarity"],
                        "performance_level": item["metadata"].get("performance_level", "unknown")
                    }
                    for item in similar_items
                ]
            })
    memory_matches = [NoveltyMatches(**match) for match in memory_matches]

    return memory_matches


def novelty_guard_node(state: AgentState) -> AgentState:
    """
    A node that checks the novelty of content topic-angles using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing generated angle strategies and memory manager instance.
    Returns:
        AgentState: Updated agent state with novelty check results.
    """
    angle_options = state.get("angles", [])
    domain_context = state.get("domain_context")
    _require_domain_scope(domain_context)
    memory_matches = get_memory_matches(angle_options, domain_context)
    content_policy = state.get("content_policy", {})
    system_prompt = compose_prompt_for_state("novelty_guard", state)
    MEMORY_POLICY = {
        "reject_similarity_threshold": 0.86,
        "warn_similarity_threshold": 0.78,
        "recent_days_strict": 14,
        "recent_days_soft": 30
        }

    template = PromptTemplate(
        input_variables=[
            "angle_options",
            "memory_matches",
            "memory_policy",
            "domain_context",
            "content_policy",
        ],
        template=(
            "输入参数如下：\n"
            "- angle_options:\n{angle_options}\n"
            "- memory_matches:\n{memory_matches}\n"
            "- memory_policy:\n{memory_policy}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "请根据 system 规则处理。"
        ),
    )
    human_prompt = template.format(
        angle_options=serialize_prompt_value(angle_options),
        memory_matches=serialize_prompt_value(memory_matches),
        memory_policy=serialize_prompt_value(MEMORY_POLICY),
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    novelty_result_json = get_model().execute(messages)

    try:
        novelty_check_results = NoveltyCheckResults(**novelty_result_json)
    except Exception as e:
        print(f"Failed to transform to NoveltyCheckResult schema, please check the detail: {e}")
        novelty_check_results = []
        raise RuntimeError(f"Process terminated due to error: {e}")

    return {"novelty_check_results": novelty_check_results}
