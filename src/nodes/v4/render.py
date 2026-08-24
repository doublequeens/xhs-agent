"""v4 render node: one exact Q0-Q2 aggregate into immutable render evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.rendering.scene.v4_adapter import V4RenderResult, render_v4_revision
from src.schemas.assets import AssetManifest
from src.schemas.content_atoms import canonical_sha256 as canonical_sha256_v3
from src.schemas.content_lock import ContentLock
from src.schemas.v4.content import ContentAtomSetV4
from src.schemas.v4.direction import PageBriefSetV4, VisualDirectionPlanV4
from src.schemas.v4.layout import CarouselDesignPlanV4, FamilyTokensV4
from src.schemas.v4.quality import DesignPlanQAResultV4
from src.schemas.v4.rendering import RenderManifestV4, RenderQAResultV4
from src.schemas.v4.semantic import SemanticContentModelV4
from src.visual_design.v4.render_qa import evaluate_v4_render
from src.visual_design.v4.tokens import get_family_tokens


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


def render_qa_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """Independently evaluate the published v4 manifest and route hard-gated."""

    if not isinstance(state, Mapping):
        raise TypeError("v4 render QA node requires a state mapping")
    values = {
        "render_manifest": _value(state, "render_manifest_v4", "render_manifest"),
        "design_plan": _value(
            state,
            "carousel_design_plan_v4",
            "carousel_design_plan",
        ),
        "design_plan_qa_result": _value(
            state,
            "design_plan_qa_result_v4",
            "design_plan_qa_result",
        ),
        "content_atom_set": _value(state, "content_atom_set", "atom_set"),
        "content_lock": _value(state, "content_lock"),
        "semantic_content_model": _value(
            state,
            "semantic_content_model",
            "semantic_model",
        ),
        "page_brief_set": _value(state, "page_brief_set", "page_briefs"),
        "visual_direction_plan": _value(state, "visual_direction_plan"),
        "asset_manifest": _value(state, "asset_manifest", "assets"),
        "family_tokens": _value(state, "family_tokens"),
        "artifact_paths": _value(
            state,
            "artifact_paths",
            "asset_transaction_paths",
        ),
    }
    missing = tuple(name for name, value in values.items() if value is None)
    if missing:
        raise ValueError(
            "v4 render QA node is missing canonical state keys: "
            + ", ".join(missing)
        )
    result = evaluate_v4_render(**values)
    route = "visual_critic" if result.passed else "design_reviser"
    return {
        "render_qa_result_v4": result,
        "render_qa_result": result,
        "route": route,
        "visual_route": route,
        "render_route": route,
        "current_node": "V4_RENDER_QA",
    }


def route_after_render_qa(state: Mapping[str, Any]) -> str:
    """Route only an intact, source-bound result from the Q3 boundary.

    This helper deliberately does not evaluate Q3.  It verifies the exact
    result model and compares every persisted binding with the canonical
    source objects still present in state before selecting one hard-gate
    route.  Partial state or duck-typed/spoofed results fail closed.
    """

    if not isinstance(state, Mapping):
        raise TypeError("v4 render QA route requires a state mapping")
    result = _value(state, "render_qa_result_v4", "render_qa_result")
    if type(result) is not RenderQAResultV4:
        raise ValueError("v4 render QA route requires an exact Q3 result")
    try:
        result.validate_integrity()
    except Exception:
        raise ValueError("v4 render QA route received an invalid Q3 result") from None

    sources = {
        "render_manifest": _value(state, "render_manifest_v4", "render_manifest"),
        "design_plan": _value(
            state,
            "carousel_design_plan_v4",
            "carousel_design_plan",
            "design_plan",
        ),
        "design_plan_qa_result": _value(
            state,
            "design_plan_qa_result_v4",
            "design_plan_qa_result",
            "design_plan_qa",
        ),
        "content_atom_set": _value(state, "content_atom_set", "atom_set"),
        "content_lock": _value(state, "content_lock"),
        "semantic_content_model": _value(
            state,
            "semantic_content_model",
            "semantic_model",
        ),
        "page_brief_set": _value(state, "page_brief_set", "page_briefs"),
        "visual_direction_plan": _value(state, "visual_direction_plan"),
        "asset_manifest": _value(state, "asset_manifest", "assets"),
        "family_tokens": _value(state, "family_tokens"),
    }
    exact_types = {
        "render_manifest": RenderManifestV4,
        "design_plan": CarouselDesignPlanV4,
        "design_plan_qa_result": DesignPlanQAResultV4,
        "content_atom_set": ContentAtomSetV4,
        "content_lock": ContentLock,
        "semantic_content_model": SemanticContentModelV4,
        "page_brief_set": PageBriefSetV4,
        "visual_direction_plan": VisualDirectionPlanV4,
        "asset_manifest": AssetManifest,
    }
    if any(
        value is None or type(value) is not expected_type
        for name, expected_type in exact_types.items()
        for value in (sources[name],)
    ):
        raise ValueError("v4 render QA route requires canonical source bindings")
    family = sources["family_tokens"]
    try:
        if isinstance(family, str):
            family_hash = get_family_tokens(family).canonical_sha256
        elif type(family) is FamilyTokensV4:
            family_hash = family.canonical_sha256
        else:
            raise ValueError
        expected_bindings = {
            "render_manifest_sha256": sources["render_manifest"].canonical_sha256,
            "design_plan_sha256": sources["design_plan"].canonical_sha256,
            "design_plan_qa_sha256": sources["design_plan_qa_result"].canonical_sha256,
            "content_atom_set_sha256": sources["content_atom_set"].canonical_sha256,
            "content_lock_sha256": sources["content_lock"].canonical_sha256,
            "semantic_content_model_sha256": sources["semantic_content_model"].canonical_sha256,
            "narrative_sha256": sources["visual_direction_plan"].narrative_sha256,
            "page_brief_set_sha256": sources["page_brief_set"].canonical_sha256,
            "visual_direction_plan_sha256": sources["visual_direction_plan"].canonical_sha256,
            "asset_manifest_sha256": canonical_sha256_v3(sources["asset_manifest"]),
            "family_tokens_sha256": family_hash,
        }
    except Exception:
        raise ValueError("v4 render QA route requires canonical source bindings") from None
    if any(
        getattr(result, name) != expected
        for name, expected in expected_bindings.items()
    ):
        raise ValueError("v4 render QA route received stale source bindings")
    plan = sources["design_plan"]
    manifest = sources["render_manifest"]
    if (
        result.artifact_identity != manifest.artifact_identity
        or result.artifact_identity.run_id != plan.run_id
        or result.artifact_identity.candidate_id != plan.candidate_id
        or result.artifact_identity.revision_id != f"revision-{plan.revision}"
    ):
        raise ValueError("v4 render QA route received mixed artifact identity")
    return "visual_critic" if result.passed else "design_reviser"


__all__ = [
    "render_node",
    "v4_render_node",
    "render_qa_node",
    "route_after_render_qa",
]
