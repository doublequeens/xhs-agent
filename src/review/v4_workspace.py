"""Transactional, local-only review workspaces for one immutable v4 revision.

The workspace is an evidence projection, never a second source of editorial
truth. Every file shown in the offline review is copied from a
descriptor-relative verified snapshot or generated from the exact Q0-Q4
contracts. ``decision.json`` is mutable intake and is excluded from the
static workspace manifest; Task 16B derives an immutable decision record from
it.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict

from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.content_atoms import canonical_sha256
from src.schemas.content_lock import ContentLock
from src.schemas.v4.content import ContentAtomSetV4, canonical_json_v4
from src.schemas.v4.critique import CarouselAestheticEvaluationV4
from src.schemas.v4.direction import CarouselNarrativeV4, PageBriefSetV4, VisualDirectionPlanV4
from src.schemas.v4.layout import CarouselDesignPlanV4
from src.schemas.v4.quality import DesignPlanQAResultV4
from src.schemas.v4.rendering import RenderManifestV4, RenderQAResultV4
from src.schemas.v4.review import HumanReviewIntentV4, ReviewWorkspaceManifestV4
from src.schemas.v4.semantic import SemanticContentModelV4
from src.visual_runtime.artifact_identity import (
    ArtifactBindingError,
    ArtifactIdentityError,
    ArtifactPaths,
    _atomic_write_at,
    _lease_context,
    _open_absolute_directory,
    _remove_tree_at,
    publish_staged_directory_at,
    quarantine_directory_at,
    read_verified_artifact_snapshot,
    read_verified_artifact_snapshot_at,
    revalidate_artifact_paths,
)
from src.nodes.v4.design_qa import aggregate_design_qa
from src.visual_design.v4.authoring_qa import evaluate_authoring
from src.visual_design.v4.render_qa import evaluate_v4_render
from src.visual_design.v4.semantic_qa import evaluate_semantic_model
from src.visual_design.v4.tokens import get_family_tokens


class ReviewBindingError(RuntimeError):
    """A review source or materialized workspace is stale, forged, or unsafe."""


_WORKSPACE_TRUST_TOKEN = object()
_WORKSPACE_TRUST_SECRET = uuid.uuid4().hex


@dataclass(frozen=True, slots=True)
class ReviewWorkspaceV4:
    """Typed, application-issued handle for one verified immutable workspace."""

    root: Path
    manifest: ReviewWorkspaceManifestV4
    artifact_paths: ArtifactPaths
    manifest_raw: bytes = b""
    _trust_token: object | None = field(default=None, repr=False, compare=False)
    _attestation: str | None = field(default=None, repr=False, compare=False)


class ReviewWorkspaceInputsV4(BaseModel):
    """The exact source contracts used to build one review workspace."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)
    artifact_paths: ArtifactPaths
    content_lock: ContentLock
    content_atom_set: ContentAtomSetV4
    semantic_content_model: SemanticContentModelV4
    carousel_narrative: CarouselNarrativeV4
    page_brief_set: PageBriefSetV4
    visual_direction_plan: VisualDirectionPlanV4
    asset_manifest: AssetManifest
    carousel_design_plan: CarouselDesignPlanV4
    design_plan_qa: DesignPlanQAResultV4
    render_manifest: RenderManifestV4
    render_qa: RenderQAResultV4
    visual_critique: CarouselAestheticEvaluationV4
    previous_review_workspace: ReviewWorkspaceV4 | None = None


@dataclass(frozen=True, slots=True)
class _RenderedAsset:
    item: AssetManifestItem
    sha256: str
    raw: bytes
    destination: str


@dataclass(frozen=True, slots=True)
class _PreviousReview:
    root: Path
    manifest: ReviewWorkspaceManifestV4
    artifact_paths: ArtifactPaths


_REVISION_ID = re.compile(r"^revision-(\d+)$")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _contract_hash(value: object) -> str:
    digest = getattr(value, "canonical_sha256", None)
    if isinstance(digest, str) and len(digest) == 64:
        return digest
    return canonical_sha256(value)


def _content_lock_hash(lock: ContentLock) -> str:
    payload = lock.model_dump(mode="json", exclude={"canonical_sha256"})
    expected = canonical_sha256(payload)
    if lock.canonical_sha256 != expected:
        raise ReviewBindingError("ContentLock canonical hash is stale")
    return expected


def _require_equal(label: str, *values: object) -> None:
    if not values or any(value != values[0] for value in values[1:]):
        raise ReviewBindingError(f"review source equality binding failed: {label}")


def _revision_number(revision_id: str) -> int:
    match = _REVISION_ID.fullmatch(revision_id)
    if match is None:
        raise ReviewBindingError("revision identity must use canonical revision-N form")
    return int(match.group(1))


def _canonical_bytes(value: BaseModel) -> bytes:
    return canonical_json_v4(value.model_dump(mode="json")).encode("utf-8")


def _workspace_attestation(workspace: ReviewWorkspaceV4) -> str:
    if not isinstance(workspace.manifest_raw, bytes):
        return ""
    try:
        payload = {
            "root": workspace.root.as_posix(),
            "base_root": workspace.artifact_paths.base_root.as_posix(),
            "run_id": workspace.artifact_paths.identity.run_id,
            "candidate_id": workspace.artifact_paths.identity.candidate_id,
            "revision_id": workspace.artifact_paths.identity.revision_id,
            "manifest_raw_sha256": _sha(workspace.manifest_raw),
        }
    except (AttributeError, TypeError, ValueError):
        return ""
    return hashlib.sha256(
        (_WORKSPACE_TRUST_SECRET + canonical_json_v4(payload)).encode("utf-8")
    ).hexdigest()


def _fresh_hard_gates(
    inputs: ReviewWorkspaceInputsV4,
    paths: ArtifactPaths,
) -> tuple[Any, Any, DesignPlanQAResultV4, RenderQAResultV4]:
    """Recompute Q0-Q3 from the exact source objects at this boundary.

    Stored results are evidence, never evaluator inputs.  In particular this
    closes the self-consistent rehash attack where a changed metric or render
    observation is wrapped in newly valid outer canonical hashes.
    """

    try:
        q0 = evaluate_semantic_model(
            inputs.content_atom_set,
            inputs.semantic_content_model,
            content_lock=inputs.content_lock,
        )
        q1 = evaluate_authoring(
            inputs.page_brief_set,
            inputs.semantic_content_model,
            inputs.carousel_narrative,
            inputs.visual_direction_plan,
            content_lock=inputs.content_lock,
            content_atom_set=inputs.content_atom_set,
        )
        if not hasattr(q1, "canonical_sha256"):
            raise ValueError("Q1 evaluator returned non-durable candidate evidence")
        aggregate = aggregate_design_qa(
            semantic_qa=q0,
            authoring_qa=q1,
            carousel_design_plan=inputs.carousel_design_plan,
            content_atom_set=inputs.content_atom_set,
            content_lock=inputs.content_lock,
            semantic_content_model=inputs.semantic_content_model,
            page_brief_set=inputs.page_brief_set,
            visual_direction_plan=inputs.visual_direction_plan,
            asset_manifest=inputs.asset_manifest,
        )
        render = evaluate_v4_render(
            render_manifest=inputs.render_manifest,
            design_plan=inputs.carousel_design_plan,
            design_plan_qa_result=aggregate,
            content_atom_set=inputs.content_atom_set,
            content_lock=inputs.content_lock,
            semantic_content_model=inputs.semantic_content_model,
            page_brief_set=inputs.page_brief_set,
            visual_direction_plan=inputs.visual_direction_plan,
            asset_manifest=inputs.asset_manifest,
            family_tokens=get_family_tokens(inputs.visual_direction_plan.template_family),
            artifact_paths=paths,
        )
    except Exception as error:
        raise ReviewBindingError("fresh Q0-Q3 hard-gate evaluation failed") from error

    stored_q2 = inputs.design_plan_qa
    stored_q3 = inputs.render_qa
    if (
        not q0.passed
        or not q1.passed
        or not aggregate.passed
        or not render.passed
        or _canonical_bytes(q0) != _canonical_bytes(stored_q2.semantic_qa)
        or _canonical_bytes(q1) != _canonical_bytes(stored_q2.authoring_qa)
        or _canonical_bytes(aggregate) != _canonical_bytes(stored_q2)
        or _canonical_bytes(render) != _canonical_bytes(stored_q3)
    ):
        raise ReviewBindingError("stored Q0-Q3 evidence differs from fresh deterministic evaluation")
    return q0, q1, aggregate, render


