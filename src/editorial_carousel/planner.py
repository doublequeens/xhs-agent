from collections.abc import Mapping, Sequence
import hashlib
from typing import Any, Final

from src.editorial_carousel.blueprints import (
    BLUEPRINTS,
    FrameBlueprint,
    materialize_blueprint,
)
from src.editorial_carousel.selector import SelectorInput, select_template
from src.schemas.assets import AssetRequirement
from src.schemas.content_contract import ContentContract
from src.schemas.editorial_templates import PageArchetype
from src.schemas.narrative import NarrativeBeat, NarrativeBeatKind, NarrativePlan
from src.schemas.visual_plan import FramePlanItem, VisualPlan


ARCHETYPES_BY_BEAT_KIND: Final[
    dict[NarrativeBeatKind, frozenset[PageArchetype]]
] = {
    "hook": frozenset({"cover"}),
    "scene": frozenset({"scene"}),
    "tension": frozenset({"story_beat"}),
    "misconception": frozenset({"diagnostic", "comparison"}),
    "reveal": frozenset({"explanation", "comparison"}),
    "principle": frozenset({"thesis", "explanation"}),
    "explanation": frozenset({"explanation"}),
    "example": frozenset({"scene", "story_beat"}),
    "steps": frozenset({"steps"}),
    "checklist": frozenset({"checklist", "save"}),
    "comparison": frozenset({"comparison"}),
    "diagnostic": frozenset({"diagnostic"}),
    "qa": frozenset({"qa"}),
    "quote": frozenset({"quote"}),
    "boundary": frozenset({"boundary"}),
    "summary": frozenset({"save", "checklist"}),
    "action": frozenset({"steps", "checklist", "save"}),
}
COLLECTION_ARCHETYPES: Final[frozenset[PageArchetype]] = frozenset(
    {"item_collection", "checklist", "comparison"}
)
PROOF_ARCHETYPES: Final[dict[str, frozenset[PageArchetype]]] = {
    "diagram": frozenset({"diagnostic", "explanation", "steps"}),
    "real_photo": frozenset({"scene", "story_beat"}),
    "product_texture": frozenset({"scene", "explanation"}),
    "comparison": frozenset({"comparison", "diagnostic"}),
    "none": frozenset(),
}
PURPOSE_BY_ARCHETYPE: Final[dict[PageArchetype, str]] = {
    "cover": "建立问题与首屏承诺",
    "thesis": "提出核心判断",
    "scene": "呈现具体使用场景",
    "story_beat": "推进关键叙事转折",
    "explanation": "解释关键原理",
    "steps": "给出有顺序的执行方法",
    "checklist": "提供可保存的检查清单",
    "comparison": "对比状态、方法或选择",
    "diagnostic": "提供判断标准",
    "qa": "回答关键疑问",
    "item_collection": "组织可浏览的条目合集",
    "quote": "突出可独立阅读的观点",
    "boundary": "说明适用范围与边界",
    "save": "提供可独立保存的参考",
    "closing": "自然收束内容",
}


def _signature_value(signature: Any, key: str) -> Any:
    if isinstance(signature, Mapping):
        return signature.get(key)
    return getattr(signature, key, None)


def _signature_archetypes(signature: Any) -> tuple[str, ...] | None:
    raw = None
    for key in (
        "frame_plan_signature",
        "page_archetypes",
        "ordered_archetypes",
        "frame_plan",
    ):
        raw = _signature_value(signature, key)
        if raw is not None:
            break
    if isinstance(raw, str):
        return tuple(part.strip() for part in raw.split("|") if part.strip())
    if not isinstance(raw, Sequence):
        return None
    normalized: list[str] = []
    for item in raw:
        if isinstance(item, Mapping):
            value = item.get("page_archetype")
        else:
            value = getattr(item, "page_archetype", item)
        if not isinstance(value, str):
            return None
        normalized.append(value)
    return tuple(normalized)


def _matches_blueprint_signature(
    signature: Any,
    blueprint: FrameBlueprint,
    archetypes: tuple[PageArchetype, ...],
) -> bool:
    recent_blueprint_id = _signature_value(signature, "blueprint_id")
    recent_archetypes = _signature_archetypes(signature)
    raw_count = _signature_value(signature, "frame_count")
    recent_count = (
        len(recent_archetypes)
        if raw_count is None and recent_archetypes is not None
        else raw_count
    )
    same_form = _signature_value(signature, "narrative_form")
    return (
        same_form == blueprint.narrative_form
        and recent_count == len(archetypes)
        and (
            recent_blueprint_id == blueprint.blueprint_id
            or recent_archetypes == archetypes
        )
    )


def _required_match_count(
    blueprint: FrameBlueprint,
    beats: Sequence[NarrativeBeat],
) -> int:
    required = set(blueprint.required)
    return sum(
        bool(required & ARCHETYPES_BY_BEAT_KIND[beat.kind])
        for beat in beats
    )


def _saveable_compatibility(
    archetypes: tuple[PageArchetype, ...],
    saveable_beat: NarrativeBeat,
) -> int:
    compatible = ARCHETYPES_BY_BEAT_KIND[saveable_beat.kind]
    return int(
        bool(set(archetypes) & compatible)
        or bool(set(archetypes) & {"save", "checklist", "comparison"})
    )


