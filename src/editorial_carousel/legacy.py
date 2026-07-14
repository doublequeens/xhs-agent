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


def _package_for_modern_regeneration(package: Mapping[str, Any]) -> dict[str, Any]:
    migrated = dict(package)
    raw_contract = migrated.get("content_contract")
    if not isinstance(raw_contract, Mapping):
        raise ValueError("legacy editorial checkpoint requires content_contract")
    migrated["content_contract"] = hydrate_legacy_content_contract(raw_contract)
    for obsolete_key in (
        "storyboards",
        "rendered_image_paths",
        "render_error",
        "render_manifest",
    ):
        migrated.pop(obsolete_key, None)
    return migrated


def persisted_checkpoint_nodes(
    graph: Any,
    config: Mapping[str, Any],
    visible_nodes: tuple[str, ...],
) -> tuple[str, ...]:
    """Recover a deleted successor hidden by the newly compiled graph.

    LangGraph omits a persisted branch from ``StateSnapshot.next`` when that
    node no longer exists in the compiled graph. The raw checkpoint retains a
    ``branch:to:<node>`` channel, so the migration adapter reads only the one
    documented retired successor and otherwise leaves terminal state alone.
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
    if not explicit_old and not inferred_old:
        return {}

    migrated_package = _package_for_modern_regeneration(package)
    # Local import keeps the migration seam acyclic: the strategy has no legacy
    # dependency and builds the same plan as a fresh modern run.
    from src.editorial_carousel.strategy import build_visual_plan

    return {
        **modern_editorial_transition_updates(),
        "visual_plan": build_visual_plan(
            migrated_package["content_contract"],
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
