"""v4 Final Guard: recompute the reviewed terminal state before publication."""

from __future__ import annotations

import pytest

from src.review.v4_decisions import HumanReviewDecisionError
from src.schemas.v4.publishing import FinalPolicyAttestationV4

from tests.v4_review_state import reviewed_state


def test_approve_state_yields_attestation_embedding_the_complete_decision(tmp_path):
    state, inputs, workspace, result = reviewed_state(tmp_path)

    from src.nodes.v4.final_guard import final_policy_guard_v4_node

    patch = final_policy_guard_v4_node(state)

    assert patch["current_node"] == "V4_FINAL_GUARD"
    assert patch["review_status"] == "approved"
    assert patch["final_policy_issues"] == []
    attestation = patch["final_policy_attestation_v4"]
    assert type(attestation) is FinalPolicyAttestationV4
    assert attestation.workflow_version == "llm_scene_v4"
    assert attestation.passed is True
    assert attestation.aesthetic_override is False
    assert attestation.decision_id == result.decision.decision_id
    assert attestation.decision_canonical_sha256 == result.decision.canonical_sha256
    assert attestation.decision_raw_sha256 == result.reference.decision_raw_sha256
    assert (
        attestation.decision_reference_canonical_sha256
        == result.reference.canonical_sha256
    )
    assert (
        attestation.workspace_reference_canonical_sha256
        == workspace.reference.canonical_sha256
    )
    # The complete reviewed decision is embedded, not just its identity.
    # (Compare through the canonical JSON form: frozen maps store tuples
    # while json-mode dumps produce lists — canonically identical.)
    from src.schemas.v4.content import canonical_json_v4

    assert canonical_json_v4(dict(attestation.human_review_decision)) == canonical_json_v4(
        result.decision.model_dump(mode="json")
    )
    # The json-mode twin in the patch round-trips through the strict schema.
    assert (
        FinalPolicyAttestationV4.model_validate(
            dict(patch["final_policy_attestation"])
        )
        == attestation
    )


def test_aesthetic_override_state_marks_the_attestation(tmp_path):
    state, inputs, workspace, result = reviewed_state(
        tmp_path, action="AESTHETIC_OVERRIDE", failed_q4=True
    )

    from src.nodes.v4.final_guard import final_policy_guard_v4_node

    patch = final_policy_guard_v4_node(state)

    attestation = patch["final_policy_attestation_v4"]
    assert attestation.aesthetic_override is True
    assert attestation.action == "AESTHETIC_OVERRIDE"
    assert attestation.human_review_decision["action"] == "AESTHETIC_OVERRIDE"


def test_final_guard_fails_closed_on_missing_evidence_or_tampered_bytes(tmp_path):
    from src.nodes.v4.final_guard import final_policy_guard_v4_node

    state, inputs, *_ = reviewed_state(tmp_path)
    with pytest.raises(Exception):
        final_policy_guard_v4_node({**state, "human_review_decision_v4": None})
    with pytest.raises(Exception):
        final_policy_guard_v4_node(
            {**state, "human_review_decision_reference_v4": None}
        )
    # A tampered page byte must fail the full recompute before attestation.
    # (Applied last: the mutation is permanent for this state's workspace.)
    page = inputs.render_manifest.pages[0]
    page_path = inputs.artifact_paths.revision_root / page.path
    page_path.write_bytes(page_path.read_bytes() + b"\x00tampered")
    with pytest.raises(Exception):
        final_policy_guard_v4_node(state)


def test_verify_seam_rejects_a_revision_decision(tmp_path):
    """REQUEST_REVISION never reaches publication through the same seam."""

    from src.nodes.v4.final_guard import verify_v4_final_policy
    from src.review.v4_decisions import submit_human_review_intent
    from src.review.v4_workspace import build_review_workspace
    from src.schemas.v4.review import HumanReviewIntentV4
    from tests.review.test_v4_decisions import _failed_inputs

    inputs = _failed_inputs(tmp_path)
    workspace = build_review_workspace(inputs)
    result = submit_human_review_intent(
        workspace,
        inputs,
        HumanReviewIntentV4(action="REQUEST_REVISION", feedback="第二页节奏重复，需要重排。"),
        clock=lambda: "2026-08-27T00:00:00Z",
        decision_id_factory=lambda: "decision-revision",
    )
    state = {
        "run_id": inputs.artifact_paths.identity.run_id,
        "publish_package": inputs.content_lock.model_dump(mode="python"),
        "review_workspace_v4": workspace,
        "review_workspace_reference_v4": workspace.reference,
        "human_review_decision_v4": result.decision,
        "human_review_decision_reference_v4": result.reference,
    }
    for name in (
        "content_lock", "content_atom_set", "semantic_content_model",
        "carousel_narrative", "page_brief_set", "visual_direction_plan",
        "asset_manifest", "asset_resolution_result",
    ):
        state[name] = getattr(inputs, name)
    state["carousel_design_plan_v4"] = inputs.carousel_design_plan
    state["design_plan_qa_result_v4"] = inputs.design_plan_qa
    state["render_manifest_v4"] = inputs.render_manifest
    state["render_qa_result_v4"] = inputs.render_qa
    state["visual_critique_v4"] = inputs.visual_critique

    with pytest.raises(HumanReviewDecisionError):
        verify_v4_final_policy(state)
