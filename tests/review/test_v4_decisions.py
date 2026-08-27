"""Public-boundary attacks for the isolated v4 Human Review decision seam."""

from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from src.review.v4_decisions import (
    HumanReviewDecisionError,
    route_after_human_review_v4,
    submit_human_review_intent,
    verify_human_review_decision,
)
from src.review.v4_workspace import build_review_workspace
from src.schemas.v4.critique import (
    AestheticIssueV4,
    CarouselAestheticEvaluationV4,
    SetAestheticEvaluationV4,
)
from src.schemas.v4.review import HumanReviewIntentV4
from src.schemas.v4.review import HumanReviewRouteContextV4, HumanReviewRouteEvidenceV4
from src.visual_design.v4.revisions import route_revision
from src.schemas.v4.revision import VisualExecutionInterrupted

from tests.review.test_v4_workspace import _inputs


def _failed_inputs(tmp_path: Path, *, with_asset: bool = False):
    inputs = _inputs(tmp_path, with_asset=with_asset)
    current = inputs.visual_critique
    rhythm_issue = AestheticIssueV4.create(
        severity="major",
        dimension="rhythm",
        page_ids=(current.pages[0].page_id,),
        evidence="页面之间的节奏重复，缺少有效变化",
    )
    failed_set = SetAestheticEvaluationV4.create(
        rhythm=60,
        repetition=90,
        family_consistency=90,
        cover_body_consistency=90,
        issues=(rhythm_issue,),
    )
    failed = CarouselAestheticEvaluationV4.create(
        render_manifest_sha256=current.render_manifest_sha256,
        render_qa_result_sha256=current.render_qa_result_sha256,
        page_brief_set_sha256=current.page_brief_set_sha256,
        semantic_content_model_sha256=current.semantic_content_model_sha256,
        authoring_model_identity=current.authoring_model_identity,
        evaluator_model_identity=current.evaluator_model_identity,
        pages=current.pages,
        set_evaluation=failed_set,
    )
    return inputs.model_copy(update={"visual_critique": failed})


def _package(inputs):
    return inputs.content_lock.model_dump(mode="python")


def _submit(
    workspace,
    inputs,
    intent,
    *,
    decision_id="decision-test",
    current_package=None,
):
    return submit_human_review_intent(
        workspace,
        inputs,
        intent,
        clock=lambda: "2026-08-26T00:00:00Z",
        decision_id_factory=lambda: decision_id,
        current_package=current_package,
    )


def test_approve_derives_every_identity_and_reopens_record_without_assets(tmp_path):
    inputs = _inputs(tmp_path)
    workspace = build_review_workspace(inputs)

    result = _submit(workspace, inputs, HumanReviewIntentV4(action="APPROVE"))

    assert result.route == "final_policy_guard"
    assert result.decision.decided_at == "2026-08-26T00:00:00Z"
    assert result.decision.decision_id == "decision-test"
    assert result.decision.asset_decisions == ()
    assert result.reference.workspace_reference_sha256 == workspace.reference.canonical_sha256
    assert result.reference.decision_raw_sha256 == hashlib.sha256(
        (inputs.artifact_paths.revision_root / "human-review-decision.json").read_bytes()
    ).hexdigest()
    assert verify_human_review_decision(
        result.decision, result.reference, workspace, inputs
    ) == result.decision
    assert route_after_human_review_v4(result) == "final_policy_guard"
    # A stale caller-provided route or synthetic decision mapping cannot steer
    # the closed helper without the exact verified action result.
    with pytest.raises(HumanReviewDecisionError, match="verified action"):
        route_after_human_review_v4({**result.state_patch, "route": "asset_resolver"})