def _checked(inputs: ReviewWorkspaceInputsV4) -> tuple[ArtifactPaths, dict[str, str]]:
    """Validate complete source equality, identity, page order and Q0-Q4 links."""

    try:
        paths = revalidate_artifact_paths(inputs.artifact_paths)
        inputs.carousel_design_plan.validate_integrity()
        inputs.design_plan_qa.validate_integrity()
        inputs.render_manifest.validate_integrity()
        inputs.render_qa.validate_integrity()
        inputs.visual_critique.validate_integrity()
        inputs.content_atom_set.validate_integrity()
        inputs.semantic_content_model.validate_integrity()
        inputs.carousel_narrative.validate_integrity()
        inputs.page_brief_set.validate_integrity()
        inputs.visual_direction_plan.validate_integrity()
        inputs.asset_manifest.require_unique_bindings()
    except (ArtifactIdentityError, ValueError, TypeError) as error:
        raise ReviewBindingError("review source contracts are invalid") from error

    identity = paths.identity
    atoms = inputs.content_atom_set
    semantic = inputs.semantic_content_model
    narrative = inputs.carousel_narrative
    briefs = inputs.page_brief_set
    direction = inputs.visual_direction_plan
    plan = inputs.carousel_design_plan
    q2 = inputs.design_plan_qa
    render = inputs.render_manifest
    q3 = inputs.render_qa
    q4 = inputs.visual_critique

    # Identity is checked on every contract that carries it. A self-consistent
    # set of rehashed but unrelated contracts must never enter review.
    _require_equal(
        "design plan identity",
        (plan.run_id, plan.candidate_id, plan.revision),
        (identity.run_id, identity.candidate_id, _revision_number(identity.revision_id)),
    )
    _require_equal(
        "render identity",
        (render.run_id, render.candidate_id, render.revision_id),
        (identity.run_id, identity.candidate_id, identity.revision_id),
    )
    _require_equal(
        "render artifact identity",
        render.artifact_identity.model_dump(mode="json"),
        {"run_id": identity.run_id, "candidate_id": identity.candidate_id, "revision_id": identity.revision_id},
    )
    _require_equal("Q3 artifact identity", q3.artifact_identity, render.artifact_identity)
    _require_equal(
        "Q2 identity",
        (q2.run_id, q2.candidate_id, q2.revision),
        (plan.run_id, plan.candidate_id, plan.revision),
    )
    _require_equal("Q2 nested design plan", q2.carousel_design_plan, plan)
    if not q2.passed or not q3.passed:
        raise ReviewBindingError("all Q0-Q3 hard gates must pass before review")
    _fresh_hard_gates(inputs, paths)

    hashes = {
        "content_atom_set_sha256": atoms.canonical_sha256,
        "semantic_content_model_sha256": semantic.canonical_sha256,
        "narrative_sha256": narrative.canonical_sha256,
        "page_brief_set_sha256": briefs.canonical_sha256,
        "visual_direction_plan_sha256": direction.canonical_sha256,
        "content_lock_sha256": _content_lock_hash(inputs.content_lock),
        "asset_manifest_sha256": _contract_hash(inputs.asset_manifest),
        "carousel_design_plan_sha256": plan.canonical_sha256,
        "design_plan_qa_sha256": q2.canonical_sha256,
        "render_manifest_sha256": render.canonical_sha256,
        "render_qa_sha256": q3.canonical_sha256,
        "visual_critique_sha256": q4.canonical_sha256,
    }
    if inputs.content_lock.content_atom_set_sha256 != hashes["content_atom_set_sha256"]:
        raise ReviewBindingError("ContentLock is not bound to ContentAtomSet")

    # Complete equality binding matrix. Every hash-bearing downstream field is
    # compared, including family, lock, and Q2/Q3 attestations.
    pairs = (
        (semantic.content_atom_set_sha256, hashes["content_atom_set_sha256"]),
        (narrative.content_atom_set_sha256, hashes["content_atom_set_sha256"]),
        (briefs.content_atom_set_sha256, hashes["content_atom_set_sha256"]),
        (briefs.semantic_content_model_sha256, hashes["semantic_content_model_sha256"]),
        (direction.semantic_content_model, semantic),
        (direction.narrative, narrative),
        (direction.page_brief_set, briefs),
        (direction.template_family, narrative.template_family),
        (direction.page_count, narrative.page_count),
        (direction.content_atom_set_sha256, hashes["content_atom_set_sha256"]),
        (direction.semantic_content_model_sha256, hashes["semantic_content_model_sha256"]),
        (direction.narrative_sha256, hashes["narrative_sha256"]),
        (direction.page_brief_set_sha256, hashes["page_brief_set_sha256"]),
        (plan.content_atom_set_sha256, hashes["content_atom_set_sha256"]),
        (plan.semantic_content_model_sha256, hashes["semantic_content_model_sha256"]),
        (plan.page_brief_set_sha256, hashes["page_brief_set_sha256"]),
        (plan.visual_direction_plan_sha256, hashes["visual_direction_plan_sha256"]),
        (plan.asset_manifest_sha256, hashes["asset_manifest_sha256"]),
        (q2.content_atom_set_sha256, hashes["content_atom_set_sha256"]),
        (q2.content_lock_sha256, hashes["content_lock_sha256"]),
        (q2.semantic_content_model_sha256, hashes["semantic_content_model_sha256"]),
        (q2.narrative_sha256, hashes["narrative_sha256"]),
        (q2.page_brief_set_sha256, hashes["page_brief_set_sha256"]),
        (q2.visual_direction_plan_sha256, hashes["visual_direction_plan_sha256"]),
        (q2.asset_manifest_sha256, hashes["asset_manifest_sha256"]),
        (render.design_plan_sha256, hashes["carousel_design_plan_sha256"]),
        (render.design_plan_qa_sha256, hashes["design_plan_qa_sha256"]),
        (render.content_lock_sha256, hashes["content_lock_sha256"]),
        (render.asset_manifest_sha256, hashes["asset_manifest_sha256"]),
        (render.content_atom_set_sha256, hashes["content_atom_set_sha256"]),
        (render.semantic_content_model_sha256, hashes["semantic_content_model_sha256"]),
        (render.narrative_sha256, hashes["narrative_sha256"]),
        (render.page_brief_set_sha256, hashes["page_brief_set_sha256"]),
        (render.visual_direction_plan_sha256, hashes["visual_direction_plan_sha256"]),
        (render.family_tokens_sha256, plan.family_tokens_sha256),
        (q3.render_manifest_sha256, hashes["render_manifest_sha256"]),
        (q3.design_plan_sha256, hashes["carousel_design_plan_sha256"]),
        (q3.design_plan_qa_sha256, hashes["design_plan_qa_sha256"]),
        (q3.content_lock_sha256, hashes["content_lock_sha256"]),
        (q3.content_atom_set_sha256, hashes["content_atom_set_sha256"]),
        (q3.semantic_content_model_sha256, hashes["semantic_content_model_sha256"]),
        (q3.narrative_sha256, hashes["narrative_sha256"]),
        (q3.page_brief_set_sha256, hashes["page_brief_set_sha256"]),
        (q3.visual_direction_plan_sha256, hashes["visual_direction_plan_sha256"]),
        (q3.asset_manifest_sha256, hashes["asset_manifest_sha256"]),
        (q3.family_tokens_sha256, plan.family_tokens_sha256),
        (q4.render_manifest_sha256, hashes["render_manifest_sha256"]),
        (q4.render_qa_result_sha256, hashes["render_qa_sha256"]),
        (q4.semantic_content_model_sha256, hashes["semantic_content_model_sha256"]),
        (q4.page_brief_set_sha256, hashes["page_brief_set_sha256"]),
    )
    if any(left != right for left, right in pairs):
        raise ReviewBindingError("review source contracts are cross-bound to stale inputs")

    plan_ids = tuple((page.page_id, page.sequence) for page in plan.pages)
    render_ids = tuple((page.page_id, page.sequence) for page in render.pages)
    brief_ids = tuple((page.page_id, page.sequence) for page in briefs.pages)
    q2_ids = tuple((page.page_id, page.sequence) for page in q2.page_metrics)
    q4_ids = tuple((page.page_id, index + 1) for index, page in enumerate(q4.pages))
    if plan_ids != render_ids or plan_ids != brief_ids or plan_ids != q2_ids or plan_ids != q4_ids:
        raise ReviewBindingError("source, QA, critic, and render page order differs")
    if len({page.page_id for page in render.pages}) != len(render.pages):
        raise ReviewBindingError("render page IDs are not unique")

    beats = {beat.beat_id: beat for beat in narrative.beats}
    for scene_page, brief in zip(plan.pages, briefs.pages):
        program = scene_page.layout_program
        if scene_page.page_id != brief.page_id or scene_page.sequence != brief.sequence:
            raise ReviewBindingError("scene page identity differs from Page Brief")
        _require_equal(f"page {brief.page_id} brief hash", program.page_brief_sha256, brief.canonical_sha256)
        _require_equal(f"page {brief.page_id} family", program.template_family, direction.template_family)
        _require_equal(f"page {brief.page_id} narrative", program.carousel_narrative_sha256, narrative.canonical_sha256)
        beat = beats.get(brief.beat_ref)
        if beat is None or program.beat_ref != beat.beat_id or program.beat_task_kind != beat.task_kind:
            raise ReviewBindingError(f"page {brief.page_id} beat duty binding differs")

    return paths, hashes


