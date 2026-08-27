"""Application-owned v4 Human Review decision binding.

The review page's ``decision.json`` is mutable intake.  This module is the
only boundary that can turn that intent into a terminal decision record.  It
revalidates the externally-authorized workspace, recomputes the deterministic
Q0-Q3 source seam, derives rendered asset bytes and all hashes, then appends a
single no-replace decision record beside (never inside) the immutable review
workspace.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal
from uuid import uuid4

from src.schemas.v4.content import canonical_json_v4, canonical_sha256_v4
from src.schemas.v4.revision import (
    FailureFingerprintV4,
    NormalizedFailureV4,
    RevisionEventV4,
    RevisionRequestV4,
    VisualExecutionInterrupted,
)
from src.schemas.v4.review import (
    AssetReviewDecisionV4,
    HumanReviewDecisionReferenceV4,
    HumanReviewDecisionV4,
    HumanReviewIntentV4,
    HumanReviewRouteContextV4,
    HumanReviewRouteEvidenceV4,
    ReviewWorkspaceManifestV4,
    ReviewWorkspaceReferenceV4,
    ReviewActionV4,
)
from src.review.v4_workspace import (
    ReviewBindingError,
    ReviewWorkspaceInputsV4,
    ReviewWorkspaceV4,
    _rendered_assets,
    validate_review_workspace_inputs,
    verify_review_workspace,
)
from src.visual_design.v4.revisions import route_revision
from src.visual_runtime.artifact_identity import (
    ArtifactBindingError,
    ArtifactIdentityError,
    _atomic_write_at,
    _lease_context,
    _open_absolute_directory,
    read_verified_artifact_snapshot,
    revalidate_artifact_paths,
    resolve_artifact_paths,
    ArtifactIdentity,
    ArtifactPaths,
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


class HumanReviewDecisionError(ReviewBindingError):
    """A review intent, record, or route failed closed validation."""


HumanReviewRouteV4 = Literal[
    "final_policy_guard", "revision", "asset_resolver", "r2_compliance"
]

_DECISION_RECORD = "human-review-decision.json"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_VISIBLE_COPY_FIELDS = frozenset(
    {
        "title",
        "cover_copy",
        "content",
        "hashtags",
        "focus_keyword",
        "topic",
        "topic_id",
        "angle",
        "angle_id",
        "target_group",
        "core_pain",
        "first_screen_promise",
    }
)
_FORBIDDEN_COPY_KEYS = frozenset(
    {
        "content_lock",
        "content_lock_sha256",
        "content_atom_set",
        "content_atom_set_sha256",
        "semantic_content_model",
        "page_brief_set",
        "visual_direction_plan",
        "asset_manifest",
        "asset_resolution_result",
        "carousel_design_plan",
        "design_plan_qa",
        "render_manifest",
        "render_qa",
        "visual_critique",
        "human_review_decision",
        "human_review_decision_reference",
        "review_workspace",
        "review_workspace_reference",
        "route",
        "review_route",
        "invalidation",
    }
)
_HASH_FIELDS = (
    "content_atom_set_sha256",
    "semantic_content_model_sha256",
    "narrative_sha256",
    "page_brief_set_sha256",
    "visual_direction_plan_sha256",
    "content_lock_sha256",
    "asset_manifest_sha256",
    "carousel_design_plan_sha256",
    "design_plan_qa_sha256",
    "render_manifest_sha256",
    "render_qa_sha256",
    "visual_critique_sha256",
)


@dataclass(frozen=True, slots=True)
class HumanReviewActionResultV4:
    """Derived action, route and state patch returned by the v4 node seam."""

    decision: HumanReviewDecisionV4
    reference: HumanReviewDecisionReferenceV4
    route: HumanReviewRouteV4
    route_context: HumanReviewRouteContextV4
    route_evidence: HumanReviewRouteEvidenceV4
    state_patch: Mapping[str, Any]
    revision_request: RevisionRequestV4 | None = None
    normalized_failures: tuple[NormalizedFailureV4, ...] = ()
    edited_publish_package: Mapping[str, Any] | None = None


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_decision_bytes(decision: HumanReviewDecisionV4) -> bytes:
    return canonical_json_v4(decision.model_dump(mode="json")).encode("utf-8")


def _identity(value: object, name: str) -> str:
    if type(value) is not str or not value or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value
    ):
        raise HumanReviewDecisionError(f"{name} is not a structural identity")
    return value


def _clock_text(clock: Callable[[], object] | None) -> str:
    value = clock() if clock is not None else datetime.now(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise HumanReviewDecisionError("decision clock must return timezone-aware UTC")
        value = value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )
    if type(value) is not str:
        raise HumanReviewDecisionError("decision clock must return RFC3339 UTC text")
    # Let the strict schema perform the complete calendar/range validation.
    from src.schemas.v4.review import _timestamp

    return _timestamp(value)


def _intent(value: HumanReviewIntentV4 | Mapping[str, Any]) -> HumanReviewIntentV4:
    if type(value) is HumanReviewIntentV4:
        return value
    if not isinstance(value, Mapping):
        raise HumanReviewDecisionError("human review intent must be exact bounded input")
    try:
        return HumanReviewIntentV4.model_validate(dict(value))
    except Exception as error:
        raise HumanReviewDecisionError("human review intent is malformed or forged") from error


def _history(value: object) -> tuple[RevisionEventV4, ...]:
    if value is None:
        return ()
    if type(value) is not tuple or any(type(item) is not RevisionEventV4 for item in value):
        raise HumanReviewDecisionError("revision history must be an exact immutable tuple")
    for event in value:
        try:
            event.validate_contract()
        except Exception as error:
            raise HumanReviewDecisionError("revision history is invalid") from error
    return value


def _workspace_source(
    workspace: ReviewWorkspaceV4,
    inputs: ReviewWorkspaceInputsV4,
) -> tuple[dict[str, str], tuple[Any, ...]]:
    """Verify external workspace authorization and the exact current source."""

    if type(workspace) is not ReviewWorkspaceV4:
        raise HumanReviewDecisionError("human review requires an exact loaded workspace")
    if workspace.reference is None:
        raise HumanReviewDecisionError("workspace has no externally-authorized reference")
    try:
        verify_review_workspace(workspace)
        paths, hashes = validate_review_workspace_inputs(inputs)
        checked_paths = revalidate_artifact_paths(paths)
    except (
        ReviewBindingError,
        ArtifactIdentityError,
        ArtifactBindingError,
        TypeError,
        ValueError,
    ) as error:
        raise HumanReviewDecisionError("review workspace or source contracts are stale") from error
    if checked_paths != workspace.artifact_paths:
        raise HumanReviewDecisionError("workspace ArtifactPaths differ from current source")
    manifest = workspace.manifest
    if (manifest.run_id, manifest.candidate_id, manifest.revision_id) != (
        paths.identity.run_id,
        paths.identity.candidate_id,
        paths.identity.revision_id,
    ):
        raise HumanReviewDecisionError("workspace identity differs from current source")
    for field in _HASH_FIELDS:
        if getattr(manifest, field) != hashes[field]:
            raise HumanReviewDecisionError(f"workspace {field} differs from current source")

    page_hashes = {
        f"pages/{page.sequence:02d}-{page.page_id}.png": page.sha256
        for page in inputs.render_manifest.pages
    }
    if dict(manifest.page_sha256) != page_hashes:
        raise HumanReviewDecisionError("workspace page hashes differ from current RenderManifest")
    try:
        contact = read_verified_artifact_snapshot(
            paths.revision_root / inputs.render_manifest.contact_sheet_path,
            inputs.render_manifest.contact_sheet_sha256,
            containment_root=paths.render_root,
        )
    except ArtifactBindingError as error:
        raise HumanReviewDecisionError("current contact-sheet bytes are stale or unsafe") from error
    if manifest.contact_sheet_sha256 != contact.sha256:
        raise HumanReviewDecisionError("workspace contact-sheet hash differs from current bytes")
    try:
        # ``validate_review_workspace_inputs`` above is the mandatory public
        # Q0-Q3 source seam.  Reuse its checked ArtifactPaths for byte-bound
        # asset derivation instead of calling that expensive Pydantic seam a
        # second time for the same immutable source snapshot.
        assets = _rendered_assets(inputs, paths)
    except ReviewBindingError as error:
        raise HumanReviewDecisionError("current rendered asset evidence is stale or unsafe") from error
    asset_hashes = {asset.destination: asset.sha256 for asset in assets}
    if dict(manifest.asset_sha256) != asset_hashes:
        raise HumanReviewDecisionError("workspace asset evidence differs from rendered asset bytes")
    return hashes, assets


def _require_substantive_rationale(intent: HumanReviewIntentV4) -> str:
    rationale = intent.rationale
    if type(rationale) is not str or len(rationale.strip()) < 8:
        raise HumanReviewDecisionError("aesthetic override requires substantive rationale")
    return rationale.strip()


def _visible_copy_edit(
    intent: HumanReviewIntentV4,
    current_package: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], str, str]:
    if not isinstance(current_package, Mapping):
        raise HumanReviewDecisionError("visible-copy edit requires the current publish package")
    try:
        payload = json.loads(intent.visible_copy_payload or "")
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise HumanReviewDecisionError("visible-copy payload must be a JSON object") from error
    if not isinstance(payload, dict) or not payload:
        raise HumanReviewDecisionError("visible-copy payload must be a non-empty object")
    keys = set(payload)
    if keys & _FORBIDDEN_COPY_KEYS or not keys <= _VISIBLE_COPY_FIELDS:
        raise HumanReviewDecisionError("visible-copy payload contains non-editorial contract fields")
    merged = dict(current_package)
    changed = False
    for key, value in payload.items():
        if key == "hashtags":
            if not isinstance(value, (list, tuple)) or any(type(item) is not str for item in value):
                raise HumanReviewDecisionError("visible-copy hashtags must be a string list")
            value = list(value)
        elif key in _VISIBLE_COPY_FIELDS and not isinstance(value, str):
            raise HumanReviewDecisionError(f"visible-copy field {key} must be text")
        if merged.get(key) != value:
            changed = True
        merged[key] = value
    if not changed:
        raise HumanReviewDecisionError("visible-copy payload does not change the current package")
    # The changed payload hash is useful for explaining the edit, but the
    # immutable decision must additionally bind the complete resulting R2
    # package.  Otherwise verification against an unrelated package that still
    # contains the same changed field would incorrectly succeed.
    return merged, canonical_sha256_v4(payload), canonical_sha256_v4(merged)


def _page_ids_for_aesthetic(inputs: ReviewWorkspaceInputsV4) -> tuple[str, ...]:
    critique = inputs.visual_critique
    page_ids = tuple(page.page_id for page in inputs.render_manifest.pages)
    selected: set[str] = set()
    for page in critique.pages:
        if page.page_id not in page_ids:
            raise HumanReviewDecisionError("Q4 page identity differs from RenderManifest")
        if any(issue.severity == "critical" for issue in page.issues) or sum(
            getattr(page, dimension) < 70
            for dimension in (
                "hierarchy", "readability", "composition", "whitespace",
                "visual_focus", "asset_integration",
            )
        ) >= 2:
            selected.add(page.page_id)
    for issue in critique.set_evaluation.issues:
        if any(page_id not in page_ids for page_id in issue.page_ids):
            raise HumanReviewDecisionError("Q4 set issue identity differs from RenderManifest")
        selected.update(issue.page_ids)
    if critique.set_evaluation.rhythm < 70 or critique.set_evaluation.repetition < 70:
        selected.update(page_ids)
    return tuple(page_id for page_id in page_ids if page_id in selected) or page_ids


def _normalized_failures(
    intent: HumanReviewIntentV4,
    inputs: ReviewWorkspaceInputsV4,
    assets: tuple[Any, ...],
) -> tuple[NormalizedFailureV4, ...]:
    if intent.action == "REJECT_OR_REPLACE_ASSET":
        by_id = {asset.item.asset_id: asset for asset in assets}
        unknown = set(intent.asset_ids) - set(by_id)
        if unknown:
            raise HumanReviewDecisionError("asset rejection names an unused or unrendered asset")
        failures = []
        for asset_id in sorted(intent.asset_ids):
            item = by_id[asset_id].item
            fingerprint = FailureFingerprintV4.create(
                node="V4_HUMAN_REVIEW",
                page_id=item.page_id,
                failure_code="HUMAN_REVIEW_ASSET_REJECTED",
                geometry_region=item.asset_id,
            )
            failures.append(NormalizedFailureV4.from_fingerprint(fingerprint))
        return tuple(failures)
    if intent.action != "REQUEST_REVISION":
        return ()
    failures = []
    for page_id in _page_ids_for_aesthetic(inputs):
        fingerprint = FailureFingerprintV4.create(
            node="V4_VISUAL_CRITIC",
            page_id=page_id,
            failure_code="AESTHETIC_REVIEW_FAILED",
            geometry_region=None,
        )
        failures.append(NormalizedFailureV4.from_fingerprint(fingerprint))
    return tuple(failures)


def _revision_request(
    failures: tuple[NormalizedFailureV4, ...],
    inputs: ReviewWorkspaceInputsV4,
    history: tuple[RevisionEventV4, ...],
) -> RevisionRequestV4 | None:
    if not failures:
        return None
    candidate_id = inputs.artifact_paths.identity.candidate_id
    prior = history[-1].revision_id if history else None
    try:
        return route_revision(
            failures,
            history,
            candidate_id=candidate_id,
            prior_revision_id=prior,
            page_brief_set=inputs.page_brief_set,
            carousel_design_plan=inputs.carousel_design_plan,
        )
    except VisualExecutionInterrupted:
        # Preserve Task 14's typed budget interruption so the caller can
        # create a fresh candidate instead of mistaking exhaustion for a
        # malformed human action.
        raise
    except Exception as error:
        raise HumanReviewDecisionError("human review action exceeds the typed revision budget") from error


def _asset_decisions(
    intent: HumanReviewIntentV4,
    assets: tuple[Any, ...],
) -> tuple[AssetReviewDecisionV4, ...]:
    if intent.action not in {"APPROVE", "AESTHETIC_OVERRIDE", "REJECT_OR_REPLACE_ASSET"}:
        return ()
    rejected = set(intent.asset_ids) if intent.action == "REJECT_OR_REPLACE_ASSET" else set()
    if intent.action == "REJECT_OR_REPLACE_ASSET" and not rejected:
        raise HumanReviewDecisionError("asset replacement requires at least one rendered asset")
    decisions = []
    for asset in sorted(assets, key=lambda value: value.item.asset_id):
        action = "rejected" if asset.item.asset_id in rejected else "approved"
        decisions.append(
            AssetReviewDecisionV4.create(
                asset_id=asset.item.asset_id,
                asset_sha256=asset.sha256,
                decision=action,
                rationale=intent.rationale if action == "rejected" else None,
            )
        )
    return tuple(decisions)


def _decision_from_intent(
    intent: HumanReviewIntentV4,
    inputs: ReviewWorkspaceInputsV4,
    hashes: Mapping[str, str],
    assets: tuple[Any, ...],
    *,
    clock: Callable[[], object] | None,
    decision_id_factory: Callable[[], str] | None,
    current_package: Mapping[str, Any] | None,
) -> tuple[HumanReviewDecisionV4, Mapping[str, Any] | None, str | None]:
    q4 = inputs.visual_critique
    if type(q4) is not CarouselAestheticEvaluationV4:
        raise HumanReviewDecisionError("current Q4 critique is not exact")
    q4.validate_integrity()
    if intent.action == "APPROVE" and not q4.passed:
        raise HumanReviewDecisionError("APPROVE requires a current passed Q4")
    if intent.action == "AESTHETIC_OVERRIDE":
        _require_substantive_rationale(intent)
        if q4.passed:
            raise HumanReviewDecisionError("AESTHETIC_OVERRIDE is valid only for a failed Q4")
    edited_package: Mapping[str, Any] | None = None
    visible_hash: str | None = None
    visible_result_hash: str | None = None
    if intent.action == "VISIBLE_COPY_EDIT":
        edited_package, visible_hash, visible_result_hash = _visible_copy_edit(
            intent, current_package
        )
    decision_id = decision_id_factory() if decision_id_factory is not None else f"decision-{uuid4().hex}"
    decision_id = _identity(decision_id, "decision_id")
    rationale = intent.feedback if intent.action == "REQUEST_REVISION" else intent.rationale
    page_hashes = {
        f"pages/{page.sequence:02d}-{page.page_id}.png": page.sha256
        for page in inputs.render_manifest.pages
    }
    decision = HumanReviewDecisionV4.create(
        decision_id=decision_id,
        decided_at=_clock_text(clock),
        run_id=inputs.artifact_paths.identity.run_id,
        candidate_id=inputs.artifact_paths.identity.candidate_id,
        revision_id=inputs.artifact_paths.identity.revision_id,
        action=intent.action,
        rationale=rationale,
        content_lock_sha256=hashes["content_lock_sha256"],
        asset_manifest_sha256=hashes["asset_manifest_sha256"],
        carousel_design_plan_sha256=hashes["carousel_design_plan_sha256"],
        design_plan_qa_sha256=hashes["design_plan_qa_sha256"],
        render_manifest_sha256=hashes["render_manifest_sha256"],
        render_qa_sha256=hashes["render_qa_sha256"],
        visual_critique_sha256=hashes["visual_critique_sha256"],
        page_sha256=page_hashes,
        contact_sheet_sha256=inputs.render_manifest.contact_sheet_sha256,
        asset_decisions=_asset_decisions(intent, assets),
        visible_copy_payload_sha256=visible_hash,
        visible_copy_result_sha256=visible_result_hash,
    )
    return decision, edited_package, visible_result_hash


def _append_decision_record(paths: Any, raw: bytes) -> None:
    try:
        with _lease_context(_open_absolute_directory(paths.revision_root, create=False)) as lease:
            lease.assert_intact()
            _atomic_write_at(lease.fd, (_DECISION_RECORD,), raw, replace_existing=False)
            lease.assert_intact()
    except (ArtifactBindingError, ArtifactIdentityError, OSError) as error:
        raise HumanReviewDecisionError("terminal human review decision already exists or cannot be appended") from error


def _read_decision_record(workspace: ReviewWorkspaceV4, reference: HumanReviewDecisionReferenceV4) -> tuple[HumanReviewDecisionV4, bytes]:
    try:
        if type(workspace) is not ReviewWorkspaceV4 or type(workspace.reference) is not ReviewWorkspaceReferenceV4:
            raise HumanReviewDecisionError(
                "terminal decision record requires an externally-authorized workspace"
            )
        if type(reference) is not HumanReviewDecisionReferenceV4:
            raise HumanReviewDecisionError("terminal decision reference is not exact")
        HumanReviewDecisionReferenceV4.model_validate(
            reference.model_dump(mode="python")
        )
        try:
            verify_review_workspace(workspace)
        except ReviewBindingError as error:
            raise HumanReviewDecisionError(
                "terminal decision workspace is stale or unauthorized"
            ) from error
        if reference.workspace_reference_sha256 != workspace.reference.canonical_sha256:
            raise HumanReviewDecisionError(
                "terminal decision reference is bound to a different workspace"
            )
        if reference.record_path != _DECISION_RECORD:
            raise HumanReviewDecisionError("terminal decision record path is not canonical")
        paths = revalidate_artifact_paths(workspace.artifact_paths)
        snapshot = read_verified_artifact_snapshot(
            paths.revision_root / reference.record_path,
            reference.decision_raw_sha256,
            containment_root=paths.revision_root,
        )
        decision = HumanReviewDecisionV4.model_validate_json(snapshot.raw)
        canonical = _canonical_decision_bytes(decision)
        if (
            snapshot.raw != canonical
            or decision.canonical_sha256 != reference.decision_canonical_sha256
            or (decision.run_id, decision.candidate_id, decision.revision_id, decision.decision_id)
            != (reference.run_id, reference.candidate_id, reference.revision_id, reference.decision_id)
        ):
            raise HumanReviewDecisionError("terminal decision record is non-canonical or stale")
        return decision, snapshot.raw
    except HumanReviewDecisionError:
        raise
    except (ArtifactBindingError, ArtifactIdentityError, ValueError, OSError) as error:
        raise HumanReviewDecisionError("terminal decision record is missing or unsafe") from error


def read_human_review_decision(
    workspace: ReviewWorkspaceV4,
    reference: HumanReviewDecisionReferenceV4,
) -> HumanReviewDecisionV4:
    """Load one decision record through its externally-authorized reference."""

    decision, _ = _read_decision_record(workspace, reference)
    return decision


def _verify_decision_binding(
    decision: HumanReviewDecisionV4,
    reference: HumanReviewDecisionReferenceV4,
    workspace: ReviewWorkspaceV4,
    inputs: ReviewWorkspaceInputsV4,
    *,
    current_package: Mapping[str, Any] | None = None,
) -> tuple[dict[str, str], tuple[Any, ...]]:
    if type(reference) is not HumanReviewDecisionReferenceV4:
        raise HumanReviewDecisionError("decision verification requires an exact reference")
    try:
        HumanReviewDecisionReferenceV4.model_validate(
            reference.model_dump(mode="python")
        )
    except Exception as error:
        raise HumanReviewDecisionError("decision reference integrity is invalid") from error
    if workspace.reference is None:
        raise HumanReviewDecisionError("decision verification requires an external workspace reference")
    expected_identity = inputs.artifact_paths.identity
    if (decision.run_id, decision.candidate_id, decision.revision_id) != (
        expected_identity.run_id,
        expected_identity.candidate_id,
        expected_identity.revision_id,
    ) or (reference.run_id, reference.candidate_id, reference.revision_id) != (
        expected_identity.run_id,
        expected_identity.candidate_id,
        expected_identity.revision_id,
    ):
        raise HumanReviewDecisionError("decision/reference identity does not match current revision")
    if reference.workspace_reference_sha256 != workspace.reference.canonical_sha256:
        raise HumanReviewDecisionError("decision reference is bound to a different workspace anchor")
    if reference.decision_id != decision.decision_id:
        raise HumanReviewDecisionError("decision reference names a different decision")
    hashes, assets = _workspace_source(workspace, inputs)
    for field in (
        "content_lock_sha256", "asset_manifest_sha256", "carousel_design_plan_sha256",
        "design_plan_qa_sha256", "render_manifest_sha256", "render_qa_sha256",
        "visual_critique_sha256",
    ):
        if getattr(decision, field) != hashes[field]:
            raise HumanReviewDecisionError(f"decision {field} differs from current source")
    page_hashes = {
        f"pages/{page.sequence:02d}-{page.page_id}.png": page.sha256
        for page in inputs.render_manifest.pages
    }
    if dict(decision.page_sha256) != page_hashes:
        raise HumanReviewDecisionError("decision page hashes differ from current source")
    if decision.contact_sheet_sha256 != inputs.render_manifest.contact_sheet_sha256:
        raise HumanReviewDecisionError("decision contact-sheet hash differs from current source")
    expected_assets = tuple(
        AssetReviewDecisionV4.create(
            asset_id=asset.item.asset_id,
            asset_sha256=asset.sha256,
            decision="approved",
        )
        for asset in sorted(assets, key=lambda value: value.item.asset_id)
    )
    if decision.action in {"APPROVE", "AESTHETIC_OVERRIDE"}:
        if tuple(decision.asset_decisions) != expected_assets:
            raise HumanReviewDecisionError("decision does not approve every current rendered asset byte")
    elif decision.action == "REJECT_OR_REPLACE_ASSET":
        if not decision.asset_decisions or tuple(item.asset_id for item in decision.asset_decisions) != tuple(sorted(item.item.asset_id for item in assets)):
            raise HumanReviewDecisionError("asset replacement decision does not cover the rendered asset set")
        if not any(item.decision == "rejected" for item in decision.asset_decisions):
            raise HumanReviewDecisionError("asset replacement decision has no rejected rendered asset")
        expected_by_id = {asset.item.asset_id: asset.sha256 for asset in assets}
        if any(item.asset_sha256 != expected_by_id.get(item.asset_id) for item in decision.asset_decisions):
            raise HumanReviewDecisionError("asset replacement decision binds stale asset bytes")
    elif decision.action == "VISIBLE_COPY_EDIT":
        if not decision.visible_copy_payload_sha256:
            raise HumanReviewDecisionError("visible-copy decision has no derived payload hash")
        if not decision.visible_copy_result_sha256:
            raise HumanReviewDecisionError("visible-copy decision has no resulting package hash")
        if not isinstance(current_package, Mapping):
            raise HumanReviewDecisionError(
                "visible-copy decision verification requires the exact resulting package"
            )
        if decision.visible_copy_result_sha256 != canonical_sha256_v4(current_package):
            raise HumanReviewDecisionError(
                "visible-copy decision resulting package hash differs from current package"
            )
    if decision.action == "APPROVE" and not inputs.visual_critique.passed:
        raise HumanReviewDecisionError("approved decision is not allowed for failed Q4")
    if decision.action == "AESTHETIC_OVERRIDE":
        if inputs.visual_critique.passed or len((decision.rationale or "").strip()) < 8:
            raise HumanReviewDecisionError("aesthetic override no longer matches current Q4")
    if reference.decision_raw_sha256 != _sha(_canonical_decision_bytes(decision)):
        raise HumanReviewDecisionError("decision reference raw hash is stale")
    return hashes, assets


def verify_human_review_decision(
    decision: HumanReviewDecisionV4,
    reference: HumanReviewDecisionReferenceV4,
    workspace: ReviewWorkspaceV4,
    inputs: ReviewWorkspaceInputsV4,
    *,
    current_package: Mapping[str, Any] | None = None,
) -> HumanReviewDecisionV4:
    """Reopen and verify every source/decision byte before routing."""

    if type(decision) is not HumanReviewDecisionV4:
        raise HumanReviewDecisionError("decision must be exact HumanReviewDecisionV4")
    try:
        HumanReviewDecisionV4.model_validate(decision.model_dump(mode="python"))
    except Exception as error:
        raise HumanReviewDecisionError("decision integrity is invalid") from error
    stored, raw = _read_decision_record(workspace, reference)
    if stored != decision or raw != _canonical_decision_bytes(decision):
        raise HumanReviewDecisionError("caller decision differs from append-only decision record")
    _verify_decision_binding(decision, reference, workspace, inputs, current_package=current_package)
    # Re-open the append-only record after source verification as well.  This
    # narrows the mutable-file TOCTOU window: a caller cannot obtain a valid
    # route after the record is replaced while the source bytes are being
    # rechecked.
    stored_again, raw_again = _read_decision_record(workspace, reference)
    if stored_again != decision or raw_again != raw:
        raise HumanReviewDecisionError("append-only decision record changed during verification")
    return decision


def _state_clears(*names: str) -> dict[str, None]:
    return {name: None for name in names}


def _action_route(action: ReviewActionV4) -> HumanReviewRouteV4:
    return {
        "APPROVE": "final_policy_guard",
        "AESTHETIC_OVERRIDE": "final_policy_guard",
        "REQUEST_REVISION": "revision",
        "REJECT_OR_REPLACE_ASSET": "asset_resolver",
        "VISIBLE_COPY_EDIT": "r2_compliance",
    }[action]


_ROUTE_SOURCE_CONTRACTS = (
    "content_lock", "content_atom_set", "semantic_content_model",
    "carousel_narrative", "page_brief_set", "visual_direction_plan",
    "asset_manifest", "carousel_design_plan", "design_plan_qa",
    "render_manifest", "render_qa", "visual_critique",
    "asset_resolution_result", "previous_review_workspace",
)
_ROUTE_PATH_FIELDS = (
    "base_root", "run_root", "candidate_root", "revision_root", "asset_root",
    "render_root", "review_root", "artifact_root",
)
_ROUTE_CONTRACT_TYPES = {
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
    "asset_resolution_result": AssetResolutionResult,
}


def _route_paths_payload(paths: ArtifactPaths) -> dict[str, Any]:
    """Serialize every exact path identity needed to rehydrate a route context."""

    if type(paths) is not ArtifactPaths or paths.trusted_base_identity is None:
        raise HumanReviewDecisionError("route context requires pinned ArtifactPaths")
    payload: dict[str, Any] = {
        field: str(getattr(paths, field)) for field in _ROUTE_PATH_FIELDS
    }
    payload["identity"] = {
        "run_id": paths.identity.run_id,
        "candidate_id": paths.identity.candidate_id,
        "revision_id": paths.identity.revision_id,
    }
    payload["trusted_base_identity"] = list(paths.trusted_base_identity)
    return payload


def _route_workspace_payload(workspace: ReviewWorkspaceV4) -> dict[str, Any]:
    if (
        type(workspace) is not ReviewWorkspaceV4
        or type(workspace.reference) is not ReviewWorkspaceReferenceV4
    ):
        raise HumanReviewDecisionError(
            "route context requires an externally-authorized workspace"
        )
    try:
        manifest_raw = workspace.manifest_raw.decode("utf-8")
    except (AttributeError, UnicodeDecodeError) as error:
        raise HumanReviewDecisionError(
            "route context workspace manifest is not canonical UTF-8"
        ) from error
    return {
        "root": str(workspace.root),
        "artifact_paths": _route_paths_payload(workspace.artifact_paths),
        "manifest": _route_json_payload(workspace.manifest),
        "manifest_raw": manifest_raw,
        "reference": _route_json_payload(workspace.reference),
    }


def _route_json_payload(value: Any) -> Any:
    if value is None:
        return None
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _route_json_payload(model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _route_json_payload(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_route_json_payload(item) for item in value]
    return value


def _build_route_context(
    decision: HumanReviewDecisionV4,
    reference: HumanReviewDecisionReferenceV4,
    workspace: ReviewWorkspaceV4,
    inputs: ReviewWorkspaceInputsV4,
    *,
    route: HumanReviewRouteV4,
    edited_package: Mapping[str, Any] | None,
) -> HumanReviewRouteContextV4:
    source_contracts = {
        name: (
            None
            if getattr(inputs, name) is None
            else (
                _route_workspace_payload(getattr(inputs, name))
                if name == "previous_review_workspace"
                else _route_json_payload(getattr(inputs, name))
            )
        )
        for name in _ROUTE_SOURCE_CONTRACTS
    }
    try:
        return HumanReviewRouteContextV4.create(
            route=route,
            decision=decision,
            reference=reference,
            workspace_reference=workspace.reference,
            artifact_paths=_route_paths_payload(inputs.artifact_paths),
            workspace_manifest=_route_json_payload(workspace.manifest),
            workspace_manifest_raw=workspace.manifest_raw.decode("utf-8"),
            source_contracts=source_contracts,
            current_package=(
                None if edited_package is None else _route_json_payload(edited_package)
            ),
        )
    except (UnicodeDecodeError, TypeError, ValueError) as error:
        raise HumanReviewDecisionError(
            "verified Human Review action could not be retained as route context"
        ) from error


def _restore_route_paths(payload: Mapping[str, Any]) -> ArtifactPaths:
    if not isinstance(payload, Mapping):
        raise HumanReviewDecisionError("route context ArtifactPaths are malformed")
    identity_payload = payload.get("identity")
    if not isinstance(identity_payload, Mapping):
        raise HumanReviewDecisionError("route context ArtifactPaths identity is missing")
    try:
        identity = ArtifactIdentity(
            run_id=identity_payload["run_id"],
            candidate_id=identity_payload["candidate_id"],
            revision_id=identity_payload["revision_id"],
        )
        expected = resolve_artifact_paths(payload["base_root"], identity)
    except (KeyError, ArtifactIdentityError, TypeError, ValueError) as error:
        raise HumanReviewDecisionError(
            "route context ArtifactPaths are unsafe or malformed"
        ) from error
    if any(
        type(payload.get(field)) is not str
        or Path(payload[field]) != getattr(expected, field)
        for field in _ROUTE_PATH_FIELDS
    ):
        raise HumanReviewDecisionError("route context ArtifactPaths drifted")
    trusted = payload.get("trusted_base_identity")
    if not isinstance(trusted, (tuple, list)) or tuple(trusted) != expected.trusted_base_identity:
        raise HumanReviewDecisionError("route context ArtifactPaths base identity drifted")
    try:
        return revalidate_artifact_paths(expected)
    except (ArtifactIdentityError, ArtifactBindingError, OSError) as error:
        raise HumanReviewDecisionError("route context ArtifactPaths are stale or unsafe") from error


def _restore_route_model(name: str, value: Any) -> Any:
    contract_type = _ROUTE_CONTRACT_TYPES.get(name)
    if contract_type is None:
        raise HumanReviewDecisionError("route context contains an unknown source contract")
    if not isinstance(value, Mapping):
        raise HumanReviewDecisionError(f"route context source contract is missing: {name}")
    try:
        restored = contract_type.model_validate_json(canonical_json_v4(value).encode("utf-8"))
    except Exception as error:
        raise HumanReviewDecisionError(
            f"route context source contract is malformed: {name}"
        ) from error
    if type(restored) is not contract_type:
        raise HumanReviewDecisionError(f"route context source contract is not exact: {name}")
    return restored


def _restore_route_workspace(
    payload: Mapping[str, Any],
) -> ReviewWorkspaceV4:
    if not isinstance(payload, Mapping):
        raise HumanReviewDecisionError("previous route workspace is malformed")
    paths = _restore_route_paths(payload.get("artifact_paths"))
    try:
        manifest = ReviewWorkspaceManifestV4.model_validate_json(
            canonical_json_v4(payload["manifest"]).encode("utf-8")
        )
        reference = ReviewWorkspaceReferenceV4.model_validate_json(
            canonical_json_v4(payload["reference"]).encode("utf-8")
        )
        root = Path(payload["root"])
        raw = payload["manifest_raw"].encode("utf-8")
    except (KeyError, TypeError, ValueError, UnicodeError) as error:
        raise HumanReviewDecisionError("route workspace payload is malformed") from error
    if root != paths.review_root or raw != canonical_json_v4(
        manifest.model_dump(mode="json")
    ).encode("utf-8"):
        raise HumanReviewDecisionError("route workspace manifest bytes are stale")
    return ReviewWorkspaceV4(
        root,
        manifest,
        paths,
        manifest_raw=raw,
        reference=reference,
    )


def _restore_route_context_inputs(
    context: HumanReviewRouteContextV4,
) -> tuple[ReviewWorkspaceV4, ReviewWorkspaceInputsV4]:
    paths = _restore_route_paths(context.artifact_paths)
    try:
        manifest = ReviewWorkspaceManifestV4.model_validate_json(
            canonical_json_v4(context.workspace_manifest).encode("utf-8")
        )
        manifest_raw = context.workspace_manifest_raw.encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise HumanReviewDecisionError("route context workspace manifest is malformed") from error
    if manifest_raw != canonical_json_v4(manifest.model_dump(mode="json")).encode("utf-8"):
        raise HumanReviewDecisionError("route context workspace manifest bytes are stale")
    workspace = ReviewWorkspaceV4(
        paths.review_root,
        manifest,
        paths,
        manifest_raw=manifest_raw,
        reference=context.workspace_reference,
    )
    source = context.source_contracts
    values: dict[str, Any] = {
        "artifact_paths": paths,
        **{
            name: (
                None
                if source[name] is None
                else _restore_route_model(name, source[name])
            )
            for name in _ROUTE_SOURCE_CONTRACTS
            if name not in {"previous_review_workspace"}
        },
        "previous_review_workspace": (
            None
            if source["previous_review_workspace"] is None
            else _restore_route_workspace(source["previous_review_workspace"])
        ),
    }
    try:
        inputs = ReviewWorkspaceInputsV4(**values)
    except Exception as error:
        raise HumanReviewDecisionError("route context source contracts are malformed") from error
    return workspace, inputs


def _route_context_evidence(
    context: HumanReviewRouteContextV4,
) -> HumanReviewRouteEvidenceV4:
    return HumanReviewRouteEvidenceV4.create(
        run_id=context.decision.run_id,
        candidate_id=context.decision.candidate_id,
        revision_id=context.decision.revision_id,
        decision_id=context.decision.decision_id,
        action=context.decision.action,
        route=context.route,
        workspace_reference_sha256=context.reference.workspace_reference_sha256,
        decision_raw_sha256=context.reference.decision_raw_sha256,
        decision_canonical_sha256=context.decision.canonical_sha256,
        route_context_sha256=context.canonical_sha256,
    )


def _state_patch(
    decision: HumanReviewDecisionV4,
    reference: HumanReviewDecisionReferenceV4,
    workspace: ReviewWorkspaceV4,
    *,
    route: HumanReviewRouteV4,
    request: RevisionRequestV4 | None,
    failures: tuple[NormalizedFailureV4, ...],
    edited_package: Mapping[str, Any] | None,
    route_context: HumanReviewRouteContextV4,
    route_evidence: HumanReviewRouteEvidenceV4,
) -> dict[str, Any]:
    patch: dict[str, Any] = {
        "human_review_decision": decision,
        "human_review_decision_reference": reference,
        "review_route": route,
        "route": route,
        "visual_route": route,
        "current_node": "V4_HUMAN_REVIEW",
        # These are historical/transient route evidence.  They intentionally
        # remain separate from the current artifact slots that non-final
        # actions invalidate, so downstream routing can re-open verification.
        "human_review_route_context_v4": route_context,
        "human_review_route_evidence_v4": route_evidence,
        "human_review_history_v4": reference,
        "human_review_terminal_decision_v4": decision,
        "human_review_terminal_reference_v4": reference,
    }
    if route == "final_policy_guard":
        patch.update(
            human_review_decision_v4=decision,
            human_review_decision_reference_v4=reference,
            review_status="approved",
            review_workspace=workspace,
            review_workspace_reference=workspace.reference,
            review_workspace_v4=workspace,
            review_workspace_reference_v4=workspace.reference,
            visual_aesthetic_override=(decision.action == "AESTHETIC_OVERRIDE"),
        )
        return patch
    patch.update(
        _state_clears(
            "human_review_decision",
            "human_review_decision_reference",
            "human_review_decision_v4",
            "human_review_decision_reference_v4",
            "review_workspace",
            "review_workspace_reference",
            "review_workspace_v4",
            "review_workspace_reference_v4",
            "final_policy_attestation",
            "final_policy_attestation_v4",
            "final_policy_issues",
        )
    )
    patch.update(
        review_status={
            "revision": "revision_requested",
            "asset_resolver": "asset_replacement_requested",
            "r2_compliance": "needs_r2_recheck",
        }[route],
        revision_invalidation_v4=None if request is None else request.invalidation,
        normalized_failures_v4=failures,
        human_review_revision_request_v4=request,
        visual_aesthetic_override=None,
    )
    if route == "revision":
        # ``revision_node`` derives its own request from these typed failures;
        # never publish a caller/request supplied ``revision_request_v4`` key.
        patch.update(
            _state_clears(
                "visual_critique", "visual_critique_v4", "revision_request", "review_feedback",
            )
        )
        patch["review_feedback"] = decision.rationale
    elif route == "asset_resolver":
        patch.update(
            _state_clears(
                "asset_manifest", "asset_resolution_result", "asset_transaction_evidence",
                "asset_manifest_v4", "asset_resolution_result_v4", "assets",
                "unresolved_optional_assets", "carousel_design_plan", "carousel_design_plan_v4",
                "layout_programs", "composition_plan", "design_metrics_qa_result",
                "design_plan_qa_result", "design_plan_qa_result_v4", "render_manifest",
                "render_manifest_v4", "render_qa_result", "render_qa_result_v4",
                "visual_critique", "visual_critique_v4", "revision_request",
                "revision_request_v4", "review_feedback",
            )
        )
        patch["review_feedback"] = decision.rationale
    else:
        from src.nodes.v4.content import invalidate_visible_copy_artifacts

        if edited_package is None:
            raise HumanReviewDecisionError("visible-copy route has no changed package")
        patch.update(invalidate_visible_copy_artifacts())
        patch.update(
            _state_clears(
                "review_workspace", "review_workspace_reference",
                "review_workspace_v4", "review_workspace_reference_v4",
                "human_review_decision", "human_review_decision_reference",
                "human_review_decision_v4", "human_review_decision_reference_v4",
                "revision_request", "revision_request_v4", "human_review_revision_request_v4",
                "revision_invalidation_v4", "normalized_failures_v4", "review_feedback",
                "asset_transaction_evidence", "unresolved_optional_assets",
            )
        )
        patch.update(
            publish_package=dict(edited_package),
            r2_input_v4=dict(edited_package),
            review_feedback=decision.rationale,
        )
    return patch


def submit_human_review_intent(
    workspace: ReviewWorkspaceV4,
    inputs: ReviewWorkspaceInputsV4,
    intent: HumanReviewIntentV4 | Mapping[str, Any],
    *,
    revision_history: tuple[RevisionEventV4, ...] = (),
    clock: Callable[[], object] | None = None,
    decision_id_factory: Callable[[], str] | None = None,
    current_package: Mapping[str, Any] | None = None,
) -> HumanReviewActionResultV4:
    """Derive, append and immediately verify one terminal human action."""

    parsed_intent = _intent(intent)
    history = _history(revision_history)
    hashes, assets = _workspace_source(workspace, inputs)
    # Validate rendered-asset membership before constructing the immutable
    # record.  This keeps an invalid asset request from surfacing as a schema
    # error for a partially-derived decision and, more importantly, guarantees
    # that no record is ever appended for an unrendered asset.
    if parsed_intent.action == "REJECT_OR_REPLACE_ASSET":
        rendered_ids = {asset.item.asset_id for asset in assets}
        if not parsed_intent.asset_ids or not set(parsed_intent.asset_ids) <= rendered_ids:
            raise HumanReviewDecisionError(
                "asset rejection names an unused or unrendered asset"
            )
    decision, edited_package, _ = _decision_from_intent(
        parsed_intent,
        inputs,
        hashes,
        assets,
        clock=clock,
        decision_id_factory=decision_id_factory,
        current_package=current_package,
    )
    failures = _normalized_failures(parsed_intent, inputs, assets)
    request = _revision_request(failures, inputs, history)
    raw = _canonical_decision_bytes(decision)
    _append_decision_record(inputs.artifact_paths, raw)
    reference = HumanReviewDecisionReferenceV4.create(
        run_id=decision.run_id,
        candidate_id=decision.candidate_id,
        revision_id=decision.revision_id,
        decision_id=decision.decision_id,
        workspace_reference_sha256=workspace.reference.canonical_sha256,
        decision_raw_sha256=_sha(raw),
        decision_canonical_sha256=decision.canonical_sha256,
    )
    # Verification is deliberately performed before returning a route.  If a
    # source changes between derivation and handoff, the terminal record stays
    # append-only but no false approval/route is emitted.
    verify_human_review_decision(
        decision,
        reference,
        workspace,
        inputs,
        current_package=edited_package if edited_package is not None else current_package,
    )
    route = _action_route(decision.action)
    route_context = _build_route_context(
        decision,
        reference,
        workspace,
        inputs,
        route=route,
        edited_package=edited_package,
    )
    route_evidence = _route_context_evidence(route_context)
    patch = _state_patch(
        decision,
        reference,
        workspace,
        route=route,
        request=request,
        failures=failures,
        edited_package=edited_package,
        route_context=route_context,
        route_evidence=route_evidence,
    )
    return HumanReviewActionResultV4(
        decision=decision,
        reference=reference,
        route=route,
        route_context=route_context,
        route_evidence=route_evidence,
        state_patch=MappingProxyType(patch),
        revision_request=request,
        normalized_failures=failures,
        edited_publish_package=None if edited_package is None else MappingProxyType(dict(edited_package)),
    )


def approve_workspace(*args: Any, **kwargs: Any) -> HumanReviewActionResultV4:
    """Compatibility convenience: submit an application-owned APPROVE intent."""

    kwargs.setdefault("intent", HumanReviewIntentV4(action="APPROVE"))
    return submit_human_review_intent(*args, **kwargs)


def _verified_route_context(
    context: HumanReviewRouteContextV4,
    evidence: HumanReviewRouteEvidenceV4,
) -> HumanReviewRouteV4:
    """Rebuild exact inputs and invoke the public verifier before routing.

    Route evidence is checked as an internal consistency record only.  It is
    never accepted as a capability: the decision record, external workspace
    reference, fresh Q0-Q3 source, page/contact/asset bytes and raw digest are
    reopened by ``verify_human_review_decision`` on every invocation.
    """

    if type(context) is not HumanReviewRouteContextV4 or type(evidence) is not HumanReviewRouteEvidenceV4:
        raise HumanReviewDecisionError(
            "v4 Human Review route requires a verified action context and evidence"
        )
    expected_route = _action_route(context.decision.action)
    if context.route != expected_route:
        raise HumanReviewDecisionError("verified action route evidence is stale")
    try:
        expected_evidence = _route_context_evidence(context)
    except Exception as error:
        raise HumanReviewDecisionError("verified action route evidence is malformed") from error
    if evidence != expected_evidence:
        raise HumanReviewDecisionError("verified action route evidence is stale")
    workspace, inputs = _restore_route_context_inputs(context)
    package = context.current_package
    try:
        checked = verify_human_review_decision(
            context.decision,
            context.reference,
            workspace,
            inputs,
            current_package=package,
        )
    except HumanReviewDecisionError:
        raise
    except Exception as error:
        raise HumanReviewDecisionError(
            "verified action could not be revalidated against current bytes"
        ) from error
    if _action_route(checked.action) != context.route:
        raise HumanReviewDecisionError("verified action route differs from context")
    return context.route


def route_after_human_review_v4(
    value: HumanReviewActionResultV4 | Mapping[str, Any],
) -> HumanReviewRouteV4:
    """Derive a closed route from a retained exact terminal action context.

    Non-final state patches clear current decision/workspace slots, so callers
    must use the historical ``human_review_route_context_v4`` and its matching
    evidence.  Legacy/synthetic mappings containing only decision hashes are
    intentionally rejected.
    """

    if type(value) is HumanReviewActionResultV4:
        context = value.route_context
        evidence = value.route_evidence
        if value.route != context.route:
            raise HumanReviewDecisionError("verified action route evidence is stale")
    elif isinstance(value, Mapping):
        context = value.get("human_review_route_context_v4")
        evidence = value.get("human_review_route_evidence_v4")
        if type(context) is not HumanReviewRouteContextV4 or type(evidence) is not HumanReviewRouteEvidenceV4:
            raise HumanReviewDecisionError(
                "v4 Human Review route requires a verified action context and evidence"
            )
        for route_key in ("route", "review_route", "visual_route"):
            route_hint = value.get(route_key)
            if route_hint is not None and route_hint != context.route:
                raise HumanReviewDecisionError("verified action route evidence is stale")
    else:
        raise HumanReviewDecisionError(
            "v4 Human Review route requires a verified action context and evidence"
        )
    return _verified_route_context(context, evidence)


def clear_human_review_route_context_v4() -> dict[str, None]:
    """Return the explicit downstream patch that retires historical route evidence."""

    return _state_clears(
        "human_review_route_context_v4",
        "human_review_route_evidence_v4",
        "human_review_history_v4",
        "human_review_terminal_decision_v4",
        "human_review_terminal_reference_v4",
    )


__all__ = [
    "HumanReviewActionResultV4",
    "HumanReviewDecisionError",
    "HumanReviewRouteV4",
    "approve_workspace",
    "clear_human_review_route_context_v4",
    "read_human_review_decision",
    "route_after_human_review_v4",
    "submit_human_review_intent",
    "verify_human_review_decision",
]
