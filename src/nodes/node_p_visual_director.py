"""LLM-directed planning for a single-family dynamic visual carousel."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, get_args

from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value
from src.schemas.content_atoms import ContentAtomSet, ContentFragment
from src.schemas.content_contract import ContentContract
from src.schemas.visual_director import AssetDirective, VisualDirectionPlan
from src.schemas.visual_style import FamilyStyleProfile, TemplateFamily
from src.visual_ai import StructuredVisualModel
from src.visual_design.model_retry import generate_validated
from src.visual_design.style_registry import load_style_registry


_SEMANTIC_BOUNDARY_CHARACTERS = frozenset(
    "。！？；：，、.!?;:,\n\t "
)
_REQUIRED_ASSET_NEGATIVE_CONSTRAINTS = (
    ("embedded text", ("embedded text", "文字", "文本")),
    (
        "AI disclosure",
        ("AI disclosure", "AI label", "AI 标签", "AI标注", "AI 标注"),
    ),
    ("disclaimer", ("disclaimer", "免责声明", "免责")),
)
_PERSISTENT_PAIN_SIGNALS = (
    "持续刺痛",
    "明显泛红",
    "第二天仍然紧绷",
)
_FORBIDDEN_DISCLOSURE_OR_CHINESE_ASSET_COPY = (
    re.compile(
        r"(?:AI|人工智能)\s*(?:技术\s*)?(?:辅助|参与)?\s*"
        r"(?:生成|绘制|创作|制作)\s*"
        r"(?:的)?(?:示意图|图片|图像|内容|素材)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:嵌入|添加|加入|写上|显示|叠加|覆盖|带有|包含)"
        r".{0,12}(?:文字|文本|字样|标签|标注)"
    ),
    re.compile(r"(?:示意图)(?:标签|标注|字样)"),
    re.compile(r"(?:免责声明|仅供参考|不构成(?:任何)?(?:医疗|医学|诊疗)建议)"),
    re.compile(
        r"(?:不能|无法|不可)(?:替代|代替)(?:专业)?"
        r"(?:医生|医师|医疗|诊断|治疗)(?:的)?(?:建议|诊疗|诊断|治疗)"
    ),
)
_ENGLISH_VISIBLE_COPY_VERBS = (
    r"add|include|show|render|overlay|embed|write|display|with|"
    r"put|insert|place|superimpose"
)
_ENGLISH_VISIBLE_COPY_TOKENS = r"texts?|captions?|labels?|words?"
_ENGLISH_NEGATIVE_VISIBLE_COPY_CONTEXTS = (
    re.compile(
        r"\b(?:no|without)\s+(?:any\s+)?"
        rf"(?:{_ENGLISH_VISIBLE_COPY_TOKENS})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:text|caption|label|word)-free\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:do\s+not|don['’]t)\s+"
        rf"(?:{_ENGLISH_VISIBLE_COPY_VERBS})\b"
        rf".{{0,24}}\b(?:{_ENGLISH_VISIBLE_COPY_TOKENS})\b",
        re.IGNORECASE,
    ),
)
_ENGLISH_POSITIVE_VISIBLE_COPY_COMMAND = re.compile(
    rf"\b(?:{_ENGLISH_VISIBLE_COPY_VERBS})\b"
    rf".{{0,24}}\b(?:{_ENGLISH_VISIBLE_COPY_TOKENS})\b",
    re.IGNORECASE,
)


def _required_atom_set(state: Mapping[str, Any]) -> ContentAtomSet:
    raw_atom_set = state.get("content_atom_set")
    if raw_atom_set is None:
        raise ValueError("visual_director requires content_atom_set")
    if isinstance(raw_atom_set, ContentAtomSet):
        return raw_atom_set
    return ContentAtomSet.model_validate(raw_atom_set)


def _required_content_contract(state: Mapping[str, Any]) -> ContentContract:
    package = state.get("publish_package")
    if not isinstance(package, Mapping):
        raise ValueError("visual_director requires publish_package")
    raw_contract = package.get("content_contract")
    if raw_contract is None:
        raise ValueError(
            "visual_director requires publish_package.content_contract"
        )
    if isinstance(raw_contract, ContentContract):
        return raw_contract
    return ContentContract.model_validate(raw_contract)


def _recent_visual_signatures(state: Mapping[str, Any]) -> tuple[object, ...]:
    memory_context = state.get("memory_context")
    if not isinstance(memory_context, Mapping):
        return ()
    signatures = memory_context.get("recent_visual_signatures")
    if not isinstance(signatures, Sequence) or isinstance(signatures, str | bytes):
        return ()
    return tuple(signatures)


def _validated_style_profiles(
    profiles: Mapping[TemplateFamily, FamilyStyleProfile] | None,
) -> Mapping[TemplateFamily, FamilyStyleProfile]:
    registry = load_style_registry() if profiles is None else profiles
    expected = set(get_args(TemplateFamily))
    if set(registry) != expected:
        raise ValueError("visual_director requires all six family profiles")
    for family, profile in registry.items():
        if family != profile.family:
            raise ValueError("style profile mapping key must match profile family")
        if not profile.reference_image_paths:
            raise ValueError("every family profile requires reference images")
    return registry


def _reference_image_paths(
    profiles: Mapping[TemplateFamily, FamilyStyleProfile],
) -> tuple[Path, ...]:
    paths = tuple(
        Path(image_path)
        for profile in profiles.values()
        for image_path in profile.reference_image_paths
    )
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise ValueError(
            "visual_director reference images do not exist: "
            + ", ".join(missing)
        )
    return paths


def _is_semantic_boundary(text: str, position: int) -> bool:
    return (
        position == 0
        or position == len(text)
        or text[position - 1] in _SEMANTIC_BOUNDARY_CHARACTERS
    )


def _validate_semantic_boundaries(
    atom_set: ContentAtomSet,
    fragments: Sequence[ContentFragment],
) -> None:
    atoms = {atom.atom_id: atom for atom in atom_set.atoms}
    for fragment in fragments:
        atom = atoms[fragment.source_atom_id]
        if not _is_semantic_boundary(
            atom.text, fragment.start
        ) or not _is_semantic_boundary(atom.text, fragment.end):
            raise ValueError(
                "content fragments must split only at semantic boundaries"
            )


def _requests_english_visible_copy(query_or_prompt: str) -> bool:
    positive_context = query_or_prompt
    for negative_pattern in _ENGLISH_NEGATIVE_VISIBLE_COPY_CONTEXTS:
        positive_context = negative_pattern.sub("", positive_context)
    return _ENGLISH_POSITIVE_VISIBLE_COPY_COMMAND.search(
        positive_context
    ) is not None


def _validate_asset_directive(directive: AssetDirective) -> None:
    query_or_prompt = directive.query_or_prompt
    if directive.preferred_source == "none":
        if directive.required:
            raise ValueError("a no-asset directive cannot be required")
        if directive.fallback_source != "none":
            raise ValueError("a no-asset directive cannot declare a fallback")
        if query_or_prompt is not None:
            raise ValueError("a no-asset directive cannot contain a query or prompt")
        return

    if not isinstance(query_or_prompt, str) or not query_or_prompt.strip():
        raise ValueError("asset directives require a non-empty query or prompt")
    if _requests_english_visible_copy(query_or_prompt) or any(
        pattern.search(query_or_prompt)
        for pattern in _FORBIDDEN_DISCLOSURE_OR_CHINESE_ASSET_COPY
    ):
        raise ValueError(
            "asset directive query_or_prompt requests forbidden visible "
            "image copy"
        )
    combined_constraints = " ".join(directive.negative_constraints).casefold()
    for label, accepted_phrases in _REQUIRED_ASSET_NEGATIVE_CONSTRAINTS:
        if not any(
            phrase.casefold() in combined_constraints
            for phrase in accepted_phrases
        ):
            raise ValueError(
                f"asset directive negative constraints must ban {label}"
            )


def _validate_content_asset_fit(
    atom_set: ContentAtomSet,
    directives: Sequence[AssetDirective],
) -> None:
    copy = "\n".join(atom.text for atom in atom_set.atoms)
    if not all(signal in copy for signal in _PERSISTENT_PAIN_SIGNALS):
        return
    has_skin_photo_evidence = any(
        directive.role == "skin_example"
        and directive.required
        and directive.preferred_source in {"search", "generate", "either"}
        for directive in directives
    )
    if not has_skin_photo_evidence:
        raise ValueError(
            "persistent-pain content requires a searched or generated "
            "skin photo evidence directive"
        )


def _validate_executable_direction(
    plan: VisualDirectionPlan,
    family_profile: FamilyStyleProfile,
) -> None:
    if not plan.art_direction.strip():
        raise ValueError("art_direction must be non-blank")
    if not plan.palette:
        raise ValueError("palette must contain at least one family color")
    if not plan.typography_direction:
        raise ValueError(
            "typography_direction must contain meaningful font-role direction"
        )
    for role, direction in plan.typography_direction.items():
        if role not in family_profile.font_roles:
            raise ValueError(
                "typography_direction roles must exist in the family profile"
            )
        if not role.strip() or not direction.strip():
            raise ValueError(
                "typography_direction keys and values must be non-blank"
            )
    if any(not page.purpose.strip() for page in plan.page_sequence):
        raise ValueError("each page purpose must be non-blank")


def _validate_candidate(
    candidate: VisualDirectionPlan,
    *,
    atom_set: ContentAtomSet,
    profiles: Mapping[TemplateFamily, FamilyStyleProfile],
) -> None:
    # Revalidate the complete dump so scripted/future adapters cannot bypass
    # Pydantic invariants by constructing a model without validation.
    validated = VisualDirectionPlan.model_validate(
        candidate.model_dump(mode="python")
    )
    family_profile = profiles[validated.template_family]
    validated.validate_against(atom_set, family_profile)
    _validate_executable_direction(validated, family_profile)
    _validate_semantic_boundaries(atom_set, validated.content_fragments)
    for directive in validated.asset_directives:
        _validate_asset_directive(directive)
    _validate_content_asset_fit(atom_set, validated.asset_directives)


def _director_prompt(
    state: Mapping[str, Any],
    *,
    atom_set: ContentAtomSet,
    content_contract: ContentContract,
    profiles: Mapping[TemplateFamily, FamilyStyleProfile],
    recent_visual_signatures: Sequence[object],
) -> str:
    base_prompt = compose_prompt_for_state(
        "visual_director",
        state,
        allow_legacy_beauty_fallback=False,
    )
    context = {
        "immutable_content_atom_set": atom_set,
        "content_contract": content_contract,
        "family_style_profiles": tuple(profiles.values()),
        "recent_visual_signatures": tuple(recent_visual_signatures),
        "asset_capabilities": {
            "searched_licensed": True,
            "generated_photoreal": True,
            "diagrammatic": True,
            "no_asset": True,
        },
        "canvas": {
            "width": 1080,
            "height": 1440,
        },
    }
    return (
        f"{base_prompt}\n\n"
        "【Visual Director Inputs】\n"
        f"{serialize_prompt_value(context)}"
    )


def visual_director_node(
    state: Mapping[str, Any],
    *,
    model: StructuredVisualModel,
    style_profiles: Mapping[
        TemplateFamily, FamilyStyleProfile
    ] | None = None,
) -> dict[str, object]:
    """Produce one validated visual direction through a three-attempt boundary."""
    atom_set = _required_atom_set(state)
    content_contract = _required_content_contract(state)
    profiles = _validated_style_profiles(style_profiles)
    recent_visual_signatures = _recent_visual_signatures(state)
    prompt = _director_prompt(
        state,
        atom_set=atom_set,
        content_contract=content_contract,
        profiles=profiles,
        recent_visual_signatures=recent_visual_signatures,
    )
    plan = generate_validated(
        model,
        prompt=prompt,
        response_model=VisualDirectionPlan,
        image_paths=_reference_image_paths(profiles),
        validate=lambda candidate: _validate_candidate(
            candidate,
            atom_set=atom_set,
            profiles=profiles,
        ),
        max_attempts=3,
    )
    return {
        "visual_direction_plan": plan,
        "current_node": "VISUAL_DIRECTOR",
    }
