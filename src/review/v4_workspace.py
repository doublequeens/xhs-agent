"""Transactional, local-only review workspaces for one immutable v4 revision.

This module is deliberately not a Human Review node.  It materializes trusted
bytes into ``ArtifactPaths.review_root`` and exposes a verifier seam for the
Task 16B decision/node boundary.  No decision intake is trusted here.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import shutil
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from pydantic import BaseModel, ConfigDict

from src.schemas.assets import AssetManifest
from src.schemas.content_atoms import canonical_sha256
from src.schemas.content_lock import ContentLock
from src.schemas.v4.content import canonical_json_v4, canonical_sha256_v4
from src.schemas.v4.content import ContentAtomSetV4
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
    read_verified_artifact_snapshot,
    revalidate_artifact_paths,
)


class ReviewBindingError(RuntimeError):
    """A review source or materialized workspace is stale, forged, or unsafe."""


class ReviewWorkspaceInputsV4(BaseModel):
    """Current source contracts; all fields are revalidated at the file boundary."""

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
    previous_review_root: Path | None = None
    previous_manifest: ReviewWorkspaceManifestV4 | None = None


@dataclass(frozen=True, slots=True)
class ReviewWorkspaceV4:
    root: Path
    manifest: ReviewWorkspaceManifestV4
    artifact_paths: ArtifactPaths


@dataclass(frozen=True, slots=True)
class _RenderedAsset:
    asset_id: str
    sha256: str
    raw: bytes


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _contract_hash(value: object) -> str:
    digest = getattr(value, "canonical_sha256", None)
    if isinstance(digest, str) and len(digest) == 64:
        return digest
    return canonical_sha256(value)  # v3 AssetManifest has no durable hash field.


def _content_lock_hash(lock: ContentLock) -> str:
    payload = lock.model_dump(mode="json", exclude={"canonical_sha256"})
    expected = canonical_sha256(payload)
    if lock.canonical_sha256 != expected:
        raise ReviewBindingError("ContentLock canonical hash is stale")
    return expected


def _checked(inputs: ReviewWorkspaceInputsV4) -> tuple[ArtifactPaths, dict[str, str]]:
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
    except (ArtifactIdentityError, ValueError, TypeError) as error:
        raise ReviewBindingError("review source contracts are invalid") from error
    identity = paths.identity
    plan = inputs.carousel_design_plan
    render = inputs.render_manifest
    q2 = inputs.design_plan_qa
    q3 = inputs.render_qa
    q4 = inputs.visual_critique
    atoms, semantic, narrative, briefs, direction = (inputs.content_atom_set, inputs.semantic_content_model,
        inputs.carousel_narrative, inputs.page_brief_set, inputs.visual_direction_plan)
    if (plan.run_id, plan.candidate_id, f"revision-{plan.revision}") != (identity.run_id, identity.candidate_id, identity.revision_id):
        raise ReviewBindingError("design plan identity does not match artifact paths")
    if (render.run_id, render.candidate_id, render.revision_id) != (identity.run_id, identity.candidate_id, identity.revision_id):
        raise ReviewBindingError("render manifest identity does not match artifact paths")
    if not q2.passed or not q3.passed:
        raise ReviewBindingError("all Q0-Q3 hard gates must pass before review")
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
    expected = (
        (semantic.content_atom_set_sha256, hashes["content_atom_set_sha256"]),
        (narrative.content_atom_set_sha256, hashes["content_atom_set_sha256"]),
        (briefs.content_atom_set_sha256, hashes["content_atom_set_sha256"]),
        (briefs.semantic_content_model_sha256, hashes["semantic_content_model_sha256"]),
        (direction.content_atom_set_sha256, hashes["content_atom_set_sha256"]),
        (direction.semantic_content_model_sha256, hashes["semantic_content_model_sha256"]),
        (direction.narrative_sha256, hashes["narrative_sha256"]),
        (direction.page_brief_set_sha256, hashes["page_brief_set_sha256"]),
        (plan.content_atom_set_sha256, hashes["content_atom_set_sha256"]),
        (plan.semantic_content_model_sha256, hashes["semantic_content_model_sha256"]),
        (plan.page_brief_set_sha256, hashes["page_brief_set_sha256"]),
        (plan.visual_direction_plan_sha256, hashes["visual_direction_plan_sha256"]),
        (q2.content_atom_set_sha256, hashes["content_atom_set_sha256"]),
        (q2.semantic_content_model_sha256, hashes["semantic_content_model_sha256"]),
        (q2.narrative_sha256, hashes["narrative_sha256"]),
        (q2.page_brief_set_sha256, hashes["page_brief_set_sha256"]),
        (q2.visual_direction_plan_sha256, hashes["visual_direction_plan_sha256"]),
        (render.design_plan_sha256, hashes["carousel_design_plan_sha256"]),
        (render.design_plan_qa_sha256, hashes["design_plan_qa_sha256"]),
        (render.content_lock_sha256, hashes["content_lock_sha256"]),
        (render.asset_manifest_sha256, hashes["asset_manifest_sha256"]),
        (q3.render_manifest_sha256, hashes["render_manifest_sha256"]),
        (q3.design_plan_qa_sha256, hashes["design_plan_qa_sha256"]),
        (q4.render_manifest_sha256, hashes["render_manifest_sha256"]),
        (q4.render_qa_result_sha256, hashes["render_qa_sha256"]),
    )
    if any(left != right for left, right in expected):
        raise ReviewBindingError("review source contracts are cross-bound to stale inputs")
    return paths, hashes


def _read_revision(paths: ArtifactPaths, relative: str, digest: str) -> bytes:
    if relative.startswith("/") or ".." in Path(relative).parts:
        raise ReviewBindingError("review artifact path is not revision-relative")
    try:
        return read_verified_artifact_snapshot(paths.revision_root / relative, digest, containment_root=paths.revision_root).raw
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


def _rendered_assets(inputs: ReviewWorkspaceInputsV4, paths: ArtifactPaths) -> tuple[_RenderedAsset, ...]:
    """Derive exact image use from the immutable Scene Plan, never filenames."""
    by_directive = {item.directive_id: item for item in inputs.asset_manifest.items}
    seen: dict[str, _RenderedAsset] = {}
    for page in inputs.carousel_design_plan.pages:
        for directive_id, binding in page.compiler_provenance.asset_binding_evidence.items():
            item = by_directive.get(directive_id)
            if item is None or item.asset_id in seen:
                if item is None:
                    raise ReviewBindingError("rendered asset directive is absent from manifest")
                continue
            if (item.sha256 != binding.asset_sha256 or item.security_status != "approved"
                    or item.human_decision != "pending" or item.run_id != paths.identity.run_id
                    or item.transaction_id != paths.identity.revision_id):
                raise ReviewBindingError("rendered asset manifest binding is stale or unsafe")
            source = Path(item.local_path)
            try:
                snapshot = read_verified_artifact_snapshot(source, item.sha256, containment_root=paths.asset_root)
            except ArtifactBindingError as error:
                raise ReviewBindingError("rendered asset bytes changed or are unsafe") from error
            seen[item.asset_id] = _RenderedAsset(item.asset_id, snapshot.sha256, snapshot.raw)
    return tuple(seen[key] for key in sorted(seen))


def _quality_report(inputs: ReviewWorkspaceInputsV4, hashes: Mapping[str, str]) -> bytes:
    q2 = inputs.design_plan_qa
    q4 = inputs.visual_critique
    payload = {
        "workflow_version": "llm_scene_v4",
        "hard_gates": {"q0_q2_passed": q2.passed, "q3_passed": inputs.render_qa.passed},
        "source_hashes": dict(hashes),
        "q2_pages": [item.model_dump(mode="json") for item in q2.page_metrics],
        "q4": q4.model_dump(mode="json"),
        "page_briefs": [
            {"page_id": page.page_id, "sequence": page.sequence,
             "role": page.layout_program.beat_task_kind,
             "duty": page.layout_program.beat_task_kind}
            for page in inputs.carousel_design_plan.pages
        ],
    }
    return canonical_json_v4(payload).encode("utf-8")


def _overlay_svg(page_id: str, sequence: int) -> bytes:
    safe = html.escape(page_id, quote=True)
    return ("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1080\" height=\"1440\" "
            "viewBox=\"0 0 1080 1440\"><rect x=\"18\" y=\"18\" width=\"1044\" height=\"1404\" "
            "fill=\"none\" stroke=\"#00a7a7\" stroke-width=\"6\"/><text x=\"40\" y=\"78\" "
            "font-size=\"38\" fill=\"#00a7a7\">Q2 overlay " + str(sequence) + " · " + safe + "</text></svg>").encode("utf-8")


def _html_page(inputs: ReviewWorkspaceInputsV4, manifest: ReviewWorkspaceManifestV4 | None, page_paths: Mapping[str, str]) -> bytes:
    title = html.escape(inputs.content_lock.title, quote=True)
    cards = "".join(
        "<article class=\"page-card\"><h3>" + html.escape(page.page_id) + "</h3>"
        "<img class=\"page-image\" src=\"" + html.escape(path) + "\" width=\"1080\" height=\"1440\" alt=\"" + html.escape(page.page_id) + "\">"
        "<img class=\"overlay\" src=\"overlays/" + f"{page.sequence:02d}-{page.page_id}.svg" + "\" alt=\"Q2 overlay\"></article>"
        for page, path in zip(inputs.render_manifest.pages, page_paths)
    )
    assets = "".join(
        "<li><b>" + html.escape(item.asset_id) + "</b> provider=" + html.escape(item.provider) +
        " source=" + html.escape(item.source_kind) + " license=" + html.escape(item.license) + " security=" + html.escape(item.security_status) +
        " human=" + html.escape(item.human_decision) + " recovery=recorded sha256=" + html.escape(item.sha256) + "</li>"
        for item in inputs.asset_manifest.items
    ) or "<li>No external assets referenced.</li>"
    manifest_hash = "" if manifest is None else html.escape(manifest.canonical_sha256)
    document = """<!doctype html><html><head><meta charset=\"utf-8\">
