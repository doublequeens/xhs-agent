"""Deterministic migration of pre-editorial checkpoints.

This module is the only production compatibility seam. It decodes old checkpoint
shapes, hydrates the modern content contract and ``VisualPlan``, discards obsolete
render/storyboard artifacts, and sends execution back through the modern
storyboard -> resolver -> renderer path. It never imports an old renderer,
resolver, schema, or prompt.
"""

from collections.abc import Mapping
from typing import Any


LEGACY_EDITORIAL_CHECKPOINT_KEY = "legacy_editorial_checkpoint"
EDITORIAL_WORKFLOW_VERSION_KEY = "editorial_workflow_version"
LEGACY_EDITORIAL_V1 = "legacy_v1"
MODERN_EDITORIAL_V2 = "modern_v2"
MODERN_REENTRY_PREDECESSOR = "visual_strategy_planner"

_MODERN_STORYBOARD_FIELDS = frozenset(
    {"role", "layout", "content_blocks", "visual_slots"}
)
_LEGACY_LAYOUT_FIELD = "layout"
_LEGACY_DESIGN_SYSTEM = "beauty_editorial_v1"
_LEGACY_CHECKPOINT_SUCCESSORS = frozenset(
    {
        "storyboard_generator",
        "carousel_qa",
        # Persisted migration key only; this node is intentionally absent from
        # the production graph and no implementation is imported or invoked.
        "text_card_renderer",
        "render_qa",
        "human_review",
        "final_policy_guard",
        "content_writer",
    }
)

# Map the pre-editorial ``storyboard_strategy`` classification onto the modern
# ``NarrativeForm`` enum. ``auto`` collapses to ``reflective_editorial`` so the
# adapter never silently preserves an ambiguous strategy.
STORYBOARD_STRATEGY_TO_NARRATIVE_FORM: dict[str, str] = {
    "cognitive_correction": "cognitive_correction",
    "step_tutorial": "step_tutorial",
    "checklist": "checklist_collection",
    "scenario_companion": "scenario_story",
    "comparison": "comparison",
    "qa": "diagnostic_qa",
    "story_reversal": "story_reversal",
    "auto": "reflective_editorial",
}
DEFAULT_LEGACY_NARRATIVE_FORM = "reflective_editorial"

# Minimal canonical beat sequences per ``NarrativeForm``. The legacy adapter only
# needs a valid plan to seed ``build_visual_plan``; downstream nodes will re-run
# the modern narrative planner. Each tuple is ``(beat_id, kind, purpose)`` and
# the final beat is reused as the ``saveable_beat``.
_LEGACY_SEED_BEATS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "cognitive_correction": (
        ("legacy-hook", "hook", "建立问题"),
        ("legacy-misconception", "misconception", "指出常见误区"),
        ("legacy-reveal", "reveal", "给出修正"),
        ("legacy-action", "action", "促发行动"),
    ),
    "step_tutorial": (
        ("legacy-hook", "hook", "建立场景"),
        ("legacy-scene", "scene", "呈现问题"),
        ("legacy-steps", "steps", "拆解步骤"),
        ("legacy-action", "action", "促发行动"),
    ),
    "checklist_collection": (
        ("legacy-hook", "hook", "建立问题"),
        ("legacy-principle", "principle", "提出原则"),
        ("legacy-checklist", "checklist", "给出清单"),
        ("legacy-action", "action", "促发行动"),
    ),
    "comparison": (
        ("legacy-hook", "hook", "建立对比"),
        ("legacy-comparison", "comparison", "并列方案"),
        ("legacy-diagnostic", "diagnostic", "提供判断"),
        ("legacy-action", "action", "促发行动"),
    ),
    "diagnostic_qa": (
        ("legacy-hook", "hook", "建立问题"),
        ("legacy-diagnostic", "diagnostic", "提供判断"),
        ("legacy-qa", "qa", "回答关键疑问"),
        ("legacy-action", "action", "促发行动"),
    ),
    "scenario_story": (
        ("legacy-hook", "hook", "建立场景"),
        ("legacy-scene", "scene", "呈现情境"),
        ("legacy-tension", "tension", "引入转折"),
        ("legacy-action", "action", "促发行动"),
    ),
    "story_reversal": (
        ("legacy-hook", "hook", "建立场景"),
        ("legacy-tension", "tension", "引入反转"),
        ("legacy-reveal", "reveal", "给出真相"),
        ("legacy-action", "action", "促发行动"),
    ),
    "reflective_editorial": (
        ("legacy-hook", "hook", "建立议题"),
        ("legacy-quote", "quote", "提出观点"),
        ("legacy-explanation", "explanation", "展开论证"),
        ("legacy-action", "action", "促发行动"),
    ),
}

