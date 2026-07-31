"""Deterministic design-plan QA node (Task 9).

Reads the same top-level state keys the rest of the visual-production pipeline
writes (``carousel_design_plan``, ``visual_direction_plan``,
``content_atom_set``, ``asset_manifest``), runs the pure
:func:`evaluate_design_plan` gate, and writes ``design_plan_qa_result`` into
state plus the ``current_node`` marker. The retry budget is enforced here so
that three consecutive failing QA results raise
:class:`VisualProductionInterrupted` (never force-pass). Graph wiring
(``route_after_design_plan_qa`` into the reviser / generic renderer loop) is
Task 14.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from src.schemas.assets import AssetManifest
from src.schemas.content_atoms import ContentAtomSet
from src.schemas.design_qa import DesignPlanQAResult
from src.schemas.scene_graph import CarouselDesignPlan
from src.schemas.visual_director import VisualDirectionPlan
from src.schemas.visual_style import FamilyStyleProfile, TemplateFamily
from src.visual_design.model_retry import VisualProductionInterrupted
from src.visual_design.plan_qa import DesignPlanQAInputs, evaluate_design_plan
from src.visual_design.style_registry import load_style_registry

# The reviser loop may consume at most this many failed QA results; on the
# third failure the QA stage interrupts with checkpointable details.
MAX_QA_FAILURES = 3

_DESIGN_PLAN_KEY = "carousel_design_plan"
_DIRECTION_KEY = "visual_direction_plan"
_ATOM_SET_KEY = "content_atom_set"
_MANIFEST_KEY = "asset_manifest"
_FAILURES_KEY = "design_plan_qa_failures"
_RESULT_KEY = "design_plan_qa_result"


def _design_plan(state: Mapping[str, Any]) -> CarouselDesignPlan:
    raw = state.get(_DESIGN_PLAN_KEY)
    if raw is None:
        raise ValueError("design_plan_qa requires carousel_design_plan")
    if isinstance(raw, CarouselDesignPlan):
        return raw
    return CarouselDesignPlan.model_validate(raw)


def _direction_plan(state: Mapping[str, Any]) -> VisualDirectionPlan:
    raw = state.get(_DIRECTION_KEY)
    if raw is None:
        raise ValueError("design_plan_qa requires visual_direction_plan")
    if isinstance(raw, VisualDirectionPlan):
        return raw
    return VisualDirectionPlan.model_validate(raw)


def _atom_set(state: Mapping[str, Any]) -> ContentAtomSet:
    raw = state.get(_ATOM_SET_KEY)
    if raw is None:
        raise ValueError("design_plan_qa requires content_atom_set")
    if isinstance(raw, ContentAtomSet):
        return raw
    return ContentAtomSet.model_validate(raw)


def _manifest(state: Mapping[str, Any]) -> AssetManifest:
    raw = state.get(_MANIFEST_KEY)
    if raw is None:
        raise ValueError("design_plan_qa requires asset_manifest")
    if isinstance(raw, AssetManifest):
        return raw
    return AssetManifest.model_validate(raw)


def _family_profile(
    family: TemplateFamily,
    style_profiles: Mapping[TemplateFamily, FamilyStyleProfile] | None,
) -> FamilyStyleProfile:
    registry = load_style_registry() if style_profiles is None else style_profiles
    profile = registry.get(family)
    if profile is None:
        raise ValueError(f"design_plan_qa requires style profile for family {family}")
    return profile


def _issue_summaries(result: DesignPlanQAResult) -> list[str]:
    return [
        f"{issue.rule} [{issue.page_id or issue.element_id or issue.atom_id}]: {issue.message}"
        for issue in result.issues
    ]


def design_plan_qa_node(
    state: Mapping[str, Any],
    *,
    style_profiles: Mapping[TemplateFamily, FamilyStyleProfile] | None = None,
) -> dict[str, object]:
    """Run the deterministic design-plan gate and thread the retry budget.

    On a passing plan the failure counter resets to 0. On a failing plan the
    counter increments; when it reaches ``MAX_QA_FAILURES`` (3) the node raises
    ``VisualProductionInterrupted(stage="design_plan_qa")`` with the issue
    details so the run can be checkpointed and resumed. The gate never
    force-passes.
    """
    design_plan = _design_plan(state)
    direction = _direction_plan(state)
    atom_set = _atom_set(state)
    manifest = _manifest(state)
    family_profile = _family_profile(direction.template_family, style_profiles)

    inputs = DesignPlanQAInputs(
        atoms=atom_set,
        direction=direction,
        assets=manifest,
        design_plan=design_plan,
        style=family_profile,
    )
    result = evaluate_design_plan(inputs)

    if result.passed:
        return {
            _RESULT_KEY: result,
            _FAILURES_KEY: 0,
            "current_node": "DESIGN_PLAN_QA",
        }

    prior_failures = int(state.get(_FAILURES_KEY, 0))
    failures = prior_failures + 1
    if failures >= MAX_QA_FAILURES:
        raise VisualProductionInterrupted(
            stage="design_plan_qa",
            errors=_issue_summaries(result),
            raw_outputs=(),
        )

    return {
        _RESULT_KEY: result,
        _FAILURES_KEY: failures,
        "current_node": "DESIGN_PLAN_QA",
    }


def route_after_design_plan_qa(
    state: Mapping[str, Any],
) -> Literal["generic_scene_renderer", "design_reviser"]:
    """Route to the reviser on failure, or to the generic renderer on pass."""
    result = state[_RESULT_KEY]
    if isinstance(result, DesignPlanQAResult):
        passed = result.passed
    else:
        passed = bool(result.get("passed"))
    return "generic_scene_renderer" if passed else "design_reviser"


__all__ = [
    "MAX_QA_FAILURES",
    "design_plan_qa_node",
    "route_after_design_plan_qa",
]
