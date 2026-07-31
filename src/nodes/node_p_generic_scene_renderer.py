"""Generic scene renderer LangGraph node (Task 11).

Reads the Task 7-10 top-level state contract (``carousel_design_plan``,
``visual_direction_plan``, ``content_atom_set``, ``asset_manifest``,
``design_plan_qa_result`` and ``run_output_dir``) and renders a QA-approved
plan into a hash-bound :class:`RenderManifest`. The node refuses to render
unless ``design_plan_qa_result.passed is True`` so a failing plan can never
reach Chromium. Graph wiring (the cutover from the editorial renderer) is a
later task.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

from src.rendering.scene.renderer import SceneRenderError, render_carousel_scenes
from src.schemas.assets import AssetManifest
from src.schemas.content_atoms import ContentAtomSet, ContentFragment
from src.schemas.design_qa import DesignPlanQAResult
from src.schemas.scene_graph import CarouselDesignPlan
from src.schemas.visual_director import VisualDirectionPlan
from src.schemas.visual_style import FamilyStyleProfile, TemplateFamily
from src.visual_design.style_registry import load_style_registry

_DESIGN_PLAN_KEY = "carousel_design_plan"
_DIRECTION_KEY = "visual_direction_plan"
_ATOM_SET_KEY = "content_atom_set"
_MANIFEST_KEY = "asset_manifest"
_QA_KEY = "design_plan_qa_result"
_OUTPUT_DIR_KEY = "run_output_dir"


def _design_plan(state: Mapping[str, Any]) -> CarouselDesignPlan:
    raw = state.get(_DESIGN_PLAN_KEY)
    if raw is None:
        raise ValueError("generic_scene_renderer requires carousel_design_plan")
    if isinstance(raw, CarouselDesignPlan):
        return raw
    return CarouselDesignPlan.model_validate(raw)


def _direction_plan(state: Mapping[str, Any]) -> VisualDirectionPlan:
    raw = state.get(_DIRECTION_KEY)
    if raw is None:
        raise ValueError("generic_scene_renderer requires visual_direction_plan")
    if isinstance(raw, VisualDirectionPlan):
        return raw
    return VisualDirectionPlan.model_validate(raw)


def _atom_set(state: Mapping[str, Any]) -> ContentAtomSet:
    raw = state.get(_ATOM_SET_KEY)
    if raw is None:
        raise ValueError("generic_scene_renderer requires content_atom_set")
    if isinstance(raw, ContentAtomSet):
        return raw
    return ContentAtomSet.model_validate(raw)


def _manifest(state: Mapping[str, Any]) -> AssetManifest:
    raw = state.get(_MANIFEST_KEY)
    if raw is None:
        raise ValueError("generic_scene_renderer requires asset_manifest")
    if isinstance(raw, AssetManifest):
        return raw
    return AssetManifest.model_validate(raw)


def _qa_result(state: Mapping[str, Any]) -> DesignPlanQAResult:
    raw = state.get(_QA_KEY)
    if raw is None:
        raise SceneRenderError(
            "generic_scene_renderer requires a passing design plan QA result; "
            "none is present in state"
        )
    if isinstance(raw, DesignPlanQAResult):
        return raw
    return DesignPlanQAResult.model_validate(raw)


def _output_dir(state: Mapping[str, Any]) -> str:
    raw = state.get(_OUTPUT_DIR_KEY)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(
            "generic_scene_renderer requires run_output_dir in state"
        )
    return raw


def _family_profile(
    family: TemplateFamily,
    style_profiles: Mapping[TemplateFamily, FamilyStyleProfile] | None,
) -> FamilyStyleProfile:
    registry = load_style_registry() if style_profiles is None else style_profiles
    profile = registry.get(family)
    if profile is None:
        raise ValueError(
            f"generic_scene_renderer requires style profile for family {family}"
        )
    return profile


def generic_scene_renderer_node(
    state: Mapping[str, Any],
    *,
    render_fn: Callable | None = None,
    style_profiles: Mapping[TemplateFamily, FamilyStyleProfile] | None = None,
) -> dict[str, object]:
    """Render a QA-approved design plan into a :class:`RenderManifest`.

    Accepts only ``design_plan_qa_result.passed is True``; otherwise raises
    :class:`SceneRenderError` without invoking the renderer. ``render_fn`` is
    an injection seam (defaults to :func:`render_carousel_scenes`) so the node
    can be exercised in tests without launching Chromium.
    """
    design_plan = _design_plan(state)
    direction = _direction_plan(state)
    atom_set = _atom_set(state)
    manifest = _manifest(state)
    qa_result = _qa_result(state)
    output_dir = _output_dir(state)

    # Gate before any rendering work: the design plan QA must have passed.
    if not qa_result.passed:
        raise SceneRenderError(
            "generic_scene_renderer requires design plan QA to have passed "
            "before rendering"
        )

    fragments: dict[str, ContentFragment] = {
        fragment.fragment_id: fragment
        for fragment in direction.content_fragments
    }
    assets = {item.asset_id: item for item in manifest.items}
    style = _family_profile(direction.template_family, style_profiles)

    renderer = render_fn or render_carousel_scenes
    manifest_result = renderer(
        design_plan,
        fragments=fragments,
        assets=assets,
        style=style,
        design_plan_qa_result=qa_result,
        output_dir=output_dir,
    )

    return {
        "render_manifest": manifest_result,
        "current_node": "GENERIC_SCENE_RENDERER",
    }


__all__ = ["generic_scene_renderer_node"]
