"""Deterministic render-QA LangGraph node (Task 12).

Reads the Task 7-11 top-level state contract (``carousel_design_plan``,
``visual_direction_plan``, ``content_atom_set``, ``asset_manifest``,
``design_plan_qa_result``, ``render_manifest``), assembles
:class:`RenderQAInputs`, runs the pure :func:`evaluate_render` gate, and writes
``render_qa_result`` plus the ``current_node`` marker and the
``render_qa_failures`` retry counter into state.

The 3-strike retry budget is enforced here so that three consecutive failing
render-QA results raise :class:`VisualProductionInterrupted` (never
force-pass). Graph wiring (the cutover so the route feeds the visual critic /
design reviser loop) is Task 14; this module MUST keep exporting
``render_qa_node`` and ``route_after_render_qa`` because ``src/graph.py``
imports both.

A single legacy helper (``_expected_probe_text``) is retained at the bottom for
the old editorial bespoke probe-attestation tests; it travels with the
obsolete editorial path and will be removed in the later obsolete-path
deletion task.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from src.nodes.node_p_carousel_qa import _get_value
from src.rendering.editorial.primitives import cover_title_text
from src.schemas.assets import AssetManifest
from src.schemas.content_atoms import ContentAtomSet
from src.schemas.design_qa import DesignPlanQAResult
from src.schemas.render_manifest import RenderManifest
from src.schemas.render_qa import RenderQAResult
from src.schemas.scene_graph import CarouselDesignPlan
from src.schemas.visual_director import VisualDirectionPlan
from src.visual_design.model_retry import VisualProductionInterrupted
from src.visual_design.render_qa import (
    MAX_RENDER_QA_FAILURES,
    RenderQAInputs,
    evaluate_render,
    render_qa_exhausted,
)

_DESIGN_PLAN_KEY = "carousel_design_plan"
_DIRECTION_KEY = "visual_direction_plan"
_ATOM_SET_KEY = "content_atom_set"
_MANIFEST_KEY = "asset_manifest"
_QA_KEY = "design_plan_qa_result"
_RENDER_MANIFEST_KEY = "render_manifest"
_FAILURES_KEY = "render_qa_failures"
_RESULT_KEY = "render_qa_result"


def _coerce(
    state: Mapping[str, Any],
    key: str,
    model_type: type,
    label: str,
):
    raw = state.get(key)
    if raw is None:
        raise ValueError(f"render_qa requires {label}")
    if isinstance(raw, model_type):
        return raw
    return model_type.model_validate(raw)


def _issue_summaries(result: RenderQAResult) -> list[str]:
    return [
        f"{issue.rule} [{issue.page_id or issue.element_id or issue.atom_id}]: {issue.message}"
        for issue in result.issues
    ]


def render_qa_node(state: Mapping[str, Any]) -> dict[str, object]:
    """Run the deterministic render gate and thread the retry budget.

    On a passing manifest the failure counter resets to 0. On a failing
    manifest the counter increments; when it reaches ``MAX_RENDER_QA_FAILURES``
    (3) the node raises ``VisualProductionInterrupted(stage="render_qa")`` with
    the issue details so the run can be checkpointed and resumed. The gate
    never force-passes.
    """
    design_plan = _coerce(state, _DESIGN_PLAN_KEY, CarouselDesignPlan, "carousel_design_plan")
    direction = _coerce(state, _DIRECTION_KEY, VisualDirectionPlan, "visual_direction_plan")
    atom_set = _coerce(state, _ATOM_SET_KEY, ContentAtomSet, "content_atom_set")
    manifest = _coerce(state, _MANIFEST_KEY, AssetManifest, "asset_manifest")
    qa_result = _coerce(state, _QA_KEY, DesignPlanQAResult, "design_plan_qa_result")
    render_manifest = _coerce(
        state, _RENDER_MANIFEST_KEY, RenderManifest, "render_manifest"
    )

    inputs = RenderQAInputs(
        atoms=atom_set,
        direction=direction,
        assets=manifest,
        design_plan=design_plan,
        design_plan_qa=qa_result,
        render_manifest=render_manifest,
    )
    result = evaluate_render(inputs)

    if result.passed:
        return {
            _RESULT_KEY: result,
            _FAILURES_KEY: 0,
            "current_node": "RENDER_QA",
        }

    prior_failures = int(state.get(_FAILURES_KEY, 0))
    failures = prior_failures + 1
    if render_qa_exhausted(prior_failures):
        raise VisualProductionInterrupted(
            stage="render_qa",
            errors=_issue_summaries(result),
            raw_outputs=(),
        )

    return {
        _RESULT_KEY: result,
        _FAILURES_KEY: failures,
        "current_node": "RENDER_QA",
    }


def route_after_render_qa(
    state: Mapping[str, Any],
) -> Literal["visual_critic", "design_reviser"]:
    """Route pass -> ``visual_critic``, fail -> ``design_reviser``.

    Never returns the old ``human_review`` / ``r1_reflector`` literals; the
    graph wiring that consumed those is updated in Task 14.
    """
    raw = state.get(_RESULT_KEY)
    if isinstance(raw, RenderQAResult):
        passed = raw.passed
    elif isinstance(raw, Mapping):
        passed = bool(raw.get("passed"))
    else:
        raise ValueError("route_after_render_qa requires render_qa_result")
    return "visual_critic" if passed else "design_reviser"


__all__ = [
    "MAX_RENDER_QA_FAILURES",
    "render_qa_node",
    "route_after_render_qa",
]


# ---------------------------------------------------------------------------
# Legacy compatibility — remove with the obsolete editorial render path.
# The old editorial bespoke probe-attestation tests
# (tests/rendering/editorial/test_*_bespoke.py) import ``_expected_probe_text``
# to assert the renderer's expected-copy sequence matches the QA's probe
# sequence. It has no role in the new visual-production path and is retained
# only until the obsolete editorial path is deleted in a later task.
# ---------------------------------------------------------------------------


def _as_list(payload: Any, key: str) -> list[Any]:
    value = _get_value(payload, key, [])
    return list(value) if isinstance(value, (list, tuple)) else []


def _expected_probe_text(frame: Any) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    kicker = _get_value(frame, "kicker")
    if kicker:
        values.append(("kicker", str(kicker)))
    hero_numeral = _get_value(frame, "hero_numeral")
    if hero_numeral:
        values.append(("hero_numeral", str(hero_numeral)))
    headline = _get_value(frame, "headline")
    if headline:
        values.append(
            (
                "headline",
                cover_title_text(
                    str(headline), str(hero_numeral) if hero_numeral else None
                ),
            )
        )
    for block_index, block in enumerate(_as_list(frame, "content_blocks")):
        heading = _get_value(block, "heading")
        body = _get_value(block, "body")
        if heading:
            values.append((f"content_blocks[{block_index}].heading", str(heading)))
        if body:
            values.append((f"content_blocks[{block_index}].body", str(body)))
        values.extend(
            (f"content_blocks[{block_index}].items[{item_index}]", str(item))
            for item_index, item in enumerate(_as_list(block, "items"))
        )
    values.extend(
        (f"emphasis[{index}]", str(value))
        for index, value in enumerate(_as_list(frame, "emphasis"))
    )
    persona = _get_value(frame, "persona")
    if persona:
        values.append(("persona", str(persona)))
    footer = _get_value(frame, "footer")
    if footer:
        values.append(("footer", str(footer)))
    return values
