import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import PromptTemplate

from src.creator_profile import CreatorProfile
from src.models import get_model
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value
from src.schemas.topic import TopicItem


_TOPIC_IDEATOR_MAX_RETRIES = 3


def _bind_profile_controlled_fields(
    item: dict[str, object], profile: CreatorProfile
) -> dict[str, object]:
    """Make account-owned audience fields deterministic, not model-authored."""
    payload = dict(item)
    content_contract = dict(payload.get("content_contract") or {})

    payload["target_group"] = profile.audience
    content_contract["audience"] = profile.audience
    payload["content_contract"] = content_contract

    return payload


def _brief_seed_keys(creative_briefs: list[object]) -> set[tuple[str, str, str, str]]:
    keys: set[tuple[str, str, str, str]] = set()
    for brief in creative_briefs:
        signal = brief.signal if hasattr(brief, "signal") else brief["signal"]
        get_value = signal.get if isinstance(signal, dict) else lambda key: getattr(signal, key)
        keys.add(
            (
                get_value("signal_type"),
                get_value("signal_name"),
                get_value("why_now"),
                get_value("domain_translation"),
            )
        )
    return keys


def _validate_candidates_bound_to_briefs(
    candidates: list[TopicItem], creative_briefs: list[object]
) -> None:
    allowed_seed_keys = _brief_seed_keys(creative_briefs)
    for candidate in candidates:
        seed = candidate.creative_seed
        seed_key = (
            seed.signal_type,
            seed.signal_name,
            seed.why_now,
            seed.domain_translation,
        )
        if seed_key not in allowed_seed_keys:
            raise RuntimeError("creative_seed must match an input brief signal")


def _validate_candidates_bound_to_profile(
    candidates: list[TopicItem], profile: CreatorProfile
) -> None:
    for candidate in candidates:
        profile.assert_domain_scope(candidate.domain, candidate.subdomain)
        if candidate.target_group != profile.audience:
            raise ValueError("candidate target_group must equal creator profile audience")
        if candidate.content_contract.audience != profile.audience:
            raise ValueError("content contract audience must equal creator profile audience")
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

    messages = [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]
    candidates: list[TopicItem] | None = None
    last_error: Exception | None = None
    for attempt in range(_TOPIC_IDEATOR_MAX_RETRIES):
        topic_json = get_model().execute(messages)
        try:
            candidates = [
                TopicItem(**_bind_profile_controlled_fields(item, creator_profile))
                for item in topic_json
            ]
            _validate_candidates_bound_to_briefs(candidates, creative_briefs)
            break
        except Exception as error:
            last_error = error
            print(
                f"[Attempt {attempt + 1}/{_TOPIC_IDEATOR_MAX_RETRIES}] "
                f"格式校验失败，触发大模型自修复机制: {error}"
            )
            if attempt == _TOPIC_IDEATOR_MAX_RETRIES - 1:
                raise RuntimeError(
                    f"Process terminated due to topic ideator error "
                    f"after {_TOPIC_IDEATOR_MAX_RETRIES} attempts: {error}"
                ) from error
            # 将错误的输出和报错信息喂给大模型，让它自己修正
            messages.append(
                AIMessage(
                    content=json.dumps(topic_json, ensure_ascii=False, default=str)
                )
            )
            messages.append(
                HumanMessage(
                    content=(
                        "你的上一次输出触发了以下数据校验错误:\n"
                        f"{error}\n"
                        "请务必严格按照要求的 JSON 数组结构重新输出。注意："
                        "每个主题的 creative_seed.signal_type / signal_name / "
                        "why_now / domain_translation 必须逐字复制某个输入 brief 的 "
                        "signal 字段，不得改写或合并；"
                        "primary_visual_subject 只能是 face_map / serum_texture / "
                        "product_cutout / skin_macro / checklist / process 之一；"
                        "proof_mode 只能是 diagram / real_photo / product_texture / "
                        "comparison / none；不要把 visual_mode 的值写到其它字段，"
                        "不要漏掉必填字段，也不要改变字段层级。"
                    )
                )
            )

    if candidates is None:
        raise RuntimeError(f"topic ideator produced no candidates: {last_error}")

    # Profile-controlled fields are a hard contract, not a model-formatting
    # problem: the creator profile is fixed input, so a domain/visual_mode the
    # profile forbids can never be fixed by re-prompting. Keep these guards
    # outside the self-repair loop so they surface the original ValueError
    # instead of being retried into a generic RuntimeError.
    _validate_candidates_bound_to_profile(candidates, creator_profile)

    return {"topic_candidates": candidates}
