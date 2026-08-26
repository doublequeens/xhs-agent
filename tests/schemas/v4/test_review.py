"""Contract tests for the isolated v4 review boundary."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.schemas.v4.review import (
    AssetReviewDecisionV4,
    HumanReviewIntentV4,
    HumanReviewDecisionV4,
    ReviewWorkspaceManifestV4,
    ReviewWorkspaceReferenceV4,
)


SHA = "a" * 64


def test_workspace_manifest_is_frozen_hash_bound_and_forbids_unsafe_paths():
    """Removing canonical path/hash validation must break this review audit record."""
    payload = {
        "workflow_version": "llm_scene_v4",
        "run_id": "run-1",
        "candidate_id": "candidate-1",
        "revision_id": "revision-0",
        "content_atom_set_sha256": SHA,
        "semantic_content_model_sha256": SHA,
        "narrative_sha256": SHA,
        "page_brief_set_sha256": SHA,
        "visual_direction_plan_sha256": SHA,
        "content_lock_sha256": SHA,
        "asset_manifest_sha256": SHA,
        "carousel_design_plan_sha256": SHA,
        "design_plan_qa_sha256": SHA,
        "render_manifest_sha256": SHA,
        "render_qa_sha256": SHA,
        "visual_critique_sha256": SHA,
        "page_sha256": {"pages/01-page-1.png": SHA},
        "contact_sheet_sha256": SHA,
        "files": {"index.html": SHA, "contact-sheet.png": SHA, "quality-report.json": SHA, "pages/01-page-1.png": SHA, "overlays/01-page-1.svg": SHA},
    }
    manifest = ReviewWorkspaceManifestV4.create(**payload)
    assert manifest.canonical_sha256 != SHA
    with pytest.raises(ValidationError):
        manifest.run_id = "another-run"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="canonical"):
        ReviewWorkspaceManifestV4.create(**{**payload, "page_sha256": {"/tmp/page.png": SHA}})


def test_workspace_reference_is_frozen_canonical_and_checkpoint_serializable():
    reference = ReviewWorkspaceReferenceV4.create(
        run_id="run-1",
        candidate_id="candidate-1",
        revision_id="revision-0",
        anchor_raw_sha256=SHA,
        anchor_canonical_sha256="b" * 64,
    )
    assert reference.reference_version == "review-reference-v1"
    restored = ReviewWorkspaceReferenceV4.model_validate_json(reference.model_dump_json())
    assert restored == reference
    with pytest.raises(ValidationError):
        reference.anchor_raw_sha256 = "c" * 64  # type: ignore[misc]
    with pytest.raises(ValidationError, match="canonical"):
        ReviewWorkspaceReferenceV4(**{
            **reference.model_dump(mode="python"),
            "canonical_sha256": SHA,
        })


def test_review_decision_rejects_forged_or_untrusted_attestation_fields():
    """A caller must not smuggle routes, hashes, or an unbound asset approval into a decision."""
    asset = AssetReviewDecisionV4.create(asset_id="asset-1", asset_sha256=SHA, decision="approved")
    payload = {
        "decision_id": "decision-1",
        "decided_at": "2026-08-26T00:00:00Z",
        "workflow_version": "llm_scene_v4",
        "run_id": "run-1",
        "candidate_id": "candidate-1",
        "revision_id": "revision-0",
        "action": "APPROVE",
        "rationale": "All rendered pages and assets were reviewed.",
        "content_lock_sha256": SHA,
        "asset_manifest_sha256": SHA,
        "carousel_design_plan_sha256": SHA,
        "design_plan_qa_sha256": SHA,
        "render_manifest_sha256": SHA,
        "render_qa_sha256": SHA,
        "visual_critique_sha256": SHA,
        "page_sha256": {"pages/01-page-1.png": SHA},
        "contact_sheet_sha256": SHA,
        "asset_decisions": (asset,),
    }
    decision = HumanReviewDecisionV4.create(**payload)
    assert decision.action == "APPROVE"
    with pytest.raises(ValidationError, match="Extra inputs"):
        HumanReviewDecisionV4.create(**{**payload, "route": "final_policy_guard"})
    with pytest.raises(ValidationError, match="canonical"):
        HumanReviewDecisionV4(**{**payload, "canonical_sha256": SHA})


def test_review_contract_nested_mappings_are_deeply_immutable_and_factory_normalizes():
    payload = {
        "workflow_version": "llm_scene_v4",
        "run_id": "run-1",
        "candidate_id": "candidate-1",
        "revision_id": "revision-0",
        "content_atom_set_sha256": SHA,
        "semantic_content_model_sha256": SHA,
        "narrative_sha256": SHA,
        "page_brief_set_sha256": SHA,
        "visual_direction_plan_sha256": SHA,
        "content_lock_sha256": SHA,
        "asset_manifest_sha256": SHA,
        "carousel_design_plan_sha256": SHA,
        "design_plan_qa_sha256": SHA,
        "render_manifest_sha256": SHA,
        "render_qa_sha256": SHA,
        "visual_critique_sha256": SHA,
        "page_sha256": {"pages/01-page-1.png": SHA},
        "contact_sheet_sha256": SHA,
        "files": {
            "index.html": SHA,
            "contact-sheet.png": SHA,
            "quality-report.json": SHA,
            "pages/01-page-1.png": SHA,
            "overlays/01-page-1.svg": SHA,
        },
    }
    manifest = ReviewWorkspaceManifestV4.create(**payload)
    with pytest.raises(TypeError):
        manifest.files["index.html"] = SHA  # type: ignore[index]
    with pytest.raises(TypeError):
        manifest.page_sha256["pages/01-page-1.png"] = SHA  # type: ignore[index]

    intent = HumanReviewIntentV4(action="REQUEST_REVISION", feedback="  tighten spacing  ")
    assert intent.feedback == "tighten spacing"
    with pytest.raises(ValidationError):
        HumanReviewIntentV4(action="REQUEST_REVISION", feedback="x" * 4001)
    with pytest.raises(ValidationError):
        HumanReviewIntentV4(action="VISIBLE_COPY_EDIT", visible_copy_payload="x" * 20001)
    with pytest.raises(ValidationError):
        HumanReviewIntentV4(action="APPROVE", feedback="not allowed")


def test_review_timestamp_is_strict_utc_and_hashes_normalized_payload():
    asset = AssetReviewDecisionV4.create(asset_id="asset-1", asset_sha256=SHA, decision="approved")
    payload = {
        "decision_id": "decision-1",
        "decided_at": "2026-08-26T00:00:00.000Z",
        "run_id": "run-1",
        "candidate_id": "candidate-1",
        "revision_id": "revision-0",
        "action": "APPROVE",
        "rationale": "  reviewed  ",
        "content_lock_sha256": SHA,
        "asset_manifest_sha256": SHA,
        "carousel_design_plan_sha256": SHA,
        "design_plan_qa_sha256": SHA,
        "render_manifest_sha256": SHA,
        "render_qa_sha256": SHA,
        "visual_critique_sha256": SHA,
        "page_sha256": {"pages/01-page-1.png": SHA},
        "contact_sheet_sha256": SHA,
        "asset_decisions": (asset,),
    }
    decision = HumanReviewDecisionV4.create(**payload)
    assert decision.decided_at == "2026-08-26T00:00:00Z"
    assert decision.rationale == "reviewed"
    with pytest.raises(ValueError):
        HumanReviewDecisionV4.create(**{**payload, "decided_at": "2026-08-26T00:00:00+00:00"})


def test_decision_factory_hashes_omitted_defaults_and_roundtrips():
    payload = {
        "decision_id": "decision-defaults",
        "decided_at": "2026-08-26T00:00:00Z",
        "run_id": "run-1",
        "candidate_id": "candidate-1",
        "revision_id": "revision-0",
        "action": "APPROVE",
        "content_lock_sha256": SHA,
        "asset_manifest_sha256": SHA,
        "carousel_design_plan_sha256": SHA,
        "design_plan_qa_sha256": SHA,
        "render_manifest_sha256": SHA,
        "render_qa_sha256": SHA,
        "visual_critique_sha256": SHA,
        "page_sha256": {"pages/01-page-1.png": SHA},
        "contact_sheet_sha256": SHA,
    }
    decision = HumanReviewDecisionV4.create(**payload)
    assert decision.rationale is None
    assert decision.asset_decisions == ()
    assert decision.workflow_version == "llm_scene_v4"
    assert HumanReviewDecisionV4.model_validate_json(decision.model_dump_json()) == decision


@pytest.mark.parametrize(
    "action,field,value",
    [
        ("REQUEST_REVISION", "feedback", "x"),
        ("AESTHETIC_OVERRIDE", "rationale", "x"),
        ("VISIBLE_COPY_EDIT", "visible_copy_payload", "x"),
    ],
)
def test_intent_requires_substantive_text_for_action_payloads(action, field, value):
    with pytest.raises(ValidationError):
        HumanReviewIntentV4(action=action, **{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("feedback", "See /Users/qinqiang/private/notes"),
        ("feedback", "See /var/log/xhs-agent/review.log"),
        ("feedback", r"\\\\server\\share\\review.txt"),
        ("feedback", "read ../secrets.txt"),
        ("rationale", "api_key=super-secret-value"),
        ("visible_copy_payload", "Bearer abcdefghijklmnop"),
    ],
)
def test_intent_rejects_private_paths_and_credentials(field, value):
    with pytest.raises(ValidationError):
        HumanReviewIntentV4(action="REQUEST_REVISION" if field == "feedback" else "VISIBLE_COPY_EDIT", **{field: value})


def test_normal_bilingual_review_prose_is_not_misclassified_as_private_data():
    intent = HumanReviewIntentV4(
        action="REQUEST_REVISION",
        feedback="请把第 2 页的标题层级拉开，让重点更清楚。 Please improve the title hierarchy.",
    )
    assert "标题层级" in intent.feedback
