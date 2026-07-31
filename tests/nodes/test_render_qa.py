"""Tests for the deterministic render-QA LangGraph node (Task 12).

The node assembles ``RenderQAInputs`` from the Task 7-11 top-level state keys,
calls :func:`evaluate_render`, threads the 3-strike retry budget, and routes
pass -> ``visual_critic`` / fail -> ``design_reviser``. These tests exercise the
node against production-shaped top-level state with synthetic manifests (no
Chromium); the pure-rule coverage lives in ``tests/visual_design/test_render_qa.py``.
"""

from __future__ import annotations

import pytest

from src.nodes.node_p_render_qa import (
    MAX_RENDER_QA_FAILURES,
    render_qa_node,
    route_after_render_qa,
)
from src.schemas.render_qa import RenderQAResult
from src.visual_design.model_retry import VisualProductionInterrupted
from tests.visual_design.test_render_qa import _inputs


def _production_state(tmp_path, *, include_image: bool = False, failures: int = 0) -> dict:
    """Build the top-level state keys the Task 7-11 contract produces."""
    inputs = _inputs(tmp_path, include_image=include_image)
    return {
        "carousel_design_plan": inputs.design_plan,
        "visual_direction_plan": inputs.direction,
        "content_atom_set": inputs.atoms,
        "asset_manifest": inputs.assets,
        "design_plan_qa_result": inputs.design_plan_qa,
        "render_manifest": inputs.render_manifest,
        "render_qa_failures": failures,
    }


def test_node_emits_passing_result_into_state(tmp_path):
    state = _production_state(tmp_path)

    result = render_qa_node(state)

    assert result["current_node"] == "RENDER_QA"
    qa = result["render_qa_result"]
    assert isinstance(qa, RenderQAResult)
    assert qa.passed is True
    assert qa.issues == ()
    # A passing result resets the retry budget to 0.
    assert result["render_qa_failures"] == 0


def test_node_emits_failing_result_into_state_and_increments_budget(tmp_path):
    state = _production_state(tmp_path)
    # Corrupt one page file so evaluate_render produces a real failure.
    from pathlib import Path

    Path(state["render_manifest"].pages[0].path).unlink()

    result = render_qa_node(state)

    qa = result["render_qa_result"]
    assert qa.passed is False
    assert qa.issues
    # First failure -> budget increments from 0 to 1, no interrupt.
    assert result["render_qa_failures"] == 1
    assert result["current_node"] == "RENDER_QA"


def test_route_returns_visual_critic_on_pass(tmp_path):
    state = _production_state(tmp_path)
    state = {**state, **render_qa_node(state)}

    assert route_after_render_qa(state) == "visual_critic"


def test_route_returns_design_reviser_on_fail(tmp_path):
    from pathlib import Path

    state = _production_state(tmp_path)
    Path(state["render_manifest"].pages[0].path).unlink()
    state = {**state, **render_qa_node(state)}

    assert route_after_render_qa(state) == "design_reviser"


def test_route_never_returns_human_review_or_r1(tmp_path):
    from pathlib import Path

    state = _production_state(tmp_path)
    Path(state["render_manifest"].contact_sheet_path).unlink()
    state = {**state, **render_qa_node(state)}

    assert route_after_render_qa(state) not in {"human_review", "r1_reflector"}


def test_third_failure_raises_interrupt_with_checkpointable_details(tmp_path):
    from pathlib import Path

    state = _production_state(tmp_path, failures=MAX_RENDER_QA_FAILURES - 1)
    # Make this attempt fail deterministically.
    Path(state["render_manifest"].pages[0].path).unlink()

    with pytest.raises(VisualProductionInterrupted) as exc_info:
        render_qa_node(state)

    interrupted = exc_info.value
    assert interrupted.stage == "render_qa"
    assert interrupted.resumable is True
    assert len(interrupted.errors) >= 1
    # raw_outputs is a tuple (checkpoint-safe) per the brief.
    assert isinstance(interrupted.raw_outputs, tuple)
    payload = interrupted.checkpoint_payload()
    assert payload["stage"] == "render_qa"
    assert payload["resumable"] is True
    assert isinstance(payload["errors"], list) and payload["errors"]


def test_second_failure_does_not_interrupt(tmp_path):
    from pathlib import Path

    state = _production_state(tmp_path, failures=MAX_RENDER_QA_FAILURES - 2)
    Path(state["render_manifest"].pages[0].path).unlink()

    # The second failure must NOT interrupt; it returns the failing result.
    result = render_qa_node(state)
    assert result["render_qa_result"].passed is False
    assert result["render_qa_failures"] == MAX_RENDER_QA_FAILURES - 1


def test_node_reads_carousel_design_plan_from_top_level_state(tmp_path):
    """Regression: Task 8 had a bug where the design plan was read from a nested
    fabricated key. The node MUST read ``carousel_design_plan`` from the
    top-level state contract."""
    inputs = _inputs(tmp_path)
    state = {
        "carousel_design_plan": inputs.design_plan,
        "visual_direction_plan": inputs.direction,
        "content_atom_set": inputs.atoms,
        "asset_manifest": inputs.assets,
        "design_plan_qa_result": inputs.design_plan_qa,
        "render_manifest": inputs.render_manifest,
    }

    result = render_qa_node(state)

    assert result["render_qa_result"].passed is True
