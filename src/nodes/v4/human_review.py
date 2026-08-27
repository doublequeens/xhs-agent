"""Isolated v4 Human Review interrupt and state-patch boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langgraph.types import interrupt

from src.review.v4_decisions import (
    HumanReviewActionResultV4,
    HumanReviewDecisionError,
    route_after_human_review_v4,
    submit_human_review_intent,
)
from src.review.v4_workspace import (
    ReviewBindingError,
    ReviewWorkspaceInputsV4,
    ReviewWorkspaceV4,
    load_review_workspace,
    read_rendered_asset_evidence,
    validate_review_workspace_inputs,
)
from src.schemas.content_lock import ContentLock
from src.schemas.assets import AssetManifest, AssetResolutionResult
from src.schemas.v4.content import ContentAtomSetV4
from src.schemas.v4.critique import CarouselAestheticEvaluationV4
from src.schemas.v4.direction import (
    CarouselNarrativeV4,
    PageBriefSetV4,
    VisualDirectionPlanV4,
)
from src.schemas.v4.layout import CarouselDesignPlanV4
from src.schemas.v4.quality import DesignPlanQAResultV4
from src.schemas.v4.rendering import RenderManifestV4, RenderQAResultV4
from src.schemas.v4.semantic import SemanticContentModelV4
from src.visual_runtime.artifact_identity import ArtifactPaths
from src.schemas.v4.review import ReviewWorkspaceReferenceV4


_ACTION_NAMES = (
    "APPROVE",
    "AESTHETIC_OVERRIDE",
    "REQUEST_REVISION",
    "REJECT_OR_REPLACE_ASSET",
    "VISIBLE_COPY_EDIT",
)


def _first(state: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = state.get(name)
        if value is not None:
            return value
    return None


def _coerce_inputs(state: Mapping[str, Any]) -> ReviewWorkspaceInputsV4:
    direct = _first(state, "review_workspace_inputs_v4", "review_inputs_v4", "review_inputs")
    if type(direct) is ReviewWorkspaceInputsV4:
        return direct
    fields = {
        "artifact_paths": _first(state, "artifact_paths", "asset_transaction_paths"),
        "content_lock": _first(state, "content_lock"),
        "content_atom_set": _first(state, "content_atom_set", "atom_set"),
        "semantic_content_model": _first(state, "semantic_content_model", "semantic_model"),
        "carousel_narrative": _first(state, "carousel_narrative"),
        "page_brief_set": _first(state, "page_brief_set", "page_briefs"),
        "visual_direction_plan": _first(state, "visual_direction_plan"),
        "asset_manifest": _first(state, "asset_manifest", "assets"),
        "carousel_design_plan": _first(state, "carousel_design_plan_v4", "carousel_design_plan"),
        "design_plan_qa": _first(state, "design_plan_qa_result_v4", "design_plan_qa_result"),
        "render_manifest": _first(state, "render_manifest_v4", "render_manifest"),
        "render_qa": _first(state, "render_qa_result_v4", "render_qa_result"),
        "visual_critique": _first(state, "visual_critique_v4", "visual_critique"),
        "asset_resolution_result": _first(
            state, "asset_resolution_result_v4", "asset_resolution_result"
        ),
        "previous_review_workspace": _first(
            state, "previous_review_workspace_v4", "previous_review_workspace"
        ),
    }
    if any(value is None for key, value in fields.items() if key != "asset_resolution_result" and key != "previous_review_workspace"):
        raise HumanReviewDecisionError("v4 Human Review state lacks exact review source contracts")
    expected = {
        "artifact_paths": ArtifactPaths,
        "content_lock": ContentLock,
        "content_atom_set": ContentAtomSetV4,
        "semantic_content_model": SemanticContentModelV4,
        "carousel_narrative": CarouselNarrativeV4,
        "page_brief_set": PageBriefSetV4,
        "visual_direction_plan": VisualDirectionPlanV4,
        "asset_manifest": AssetManifest,
        "carousel_design_plan": CarouselDesignPlanV4,
        "design_plan_qa": DesignPlanQAResultV4,
        "render_manifest": RenderManifestV4,
        "render_qa": RenderQAResultV4,
        "visual_critique": CarouselAestheticEvaluationV4,
    }
    for name, contract_type in expected.items():
        if type(fields[name]) is not contract_type:
            raise HumanReviewDecisionError(
                f"v4 Human Review {name} must be an exact source contract"
            )
    for name in ("asset_resolution_result", "previous_review_workspace"):
        value = fields[name]
        if value is not None and type(value) not in (
            AssetResolutionResult if name == "asset_resolution_result" else ReviewWorkspaceV4,
        ):
            raise HumanReviewDecisionError(
                f"v4 Human Review {name} must be an exact optional contract"
            )
    try:
        return ReviewWorkspaceInputsV4(**fields)
    except Exception as error:
        raise HumanReviewDecisionError("v4 Human Review source contracts are malformed") from error


def _coerce_workspace(
    state: Mapping[str, Any],
    inputs: ReviewWorkspaceInputsV4,
) -> ReviewWorkspaceV4:
    workspace = _first(state, "review_workspace", "review_workspace_v4")
    reference = _first(
        state, "review_workspace_reference", "review_workspace_reference_v4"
    )
    if type(workspace) is ReviewWorkspaceV4:
        if type(workspace.reference) is not ReviewWorkspaceReferenceV4:
            raise HumanReviewDecisionError("state workspace has no externally-authorized reference")
        if reference is not None and reference != workspace.reference:
            raise HumanReviewDecisionError("state workspace reference differs from loaded workspace")
        return workspace
    if type(reference) is not ReviewWorkspaceReferenceV4:
        raise HumanReviewDecisionError("v4 Human Review requires persisted workspace reference")
    try:
        return load_review_workspace(inputs.artifact_paths, reference)
    except ReviewBindingError as error:
        raise HumanReviewDecisionError("persisted v4 review workspace is stale or unauthorized") from error


def _interrupt_payload(
    inputs: ReviewWorkspaceInputsV4,
    workspace: ReviewWorkspaceV4,
    assets=None,
) -> dict[str, Any]:
    # This payload is intentionally an evidence pointer, not an authorization
    # object.  It carries no caller-controlled route, hash, or filesystem path.
    q4 = inputs.visual_critique
    rendered_assets = (
        read_rendered_asset_evidence(inputs) if assets is None else tuple(assets)
    )
    return {
        "kind": "v4_human_review",
        "message": "Review the local v4 workspace, then submit one bounded action.",
        "workspace_index": "review/index.html",
        "workflow_version": "llm_scene_v4",
        "identity": {
            "run_id": workspace.manifest.run_id,
            "candidate_id": workspace.manifest.candidate_id,
            "revision_id": workspace.manifest.revision_id,
        },
        "q4": {"passed": q4.passed, "canonical_sha256": q4.canonical_sha256},
        "actions": _ACTION_NAMES,
        # Asset IDs are application-derived from the exact rendered evidence;
        # manifest destination paths are intentionally not exposed as IDs.
        "asset_ids": tuple(sorted(asset.item.asset_id for asset in rendered_assets)),
    }


def human_review_node(
    state: Mapping[str, Any],
    *,
    clock=None,
    decision_id_factory=None,
) -> dict[str, Any]:
    """Interrupt once, then apply one application-derived terminal action."""

    if not isinstance(state, Mapping):
        raise HumanReviewDecisionError("v4 Human Review requires a state mapping")
    inputs = _coerce_inputs(state)
    workspace = _coerce_workspace(state, inputs)
    # Validate before presenting an action surface.  This also ensures a
    # stale workspace cannot be used as a UI-only approval shortcut.
    validate_review_workspace_inputs(inputs)
    rendered_assets = read_rendered_asset_evidence(inputs)
    resume = interrupt(_interrupt_payload(inputs, workspace, rendered_assets))
    if resume is None:
        from src.review.v4_workspace import read_review_intent

        intent = read_review_intent(workspace)
    elif isinstance(resume, Mapping):
        raw_intent = resume.get("intent", resume)
        if not isinstance(raw_intent, Mapping):
            raise HumanReviewDecisionError("v4 Human Review resume payload must be a bounded intent")
        intent = raw_intent
    else:
        raise HumanReviewDecisionError("v4 Human Review resume payload must be a mapping")
    result: HumanReviewActionResultV4 = submit_human_review_intent(
        workspace,
        inputs,
        intent,
        revision_history=state.get("revision_history_v4", ()),
        clock=clock,
        decision_id_factory=decision_id_factory,
        current_package=state.get("publish_package"),
    )
    return dict(result.state_patch)


v4_human_review_node = human_review_node


__all__ = [
    "human_review_node",
    "route_after_human_review_v4",
    "v4_human_review_node",
]
