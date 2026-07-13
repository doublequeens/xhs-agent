from collections.abc import Mapping, Sequence
from typing import Any, Final

from src.schemas.assets import AssetRequirement, LayoutName
from src.schemas.content_contract import ContentContract
from src.schemas.visual_plan import (
    ContentJob,
    FramePlanItem,
    VisualFamily,
    VisualPlan,
)


RecipeItem = tuple[str, LayoutName, str]
Recipe = tuple[RecipeItem, ...]


PRIMARY_FAMILY_BY_JOB: Final[dict[ContentJob, VisualFamily]] = {
    "diagnose_and_adjust": "face_zone_map",
    "follow_steps": "step_flow",
    "compare_and_choose": "comparison_decision",
    "save_and_check": "saveable_reference",
    "understand_and_notice": "beauty_editorial",
}

LAYOUT_FAMILY: Final[dict[LayoutName, VisualFamily]] = {
    "editorial_cover": "beauty_editorial",
    "texture_baseline": "beauty_editorial",
    "front_face_zone": "face_zone_map",
    "three_quarter_face_zone": "face_zone_map",
    "step_timeline": "step_flow",
    "morning_evening_flow": "step_flow",
    "left_right_comparison": "comparison_decision",
    "three_state_diagnostic": "comparison_decision",
    "decision_tree": "comparison_decision",
    "saveable_checklist": "saveable_reference",
    "saveable_reference": "saveable_reference",
}

RECIPES: Final[dict[ContentJob, Recipe]] = {
    "diagnose_and_adjust": (
        ("cover", "editorial_cover", "beauty_subject"),
        ("baseline", "texture_baseline", "product_texture"),
        ("applicable_case", "front_face_zone", "face_map"),
        ("zone_adjustment", "three_quarter_face_zone", "face_map"),
        ("feedback_diagnosis", "three_state_diagnostic", "comparison"),
        ("save", "saveable_reference", "reference"),
    ),
    "follow_steps": (
        ("cover", "editorial_cover", "beauty_subject"),
        ("sequence", "step_timeline", "process"),
        ("routine", "morning_evening_flow", "process"),
        ("decision", "decision_tree", "comparison"),
        ("save", "saveable_checklist", "reference"),
    ),
    "compare_and_choose": (
        ("cover", "editorial_cover", "beauty_subject"),
        ("comparison", "left_right_comparison", "comparison"),
        ("feedback_diagnosis", "three_state_diagnostic", "comparison"),
        ("decision", "decision_tree", "comparison"),
        ("save", "saveable_reference", "reference"),
    ),
    "save_and_check": (
        ("cover", "editorial_cover", "beauty_subject"),
        ("checklist", "saveable_checklist", "reference"),
        ("decision", "decision_tree", "comparison"),
        ("comparison", "left_right_comparison", "comparison"),
        ("save", "saveable_reference", "reference"),
    ),
    "understand_and_notice": (
        ("cover", "editorial_cover", "beauty_subject"),
        ("baseline", "texture_baseline", "product_texture"),
        ("observation", "three_state_diagnostic", "comparison"),
        ("method", "step_timeline", "process"),
        ("save", "saveable_reference", "reference"),
    ),
}

# Each alternative changes a non-cover, non-save auxiliary layout while retaining
# the recipe's semantic role and primary visual family.
ALTERNATIVE_LAYOUTS: Final[dict[ContentJob, tuple[int, LayoutName]]] = {
    "diagnose_and_adjust": (4, "decision_tree"),
    "follow_steps": (2, "step_timeline"),
    "compare_and_choose": (2, "decision_tree"),
    "save_and_check": (2, "step_timeline"),
    "understand_and_notice": (3, "morning_evening_flow"),
}

