from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import PromptTemplate

from src.creator_profile import CreatorProfile
from src.models import get_model
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value
from src.schemas.topic import TopicItem


def _brief_seed_keys(creative_briefs: list[object]) -> set[tuple[str, str]]:
    """Identity of a brief's signal. The topic_ideator prompt guarantees a topic's
    creative_seed copies signal_type + signal_name verbatim (必须来自), while why_now
    and domain_translation may be paraphrased (基于). Bind topics to briefs by
    identity, not by verbatim prose."""
    keys: set[tuple[str, str]] = set()
    for brief in creative_briefs:
        signal = brief.signal if hasattr(brief, "signal") else brief["signal"]
        get_value = signal.get if isinstance(signal, dict) else lambda key: getattr(signal, key)
        keys.add((get_value("signal_type"), get_value("signal_name")))
    return keys


def _validate_candidates_bound_to_briefs(
    candidates: list[TopicItem], creative_briefs: list[object]
) -> None:
    allowed_seed_keys = _brief_seed_keys(creative_briefs)
    for candidate in candidates:
        seed = candidate.creative_seed
        seed_key = (seed.signal_type, seed.signal_name)
        if seed_key not in allowed_seed_keys:
            raise RuntimeError("creative_seed must match an input brief signal")


def _bind_audience_to_profile(
    candidates: list[TopicItem], profile: CreatorProfile
) -> None:
    """profile.audience is the single correct value for both target_group and
    content_contract.audience. The LLM sometimes paraphrases it; coerce rather
    than reject, so a faithful-but-reworded candidate isn't dropped."""
    for candidate in candidates:
        candidate.target_group = profile.audience
        candidate.content_contract.audience = profile.audience


def _validate_candidates_bound_to_profile(
    candidates: list[TopicItem], profile: CreatorProfile
) -> None:
    for candidate in candidates:
        profile.assert_domain_scope(candidate.domain, candidate.subdomain)
        if candidate.content_contract.visual_mode not in profile.visual_modes:
            raise ValueError(
                "content contract visual mode is not allowed by creator profile"
            )


def topic_ideator_node(state: dict) -> dict:
    creative_briefs = state.get("creative_briefs", [])
    creator_profile = state.get("creator_profile")
    if creator_profile is None:
        raise ValueError("creator profile is required")
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})

    system_prompt = compose_prompt_for_state("topic_ideator", state)
    template = PromptTemplate(
        input_variables=["creative_briefs", "domain_context", "content_policy"],
        template=(
            "输入参数如下：\n"
            "- creative_briefs:\n{creative_briefs}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "请根据 system 规则生成候选主题。"
        ),
    )
    human_prompt = template.format(
        creative_briefs=serialize_prompt_value(creative_briefs),
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
    )

    topic_json = get_model().execute(
        [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]
    )

    try:
        candidates = [TopicItem(**item) for item in topic_json]
    except Exception as error:
        raise RuntimeError(
            f"Process terminated due to topic ideator schema error: {error}"
        ) from error

    _validate_candidates_bound_to_briefs(candidates, creative_briefs)
    _bind_audience_to_profile(candidates, creator_profile)
    _validate_candidates_bound_to_profile(candidates, creator_profile)

    return {"topic_candidates": candidates}
