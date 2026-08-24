"""v4 render node: one exact Q0-Q2 aggregate into immutable render evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.rendering.scene.v4_adapter import V4RenderResult, render_v4_revision


_CURRENT_NODE = "V4_RENDER"
_NEXT_ROUTE = "render_qa"


def _value(state: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in state and state[name] is not None:
            return state[name]
    return None


def render_node(
    state: Mapping[str, Any],
    *,
    artifact_paths=None,
    render_page_fn=None,
    contact_sheet_fn=None,
    playwright_factory=None,
) -> dict[str, Any]:
    """Render only a fresh, passed v4 design-plan aggregate.

    The adapter owns all source and identity revalidation.  This node only
    normalizes the state aliases used by the preceding v4 nodes and returns a
    route suitable for the graph's later Q3 consumer.
    """

    if not isinstance(state, Mapping):
        raise TypeError("v4 render node requires a state mapping")
    plan = _value(state, "carousel_design_plan_v4", "carousel_design_plan")
    aggregate = _value(state, "design_plan_qa_result_v4", "design_plan_qa_result")
    atom_set = _value(state, "content_atom_set", "atom_set")
    semantic = _value(state, "semantic_content_model", "semantic_model")
    page_set = _value(state, "page_brief_set", "page_briefs")
    direction = _value(state, "visual_direction_plan")
    manifest = _value(state, "asset_manifest", "assets")
    lock = _value(state, "content_lock")
    family = _value(state, "family_tokens")
    paths = artifact_paths if artifact_paths is not None else _value(
        state,
        "artifact_paths",
        "asset_transaction_paths",
    )
    missing = tuple(
        name
        for name, value in (
            ("carousel_design_plan", plan),
            ("design_plan_qa_result", aggregate),
            ("content_atom_set", atom_set),
            ("content_lock", lock),
            ("semantic_content_model", semantic),
            ("page_brief_set", page_set),
            ("visual_direction_plan", direction),
            ("asset_manifest", manifest),
            ("family_tokens", family),
            ("artifact_paths", paths),
        )
        if value is None
    )
    if missing:
        raise ValueError(
            "v4 render node is missing canonical state keys: " + ", ".join(missing)
        )
    result: V4RenderResult = render_v4_revision(
        design_plan=plan,
        design_plan_qa_result=aggregate,
        content_atom_set=atom_set,
        content_lock=lock,
        semantic_content_model=semantic,
        page_brief_set=page_set,
        visual_direction_plan=direction,
        asset_manifest=manifest,
        family_tokens=family,
        artifact_paths=paths,
        render_page_fn=render_page_fn,
        contact_sheet_fn=contact_sheet_fn,
        playwright_factory=playwright_factory,
    )
    # Task 13A only publishes immutable browser observations.  Q3 owns every
    # policy decision and must see the manifest even when those observations
    # later prove actionable.  Structural failures are raised by the adapter
    # above and therefore fail closed before this route is returned.
    route = _NEXT_ROUTE
    return {
        "render_manifest_v4": result.manifest,
        "render_manifest": result.manifest,
        "artifact_paths": result.artifact_paths,
        "route": route,
        "visual_route": route,
        "render_route": route,
        "current_node": _CURRENT_NODE,
    }


v4_render_node = render_node


__all__ = ["render_node", "v4_render_node"]