@pytest.mark.parametrize(
    ("action", "expected_route"),
    (
        ("APPROVE", "final_policy_guard"),
        ("AESTHETIC_OVERRIDE", "final_policy_guard"),
        ("REQUEST_REVISION", "revision"),
        ("REJECT_OR_REPLACE_ASSET", "asset_resolver"),
        ("VISIBLE_COPY_EDIT", "r2_compliance"),
    ),
)
def test_all_actions_route_from_verified_result_and_keep_history_after_invalidation(
    tmp_path, action, expected_route
):
    with_asset = action == "REJECT_OR_REPLACE_ASSET"
    inputs = (
        _failed_inputs(tmp_path, with_asset=with_asset)
        if action in {"AESTHETIC_OVERRIDE", "REQUEST_REVISION"}
        else _inputs(tmp_path, with_asset=with_asset)
    )
    workspace = build_review_workspace(inputs)
    package = _package(inputs)
    intent = {
        "APPROVE": HumanReviewIntentV4(action="APPROVE"),
        "AESTHETIC_OVERRIDE": HumanReviewIntentV4(
            action="AESTHETIC_OVERRIDE", rationale="明确接受当前审美问题并继续审核。"
        ),
        "REQUEST_REVISION": HumanReviewIntentV4(
            action="REQUEST_REVISION", feedback="第 2 页层级需要拉开，减少重复节奏。"
        ),
        "REJECT_OR_REPLACE_ASSET": HumanReviewIntentV4(
            action="REJECT_OR_REPLACE_ASSET",
            asset_ids=("fixture-asset",),
            rationale="素材主体与当前页面重点不匹配，需要替换。",
        ),
        "VISIBLE_COPY_EDIT": HumanReviewIntentV4(
            action="VISIBLE_COPY_EDIT",
            visible_copy_payload=json.dumps({"title": "已更新的标题"}, ensure_ascii=False),
        ),
    }[action]
    result = _submit(
        workspace,
        inputs,
        intent,
        decision_id=f"decision-{action.lower()}",
        current_package=package if action == "VISIBLE_COPY_EDIT" else None,
    )

    assert route_after_human_review_v4(result) == expected_route
    evidence = result.state_patch["human_review_route_evidence_v4"]
    assert type(evidence) is HumanReviewRouteEvidenceV4
    assert HumanReviewRouteEvidenceV4.model_validate_json(evidence.model_dump_json()) == evidence
    context = result.state_patch["human_review_route_context_v4"]
    assert type(context) is HumanReviewRouteContextV4
    restored_context = HumanReviewRouteContextV4.model_validate_json(context.model_dump_json())
    restored_evidence = HumanReviewRouteEvidenceV4.model_validate_json(evidence.model_dump_json())
    assert restored_context == context
    assert route_after_human_review_v4(
        {
            **result.state_patch,
            "human_review_route_context_v4": restored_context,
            "human_review_route_evidence_v4": restored_evidence,
        }
    ) == expected_route
    assert evidence.action == action
    assert result.state_patch["human_review_history_v4"] == result.reference
    assert result.state_patch["human_review_terminal_reference_v4"] == result.reference
    if expected_route != "final_policy_guard":
        assert result.state_patch["human_review_decision"] is None
        assert result.state_patch["human_review_decision_reference"] is None


def test_approve_override_q4_matrix_is_closed(tmp_path):
    passed_inputs = _inputs(tmp_path / "passed")
    passed_workspace = build_review_workspace(passed_inputs)
    with pytest.raises(HumanReviewDecisionError, match="failed Q4"):
        _submit(
            passed_workspace,
            passed_inputs,
            HumanReviewIntentV4(
                action="AESTHETIC_OVERRIDE", rationale="override should be rejected"
            ),
        )

    failed_inputs = _failed_inputs(tmp_path / "failed")
    failed_workspace = build_review_workspace(failed_inputs)
    with pytest.raises(HumanReviewDecisionError, match="passed Q4"):
        _submit(
            failed_workspace,
            failed_inputs,
            HumanReviewIntentV4(action="APPROVE"),
            decision_id="decision-failed-approve",
        )
    with pytest.raises(HumanReviewDecisionError, match="substantive"):
        _submit(
            failed_workspace,
            failed_inputs,
            HumanReviewIntentV4(action="AESTHETIC_OVERRIDE", rationale="short"),
            decision_id="decision-short-override",
        )
    result = _submit(
        failed_workspace,
        failed_inputs,
        HumanReviewIntentV4(
            action="AESTHETIC_OVERRIDE", rationale="明确接受当前审美问题，继续发布流程"
        ),
        decision_id="decision-override",
    )
    assert result.route == "final_policy_guard"
    assert result.decision.visual_critique_sha256 == failed_inputs.visual_critique.canonical_sha256
    assert result.decision.action == "AESTHETIC_OVERRIDE"
    assert result.state_patch["visual_aesthetic_override"] is True