def _read_revision(paths: ArtifactPaths, relative: str, digest: str) -> bytes:
    if relative.startswith("/") or ".." in Path(relative).parts:
        raise ReviewBindingError("review artifact path is not revision-relative")
    try:
        return read_verified_artifact_snapshot(
            paths.revision_root / relative, digest, containment_root=paths.revision_root
        ).raw
    except ArtifactBindingError as error:
        raise ReviewBindingError("review source bytes are missing, changed, or unsafe") from error


def _page_paths(render: RenderManifestV4) -> dict[str, str]:
    result: dict[str, str] = {}
    for page in render.pages:
        name = f"pages/{page.sequence:02d}-{page.page_id}.png"
        if name in result:
            raise ReviewBindingError("review page names are not unique")
        result[name] = page.sha256
    return result


def _asset_extension(raw: bytes) -> str:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return "webp"
    return "bin"


def _rendered_assets(inputs: ReviewWorkspaceInputsV4, paths: ArtifactPaths) -> tuple[_RenderedAsset, ...]:
    """Derive exact rendered assets from Scene Plan and RenderManifest."""

    by_directive = {item.directive_id: item for item in inputs.asset_manifest.items}
    bindings: dict[str, Any] = {}
    for page in inputs.carousel_design_plan.pages:
        bindings.update(page.compiler_provenance.asset_binding_evidence)
    render_bindings = {
        element.asset.directive_id: element.asset
        for page in inputs.render_manifest.pages
        for element in page.elements
        if element.asset is not None
    }
    if set(bindings) != set(render_bindings):
        raise ReviewBindingError("Scene Plan and RenderManifest rendered asset sets differ")
    seen: list[_RenderedAsset] = []
    for directive_id in sorted(bindings):
        binding = bindings[directive_id]
        item = by_directive.get(directive_id)
        if item is None:
            raise ReviewBindingError("rendered asset directive is absent from manifest")
        render_binding = render_bindings[directive_id]
        if (
            item.sha256 != binding.asset_sha256
            or binding.asset_ref != render_binding.asset_ref
            or binding.asset_sha256 != render_binding.asset_sha256
            or item.security_status != "approved"
            or item.human_decision != "pending"
            or item.run_id != paths.identity.run_id
            or item.transaction_id != paths.identity.revision_id
        ):
            raise ReviewBindingError("rendered asset manifest binding is stale or unsafe")
        try:
            snapshot = read_verified_artifact_snapshot(
                Path(item.local_path), item.sha256, containment_root=paths.asset_root
            )
        except ArtifactBindingError as error:
            raise ReviewBindingError("rendered asset bytes changed or are unsafe") from error
        seen.append(
            _RenderedAsset(item, snapshot.sha256, snapshot.raw, f"assets/{item.asset_id}.{_asset_extension(snapshot.raw)}")
        )
    return tuple(seen)