def _select_blueprint(
    narrative_plan: NarrativePlan,
    frame_count: int,
    publish_package: Mapping[str, Any],
    recent_signatures: Sequence[Any],
) -> tuple[FrameBlueprint, tuple[PageArchetype, ...]]:
    topic_id = str(publish_package.get("topic_id") or "")
    angle_id = str(publish_package.get("angle_id") or "")
    candidates = []
    for blueprint in BLUEPRINTS[narrative_plan.narrative_form]:
        archetypes = materialize_blueprint(blueprint, frame_count)
        recent_penalty = sum(
            _matches_blueprint_signature(signature, blueprint, archetypes)
            for signature in recent_signatures
        )
        tie_break = hashlib.sha256(
            f"{topic_id}|{angle_id}|{blueprint.blueprint_id}".encode("utf-8")
        ).hexdigest()
        candidates.append(
            (
                -_required_match_count(blueprint, narrative_plan.beats),
                -_saveable_compatibility(
                    archetypes,
                    narrative_plan.saveable_beat,
                ),
                recent_penalty,
                tie_break,
                blueprint,
                archetypes,
            )
        )
    *_rank, blueprint, archetypes = min(candidates)
    return blueprint, archetypes


def _purpose_assignments(
    archetypes: tuple[PageArchetype, ...],
    narrative_plan: NarrativePlan,
) -> list[str]:
    purposes: list[str | None] = [None] * len(archetypes)
    unused_beats = list(narrative_plan.beats)
    saveable = narrative_plan.saveable_beat
    save_candidates = [
        index
        for index, archetype in enumerate(archetypes)
        if archetype in ARCHETYPES_BY_BEAT_KIND[saveable.kind]
    ] or [
        index
        for index, archetype in enumerate(archetypes)
        if archetype in {"save", "checklist", "comparison"}
    ]
    if save_candidates:
        save_index = save_candidates[-1]
        purposes[save_index] = saveable.purpose
        unused_beats.remove(saveable)

    for index, archetype in enumerate(archetypes):
        if purposes[index] is not None:
            continue
        matching = next(
            (
                beat
                for beat in unused_beats
                if archetype in ARCHETYPES_BY_BEAT_KIND[beat.kind]
            ),
            None,
        )
        if matching is not None:
            purposes[index] = matching.purpose
            unused_beats.remove(matching)

    for index in range(len(purposes)):
        if purposes[index] is not None:
            continue
        if unused_beats:
            beat = unused_beats.pop(0)
            purposes[index] = beat.purpose
        else:
            purposes[index] = PURPOSE_BY_ARCHETYPE[archetypes[index]]

    if unused_beats:
        combined = "；".join(beat.purpose for beat in unused_beats)
        purposes[-1] = f"{purposes[-1]}；{combined}"[:160]
    return [purpose or "承载叙事任务" for purpose in purposes]


def plan_frames(
    contract: ContentContract,
    narrative_plan: NarrativePlan,
    publish_package: Mapping[str, Any],
    recent_signatures: Sequence[Any],
) -> list[FramePlanItem]:
    target_count = max(
        5,
        min(
            7,
            max(
                contract.recommended_frame_count,
                len(narrative_plan.beats),
            ),
        ),
    )
    _blueprint, archetypes = _select_blueprint(
        narrative_plan,
        target_count,
        publish_package,
        recent_signatures,
    )
    purposes = _purpose_assignments(archetypes, narrative_plan)
    proof_archetypes = PROOF_ARCHETYPES[contract.proof_mode]
    return [
        FramePlanItem(
            frame_id=f"frame-{index:02d}-{archetype}",
            role=archetype,
            page_archetype=archetype,
            purpose=purposes[index - 1],
            allowed_density=(
                ["standard", "dense"]
                if archetype in COLLECTION_ARCHETYPES
                else ["sparse", "standard", "dense"]
            ),
            asset_roles=(
                [contract.proof_mode]
                if archetype in proof_archetypes
                else []
            ),
        )
        for index, archetype in enumerate(archetypes, start=1)
    ]


def required_assets_for(
    frame_plan: Sequence[FramePlanItem],
    contract: ContentContract,
) -> list[AssetRequirement]:
    if contract.proof_mode == "none":
        return []
    return [
        AssetRequirement(
            slot_id=f"{frame.frame_id}-{contract.proof_mode}",
            role=contract.proof_mode,
            page_archetype=frame.page_archetype,
            min_width=1080,
            min_height=1440,
            context_tags=[contract.proof_asset],
            orientation="portrait",
        )
        for frame in frame_plan
        if (
            frame.page_archetype in PROOF_ARCHETYPES[contract.proof_mode]
            and contract.proof_mode in frame.asset_roles
        )
    ]


def build_visual_plan(
    contract: ContentContract | Mapping[str, Any],
    narrative_plan: NarrativePlan | Mapping[str, Any],
    publish_package: Mapping[str, Any],
    recent_signatures: Sequence[Any],
) -> VisualPlan:
    validated_contract = ContentContract.model_validate(contract)
    validated_narrative = NarrativePlan.model_validate(narrative_plan)
    frame_plan = plan_frames(
        validated_contract,
        validated_narrative,
        publish_package,
        recent_signatures,
    )
    selection = select_template(
        SelectorInput.from_content(
            validated_contract,
            validated_narrative,
            publish_package,
            frame_plan,
        ),
        recent_signatures,
    )
    return VisualPlan(
        design_system="beauty_editorial_v2",
        template_family=selection.template_family,
        template_selection=selection,
        narrative_form=validated_narrative.narrative_form,
        content_job=validated_contract.content_job,
        frame_plan=frame_plan,
        required_assets=required_assets_for(
            frame_plan,
            validated_contract,
        ),
    )