def test_request_revision_uses_typed_aesthetic_history_and_preserves_content(tmp_path):
    inputs = _failed_inputs(tmp_path)
    workspace = build_review_workspace(inputs)
    result = _submit(
        workspace,
        inputs,
        HumanReviewIntentV4(
            action="REQUEST_REVISION",
            feedback="第 3 页层级需要拉开，减少重复的视觉节奏。",
        ),
    )

    assert result.route == "revision"
    assert result.revision_request is not None
    assert result.revision_request.target_layer == "AESTHETIC"
    assert result.revision_request.failure_codes == ("AESTHETIC_REVIEW_FAILED",)
    assert result.state_patch["human_review_revision_request_v4"] == result.revision_request
    assert "revision_request_v4" not in result.state_patch
    assert result.state_patch["review_feedback"] == "第 3 页层级需要拉开，减少重复的视觉节奏。"
    assert "content_lock" not in result.state_patch
    assert "content_atom_set" not in result.state_patch
    assert "asset_manifest" not in result.state_patch

    first_request = route_revision(
        result.normalized_failures,
        (),
        candidate_id=inputs.artifact_paths.identity.candidate_id,
        prior_revision_id=None,
        page_brief_set=inputs.page_brief_set,
        carousel_design_plan=inputs.carousel_design_plan,
    )
    from src.visual_design.v4.revisions import append_revision_event

    event = append_revision_event(
        first_request,
        result.normalized_failures,
        candidate_id=inputs.artifact_paths.identity.candidate_id,
        revision_id="revision-2",
        page_brief_set=inputs.page_brief_set,
        carousel_design_plan=inputs.carousel_design_plan,
    )
    with pytest.raises(VisualExecutionInterrupted):
        route_revision(
            result.normalized_failures,
            (event,),
            candidate_id=inputs.artifact_paths.identity.candidate_id,
            prior_revision_id="revision-2",
            page_brief_set=inputs.page_brief_set,
            carousel_design_plan=inputs.carousel_design_plan,
        )


def test_asset_rejection_binds_rendered_bytes_and_invalidates_only_downstream(tmp_path):
    inputs = _inputs(tmp_path, with_asset=True)
    workspace = build_review_workspace(inputs)
    result = _submit(
        workspace,
        inputs,
        HumanReviewIntentV4(
            action="REJECT_OR_REPLACE_ASSET",
            asset_ids=("fixture-asset",),
            rationale="素材主体与当前页面重点不匹配，需要替换。",
        ),
    )

    assert result.route == "asset_resolver"
    assert result.revision_request is not None
    assert result.revision_request.target_layer == "ASSET"
    assert result.revision_request.failure_codes == ("HUMAN_REVIEW_ASSET_REJECTED",)
    assert result.decision.asset_decisions[0].decision == "rejected"
    assert result.decision.asset_decisions[0].asset_sha256 == inputs.asset_manifest.items[0].sha256
    assert inputs.asset_manifest.items[0].human_decision == "pending"
    assert result.state_patch["asset_manifest"] is None
    assert result.state_patch["asset_resolution_result"] is None
    assert result.state_patch["carousel_design_plan"] is None
    assert result.state_patch["layout_programs"] is None
    assert result.state_patch["composition_plan"] is None
    assert result.state_patch["design_metrics_qa_result"] is None
    assert result.state_patch["render_manifest"] is None
    assert result.state_patch["visual_critique"] is None
    assert result.state_patch["review_workspace"] is None
    assert result.state_patch["human_review_decision"] is None
    assert "content_lock" not in result.state_patch
    assert "content_atom_set" not in result.state_patch


def test_visible_copy_edit_requires_changed_editorial_payload_and_clears_all_visual_state(tmp_path):
    inputs = _inputs(tmp_path)
    workspace = build_review_workspace(inputs)
    package = _package(inputs)
    unchanged = json.dumps({"title": package["title"]}, ensure_ascii=False)
    with pytest.raises(HumanReviewDecisionError, match="does not change"):
        _submit(
            workspace,
            inputs,
            HumanReviewIntentV4(action="VISIBLE_COPY_EDIT", visible_copy_payload=unchanged),
            decision_id="decision-unchanged",
            # The first failed action does not append a record.
            current_package=package,
        )

    result = _submit(
        workspace,
        inputs,
        HumanReviewIntentV4(
            action="VISIBLE_COPY_EDIT",
            visible_copy_payload=json.dumps({"title": "新的可见标题"}, ensure_ascii=False),
        ),
        current_package=package,
    )
    assert result.route == "r2_compliance"
    assert result.edited_publish_package["title"] == "新的可见标题"
    assert result.state_patch["publish_package"]["title"] == "新的可见标题"
    for key in (
        "content_lock", "content_atom_set", "semantic_content_model", "page_brief_set",
        "visual_direction_plan", "asset_manifest", "asset_resolution_result",
        "carousel_design_plan", "design_plan_qa_result", "render_manifest",
        "render_qa_result", "visual_critique", "human_review_decision",
        "final_policy_attestation", "revision_request",
    ):
        assert result.state_patch[key] is None
    assert result.state_patch["r2_input_v4"]["title"] == "新的可见标题"