def _quality_report(inputs: ReviewWorkspaceInputsV4, hashes: Mapping[str, str]) -> bytes:
    q2 = inputs.design_plan_qa
    q3 = inputs.render_qa
    q4 = inputs.visual_critique
    beats = {beat.beat_id: beat for beat in inputs.carousel_narrative.beats}
    payload = {
        "workflow_version": "llm_scene_v4",
        "identity": {
            "run_id": inputs.artifact_paths.identity.run_id,
            "candidate_id": inputs.artifact_paths.identity.candidate_id,
            "revision_id": inputs.artifact_paths.identity.revision_id,
        },
        "hard_gates": {
            "q0_semantic": q2.semantic_qa.model_dump(mode="json"),
            "q1_authoring": q2.authoring_qa.model_dump(mode="json"),
            "q2_passed": q2.passed,
            "q3_passed": q3.passed,
        },
        "source_hashes": dict(hashes),
        "q2_pages": [item.model_dump(mode="json") for item in q2.page_metrics],
        "q2_issues": [item.model_dump(mode="json") for item in q2.issues],
        "q3": q3.model_dump(mode="json"),
        "q4": q4.model_dump(mode="json"),
        "narrative_beats": [item.model_dump(mode="json") for item in inputs.carousel_narrative.beats],
        "page_briefs": [
            {
                "page_id": brief.page_id,
                "sequence": brief.sequence,
                "role": brief.narrative_role,
                "beat_ref": brief.beat_ref,
                "duty": beats[brief.beat_ref].task,
                "task_kind": beats[brief.beat_ref].task_kind,
                "density_budget": brief.density_budget,
                "visual_priority": list(brief.visual_priority),
            }
            for brief in inputs.page_brief_set.pages
        ],
    }
    return canonical_json_v4(payload).encode("utf-8")


def _overlay_svg(page_id: str, sequence: int, metrics: Any = (), *, page: Any | None = None) -> bytes:
    """Create Q2 evidence overlays from the compiler's actual region geometry."""

    rows = [
        f'<text x="52" y="72" font-size="34" fill="#0a5555">Q2 metrics · {sequence} · {html.escape(page_id, quote=True)}</text>'
    ]
    region_geometry = {} if page is None else page.compiler_provenance.region_geometry_evidence
    element_regions = {} if page is None else page.compiler_provenance.element_region_bindings
    for index, metric in enumerate(metrics):
        label = html.escape(str(metric.metric), quote=True)
        region_id = metric.region_id or (element_regions.get(metric.element_id) if metric.element_id else None)
        region = region_geometry.get(region_id) if region_id is not None else None
        location = html.escape(": ".join(str(value) for value in (region_id, metric.element_id) if value) or "page", quote=True)
        color = "#0a8f6f" if metric.passed else "#c53030"
        y = 130 + index * 56
        if region is not None:
            rows.append(
                f'<rect class="q2-region" data-region-id="{html.escape(region.region_id, quote=True)}" '
                f'data-element-id="{html.escape(str(metric.element_id or ""), quote=True)}" '
                f'x="{region.x:g}" y="{region.y:g}" width="{region.width:g}" height="{region.height:g}" '
                f'fill="{color}" fill-opacity="0.12" stroke="{color}" stroke-width="3"/>'
            )
        rows.append(f'<rect x="48" y="{y - 28}" width="984" height="38" fill="{color}" opacity="0.15"/>')
        rows.append(
            f'<text x="64" y="{y}" font-size="24" fill="{color}">{label}: '
            f'{html.escape(str(metric.actual), quote=True)} / {html.escape(str(metric.threshold), quote=True)} '
            f'[{location}]</text>'
        )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1440" viewBox="0 0 1080 1440">'
        '<rect x="20" y="20" width="1040" height="1400" fill="#ffffff" fill-opacity="0.88" stroke="#0a8f8f" stroke-width="6"/>'
        + "".join(rows)
        + "</svg>"
    ).encode("utf-8")


def _safe_json_text(value: object) -> str:
    return html.escape(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2), quote=False)