<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; script-src 'none'; connect-src 'none'; font-src 'none'; media-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'\">
<style>body{font-family:system-ui;margin:24px;color:#17202a}img{max-width:280px;height:auto}.page-card{display:inline-block;vertical-align:top;width:300px;margin:8px}.overlay{display:block;border:1px solid #0aa}section{margin:24px 0}code{word-break:break-all}</style></head><body>"""
    document += "<h1>V4 Review: " + title + "</h1><p id=\"content-lock\">ContentLock hash: <code>" + html.escape(_content_lock_hash(inputs.content_lock)) + "</code></p>"
    document += "<section id=\"contact-sheet\"><h2>Contact sheet</h2><img src=\"contact-sheet.png\" alt=\"Contact sheet\"></section>"
    document += "<section id=\"pages\"><h2>Original-size pages</h2>" + cards + "</section>"
    document += "<section id=\"quality-report\"><h2>Q0-Q4 evidence</h2><a href=\"quality-report.json\">quality report</a></section>"
    document += "<section id=\"asset-evidence\"><h2>Asset internal evidence</h2><ul>" + assets + "</ul></section>"
    if inputs.previous_review_root is not None:
        document += "<section id=\"previous-revision\"><h2>Previous revision comparison</h2><img src=\"previous-revision/contact-sheet.png\" alt=\"Previous contact sheet\"></section>"
    document += "<section id=\"decision-intake\"><h2>Untrusted decision intake</h2><a href=\"decision.json\">decision.json</a></section>"
    document += "<footer>Workspace manifest: <code>" + manifest_hash + "</code></footer></body></html>"
    return document.encode("utf-8")


def _stage_write(lease, stage: str, name: str, raw: bytes) -> None:
    _atomic_write_at(lease.fd, (stage, *Path(name).parts), raw)


def _publish_stage(paths: ArtifactPaths, stage: str) -> None:
    # Existing primitive's direct-child constraints are matched here, but the
    # final rename must be no-replace.  It is implemented descriptor-relatively.
    from src.visual_runtime.artifact_identity import bind_staged_directory
    bind_staged_directory(paths.revision_root / stage, paths.review_root, revision_root=paths.revision_root)


def _previous_files(inputs: ReviewWorkspaceInputsV4) -> tuple[Path, ReviewWorkspaceManifestV4] | None:
    root, manifest = inputs.previous_review_root, inputs.previous_manifest
    if (root is None) != (manifest is None):
        raise ReviewBindingError("previous review root and manifest must be supplied together")
    if root is None or manifest is None:
        return None
    if root.is_symlink() or not root.is_dir():
        raise ReviewBindingError("previous review root is unsafe")
    if (manifest.run_id, manifest.candidate_id) != (inputs.artifact_paths.identity.run_id, inputs.artifact_paths.identity.candidate_id):
        raise ReviewBindingError("previous review identity does not match candidate")
    if manifest.revision_id == inputs.artifact_paths.identity.revision_id:
        raise ReviewBindingError("previous review cannot equal current revision")
    # Check every copied byte against the exact supplied manifest before it is
    # linked into a current comparison.  The prior manifest itself is immutable
    # application state; this function never trusts a mutable review intake.
    for relative, digest in manifest.files.items():
        try:
            read_verified_artifact_snapshot(root / relative, digest, containment_root=root)
        except ArtifactBindingError as error:
            raise ReviewBindingError("previous review bytes no longer match manifest") from error
    return root, manifest


def build_review_workspace(inputs: ReviewWorkspaceInputsV4) -> ReviewWorkspaceV4:
    """Publish one complete local workspace, refusing stale sources and overwrite."""
    paths, hashes = _checked(inputs)
    rendered_assets = _rendered_assets(inputs, paths)
    previous = _previous_files(inputs)
    if paths.review_root.exists():
        raise ReviewBindingError("an immutable review workspace already exists for this revision")
    pages = _page_paths(inputs.render_manifest)
    stage = ".review-staging-" + uuid.uuid4().hex
    files: dict[str, str] = {}
    try:
        with _lease_context(_open_absolute_directory(paths.revision_root, create=False)) as lease:
            lease.assert_intact()
            os.mkdir(stage, mode=0o700, dir_fd=lease.fd)
            _stage_write(lease, stage, "contact-sheet.png", _read_revision(paths, inputs.render_manifest.contact_sheet_path, inputs.render_manifest.contact_sheet_sha256))
            files["contact-sheet.png"] = inputs.render_manifest.contact_sheet_sha256
            for source, (destination, digest) in zip(inputs.render_manifest.pages, pages.items()):
                _stage_write(lease, stage, destination, _read_revision(paths, source.path, digest))
                files[destination] = digest
                _stage_write(lease, stage, f"overlays/{source.sequence:02d}-{source.page_id}.svg", _overlay_svg(source.page_id, source.sequence))
                files[f"overlays/{source.sequence:02d}-{source.page_id}.svg"] = _sha(_overlay_svg(source.page_id, source.sequence))
            for asset in rendered_assets:
                target = f"assets/{asset.asset_id}.bin"
                _stage_write(lease, stage, target, asset.raw)
                files[target] = asset.sha256
            if previous is not None:
                previous_root, previous_manifest = previous
                previous_contact = read_verified_artifact_snapshot(
                    previous_root / "contact-sheet.png", previous_manifest.contact_sheet_sha256,
                    containment_root=previous_root,
                ).raw
                _stage_write(lease, stage, "previous-revision/contact-sheet.png", previous_contact)
                files["previous-revision/contact-sheet.png"] = _sha(previous_contact)
                for destination, digest in previous_manifest.page_sha256.items():
                    prior = read_verified_artifact_snapshot(previous_root / destination, digest, containment_root=previous_root).raw
                    copied = "previous-revision/" + destination
                    _stage_write(lease, stage, copied, prior)
                    files[copied] = _sha(prior)
            quality = _quality_report(inputs, hashes)
            _stage_write(lease, stage, "quality-report.json", quality)
            files["quality-report.json"] = _sha(quality)
            intake = canonical_json_v4({"untrusted": True, "action": None, "rationale": None, "asset_ids": []}).encode()
            _stage_write(lease, stage, "decision.json", intake)
            # index is deliberately generated before manifest; it exposes only the
            # existing ContentLock digest and references local relative resources.
            index = _html_page(inputs, None, pages)
            _stage_write(lease, stage, "index.html", index)
            files["index.html"] = _sha(index)
            # A manifest cannot hash its own bytes without a cycle.  Its canonical
            # hash binds every other file, and the verifier re-parses its bytes.
            manifest = ReviewWorkspaceManifestV4.create(
                run_id=paths.identity.run_id, candidate_id=paths.identity.candidate_id,
                revision_id=paths.identity.revision_id, **hashes, page_sha256=pages,
                contact_sheet_sha256=inputs.render_manifest.contact_sheet_sha256, files=files,
            )
            manifest_raw = canonical_json_v4(manifest.model_dump(mode="json")).encode("utf-8")
            _stage_write(lease, stage, "workspace-manifest.json", manifest_raw)
            lease.assert_intact()
        _publish_stage(paths, stage)
    except (ArtifactBindingError, ArtifactIdentityError, OSError, ValueError) as error:
        try:
            staged = paths.revision_root / stage
            if staged.exists() and staged.is_dir() and not staged.is_symlink():
                shutil.rmtree(staged)
        except OSError:
            pass
        raise ReviewBindingError("review workspace transaction failed") from error
    workspace = ReviewWorkspaceV4(paths.review_root, manifest, paths)
    verify_review_workspace(workspace)
    return workspace


def verify_review_workspace(workspace: ReviewWorkspaceV4) -> None:
    """Re-read a published workspace through no-follow source validation."""
    try:
        paths = revalidate_artifact_paths(workspace.artifact_paths)
    except (ArtifactIdentityError, OSError) as error:
        raise ReviewBindingError("review workspace artifact root changed") from error
    if workspace.root != paths.review_root:
        raise ReviewBindingError("review workspace root drifted")
    manifest_path = workspace.root / "workspace-manifest.json"
    try:
        raw = read_verified_artifact_snapshot(manifest_path, None, containment_root=workspace.root).raw
        actual = ReviewWorkspaceManifestV4.model_validate_json(raw)
    except (OSError, ArtifactBindingError, ValueError) as error:
        raise ReviewBindingError("workspace manifest is invalid or unsafe") from error
    if actual != workspace.manifest:
        raise ReviewBindingError("workspace manifest differs from published review")
    for relative, digest in actual.files.items():
        path = workspace.root / relative
        try:
            read_verified_artifact_snapshot(path, digest, containment_root=workspace.root)
        except (OSError, ArtifactBindingError) as error:
            raise ReviewBindingError("workspace file bytes changed or path is unsafe") from error


def read_review_intent(workspace: ReviewWorkspaceV4) -> HumanReviewIntentV4:
    """Safely parse mutable review/decision.json without binding it to approval."""
    try:
        paths = revalidate_artifact_paths(workspace.artifact_paths)
        snapshot = read_verified_artifact_snapshot(paths.review_root / "decision.json", None, containment_root=paths.review_root)
        return HumanReviewIntentV4.model_validate_json(snapshot.raw)
    except (ArtifactIdentityError, ArtifactBindingError, ValueError) as error:
        raise ReviewBindingError("review decision intake is malformed or unsafe") from error


__all__ = [
    "ReviewBindingError", "ReviewWorkspaceInputsV4", "ReviewWorkspaceV4",
    "build_review_workspace", "verify_review_workspace",
    "read_review_intent",
]
