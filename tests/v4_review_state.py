"""Shared v4 post-review terminal-state fixtures for Final Guard and publishers.

Builds one real, reviewed terminal state: the exact Task 16A workspace, the
Task 16B append-only decision, and the state patch an APPROVE/AESTHETIC_OVERRIDE
action leaves for the Final Guard / exporters to consume.
"""

from __future__ import annotations

from pathlib import Path

from src.review.v4_decisions import submit_human_review_intent
from src.review.v4_workspace import build_review_workspace
from src.schemas.v4.review import HumanReviewIntentV4

from tests.review.test_v4_decisions import _failed_inputs
from tests.review.test_v4_workspace import _inputs

_INPUT_CONTRACT_FIELDS = (
    "content_lock",
    "content_atom_set",
    "semantic_content_model",
    "carousel_narrative",
    "page_brief_set",
    "visual_direction_plan",
    "asset_manifest",
    "asset_resolution_result",
)


def reviewed_state(
    tmp_path: Path,
    *,
    with_asset: bool = False,
    action: str = "APPROVE",
    failed_q4: bool = False,
):
    """Return ``(state, inputs, workspace, result)`` for one terminal action.

    ``_failed_inputs`` builds its own ``run-a`` world, so the state ``run_id``
    always mirrors the artifact identity it actually carries.
    """

    if failed_q4:
        inputs = _failed_inputs(tmp_path, with_asset=with_asset)
    else:
        inputs = _inputs(tmp_path, with_asset=with_asset)
    run_id = inputs.artifact_paths.identity.run_id
    workspace = build_review_workspace(inputs)
    package = inputs.content_lock.model_dump(mode="python")
    intent = {
        "APPROVE": HumanReviewIntentV4(action="APPROVE"),
        "AESTHETIC_OVERRIDE": HumanReviewIntentV4(
            action="AESTHETIC_OVERRIDE", rationale="明确接受当前审美问题并继续发布。"
        ),
    }[action]
    result = submit_human_review_intent(
        workspace,
        inputs,
        intent,
        clock=lambda: "2026-08-27T00:00:00Z",
        decision_id_factory=lambda: f"decision-{action.lower()}",
        current_package=package if action == "VISIBLE_COPY_EDIT" else None,
    )
    state: dict = {
        "run_id": run_id,
        "artifact_paths": inputs.artifact_paths,
        "publish_package": package,
        "carousel_design_plan_v4": inputs.carousel_design_plan,
        "design_plan_qa_result_v4": inputs.design_plan_qa,
        "render_manifest_v4": inputs.render_manifest,
        "render_qa_result_v4": inputs.render_qa,
        "visual_critique_v4": inputs.visual_critique,
        "asset_resolution_result_v4": inputs.asset_resolution_result,
        "previous_review_workspace_v4": inputs.previous_review_workspace,
        "review_workspace_v4": workspace,
        "review_workspace_reference_v4": workspace.reference,
    }
    for field in _INPUT_CONTRACT_FIELDS:
        state[field] = getattr(inputs, field)
    state.update(result.state_patch)
    return state, inputs, workspace, result