def _html_page(
    inputs: ReviewWorkspaceInputsV4,
    manifest: ReviewWorkspaceManifestV4 | None,
    page_paths: Mapping[str, str],
    *,
    asset_paths: Mapping[str, str] | None = None,
    previous: _PreviousReview | None = None,
    revision_diff: bytes | None = None,
) -> bytes:
    """Render a fully escaped, script-free, file://-safe review index."""

    title = html.escape(inputs.content_lock.title, quote=True)
    cards: list[str] = []
    for page, path in zip(inputs.render_manifest.pages, page_paths):
        overlay = f"overlays/{page.sequence:02d}-{page.page_id}.svg"
        cards.append(
            '<article class="page-card" data-page-id="' + html.escape(page.page_id, quote=True) + '">'
            "<h3>" + html.escape(f"{page.sequence:02d} · {page.page_id}", quote=True) + "</h3>"
            '<a class="full-size" href="' + html.escape(path, quote=True) + '">'
            '<img class="page-image" src="' + html.escape(path, quote=True) + '" width="1080" height="1440" alt="'
            + html.escape(page.page_id, quote=True) + '"></a>'
            '<img class="overlay" src="' + html.escape(overlay, quote=True) + '" width="1080" height="1440" alt="Q2 metrics overlay for '
            + html.escape(page.page_id, quote=True) + '"></article>'
        )

    rendered_paths = asset_paths or {}
    asset_items: list[str] = []
    for item in inputs.asset_manifest.items:
        preview = rendered_paths.get(item.asset_id)
        if preview and not preview.endswith(".bin"):
            image = ('<img class="asset-preview" src="' + html.escape(preview, quote=True)
                     + '" alt="local preview of ' + html.escape(item.asset_id, quote=True) + '">')
        elif preview:
            image = '<a class="asset-preview-link" href="' + html.escape(preview, quote=True) + '">local verified bytes</a>'
        else:
            image = "<span>not rendered</span>"
        asset_items.append(
            '<li class="asset-item"><b>' + html.escape(item.asset_id, quote=True) + '</b>' + image
            + '<span>provider=' + html.escape(item.provider, quote=True)
            + ' source_kind=' + html.escape(item.source_kind, quote=True)
            + ' license=' + html.escape(item.license, quote=True)
            + ' security=' + html.escape(item.security_status, quote=True)
            + ' transaction_id=' + html.escape(item.transaction_id, quote=True)
            + ' recovery=unavailable human=' + html.escape(item.human_decision, quote=True)
            + ' sha256=' + html.escape(item.sha256, quote=True) + '</span></li>'
        )
    assets = "".join(asset_items) or "<li>No external assets referenced.</li>"
    plan_by_page = {page.page_id: page for page in inputs.carousel_design_plan.pages}
    def metric_geometry(page_id: str, metric: Any) -> tuple[str | None, tuple[float, float, float, float] | None]:
        plan_page = plan_by_page.get(page_id)
        if plan_page is None:
            return None, None
        region_id = metric.region_id or (
            plan_page.compiler_provenance.element_region_bindings.get(metric.element_id)
            if metric.element_id else None
        )
        evidence = plan_page.compiler_provenance.region_geometry_evidence.get(region_id) if region_id else None
        if evidence is None:
            return region_id, None
        return region_id, (evidence.x, evidence.y, evidence.width, evidence.height)

    def metric_card(page_id: str, metric: Any) -> str:
        region_id, geometry = metric_geometry(page_id, metric)
        return (
            '<dt>' + html.escape(metric.metric, quote=True) + '</dt><dd>'
            + html.escape(f"actual={metric.actual} threshold={metric.threshold} passed={metric.passed}", quote=True)
            + ' region=' + html.escape(str(region_id or "page"), quote=True)
            + ' element=' + html.escape(str(metric.element_id or "page"), quote=True)
            + ' geometry=' + html.escape(str(geometry or "unavailable"), quote=True) + '</dd>'
        )

    metric_cards = "".join(
        '<article class="q2-card"><h3>' + html.escape(page.page_id, quote=True) + '</h3><dl>'
        + "".join(metric_card(page.page_id, metric) for metric in page.metrics)
        + '</dl></article>'
        for page in inputs.design_plan_qa.page_metrics
    )
    q4_page_issues = "".join(
        '<li>' + html.escape(page.page_id, quote=True) + ': '
        + html.escape(json.dumps([issue.model_dump(mode="json") for issue in page.issues], ensure_ascii=False), quote=True)
        + '</li>' for page in inputs.visual_critique.pages
    ) or "<li>none</li>"
    q4_set_issues = html.escape(
        json.dumps([issue.model_dump(mode="json") for issue in inputs.visual_critique.set_evaluation.issues], ensure_ascii=False),
        quote=True,
    )
    beats_by_id = {beat.beat_id: beat for beat in inputs.carousel_narrative.beats}
    briefs = "".join(
        '<li><b>' + html.escape(brief.page_id, quote=True) + '</b> role='
        + html.escape(brief.narrative_role, quote=True) + ' beat=' + html.escape(brief.beat_ref, quote=True)
        + ' duty=' + html.escape(beats_by_id[brief.beat_ref].task, quote=True)
        + ' density=' + html.escape(brief.density_budget, quote=True) + '</li>'
        for brief in inputs.page_brief_set.pages
    )
    beats = "".join(
        '<li><b>' + html.escape(beat.beat_id, quote=True) + '</b> task_kind='
        + html.escape(beat.task_kind, quote=True) + ' duty=' + html.escape(beat.task, quote=True) + '</li>'
        for beat in inputs.carousel_narrative.beats
    )
    q3_evidence = {
        "q0_semantic": inputs.design_plan_qa.semantic_qa.model_dump(mode="json"),
        "q1_authoring": inputs.design_plan_qa.authoring_qa.model_dump(mode="json"),
        "q2_passed": inputs.design_plan_qa.passed,
        "passed": inputs.render_qa.passed,
        "content_attestation": inputs.render_qa.content_attestation,
        "geometry_attestation": inputs.render_qa.geometry_attestation,
        "font_attestation": inputs.render_qa.font_attestation,
        "asset_attestation": inputs.render_qa.asset_attestation,
        "bytes_attestation": inputs.render_qa.bytes_attestation,
        "issues": [issue.model_dump(mode="json") for issue in inputs.render_qa.issues],
    }
    identity = inputs.artifact_paths.identity
    manifest_identity = f"run={identity.run_id} · candidate={identity.candidate_id} · revision={identity.revision_id}"
    manifest_hash = manifest.canonical_sha256 if manifest is not None else inputs.render_manifest.canonical_sha256
    previous_section = ""
    if previous is not None:
        pairs: list[str] = []
        diff_payload = json.loads(revision_diff or b"{}")
        for entry in diff_payload.get("pages", ()):
            current = entry.get("current")
            prior = entry.get("previous")
            current_view = (
                '<a class="revision-full-size" href="' + html.escape(str(current["path"]), quote=True)
                + '"><img src="' + html.escape(str(current["path"]), quote=True)
                + '" width="1080" height="1440" alt="current full-size page '
                + html.escape(str(entry.get("page_id", "")), quote=True) + '"></a>'
                if current is not None else '<span class="missing-page">current page unavailable</span>'
            )
            previous_view = (
                '<a class="revision-full-size" href="previous-revision/' + html.escape(str(prior["path"]), quote=True)
                + '"><img src="previous-revision/' + html.escape(str(prior["path"]), quote=True)
                + '" width="1080" height="1440" alt="previous full-size page '
                + html.escape(str(entry.get("page_id", "")), quote=True) + '"></a>'
                if prior is not None else '<span class="missing-page">previous page unavailable</span>'
            )
            pairs.append(
                '<article class="revision-pair" data-page-id="' + html.escape(str(entry.get("page_id", "")), quote=True)
                + '" data-status="' + html.escape(str(entry.get("status", "")), quote=True)
                + '"><h3>' + html.escape(str(entry.get("page_id", "")), quote=True)
                + ' · ' + html.escape(str(entry.get("status", "")), quote=True)
                + '</h3><div class="current-page">' + current_view + '</div><div class="previous-page">'
                + previous_view + '</div></article>'
            )
        previous_section = (
            '<section id="previous-revision"><h2>Current vs previous revision</h2><p>previous='
            + html.escape(previous.manifest.revision_id, quote=True) + '</p><img src="previous-revision/contact-sheet.png" alt="previous contact sheet"><div id="revision-pairs">'
            + "".join(pairs) + '</div>'
            '<a href="revision-diff.json">hash-bound revision diff</a></section>'
        )
    diff_section = (
        '<section id="revision-diff"><h2>Revision diff</h2><pre>'
        + _safe_json_text(json.loads(revision_diff or b"{}")) + '</pre></section>'
        if revision_diff is not None else ""
    )
    document = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\'; style-src \'unsafe-inline\'; script-src \'none\'; connect-src \'none\'; font-src \'none\'; media-src \'none\'; object-src \'none\'; base-uri \'none\'; form-action \'none\'">'
        '<style>body{font-family:system-ui,sans-serif;margin:24px;color:#17202a;background:#f7fafb}section{margin:32px 0;padding:20px;background:#fff;border:1px solid #d6e2e3;border-radius:12px}img{max-width:100%;height:auto}.page-card{display:inline-block;vertical-align:top;width:320px;margin:8px;padding:12px;border:1px solid #d6e2e3;border-radius:8px}.page-image{display:block;max-width:300px}.overlay{display:block;margin-top:8px;max-width:300px;border:1px solid #0aa}.asset-item{display:grid;grid-template-columns:180px 1fr;gap:8px;margin:12px 0;align-items:center}.asset-preview{max-width:160px;max-height:160px}.q2-card{display:inline-block;vertical-align:top;width:280px;margin:8px;padding:10px;background:#f7fafb}.q2-card dd{margin:2px 0 8px}pre{white-space:pre-wrap;word-break:break-word}code{word-break:break-all}</style></head><body>'
        '<h1>V4 Review · ' + title + '</h1><p id="identity">' + html.escape(manifest_identity, quote=True) + '</p>'
        '<p id="content-lock">ContentLock sha256: <code>' + html.escape(_content_lock_hash(inputs.content_lock), quote=True) + '</code></p>'
        '<section id="contact-sheet"><h2>Contact sheet</h2><img src="contact-sheet.png" alt="verified contact sheet"></section>'
        '<section id="pages"><h2>Original-size pages (click to open)</h2>' + "".join(cards) + '</section>'
        '<section id="narrative-beats"><h2>Narrative beats and duties</h2><ul>' + beats + '</ul></section>'
        '<section id="page-briefs"><h2>Page Brief roles and duties</h2><ul>' + briefs + '</ul></section>'
        '<section id="q0-q3-evidence"><h2>Q0-Q3 hard evidence</h2><pre>' + _safe_json_text(q3_evidence) + '</pre></section>'
        '<section id="q2-metrics"><h2>Q2 density, whitespace, alignment and failure regions</h2>' + metric_cards + '</section>'
        '<section id="q3-evidence"><h2>Q3 render attestations and issues</h2><pre>' + _safe_json_text(inputs.render_qa.model_dump(mode="json")) + '</pre></section>'
        '<section id="q4-evidence"><h2>Q4 page and set issues</h2><ul>' + q4_page_issues + '</ul><p>set issues=' + q4_set_issues + '</p><p>passed=' + html.escape(str(inputs.visual_critique.passed), quote=True) + '</p></section>'
        '<section id="quality-report"><h2>Complete quality report</h2><a href="quality-report.json">quality-report.json</a></section>'
        '<section id="asset-evidence"><h2>Rendered asset evidence and local previews</h2><ul>' + assets + '</ul></section>'
        + previous_section + diff_section
        + '<section id="decision-intake"><h2>Untrusted mutable decision intake</h2><a href="decision.json">decision.json</a></section>'
        + '<footer id="workspace-identity">source RenderManifest identity: <code>' + html.escape(manifest_hash, quote=True) + '</code></footer></body></html>'
    )
    return document.encode("utf-8")


