"""Deterministic migration of pre-v3 checkpoints to the llm_scene_v3 seam.

This module is the only production compatibility boundary. It detects legacy
(``legacy_v1``) and ``modern_v2`` checkpoints that still carry retired visual
artifacts (storyboards, layout-based ``visual_plan``, rendered image paths,
old QA), preserves the human content contract (R1/R2/title/hashtags and the
assembler ``publish_package``), discards every obsolete visual slot, stamps
version ``llm_scene_v3``, and re-enters the production graph after ``assembler``
so ``content_atomizer`` re-derives the dynamic visual plan from scratch.

It never imports or executes an old renderer, resolver, schema, or prompt, and
performs no old layout conversion. Unknown future versions fail closed.
"""

from collections.abc import Mapping
from typing import Any


LEGACY_EDITORIAL_CHECKPOINT_KEY = "legacy_editorial_checkpoint"
EDITORIAL_WORKFLOW_VERSION_KEY = "editorial_workflow_version"
LEGACY_EDITORIAL_V1 = "legacy_v1"
MODERN_EDITORIAL_V2 = "modern_v2"
DYNAMIC_VISUAL_V3 = "llm_scene_v3"

# Re-enter the production graph after the assembler so content_atomizer is the
# first dynamic-visual node to run on a migrated checkpoint.
DYNAMIC_REENTRY_PREDECESSOR = "assembler"

# Retired v1/v2 visual-graph successors that may still persist a checkpoint.
# Used only to recover a hidden ``branch:to:<node>`` channel from the raw
# checkpoint when ``StateSnapshot.next`` is empty (the node no longer exists in
# the compiled graph). The new dynamic-visual nodes remain in the graph, so a
# v3 checkpoint at one of them resumes normally without this recovery.
_LEGACY_CHECKPOINT_SUCCESSORS = frozenset(
    {
        "visual_strategy_planner",
        "storyboard_generator",
        "asset_resolver",
        "carousel_qa",
        "editorial_carousel_renderer",
        # Persisted migration key only; this node is intentionally absent from
        # the production graph and no implementation is imported or invoked.
        "text_card_renderer",
        "render_qa",
        "human_review",
        "final_policy_guard",
        "content_writer",
    }
)

# Visual state slots that belong to a retired v1/v2 visual run. A non-null value
# in any of them (or storyboards/rendered paths in the package) marks the
# checkpoint as needing re-derivation through the dynamic visual pipeline.
_RETIRED_VISUAL_STATE_KEYS = (
    "visual_plan",
    "carousel_qa_result",
    "asset_manifest",
    "render_manifest",
    "render_qa_result",
    "visual_critique",
    "carousel_design_plan",
    "design_plan_qa_result",
    "visual_direction_plan",
    "content_atom_set",
)


def dynamic_visual_transition_updates(values: Mapping[str, Any]) -> dict[str, Any]:
    """Return the canonical v3 marker and invalidated visual slots.

    Preserves the assembler ``publish_package`` (content contract, title,
    hashtags, R1/R2-derived copy) while stripping the obsolete storyboard
    frames, and resets every dynamic visual slot so ``content_atomizer`` and
    its successors rebuild the carousel from the canonical content atoms.
    """

    package = dict(values.get("publish_package") or {})
    package.pop("storyboards", None)
    return {
        EDITORIAL_WORKFLOW_VERSION_KEY: DYNAMIC_VISUAL_V3,
        LEGACY_EDITORIAL_CHECKPOINT_KEY: False,
        "publish_package": package,
        "content_atom_set": None,
        "visual_direction_plan": None,
        "asset_manifest": None,
        "carousel_design_plan": None,
        "design_plan_qa_result": None,
        "render_manifest": None,
        "render_qa_result": None,
        "visual_critique": None,
        "review_status": None,
        "review_route": None,
    }


def _has_retired_visual_artifacts(
    values: Mapping[str, Any],
    package: Mapping[str, Any],
) -> bool:
    """Detect any of the v1/v2 visual triggers that require re-derivation."""

    for key in _RETIRED_VISUAL_STATE_KEYS:
        if values.get(key) is not None:
            return True
    storyboards = package.get("storyboards")
    if isinstance(storyboards, list) and storyboards:
        return True
    rendered = package.get("rendered_image_paths")
    if isinstance(rendered, list) and rendered:
        return True
    if values.get(LEGACY_EDITORIAL_CHECKPOINT_KEY) is True:
        return True
    return False


def hydrate_legacy_editorial_state(
    values: Mapping[str, Any],
    *,
    checkpoint_nodes: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Hydrate a pre-v3 checkpoint into the ``llm_scene_v3`` re-entry state.

    Returns the migration updates when a legacy/v2 checkpoint carries retired
    visual artifacts; returns ``{}`` for an already-v3 or clean checkpoint;
    raises ``ValueError`` for unknown future versions (fail-closed).
    """

    package = values.get("publish_package")
    if not isinstance(package, Mapping):
        return {}

    version = values.get(EDITORIAL_WORKFLOW_VERSION_KEY)

    # Already on the v3 production path: never re-migrate, never downgrade.
    if version == DYNAMIC_VISUAL_V3:
        if values.get(LEGACY_EDITORIAL_CHECKPOINT_KEY) is True:
            return {LEGACY_EDITORIAL_CHECKPOINT_KEY: False}
        return {}

    # Unknown future versions fail closed.
    if version not in {None, LEGACY_EDITORIAL_V1, MODERN_EDITORIAL_V2}:
        raise ValueError(f"unsupported editorial workflow version: {version}")

    if not _has_retired_visual_artifacts(values, package):
        return {}

    return dynamic_visual_transition_updates(values)


def persisted_checkpoint_nodes(
    graph: Any,
    config: Mapping[str, Any],
    visible_nodes: tuple[str, ...],
) -> tuple[str, ...]:
    """Recover one allowlisted retired successor hidden from visible state.

    LangGraph omits a persisted branch from ``StateSnapshot.next`` when that
    node no longer exists in the compiled graph; the raw checkpoint retains the
    ``branch:to:<node>`` channel this adapter reads. Recovery is gated so a
    non-empty visible ``next`` is returned untouched and only a uniquely
    recovered retired successor is honored.
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


def migration_reentry_predecessor(
    updates: Mapping[str, Any],
    checkpoint_nodes: tuple[str, ...],
) -> str | None:
    """Return the graph node whose successor is the safe v3 re-entry seam.

    When the migration stamped version ``llm_scene_v3`` (i.e. a legacy/v2
    checkpoint was re-derived), execution re-enters after ``assembler`` so
    ``content_atomizer`` runs first. Clean or already-v3 checkpoints return
    ``None`` so they resume from their persisted position untouched.
    """

    if updates.get(EDITORIAL_WORKFLOW_VERSION_KEY) == DYNAMIC_VISUAL_V3:
        return DYNAMIC_REENTRY_PREDECESSOR
    return None
