from collections.abc import Mapping, Sequence
from typing import Any, Final, Literal

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

ASSET_ROLE_BY_LAYOUT: Final[dict[LayoutName, str]] = {
    "editorial_cover": "background_token",
    "texture_baseline": "serum_texture",
    "front_face_zone": "face_angle",
    "three_quarter_face_zone": "face_zone_mask",
    "step_timeline": "line_token",
    "morning_evening_flow": "pump_shape",
    "left_right_comparison": "skin_detail",
    "three_state_diagnostic": "skin_detail",
    "decision_tree": "container_shape",
    "saveable_checklist": "background_token",
    "saveable_reference": "background_token",
}

AssetOrientation = Literal["portrait", "landscape", "square", "any"]
ASSET_PROFILE_BY_ROLE: Final[dict[str, tuple[int, int, AssetOrientation]]] = {
    "background_token": (1080, 1440, "portrait"),
    "line_token": (1080, 300, "landscape"),
    "serum_texture": (512, 512, "square"),
    "face_angle": (512, 512, "square"),
    "face_zone_mask": (512, 512, "square"),
    "skin_detail": (512, 512, "square"),
    "container_shape": (512, 512, "square"),
    "pump_shape": (512, 512, "square"),
}

# Fallback IDs are included only where the manifest-declared fallback role has
# the same layout compatibility, minimum dimensions, and orientation.
FALLBACK_ASSET_IDS: Final[dict[tuple[str, LayoutName], tuple[str, ...]]] = {
    ("serum_texture", "texture_baseline"): ("liquid_drips",),
    ("face_angle", "front_face_zone"): ("mask_chin",),
    ("face_zone_mask", "three_quarter_face_zone"): ("face_front",),
}

RECIPES: Final[dict[ContentJob, Recipe]] = {
    "diagnose_and_adjust": (
        ("cover", "editorial_cover", "background_token"),
        ("baseline", "texture_baseline", "serum_texture"),
        ("applicable_case", "front_face_zone", "face_angle"),
        ("zone_adjustment", "three_quarter_face_zone", "face_zone_mask"),
        ("feedback_diagnosis", "three_state_diagnostic", "skin_detail"),
        ("save", "saveable_reference", "background_token"),
    ),
    "follow_steps": (
        ("cover", "editorial_cover", "background_token"),
        ("sequence", "step_timeline", "line_token"),
        ("routine", "morning_evening_flow", "pump_shape"),
        ("decision", "decision_tree", "container_shape"),
        ("save", "saveable_checklist", "background_token"),
    ),
    "compare_and_choose": (
        ("cover", "editorial_cover", "background_token"),
        ("comparison", "left_right_comparison", "skin_detail"),
        ("feedback_diagnosis", "three_state_diagnostic", "skin_detail"),
        ("decision", "decision_tree", "container_shape"),
        ("save", "saveable_reference", "background_token"),
    ),
    "save_and_check": (
        ("cover", "editorial_cover", "background_token"),
        ("checklist", "saveable_checklist", "background_token"),
        ("decision", "decision_tree", "container_shape"),
        ("comparison", "left_right_comparison", "skin_detail"),
        ("save", "saveable_reference", "background_token"),
    ),
    "understand_and_notice": (
        ("cover", "editorial_cover", "background_token"),
        ("baseline", "texture_baseline", "serum_texture"),
        ("observation", "three_state_diagnostic", "skin_detail"),
        ("method", "step_timeline", "line_token"),
        ("save", "saveable_reference", "background_token"),
    ),
}

# Each alternative changes a non-cover, non-save auxiliary layout while retaining
# the recipe's semantic role and primary visual family.
ALTERNATIVE_LAYOUTS: Final[dict[ContentJob, tuple[int, LayoutName]]] = {
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

    alternative_recipe = ALTERNATIVE_LAYOUTS.get(content_job)
    if alternative_recipe is None:
        return recipe

    index, alternative_layout = alternative_recipe
    alternative = list(recipe)
    role, _layout, _asset_role = alternative[index]
    alternative[index] = (
        role,
        alternative_layout,
        ASSET_ROLE_BY_LAYOUT[alternative_layout],
    )
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
    requirements: list[AssetRequirement] = []
    for role, layout, asset_role in recipe:
        min_width, min_height, orientation = ASSET_PROFILE_BY_ROLE[asset_role]
        requirements.append(
            AssetRequirement(
                slot_id=(
                    f"{role.replace('_', '-')}-{asset_role.replace('_', '-')}"
                ),
                role=asset_role,
                layout=layout,
                min_width=min_width,
                min_height=min_height,
                context_tags=[asset_role],
                orientation=orientation,
                fallback_asset_ids=list(
                    FALLBACK_ASSET_IDS.get((asset_role, layout), ())
                ),
            )
        )
    return requirements


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