def _stage_write(lease: Any, stage: str, name: str, raw: bytes) -> None:
    _atomic_write_at(lease.fd, (stage, *Path(name).parts), raw)


def _publish_stage(lease: Any, stage: str, expected_source_identity: tuple[int, int]) -> None:
    """Publish the already verified stage without reopening its pathname."""

    publish_staged_directory_at(
        lease,
        stage,
        "review",
        expected_source_identity=expected_source_identity,
    )


def _revision_diff(current: Mapping[str, str], previous: ReviewWorkspaceManifestV4) -> bytes:
    def page_id(path: str) -> str:
        return path.split("/", 1)[1].removesuffix(".png").split("-", 1)[1]

    current_by_id = {page_id(path): (path, digest) for path, digest in current.items()}
    prior_by_id = {page_id(path): (path, digest) for path, digest in previous.page_sha256.items()}
    mapping = []
    for identifier in sorted(set(current_by_id) | set(prior_by_id)):
        now, old = current_by_id.get(identifier), prior_by_id.get(identifier)
        if now is None:
            status = "removed"
        elif old is None:
            status = "added"
        elif now[1] == old[1]:
            status = "unchanged"
        else:
            status = "changed"
        mapping.append({
            "page_id": identifier,
            "status": status,
            "current": None if now is None else {"path": now[0], "sha256": now[1]},
            "previous": None if old is None else {"path": old[0], "sha256": old[1]},
        })
    return canonical_json_v4({
        "previous_revision_id": previous.revision_id,
        "pages": mapping,
        "summary": {status: sum(item["status"] == status for item in mapping) for status in ("added", "removed", "changed", "unchanged")},
    }).encode("utf-8")


def _enumerate_tree_fd(root_fd: int, prefix: tuple[str, ...] = ()) -> tuple[set[str], set[str]]:
    """Enumerate a tree exclusively through pinned descriptors and no-follow opens."""

    import stat

    files: set[str] = set()
    directories: set[str] = set()
    try:
        entries = sorted(os.listdir(root_fd))
    except OSError as error:
        raise ReviewBindingError("workspace directory enumeration failed") from error
    for name in entries:
        if type(name) is not str or not name or name in {".", ".."} or "/" in name or "\\" in name:
            raise ReviewBindingError("workspace contains an unsafe path component")
        relative = prefix + (name,)
        try:
            info = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        except OSError as error:
            raise ReviewBindingError("workspace entry disappeared during enumeration") from error
        if stat.S_ISLNK(info.st_mode):
            raise ReviewBindingError("workspace contains a symlink")
        if stat.S_ISDIR(info.st_mode):
            directories.add("/".join(relative))
            child_fd: int | None = None
            try:
                child_fd = os.open(
                    name,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=root_fd,
                )
                child_info = os.fstat(child_fd)
                if (child_info.st_dev, child_info.st_ino) != (info.st_dev, info.st_ino):
                    raise ReviewBindingError("workspace directory changed during enumeration")
                child_files, child_dirs = _enumerate_tree_fd(child_fd, relative)
                files.update(child_files)
                directories.update(child_dirs)
            except ReviewBindingError:
                raise
            except OSError as error:
                raise ReviewBindingError("workspace directory is unreadable") from error
            finally:
                if child_fd is not None:
                    os.close(child_fd)
        elif stat.S_ISREG(info.st_mode):
            files.add("/".join(relative))
        else:
            raise ReviewBindingError("workspace contains a non-regular entry")
    return files, directories


def _verify_workspace_fd(
    root_fd: int,
    manifest: ReviewWorkspaceManifestV4,
    *,
    expected_manifest_raw: bytes | None = None,
) -> None:
    """Verify one root below a caller-owned pinned directory descriptor."""

    try:
        manifest_snapshot = read_verified_artifact_snapshot_at(
            root_fd, ("workspace-manifest.json",), None
        )
        raw = manifest_snapshot.raw
        actual = ReviewWorkspaceManifestV4.model_validate_json(raw)
    except (OSError, ArtifactBindingError, ValueError) as error:
        raise ReviewBindingError("workspace manifest is invalid or unsafe") from error
    trusted = expected_manifest_raw or canonical_json_v4(manifest.model_dump(mode="json")).encode("utf-8")
    if raw != trusted or actual != manifest:
        raise ReviewBindingError("workspace manifest bytes are not the trusted canonical manifest")
    try:
        intent = read_verified_artifact_snapshot_at(root_fd, ("decision.json",), None)
        HumanReviewIntentV4.model_validate_json(intent.raw)
        actual_names, actual_dirs = _enumerate_tree_fd(root_fd)
    except (OSError, ArtifactBindingError, ValueError) as error:
        raise ReviewBindingError("decision intake or workspace enumeration is unsafe") from error
    allowed_dirs = {"pages", "overlays", "assets"}
    if manifest.previous_revision_id is not None:
        allowed_dirs.update({"previous-revision", "previous-revision/pages"})
    if actual_names != set(manifest.files) | {"workspace-manifest.json", "decision.json"}:
        raise ReviewBindingError("workspace contains missing or extra files")
    if not actual_dirs <= allowed_dirs:
        raise ReviewBindingError("workspace contains an unexpected directory")
    for relative, digest in manifest.files.items():
        try:
            read_verified_artifact_snapshot_at(root_fd, tuple(Path(relative).parts), digest)
        except (OSError, ArtifactBindingError) as error:
            raise ReviewBindingError("workspace file bytes changed or path is unsafe") from error