def test_mutable_intent_forgery_and_unknown_asset_fail_before_append(tmp_path):
    inputs = _inputs(tmp_path)
    workspace = build_review_workspace(inputs)
    with pytest.raises(HumanReviewDecisionError, match="malformed|forged"):
        _submit(
            workspace,
            inputs,
            {"action": "APPROVE", "route": "final_policy_guard"},
            decision_id="decision-forged",
        )
    with pytest.raises(HumanReviewDecisionError, match="unrendered"):
        _submit(
            workspace,
            inputs,
            HumanReviewIntentV4(
                action="REJECT_OR_REPLACE_ASSET",
                asset_ids=("not-rendered",),
                rationale="替换当前不存在的素材。",
            ),
            decision_id="decision-unknown-asset",
        )
    assert not (inputs.artifact_paths.revision_root / "human-review-decision.json").exists()


def test_replay_and_record_tampering_fail_closed(tmp_path):
    inputs = _inputs(tmp_path)
    workspace = build_review_workspace(inputs)
    result = _submit(workspace, inputs, HumanReviewIntentV4(action="APPROVE"))
    record = inputs.artifact_paths.revision_root / "human-review-decision.json"
    original = record.read_bytes()
    with pytest.raises(HumanReviewDecisionError, match="already exists"):
        _submit(
            workspace,
            inputs,
            HumanReviewIntentV4(action="APPROVE"),
            decision_id="decision-replay",
        )
    assert record.read_bytes() == original
    record.write_bytes(b"{}")
    with pytest.raises(HumanReviewDecisionError):
        verify_human_review_decision(result.decision, result.reference, workspace, inputs)


def test_terminal_record_is_append_once_under_concurrent_submissions(tmp_path):
    inputs = _inputs(tmp_path)
    workspace = build_review_workspace(inputs)
    intent = HumanReviewIntentV4(action="APPROVE")

    def submit(index):
        try:
            result = _submit(
                workspace,
                inputs,
                intent,
                decision_id=f"concurrent-{index}",
            )
            return ("ok", result.decision.decision_id)
        except HumanReviewDecisionError as error:
            return ("rejected", str(error))

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(submit, (1, 2)))

    assert sorted(outcome[0] for outcome in outcomes) == ["ok", "rejected"]
    assert (inputs.artifact_paths.revision_root / "human-review-decision.json").is_file()


@pytest.mark.parametrize("kind", ("page", "contact"))
def test_changed_render_or_contact_bytes_fail_before_decision(tmp_path, kind):
    inputs = _inputs(tmp_path)
    workspace = build_review_workspace(inputs)
    if kind == "page":
        path = inputs.artifact_paths.revision_root / inputs.render_manifest.pages[0].path
    else:
        path = inputs.artifact_paths.revision_root / inputs.render_manifest.contact_sheet_path
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(HumanReviewDecisionError):
        _submit(workspace, inputs, HumanReviewIntentV4(action="APPROVE"))
    assert not (inputs.artifact_paths.revision_root / "human-review-decision.json").exists()


def test_changed_rendered_asset_bytes_fail_before_decision(tmp_path):
    inputs = _inputs(tmp_path, with_asset=True)
    workspace = build_review_workspace(inputs)
    asset_path = Path(inputs.asset_manifest.items[0].local_path)
    asset_path.write_bytes(asset_path.read_bytes() + b"changed")

    with pytest.raises(HumanReviewDecisionError, match="asset|stale|unsafe"):
        _submit(workspace, inputs, HumanReviewIntentV4(action="APPROVE"))
    assert not (inputs.artifact_paths.revision_root / "human-review-decision.json").exists()


