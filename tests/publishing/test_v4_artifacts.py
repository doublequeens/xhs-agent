"""v4 publisher: the ten reviewed contracts plus every reviewed PNG, attested."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.review.v4_workspace import validate_review_workspace_inputs
from src.schemas.v4.publishing import V4_CANONICAL_CONTRACT_FILES

from tests.v4_review_state import reviewed_state


def _export(tmp_path, *, with_asset=False, action="APPROVE", failed_q4=False):
    from src.publishing.v4_artifacts import export_v4_publish_package

    state, inputs, workspace, result = reviewed_state(
        tmp_path / "world",
        with_asset=with_asset,
        action=action,
        failed_q4=failed_q4,
    )
    artifacts = export_v4_publish_package(
        state, publish_root=tmp_path / "publish"
    )
    return artifacts, state, inputs, workspace, result


def test_v4_export_writes_ten_contracts_and_attests_every_reviewed_byte(tmp_path):
    artifacts, state, inputs, workspace, result = _export(tmp_path)

    package_dir = artifacts.package_directory
    assert package_dir.is_dir()
    assert package_dir.parent == tmp_path / "publish"
    assert set(artifacts.contract_paths) == set(V4_CANONICAL_CONTRACT_FILES)
    for name, path in artifacts.contract_paths.items():
        assert path == package_dir / name
        assert path.is_file(), name

    attestation = artifacts.publish_attestation
    assert attestation.workflow_version == "llm_scene_v4"
    # The ten contract hashes equal the public review-source seam's hashes.
    _, hashes = validate_review_workspace_inputs(inputs)
    assert attestation.content_atom_set_sha256 == hashes["content_atom_set_sha256"]
    assert attestation.visual_direction_plan_sha256 == hashes["visual_direction_plan_sha256"]
    assert attestation.asset_manifest_sha256 == hashes["asset_manifest_sha256"]
    assert attestation.carousel_design_plan_sha256 == hashes["carousel_design_plan_sha256"]
    assert attestation.design_plan_qa_sha256 == hashes["design_plan_qa_sha256"]
    assert attestation.render_manifest_sha256 == hashes["render_manifest_sha256"]
    assert attestation.render_qa_sha256 == hashes["render_qa_sha256"]
    assert attestation.visual_critique_sha256 == hashes["visual_critique_sha256"]
    assert attestation.content_lock_sha256 == hashes["content_lock_sha256"]
    assert attestation.final_policy_attestation_sha256 == (
        artifacts.final_policy_attestation.canonical_sha256
    )

    # Every reviewed PNG is covered: pages plus the contact sheet.
    expected_pages = {
        f"pages/{page.sequence:02d}-{page.page_id}.png": page.sha256
        for page in inputs.render_manifest.pages
    }
    expected_pages["contact-sheet.png"] = inputs.render_manifest.contact_sheet_sha256
    assert dict(attestation.page_sha256) == expected_pages
    for name, digest in attestation.page_sha256.items():
        data = (package_dir / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest
        assert data.startswith(b"\x89PNG\r\n\x1a\n")

    # The written attestation file matches the returned model byte-for-byte.
    written = json.loads(
        (package_dir / "publish-attestation.json").read_text(encoding="utf-8")
    )
    assert written == attestation.model_dump(mode="json")


def test_final_policy_attestation_embeds_the_complete_review_decision(tmp_path):
    artifacts, state, inputs, workspace, result = _export(tmp_path)

    written = json.loads(
        (
            artifacts.package_directory / "final_policy_attestation.json"
        ).read_text(encoding="utf-8")
    )
    assert written["workflow_version"] == "llm_scene_v4"
    assert written["passed"] is True
    assert written["decision_id"] == result.decision.decision_id
    assert written["human_review_decision"] == result.decision.model_dump(mode="json")
    assert written["decision_raw_sha256"] == result.reference.decision_raw_sha256


def test_pending_manifest_human_decision_is_accepted_when_review_approved_bytes(
    tmp_path,
):
    artifacts, state, inputs, workspace, result = _export(tmp_path, with_asset=True)

    # v4 keeps AssetManifest.human_decision=pending through review; the
    # byte-bound approved decisions live in the terminal review decision.
    assert inputs.asset_manifest.items
    manifest_written = json.loads(
        (artifacts.package_directory / "asset_manifest.json").read_text("utf-8")
    )
    assert all(
        item["human_decision"] == "pending" for item in manifest_written["items"]
    )
    decision_written = json.loads(
        (
            artifacts.package_directory / "final_policy_attestation.json"
        ).read_text("utf-8")
    )
    approved = {
        item["asset_id"]: item["asset_sha256"]
        for item in decision_written["human_review_decision"]["asset_decisions"]
    }
    rendered = {
        item["asset_id"]: item["sha256"] for item in manifest_written["items"]
    }
    assert approved == rendered
    assert all(
        item["decision"] == "approved"
        for item in decision_written["human_review_decision"]["asset_decisions"]
    )


def test_export_fails_closed_and_leaves_no_partial_package(tmp_path):
    from src.publishing.v4_artifacts import export_v4_publish_package

    state, inputs, *_ = reviewed_state(tmp_path / "world")
    root = tmp_path / "publish"

    # Missing terminal decision evidence.
    with pytest.raises(Exception):
        export_v4_publish_package(
            {**state, "human_review_decision_v4": None}, publish_root=root
        )
    # Tampered page bytes fail the verified recompute.
    page = inputs.render_manifest.pages[0]
    page_path = inputs.artifact_paths.revision_root / page.path
    page_path.write_bytes(page_path.read_bytes() + b"\x00tampered")
    with pytest.raises(Exception):
        export_v4_publish_package(state, publish_root=root)

    assert not root.exists() or not any(root.iterdir())
    assert not list(root.glob(".-*-staging")) if root.exists() else True


def test_export_never_overwrites_an_existing_package(tmp_path):
    from src.publishing.v4_artifacts import export_v4_publish_package

    state, *_ = reviewed_state(tmp_path / "world")
    root = tmp_path / "publish"
    first = export_v4_publish_package(state, publish_root=root)
    with pytest.raises(Exception):
        export_v4_publish_package(state, publish_root=root)
    assert first.package_directory.is_dir()