def _verify_workspace_root(
    root: Path,
    manifest: ReviewWorkspaceManifestV4,
    *,
    expected_manifest_raw: bytes | None = None,
) -> None:
    """Verify one root without trusting an on-disk manifest digest."""

    try:
        if root.is_symlink() or not root.is_dir():
            raise ReviewBindingError("review workspace root is unsafe")
        with _lease_context(_open_absolute_directory(root, create=False)) as lease:
            lease.assert_intact()
            _verify_workspace_fd(lease.fd, manifest, expected_manifest_raw=expected_manifest_raw)
            lease.assert_intact()
    except (OSError, ArtifactBindingError, ArtifactIdentityError) as error:
        raise ReviewBindingError("workspace root is invalid or unsafe") from error


def _verify_staging(
    paths: ArtifactPaths,
    stage: str,
    manifest: ReviewWorkspaceManifestV4,
    raw: bytes,
    lease: Any,
) -> tuple[int, int]:
    """Verify staging through the same pinned revision lease used to publish."""

    if type(stage) is not str or not stage or Path(stage).name != stage or stage in {".", ".."}:
        raise ReviewBindingError("staging root escaped revision root")
    lease.assert_intact()
    stage_fd: int | None = None
    try:
        stage_fd = os.open(
            stage,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=lease.fd,
        )
        info = os.fstat(stage_fd)
        _verify_workspace_fd(stage_fd, manifest, expected_manifest_raw=raw)
        lease.assert_intact()
        return (info.st_dev, info.st_ino)
    except (OSError, ArtifactBindingError) as error:
        raise ReviewBindingError("staging workspace is invalid or unsafe") from error
    finally:
        if stage_fd is not None:
            os.close(stage_fd)


def _previous_files(inputs: ReviewWorkspaceInputsV4) -> _PreviousReview | None:
    supplied_workspace = inputs.previous_review_workspace
    if supplied_workspace is None:
        return None
    if type(supplied_workspace) is not ReviewWorkspaceV4:
        raise ReviewBindingError("previous review must be a typed ReviewWorkspaceV4")
    if supplied_workspace._trust_token is not _WORKSPACE_TRUST_TOKEN:
        raise ReviewBindingError("previous review workspace was not issued by the verifier")
    verify_review_workspace(supplied_workspace)
    previous_paths = revalidate_artifact_paths(supplied_workspace.artifact_paths)
    if supplied_workspace.root != previous_paths.review_root:
        raise ReviewBindingError("previous review root is not bound to its ArtifactPaths")
    previous = _PreviousReview(supplied_workspace.root, supplied_workspace.manifest, previous_paths)
    current_identity = inputs.artifact_paths.identity
    if previous.manifest.workflow_version != "llm_scene_v4":
        raise ReviewBindingError("previous review workflow version mismatch")
    if (previous.manifest.run_id, previous.manifest.candidate_id) != (current_identity.run_id, current_identity.candidate_id):
        raise ReviewBindingError("previous review identity does not match candidate")
    if _revision_number(previous.manifest.revision_id) >= _revision_number(current_identity.revision_id):
        raise ReviewBindingError("previous review must be a strictly prior revision")
    p = previous.artifact_paths
    if p.base_root != inputs.artifact_paths.base_root or p.identity.run_id != current_identity.run_id or p.identity.candidate_id != current_identity.candidate_id:
        raise ReviewBindingError("previous ArtifactPaths base or candidate identity differs")
    if previous.root.is_symlink() or not previous.root.is_dir():
        raise ReviewBindingError("previous review root is unsafe")
    _verify_workspace_root(previous.root, previous.manifest, expected_manifest_raw=supplied_workspace.manifest_raw)
    return previous


def _cleanup_stage(paths: ArtifactPaths, stage: str) -> BaseException | None:
    try:
        with _lease_context(_open_absolute_directory(paths.revision_root, create=False)) as lease:
            lease.assert_intact()
            try:
                _remove_tree_at(lease.fd, stage)
            except FileNotFoundError:
                pass
    except BaseException as error:
        return error
    return None


def _remove_published_review(paths: ArtifactPaths) -> BaseException | None:
    """Remove only the exact failed review destination through a pinned lease."""

    try:
        with _lease_context(_open_absolute_directory(paths.revision_root, create=False)) as lease:
            lease.assert_intact()
            try:
                _remove_tree_at(lease.fd, "review")
            except FileNotFoundError:
                pass
            except BaseException as primary:
                try:
                    info = os.stat("review", dir_fd=lease.fd, follow_symlinks=False)
                    quarantine = ".review-recovery-" + uuid.uuid4().hex
                    quarantine_directory_at(
                        lease,
                        "review",
                        quarantine,
                        expected_source_identity=(info.st_dev, info.st_ino),
                    )
                    primary.add_note(f"failed review quarantined as {quarantine}")
                except BaseException as quarantine_error:
                    primary.add_note(f"failed review quarantine failed: {quarantine_error}")
                raise
            lease.assert_intact()
    except BaseException as error:
        return error
    return None


def _write_recovery_journal(paths: ArtifactPaths, message: str) -> None:
    payload = canonical_json_v4({
        "workflow_version": "llm_scene_v4", "run_id": paths.identity.run_id,
        "candidate_id": paths.identity.candidate_id, "revision_id": paths.identity.revision_id,
        "error": message[:1000],
    }).encode("utf-8")
    name = "review-recovery-" + uuid.uuid4().hex + ".json"
    with _lease_context(_open_absolute_directory(paths.revision_root, create=False)) as lease:
        _atomic_write_at(lease.fd, (name,), payload)