_LEGACY_VISIBLE_SNAPSHOT_KEY = "storyboard_visible_text_snapshot"


def hydrate_legacy_content_contract(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Upgrade the old content-contract keys without changing its copy."""

    hydrated = dict(raw)
    mode = hydrated.get("visual_mode")
    hydrated.setdefault("content_job", "save_and_check")
    hydrated.setdefault("primary_visual_family", "saveable_reference")
    hydrated.setdefault("primary_visual_subject", "checklist")
    hydrated.setdefault(
        "proof_mode",
        "comparison" if mode == "comparison_table" else "diagram",
    )
    hydrated.setdefault("recommended_frame_count", 6)
    return hydrated


def modern_editorial_transition_updates() -> dict[str, Any]:
    """Return the canonical modern marker and invalidated downstream slots."""

    return {
        EDITORIAL_WORKFLOW_VERSION_KEY: MODERN_EDITORIAL_V2,
        LEGACY_EDITORIAL_CHECKPOINT_KEY: False,
        "visual_plan": None,
        "asset_manifest": None,
        "render_manifest": None,
        "carousel_qa_result": None,
        "render_qa_result": None,
    }


def _strict_old_storyboards(package: Mapping[str, Any]) -> bool:
    storyboards = package.get("storyboards")
    return (
        isinstance(storyboards, list)
        and bool(storyboards)
        and all(
            isinstance(frame, Mapping)
            and isinstance(frame.get("template"), str)
            and bool(frame.get("template"))
            and not _MODERN_STORYBOARD_FIELDS.intersection(frame)
            for frame in storyboards
        )
    )


def _frames_contain_layout(frames: Any) -> bool:
    if not isinstance(frames, list):
        return False
    return any(
        isinstance(frame, Mapping) and _LEGACY_LAYOUT_FIELD in frame
        for frame in frames
    )


def _has_legacy_visual_marker(values: Mapping[str, Any], package: Mapping[str, Any]) -> bool:
    """Detect any of the four v1 triggers listed in the task-11 brief."""

    if values.get("design_system") == _LEGACY_DESIGN_SYSTEM:
        return True
    visual_plan = values.get("visual_plan")
    if isinstance(visual_plan, Mapping) and _frames_contain_layout(
        visual_plan.get("frame_plan")
    ):
        return True
    if _frames_contain_layout(package.get("storyboards")):
        return True
    strategy = package.get("storyboard_strategy")
    if isinstance(strategy, str) and strategy:
        return True
    return False


def _is_exact_old_checkpoint(
    package: Mapping[str, Any],
    checkpoint_nodes: tuple[str, ...],
) -> bool:
    if len(checkpoint_nodes) != 1:
        return False
    successor = checkpoint_nodes[0]
    if successor not in _LEGACY_CHECKPOINT_SUCCESSORS:
        return False
    raw_contract = package.get("content_contract")
    old_contract = (
        isinstance(raw_contract, Mapping)
        and "visual_mode" in raw_contract
        and not {
            "content_job",
            "primary_visual_family",
            "primary_visual_subject",
            "proof_mode",
            "recommended_frame_count",
        }.intersection(raw_contract)
    )
    return old_contract and (
        successor == "storyboard_generator" or _strict_old_storyboards(package)
    )


def _storyboard_visible_text_snapshot(storyboards: Any) -> list[dict[str, Any]]:
    """Preserve the human-visible text snapshot before dropping old frames.

    Mirrors ``extract_storyboard_visible_text`` from ``src.nodes.publish_patch``
    but inlines the logic so the legacy seam never imports a business node.
    Only the human-visible text fields are retained; structural fields such as
    ``template`` or ``layout`` are intentionally discarded.
    """

    snapshot: list[dict[str, Any]] = []
    for frame in list(storyboards or []):
        if not isinstance(frame, Mapping):
            continue
        text_blocks: dict[str, str] = {}
        for field_name in ("kicker", "headline", "footer"):
            if field_name in frame:
                text_blocks[field_name] = str(frame.get(field_name) or "")
        for index, value in enumerate(frame.get("emphasis") or []):
            text_blocks[f"emphasis[{index}]"] = str(value or "")
        for block_index, block in enumerate(frame.get("content_blocks") or []):
            if not isinstance(block, Mapping):
                continue
            for field_name in ("heading", "body"):
                if field_name in block:
                    text_blocks[f"content_blocks[{block_index}].{field_name}"] = str(
                        block.get(field_name) or ""
                    )
            for item_index, item in enumerate(block.get("items") or []):
                text_blocks[
                    f"content_blocks[{block_index}].items[{item_index}]"
                ] = str(item or "")
        snapshot.append(
            {
                "frame_id": str(frame.get("frame_id") or ""),
                "role": str(frame.get("role") or ""),
                "page_archetype": str(frame.get("page_archetype") or ""),
                "text_blocks": text_blocks,
            }
        )
    return snapshot


def _narrative_form_from_legacy_strategy(package: Mapping[str, Any]) -> str:
    raw_strategy = package.get("storyboard_strategy")
    if isinstance(raw_strategy, str) and raw_strategy:
        return STORYBOARD_STRATEGY_TO_NARRATIVE_FORM.get(
            raw_strategy, DEFAULT_LEGACY_NARRATIVE_FORM
        )
    return DEFAULT_LEGACY_NARRATIVE_FORM


def _build_legacy_seed_narrative_plan(narrative_form: str) -> dict[str, Any]:
    beats = [
        {"beat_id": beat_id, "kind": kind, "purpose": purpose}
        for beat_id, kind, purpose in _LEGACY_SEED_BEATS[narrative_form]
    ]
    return {
        "narrative_form": narrative_form,
        "beats": beats,
        "saveable_beat": beats[-1],
        "closing_mode": "action_prompt",
    }


def _package_for_modern_regeneration(package: Mapping[str, Any]) -> dict[str, Any]:
    migrated = dict(package)
    raw_contract = migrated.get("content_contract")
    if not isinstance(raw_contract, Mapping):
        raise ValueError("legacy editorial checkpoint requires content_contract")
    migrated["content_contract"] = hydrate_legacy_content_contract(raw_contract)

    # Preserve the human-visible text snapshot before removing the old frames.
    existing_snapshot = migrated.get(_LEGACY_VISIBLE_SNAPSHOT_KEY)
    if existing_snapshot is None:
        migrated[_LEGACY_VISIBLE_SNAPSHOT_KEY] = _storyboard_visible_text_snapshot(
            migrated.get("storyboards")
        )

    narrative_plan = migrated.get("narrative_plan")
    if not isinstance(narrative_plan, Mapping):
        migrated["narrative_plan"] = _build_legacy_seed_narrative_plan(
            _narrative_form_from_legacy_strategy(package)
        )
        migrated["narrative_form"] = migrated["narrative_plan"]["narrative_form"]
        migrated["closing_mode"] = migrated["narrative_plan"]["closing_mode"]

    for obsolete_key in (
        "storyboards",
        "rendered_image_paths",
        "render_error",
        "render_manifest",
        "storyboard_strategy",
        "visual_plan",
        "asset_manifest",
    ):
        migrated.pop(obsolete_key, None)
    return migrated


def persisted_checkpoint_nodes(
    graph: Any,
    config: Mapping[str, Any],
    visible_nodes: tuple[str, ...],
) -> tuple[str, ...]:
    """Recover one allowlisted retired successor hidden from visible state.

    LangGraph omits a persisted branch from ``StateSnapshot.next`` when that
    node no longer exists in the compiled graph; the raw checkpoint retains the
    ``branch:to:<node>`` channel this adapter reads. Recovery is gated by four
    safety conditions:

    - Raw checkpoint channels are consulted only when visible
      ``StateSnapshot.next`` is empty; a non-empty ``next`` is returned
      untouched so modern checkpoints resume normally.
    - Only ``branch:to:<node>`` channels whose node is in the legacy successor
      allowlist are considered; every other channel is ignored.
    - Recovery occurs only when the filtered result is unique.
    - Missing, ambiguous, or empty filtered values leave terminal state
      unchanged (the visible ``next`` is returned as-is).

    The allowlist is the fixed retired-successor set; this documentation does
    not broaden it.
    """

    if visible_nodes:
        return visible_nodes
    checkpointer = getattr(graph, "checkpointer", None)
    get_tuple = getattr(checkpointer, "get_tuple", None)
    if not callable(get_tuple):
        return visible_nodes
    checkpoint_tuple = get_tuple(dict(config))
    checkpoint = getattr(checkpoint_tuple, "checkpoint", None)
    if not isinstance(checkpoint, Mapping):
        return visible_nodes
    channels = checkpoint.get("channel_values")
    if not isinstance(channels, Mapping):
        return visible_nodes
    prefix = "branch:to:"
    successors = tuple(
        key.removeprefix(prefix)
        for key in channels
        if isinstance(key, str)
        and key.startswith(prefix)
        and key.removeprefix(prefix) in _LEGACY_CHECKPOINT_SUCCESSORS
    )
    return successors if len(successors) == 1 else visible_nodes


def hydrate_legacy_editorial_state(
    values: Mapping[str, Any],
    *,
    checkpoint_nodes: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Hydrate an old checkpoint into a deterministic modern re-entry state."""

    package = values.get("publish_package")
    if not isinstance(package, Mapping):
        return {}
    version = values.get(EDITORIAL_WORKFLOW_VERSION_KEY)
    if version == MODERN_EDITORIAL_V2:
        return (
            {LEGACY_EDITORIAL_CHECKPOINT_KEY: False}
            if values.get(LEGACY_EDITORIAL_CHECKPOINT_KEY) is True
            else {}
        )
    if version not in {None, LEGACY_EDITORIAL_V1}:
        raise ValueError(f"unsupported editorial workflow version: {version}")

    modern_storyboard = any(
        isinstance(frame, Mapping)
        and bool(_MODERN_STORYBOARD_FIELDS.intersection(frame))
        for frame in list(package.get("storyboards") or [])
    )
    manifest_slots = ("visual_plan", "asset_manifest", "render_manifest")
    if modern_storyboard or all(name in values for name in manifest_slots):
        if version == LEGACY_EDITORIAL_V1:
            raise ValueError("legacy editorial version conflicts with modern artifacts")
        return (
            {
                LEGACY_EDITORIAL_CHECKPOINT_KEY: False,
                EDITORIAL_WORKFLOW_VERSION_KEY: MODERN_EDITORIAL_V2,
            }
            if values.get(LEGACY_EDITORIAL_CHECKPOINT_KEY) is True
            else {}
        )

    explicit_old = version == LEGACY_EDITORIAL_V1
    inferred_old = _is_exact_old_checkpoint(package, checkpoint_nodes)
    legacy_marker = _has_legacy_visual_marker(values, package)
    if not explicit_old and not inferred_old and not legacy_marker:
        return {}

    migrated_package = _package_for_modern_regeneration(package)
    # Local import keeps the migration seam acyclic: the planner has no legacy
    # dependency and builds the same plan as a fresh modern run.
    from src.editorial_carousel.planner import build_visual_plan

    return {
        **modern_editorial_transition_updates(),
        "visual_plan": build_visual_plan(
            migrated_package["content_contract"],
            migrated_package["narrative_plan"],
            migrated_package,
            recent_signatures=[],
        ),
        "publish_package": migrated_package,
    }


def migration_reentry_predecessor(
    updates: Mapping[str, Any],
    checkpoint_nodes: tuple[str, ...],
) -> str | None:
    """Return the graph node whose successor is the safe modern re-entry seam."""

    if (
        len(checkpoint_nodes) == 1
        and checkpoint_nodes[0] in _LEGACY_CHECKPOINT_SUCCESSORS
        and updates.get(EDITORIAL_WORKFLOW_VERSION_KEY) == MODERN_EDITORIAL_V2
        and updates.get(LEGACY_EDITORIAL_CHECKPOINT_KEY) is False
        and updates.get("visual_plan") is not None
    ):
        return MODERN_REENTRY_PREDECESSOR
    return None