PURPOSE_BY_ROLE: Final[dict[str, str]] = {
    "cover": "establish the problem and first-screen promise",
    "baseline": "establish the visual or product baseline",
    "applicable_case": "identify when the guidance applies",
    "zone_adjustment": "show where and how to adjust",
    "feedback_diagnosis": "interpret observable feedback",
    "sequence": "present the required execution order",
    "routine": "separate the parallel routine paths",
    "comparison": "contrast the available states or choices",
    "checklist": "provide an actionable checklist",
    "observation": "make the key states easy to notice",
    "method": "turn the observation into an action",
    "decision": "connect conditions to decisions",
    "save": "provide a standalone saveable reference",
}


def _frame_signature(recipe: Recipe) -> tuple[tuple[str, str], ...]:
    return tuple((role, layout) for role, layout, _asset_role in recipe)


def _normalize_signature(value: Any) -> tuple[Any, ...] | None:
    if isinstance(value, Mapping):
        for key in ("frame_plan_signature", "signature", "frame_plan"):
            if key in value:
                return _normalize_signature(value[key])
        return None
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split("|") if part.strip())
    if not isinstance(value, Sequence):
        return None

    items = list(value)
    if all(isinstance(item, Mapping) for item in items):
        return tuple(
            (str(item.get("role", "")), str(item.get("layout", "")))
            for item in items
        )
    if all(
        isinstance(item, Sequence)
        and not isinstance(item, str)
        and len(item) >= 2
        for item in items
    ):
        return tuple((str(item[0]), str(item[1])) for item in items)
    if all(isinstance(item, str) for item in items):
        return tuple(items)
    return None


def _matches_recipe_signature(value: Any, recipe: Recipe) -> bool:
    normalized = _normalize_signature(value)
    if normalized is None:
        return False
    pairs = _frame_signature(recipe)
    layouts = tuple(layout for _role, layout in pairs)
    encoded_pairs = tuple(f"{role}:{layout}" for role, layout in pairs)
    return normalized in (pairs, layouts, encoded_pairs)


def _select_recipe(
    content_job: ContentJob,
    recent_signatures: Sequence[Any],
) -> Recipe:
    recipe = RECIPES[content_job]
    if not any(
        _matches_recipe_signature(signature, recipe)
        for signature in recent_signatures
    ):
        return recipe

    index, alternative_layout = ALTERNATIVE_LAYOUTS[content_job]
    alternative = list(recipe)
    role, _layout, asset_role = alternative[index]
    alternative[index] = (role, alternative_layout, asset_role)
    return tuple(alternative)


def _supporting_families(
    recipe: Recipe,
    primary_family: VisualFamily,
) -> list[VisualFamily]:
    families: list[VisualFamily] = []
    for _role, layout, _asset_role in recipe:
        family = LAYOUT_FAMILY[layout]
        if family != primary_family and family not in families:
            families.append(family)
    return families


def _required_assets(recipe: Recipe) -> list[AssetRequirement]:
    return [
        AssetRequirement(
            slot_id=f"{role.replace('_', '-')}-{asset_role.replace('_', '-')}",
            role=asset_role,
            layout=layout,
            min_width=1080,
            min_height=1440,
            context_tags=[asset_role],
            orientation="portrait",
        )
        for role, layout, asset_role in recipe
        if asset_role
    ]


def build_visual_plan(
    contract: ContentContract | Mapping[str, Any],
    recent_signatures: Sequence[Any],
) -> VisualPlan:
    """Build a deterministic, content-job-aware editorial frame plan."""

    validated_contract = ContentContract.model_validate(contract)
    content_job = validated_contract.content_job
    primary_family = PRIMARY_FAMILY_BY_JOB[content_job]
    recipe = _select_recipe(content_job, recent_signatures)
    frames = [
        FramePlanItem(
            frame_id=role.replace("_", "-"),
            role=role,
            layout=layout,
            purpose=PURPOSE_BY_ROLE[role],
            asset_roles=[asset_role] if asset_role else [],
        )
        for role, layout, asset_role in recipe
    ]

    return VisualPlan(
        design_system="beauty_editorial_v1",
        content_job=content_job,
        primary_visual_family=primary_family,
        supporting_families=_supporting_families(recipe, primary_family),
        frame_plan=frames,
        required_assets=_required_assets(recipe),
    )