def build_review_workspace(inputs: ReviewWorkspaceInputsV4) -> ReviewWorkspaceV4:
    """Build and verify a complete workspace before one atomic no-replace publish."""

    paths, hashes = _checked(inputs)
    rendered_assets = _rendered_assets(inputs, paths)
    previous = _previous_files(inputs)
    try:
        if paths.review_root.is_symlink() or paths.review_root.exists():
            raise ReviewBindingError("an immutable review workspace already exists for this revision")
    except OSError as error:
        raise ReviewBindingError("cannot inspect review workspace destination") from error

    pages = _page_paths(inputs.render_manifest)
    asset_paths = {asset.item.asset_id: asset.destination for asset in rendered_assets}
    stage = ".review-staging-" + uuid.uuid4().hex
    files: dict[str, str] = {}
    published = False
    manifest: ReviewWorkspaceManifestV4 | None = None
    manifest_raw = b""
    stage_identity: tuple[int, int] | None = None
    try:
        with _lease_context(_open_absolute_directory(paths.revision_root, create=False)) as lease:
            lease.assert_intact()
            try:
                os.mkdir(stage, mode=0o700, dir_fd=lease.fd)
                contact = _read_revision(paths, inputs.render_manifest.contact_sheet_path, inputs.render_manifest.contact_sheet_sha256)
                _stage_write(lease, stage, "contact-sheet.png", contact)
                files["contact-sheet.png"] = _sha(contact)
                q2_by_page = {item.page_id: item for item in inputs.design_plan_qa.page_metrics}
                for source, (destination, digest) in zip(inputs.render_manifest.pages, pages.items()):
                    page_raw = _read_revision(paths, source.path, digest)
                    _stage_write(lease, stage, destination, page_raw)
                    files[destination] = _sha(page_raw)
                    overlay = _overlay_svg(
                        source.page_id,
                        source.sequence,
                        q2_by_page[source.page_id].metrics,
                        page=next(item for item in inputs.carousel_design_plan.pages if item.page_id == source.page_id),
                    )
                    overlay_path = f"overlays/{source.sequence:02d}-{source.page_id}.svg"
                    _stage_write(lease, stage, overlay_path, overlay)
                    files[overlay_path] = _sha(overlay)
                for asset in rendered_assets:
                    _stage_write(lease, stage, asset.destination, asset.raw)
                    files[asset.destination] = asset.sha256
                revision_diff = None
                if previous is not None:
                    previous_contact = read_verified_artifact_snapshot(previous.root / "contact-sheet.png", previous.manifest.contact_sheet_sha256, containment_root=previous.root).raw
                    _stage_write(lease, stage, "previous-revision/contact-sheet.png", previous_contact)
                    files["previous-revision/contact-sheet.png"] = _sha(previous_contact)
                    for destination, digest in previous.manifest.page_sha256.items():
                        prior = read_verified_artifact_snapshot(previous.root / destination, digest, containment_root=previous.root).raw
                        copied = "previous-revision/" + destination
                        _stage_write(lease, stage, copied, prior)
                        files[copied] = _sha(prior)
                    revision_diff = _revision_diff(pages, previous.manifest)
                    _stage_write(lease, stage, "revision-diff.json", revision_diff)
                    files["revision-diff.json"] = _sha(revision_diff)
                quality = _quality_report(inputs, hashes)
                _stage_write(lease, stage, "quality-report.json", quality)
                files["quality-report.json"] = _sha(quality)
                intake = canonical_json_v4({"action": "APPROVE", "rationale": None, "feedback": None, "asset_ids": [], "visible_copy_payload": None}).encode("utf-8")
                _stage_write(lease, stage, "decision.json", intake)
                index = _html_page(inputs, None, pages, asset_paths=asset_paths, previous=previous, revision_diff=revision_diff)
                _stage_write(lease, stage, "index.html", index)
                files["index.html"] = _sha(index)
                manifest = ReviewWorkspaceManifestV4.create(
                    run_id=paths.identity.run_id,
                    candidate_id=paths.identity.candidate_id,
                    revision_id=paths.identity.revision_id,
                    **hashes,
                    page_sha256=pages,
                    contact_sheet_sha256=files["contact-sheet.png"],
                    asset_sha256={asset.destination: asset.sha256 for asset in rendered_assets},
                    previous_revision_id=None if previous is None else previous.manifest.revision_id,
                    previous_contact_sheet_sha256=None if previous is None else previous.manifest.contact_sheet_sha256,
                    previous_page_sha256={} if previous is None else dict(previous.manifest.page_sha256),
                    revision_diff_sha256=None if revision_diff is None else files["revision-diff.json"],
                    files=files,
                )
                manifest_raw = canonical_json_v4(manifest.model_dump(mode="json")).encode("utf-8")
                _stage_write(lease, stage, "workspace-manifest.json", manifest_raw)
                lease.assert_intact()
                stage_identity = _verify_staging(paths, stage, manifest, manifest_raw, lease)
                prepublish_identity = _verify_staging(paths, stage, manifest, manifest_raw, lease)
                if prepublish_identity != stage_identity:
                    raise ReviewBindingError("staging directory identity changed before publication")
                _publish_stage(lease, stage, stage_identity)
                published = True
            except BaseException as transaction_error:
                if not published:
                    try:
                        _remove_tree_at(lease.fd, stage)
                    except FileNotFoundError:
                        pass
                    except BaseException as cleanup_error:
                        transaction_error.add_note(f"staging cleanup failed: {cleanup_error}")
                raise
    except BaseException as error:
        if not published:
            cleanup_error = _cleanup_stage(paths, stage)
            if cleanup_error is not None:
                error.add_note(f"staging cleanup retry failed: {cleanup_error}")
        if isinstance(error, ReviewBindingError):
            raise
        raise ReviewBindingError("review workspace transaction failed") from error

    assert manifest is not None
    workspace = ReviewWorkspaceV4(
        paths.review_root,
        manifest,
        paths,
        manifest_raw,
        _WORKSPACE_TRUST_TOKEN,
    )
    object.__setattr__(workspace, "_attestation", _workspace_attestation(workspace))
    try:
        verify_review_workspace(workspace)
    except BaseException as error:
        cleanup_error = _remove_published_review(paths)
        if cleanup_error is not None:
            error.add_note(f"failed review quarantine/cleanup: {cleanup_error}")
        try:
            notes = " ".join(str(note) for note in getattr(error, "__notes__", ()))
            _write_recovery_journal(paths, (str(error) + " " + notes).strip())
        except BaseException as recovery_error:
            error.add_note(f"recovery journal failed: {recovery_error}")
        raise ReviewBindingError("published review workspace failed post-publish verification") from error
    return workspace


def verify_review_workspace(workspace: ReviewWorkspaceV4) -> None:
    """Re-read a published workspace through no-follow, trusted-manifest reads."""

    if not isinstance(workspace, ReviewWorkspaceV4):
        raise ReviewBindingError("workspace must be a ReviewWorkspaceV4")
    if workspace._trust_token is not _WORKSPACE_TRUST_TOKEN:
        raise ReviewBindingError("workspace handle was not issued by the verifier")
    if workspace._attestation != _workspace_attestation(workspace):
        raise ReviewBindingError("workspace handle attestation does not bind its manifest and paths")
    try:
        paths = revalidate_artifact_paths(workspace.artifact_paths)
    except (ArtifactIdentityError, OSError) as error:
        raise ReviewBindingError("review workspace artifact root changed") from error
    if workspace.root != paths.review_root:
        raise ReviewBindingError("review workspace root drifted")
    expected_raw = workspace.manifest_raw
    canonical_manifest_raw = canonical_json_v4(workspace.manifest.model_dump(mode="json")).encode("utf-8")
    if expected_raw != canonical_manifest_raw:
        raise ReviewBindingError("workspace manifest raw bytes are not the trusted canonical payload")
    _verify_workspace_root(workspace.root, workspace.manifest, expected_manifest_raw=expected_raw)


def read_review_intent(workspace: ReviewWorkspaceV4) -> HumanReviewIntentV4:
    """Safely parse mutable review/decision.json without binding it to approval."""

    if (
        type(workspace) is not ReviewWorkspaceV4
        or workspace._trust_token is not _WORKSPACE_TRUST_TOKEN
        or workspace._attestation != _workspace_attestation(workspace)
    ):
        raise ReviewBindingError("workspace handle was not issued by the verifier")
    try:
        paths = revalidate_artifact_paths(workspace.artifact_paths)
        snapshot = read_verified_artifact_snapshot(paths.review_root / "decision.json", None, containment_root=paths.review_root)
        return HumanReviewIntentV4.model_validate_json(snapshot.raw)
    except (ArtifactIdentityError, ArtifactBindingError, ValueError) as error:
        raise ReviewBindingError("review decision intake is malformed or unsafe") from error


__all__ = [
    "ReviewBindingError", "ReviewWorkspaceInputsV4", "ReviewWorkspaceV4",
    "build_review_workspace", "verify_review_workspace", "read_review_intent",
]