def test_visible_copy_payload_cannot_smuggle_visual_contract_fields(tmp_path):
    inputs = _inputs(tmp_path)
    workspace = build_review_workspace(inputs)
    package = _package(inputs)

    with pytest.raises(HumanReviewDecisionError, match="contract fields"):
        _submit(
            workspace,
            inputs,
            HumanReviewIntentV4(
                action="VISIBLE_COPY_EDIT",
                visible_copy_payload=json.dumps(
                    {"content_lock_sha256": "b" * 64}, ensure_ascii=False
                ),
            ),
            current_package=package,
        )
    assert not (inputs.artifact_paths.revision_root / "human-review-decision.json").exists()


def test_visible_copy_verification_binds_exact_resulting_r2_package(tmp_path):
    inputs = _inputs(tmp_path)
    workspace = build_review_workspace(inputs)
    original = _package(inputs)
    result = _submit(
        workspace,
        inputs,
        HumanReviewIntentV4(
            action="VISIBLE_COPY_EDIT",
            visible_copy_payload=json.dumps({"title": "结果包中的标题"}, ensure_ascii=False),
        ),
        current_package=original,
    )

    assert verify_human_review_decision(
        result.decision,
        result.reference,
        workspace,
        inputs,
        current_package=result.edited_publish_package,
    ) == result.decision
    with pytest.raises(HumanReviewDecisionError, match="package|payload"):
        verify_human_review_decision(
            result.decision,
            result.reference,
            workspace,
            inputs,
            current_package=original,
        )
    unrelated = dict(result.edited_publish_package)
    unrelated["title"] = "另一个 R2 结果"
    with pytest.raises(HumanReviewDecisionError, match="package|payload"):
        verify_human_review_decision(
            result.decision,
            result.reference,
            workspace,
            inputs,
            current_package=unrelated,
        )


def test_route_helper_rejects_forged_or_stale_verified_action_evidence(tmp_path):
    inputs = _inputs(tmp_path)
    workspace = build_review_workspace(inputs)
    result = _submit(workspace, inputs, HumanReviewIntentV4(action="APPROVE"))

    forged_route = replace(result, route="asset_resolver")
    with pytest.raises(HumanReviewDecisionError, match="route|evidence"):
        route_after_human_review_v4(forged_route)
    forged_evidence = replace(
        result,
        route_evidence=result.route_evidence.model_copy(update={"route": "asset_resolver"}),
    )
    with pytest.raises(HumanReviewDecisionError, match="route|evidence"):
        route_after_human_review_v4(forged_evidence)
    with pytest.raises(HumanReviewDecisionError, match="verified action"):
        route_after_human_review_v4(
            {"human_review_route_evidence_v4": result.route_evidence}
        )


def test_asset_hardlink_and_cross_workspace_reference_are_rejected(tmp_path):
    inputs = _inputs(tmp_path / "asset", with_asset=True)
    workspace = build_review_workspace(inputs)
    asset_path = Path(inputs.asset_manifest.items[0].local_path)
    os.link(asset_path, asset_path.with_name("alias.png"))
    with pytest.raises(HumanReviewDecisionError, match="asset|unsafe|stale"):
        _submit(workspace, inputs, HumanReviewIntentV4(action="APPROVE"))

    other_inputs = _inputs(tmp_path / "other")
    other_workspace = build_review_workspace(other_inputs)
    forged_handle = replace(workspace, reference=other_workspace.reference)
    with pytest.raises(HumanReviewDecisionError):
        _submit(forged_handle, inputs, HumanReviewIntentV4(action="APPROVE"), decision_id="cross")


def test_self_rehashed_contract_cannot_replace_workspace_source(tmp_path):
    inputs = _inputs(tmp_path)
    workspace = build_review_workspace(inputs)
    changed_inputs = _failed_inputs(tmp_path / "changed")
    # Keep the original authorized workspace while supplying a self-consistent
    # but different Q4 object.  The workspace manifest/reference must win.
    changed_inputs = changed_inputs.model_copy(
        update={"artifact_paths": inputs.artifact_paths}
    )
    with pytest.raises(HumanReviewDecisionError, match="workspace|source|stale"):
        _submit(workspace, changed_inputs, HumanReviewIntentV4(action="APPROVE"))
