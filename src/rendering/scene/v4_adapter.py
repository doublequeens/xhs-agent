"""Adapter from the hash-bound v4 Scene Plan to the generic renderer.

This module is the only v4-specific rendering seam.  It constructs private
v3-compatible fragments, assets and style inputs, invokes the existing single
generic compiler/Chromium renderer, then publishes sanitized evidence through
the descriptor-relative Task 9 artifact primitives.  No provider metadata or
absolute path is allowed into the durable v4 manifest.
"""

from __future__ import annotations

import hashlib
import math
import shutil
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from src.nodes.v4.design_qa import aggregate_design_qa
from src.rendering.scene.compiler import CompiledPage, compile_page_scene
from src.rendering.scene.probes import (
    V4_PROBE_SCRIPT,
    ProbeBuildError,
    build_element_probes,
)
from src.rendering.scene.renderer import (
    RenderedPageDraft,
    _ChromiumPageRenderer,
    _atomic_write_bytes,
    _default_contact_sheet,
    _render_with_retry,
)
from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.content_atoms import ContentFragment, canonical_sha256 as canonical_sha256_v3
from src.schemas.content_lock import ContentLock
from src.schemas.scene_graph import ImageElement, PageScene, TextElement
from src.schemas.v4.content import (
    ContentAtomSetV4,
    canonical_json_v4,
    canonical_sha256_v4,
    sha256_text_v4,
)
from src.schemas.v4.direction import PageBriefSetV4, VisualDirectionPlanV4
from src.schemas.v4.layout import CarouselDesignPlanV4, FamilyTokensV4
from src.schemas.v4.quality import DesignPlanQAResultV4
from src.schemas.v4.rendering import (
    ArtifactIdentityV4,
    RenderAssetEvidenceV4,
    RenderElementEvidenceV4,
    RenderFontEvidenceV4,
    RenderGlyphCoverageV4,
    RenderGlyphEvidenceV4,
    RenderManifestV4,
    RenderPageEvidenceV4,
    RenderBoxV4,
)
from src.schemas.v4.semantic import SemanticContentModelV4
from src.visual_design.v4.tokens import get_family_tokens
from src.visual_design.v4.typography import (
    CANONICAL_FONT_NOMINAL_WEIGHTS_V4,
    reconstruct_source_lines_v4,
    resolve_font_file_v4,
)
from src.visual_runtime.artifact_identity import (
    ArtifactBindingError,
    ArtifactPaths,
    bind_staged_directory,
    ensure_artifact_paths,
    read_verified_artifact,
    revalidate_artifact_paths,
    resolve_artifact_paths,
)
from src.schemas.visual_style import FamilyStyleProfile


class V4RenderError(RuntimeError):
    """A v4 input, render, or immutable-publication invariant failed."""


@dataclass(frozen=True)
class V4RenderResult:
    manifest: RenderManifestV4
    artifact_paths: ArtifactPaths


RenderPageFn = Callable[[CompiledPage], RenderedPageDraft]
ContactSheetFn = Callable[[tuple[Path, ...]], bytes]


def _coerce(model_type: type[Any], value: Any, name: str):
    raw = value.model_dump(mode="python") if isinstance(value, model_type) else value
    if not isinstance(raw, Mapping):
        raise V4RenderError(f"{name} is missing or not a persisted mapping")
    try:
        checked = model_type.model_validate(raw)
        validate_integrity = getattr(checked, "validate_integrity", None)
        if callable(validate_integrity):
            validate_integrity()
        return checked
    except Exception:
        raise V4RenderError(f"{name} is stale or structurally invalid") from None


def _lock_hash(lock: ContentLock) -> str:
    try:
        payload = lock.model_dump(mode="json", exclude={"canonical_sha256"})
        expected = canonical_sha256_v4(payload)
    except Exception:
        raise V4RenderError("content lock is not serializable") from None
    if lock.canonical_sha256 != expected:
        raise V4RenderError("content lock canonical hash is stale")
    return lock.canonical_sha256


def _private_style(tokens: FamilyTokensV4) -> FamilyStyleProfile:
    """Project canonical v4 tokens into the generic compiler's private style."""

    return FamilyStyleProfile(
        family=tokens.family,
        # The generic compiler only needs this non-empty field to satisfy the
        # v3 profile contract.  It never emits the private reference path.
        reference_image_paths=("v4-private-reference",),
        palette=tokens.palette,
        font_roles=tokens.font_roles.model_dump(mode="python"),
        composition_principles=tokens.composition_principles,
        whitespace_range=(tokens.whitespace_envelope.low, tokens.whitespace_envelope.high),
        density_range=(tokens.density_envelope.low, tokens.density_envelope.high),
        allowed_motifs=tokens.motif_rules.allowed,
        prohibited_patterns=tokens.motif_rules.prohibited,
    )


def _private_fragments(model: SemanticContentModelV4) -> dict[str, ContentFragment]:
    return {
        fragment.fragment_id: ContentFragment(
            fragment_id=fragment.fragment_id,
            source_atom_id=fragment.source_atom_id,
            start=fragment.start,
            end=fragment.end,
            text=fragment.exact_text,
        )
        for fragment in model.fragments
    }


def _private_assets(
    plan: CarouselDesignPlanV4,
    manifest: AssetManifest,
    paths: ArtifactPaths,
    *,
    verified_bytes: dict[str, bytes] | None = None,
) -> dict[str, AssetManifestItem]:
    """Map opaque scene refs to private resolver items after byte validation."""

    by_directive = {item.directive_id: item for item in manifest.items}
    private: dict[str, AssetManifestItem] = {}
    for page in plan.pages:
        evidence = page.compiler_provenance.asset_binding_evidence
        for directive_id, binding in evidence.items():
            item = by_directive.get(directive_id)
            if (
                item is None
                or item.page_id != page.page_id
                or binding.directive_id != directive_id
                or binding.page_id != page.page_id
            ):
                raise V4RenderError("scene asset directive is not bound to the exact manifest")
            if item.run_id != plan.run_id:
                raise V4RenderError("scene asset transaction is bound to a different run")
            if item.transaction_id != paths.identity.revision_id:
                raise V4RenderError("scene asset transaction is bound to a different revision")
            if item.security_status != "approved" or item.human_decision != "pending":
                raise V4RenderError("scene asset is not approved and pending human review")
            if item.sha256 != binding.asset_sha256:
                raise V4RenderError("scene asset byte hash is stale")
            try:
                body = read_verified_artifact(
                    item.local_path,
                    item.sha256,
                    containment_root=paths.asset_root,
                )
            except ArtifactBindingError:
                raise V4RenderError("approved asset source is unsafe or unstable") from None
            existing = verified_bytes.get(binding.asset_ref) if verified_bytes is not None else None
            if existing is not None and existing != body:
                raise V4RenderError("opaque asset ref is bound to conflicting bytes")
            if verified_bytes is not None:
                verified_bytes[binding.asset_ref] = body
            private[binding.asset_ref] = item.model_copy(update={"asset_id": binding.asset_ref})
    return private


def _text_options(
    plan: CarouselDesignPlanV4,
    semantic_model: SemanticContentModelV4,
) -> dict[tuple[str, str], dict[str, object]]:
    fragments = {item.fragment_id: item for item in semantic_model.fragments}
    options: dict[tuple[str, str], dict[str, object]] = {}
    for page in plan.pages:
        for ref, evidence in page.compiler_provenance.text_measurement_evidence.items():
            fragment = fragments.get(ref)
            if fragment is None:
                raise V4RenderError("text measurement references an unknown semantic fragment")
            try:
                lines = reconstruct_source_lines_v4(
                    fragment.exact_text,
                    explicit_break_spans=evidence.explicit_break_spans,
                    inserted_break_offsets=evidence.inserted_break_offsets,
                )
            except Exception:
                raise V4RenderError("text measurement break evidence is stale") from None
            options[(page.page_id, ref)] = {
                "text": "\n".join(lines.lines),
                "preformatted": True,
                "content_inset": (
                    evidence.content_inset_left_px,
                    evidence.content_inset_top_px,
                    evidence.content_inset_right_px,
                    evidence.content_inset_bottom_px,
                ),
            }
    return options


def _font_sources(tokens: FamilyTokensV4) -> dict[str, tuple[Path, int]]:
    sources: dict[str, tuple[Path, int]] = {}
    for role in ("display", "heading", "body", "caption"):
        font = resolve_font_file_v4(tokens.family, role)
        expected_weight = CANONICAL_FONT_NOMINAL_WEIGHTS_V4[font.family_name]
        if font.nominal_weight != expected_weight:
            raise V4RenderError("canonical v4 font nominal weight is stale")
        sources[font.family_name] = (font.path, font.nominal_weight)
    return sources


def _raw_by_id(raw_probes: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for raw in raw_probes:
        if not isinstance(raw, dict):
            continue
        element_id = raw.get("element_id")
        if isinstance(element_id, str) and element_id and element_id not in result:
            result[element_id] = raw
    return result


def _required_raw(raw: Mapping[str, object], key: str) -> object:
    if key not in raw or raw[key] is None:
        raise V4RenderError(f"browser probe is missing measured field: {key}")
    return raw[key]


def _required_float(raw: Mapping[str, object], key: str) -> float:
    value = _required_raw(raw, key)
    if isinstance(value, bool):
        raise V4RenderError(f"browser probe field is not numeric: {key}")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise V4RenderError(f"browser probe field is not numeric: {key}") from None
    if not math.isfinite(result):
        raise V4RenderError(f"browser probe field is not finite: {key}")
    return result


def _required_bool(raw: Mapping[str, object], key: str) -> bool:
    value = _required_raw(raw, key)
    if type(value) is not bool:
        raise V4RenderError(f"browser probe field is not boolean: {key}")
    return value


def _required_int(raw: Mapping[str, object], key: str) -> int:
    value = _required_float(raw, key)
    if value != int(value):
        raise V4RenderError(f"browser probe field is not integral: {key}")
    return int(value)


def _required_hash(raw: Mapping[str, object], key: str) -> str:
    value = _required_raw(raw, key)
    if type(value) is not str or len(value) != 64:
        raise V4RenderError(f"browser probe field is not a sha256: {key}")
    try:
        int(value, 16)
    except ValueError:
        raise V4RenderError(f"browser probe field is not a sha256: {key}") from None
    return value.lower()


def _raw_box(raw: Mapping[str, object]) -> RenderBoxV4:
    return RenderBoxV4(
        x=_required_float(raw, "x"),
        y=_required_float(raw, "y"),
        width=_required_float(raw, "width"),
        height=_required_float(raw, "height"),
    )


def _scene_box(box) -> RenderBoxV4:
    return RenderBoxV4(
        x=float(box.x),
        y=float(box.y),
        width=float(box.width),
        height=float(box.height),
    )


def _raw_line_boxes(raw: Mapping[str, object]) -> tuple[RenderBoxV4, ...]:
    value = _required_raw(raw, "line_boxes")
    if not isinstance(value, (list, tuple)):
        raise V4RenderError("browser line-box evidence is not a sequence")
    boxes: list[RenderBoxV4] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise V4RenderError("browser line-box evidence is malformed")
        boxes.append(
            RenderBoxV4(
                x=_required_float(item, "x"),
                y=_required_float(item, "y"),
                width=_required_float(item, "width"),
                height=_required_float(item, "height"),
            )
        )
    return tuple(boxes)


def _require_probe_shape(raw: Mapping[str, object], element) -> None:
    common = (
        "x", "y", "width", "height", "scroll_width", "scroll_height",
        "client_width", "client_height", "line_boxes",
    )
    required = list(common)
    if isinstance(element, TextElement):
        required.extend(
            (
                "actual_text", "font_family", "font_size", "line_height",
                "font_weight", "font_loaded", "document_fonts_status",
                "dom_text_measured", "glyph_visible", "missing_codepoint_count",
                "glyph_coverage",
            )
        )
    elif isinstance(element, ImageElement):
        required.extend(
            (
                "asset_loaded", "natural_width", "natural_height",
                "rendered_image_width", "rendered_image_height",
            )
        )
    for key in required:
        _required_raw(raw, key)


def _make_glyph(
    *, raw: Mapping[str, object], actual_text: str
) -> RenderGlyphEvidenceV4:
    loaded = _required_bool(raw, "font_loaded")
    visible = _required_bool(raw, "glyph_visible")
    coverage_raw = _required_raw(raw, "glyph_coverage")
    if not isinstance(coverage_raw, (list, tuple)):
        raise V4RenderError("browser glyph coverage is not a sequence")
    if actual_text and not coverage_raw:
        raise V4RenderError("browser glyph coverage is missing for measured text")
    coverage: list[RenderGlyphCoverageV4] = []
    for item in coverage_raw:
        if not isinstance(item, Mapping) or type(item.get("visible")) is not bool:
            raise V4RenderError("browser glyph coverage is malformed")
        raster_signature = _required_hash(item, "raster_signature")
        try:
            coverage.append(
                RenderGlyphCoverageV4(
                    visible=item["visible"],
                    width=_required_float(item, "width"),
                    height=_required_float(item, "height"),
                    is_whitespace=_required_bool(item, "is_whitespace"),
                    face_loaded=_required_bool(item, "face_loaded"),
                    font_check=_required_bool(item, "font_check"),
                    ink_pixel_count=_required_int(item, "ink_pixel_count"),
                    raster_signature=raster_signature,
                    fallback_ink_pixel_count=_required_int(
                        item, "fallback_ink_pixel_count"
                    ),
                    fallback_raster_signature=_required_hash(
                        item, "fallback_raster_signature"
                    ),
                    tofu_ink_pixel_count=_required_int(item, "tofu_ink_pixel_count"),
                    tofu_raster_signature=_required_hash(item, "tofu_raster_signature"),
                )
            )
        except V4RenderError:
            raise
        except Exception:
            raise V4RenderError("browser glyph coverage is malformed") from None
    non_whitespace = [item for item in coverage if not item.is_whitespace]
    expected_visible = bool(non_whitespace) and all(
        item.visible for item in non_whitespace
    )
    if visible != expected_visible:
        raise V4RenderError("browser glyph visibility disagrees with coverage")
    missing = sum(1 for item in non_whitespace if not item.visible)
    if _required_int(raw, "missing_codepoint_count") != missing:
        raise V4RenderError("browser missing-codepoint count disagrees with coverage")
    payload = {
        "visible": visible,
        "loaded": loaded,
        "missing_codepoint_count": missing,
        "coverage": tuple(coverage),
    }
    return RenderGlyphEvidenceV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def _make_font(
    *,
    element: TextElement,
    raw: Mapping[str, object],
    tokens: FamilyTokensV4,
    font_sha256: str,
) -> RenderFontEvidenceV4:
    expected_family = getattr(tokens.font_roles, element.style.font_role)
    expected_weight = CANONICAL_FONT_NOMINAL_WEIGHTS_V4[expected_family]
    status = _required_raw(raw, "document_fonts_status")
    if status not in {"loaded", "loading", "unloaded", "error", "unknown"}:
        raise V4RenderError("browser font status is not recognized")
    family = _required_raw(raw, "font_family")
    if type(family) is not str or not family.strip():
        raise V4RenderError("browser computed font family is missing")
    payload = {
        "role": element.style.font_role,
        "expected_family": expected_family,
        "computed_family": family,
        "expected_font_sha256": font_sha256,
        "computed_weight": _required_int(raw, "font_weight"),
        "expected_weight": expected_weight,
        "font_size_px": _required_float(raw, "font_size"),
        "line_height_px": _required_float(raw, "line_height"),
        "font_loaded": _required_bool(raw, "font_loaded"),
        "document_fonts_status": status,
    }
    return RenderFontEvidenceV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def _make_asset(
    *,
    element: ImageElement,
    raw: Mapping[str, object],
    binding,
    asset_sha256: str,
) -> RenderAssetEvidenceV4:
    payload = {
        "directive_id": binding.directive_id,
        "asset_ref": element.asset_ref,
        "asset_sha256": asset_sha256,
        "fit": element.fit,
        "orientation": binding.orientation,
        "loaded": _required_bool(raw, "asset_loaded"),
        "natural_width": _required_float(raw, "natural_width"),
        "natural_height": _required_float(raw, "natural_height"),
        "rendered_width": _required_float(raw, "rendered_image_width"),
        "rendered_height": _required_float(raw, "rendered_image_height"),
        "box_ratio": float(binding.box_ratio),
        "crop_factor": float(binding.crop_factor),
    }
    return RenderAssetEvidenceV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def _element_evidence(
    *,
    page: PageScene,
    plan_page,
    raw: Mapping[str, object],
    raw_probes: list[Mapping[str, object]],
    fragments: Mapping[str, ContentFragment],
    assets: Mapping[str, AssetManifestItem],
    tokens: FamilyTokensV4,
) -> RenderElementEvidenceV4:
    element_id = raw.get("element_id")
    element = next((item for item in page.elements if item.element_id == element_id), None)
    if element is None:
        raise V4RenderError("browser probe references an unknown scene element")
    _require_probe_shape(raw, element)
    try:
        base_probes = build_element_probes(
            raw_probes=[dict(item) for item in raw_probes],
            page=page,
            fragments=fragments,
            assets=assets,
            page_background=page.background,
        )
        base = next(
            (item for item in base_probes if item.element_id == element.element_id),
            None,
        )
        if base is None:
            raise ProbeBuildError("probe data is missing for planned element")
    except ProbeBuildError:
        raise V4RenderError("browser probe evidence is incomplete") from None
    actual_box = _raw_box(raw)
    expected_box = _scene_box(getattr(element, "box", actual_box))
    scroll_width = _required_float(raw, "scroll_width")
    scroll_height = _required_float(raw, "scroll_height")
    client_width = _required_float(raw, "client_width")
    client_height = _required_float(raw, "client_height")
    common = {
        "page_id": page.page_id,
        "element_id": element.element_id,
        "kind": element.kind,
        "content_ref": None,
        "asset_ref": None,
        "expected_text_sha256": None,
        "actual_text_sha256": None,
        "actual_text": None,
        "dom_text_measured": False,
        "expected_box": expected_box,
        "actual_box": actual_box,
        "scroll_width": scroll_width,
        "scroll_height": scroll_height,
        "client_width": client_width,
        "client_height": client_height,
        "overflow": bool(base.overflow),
        "clipped": bool(base.ink_clipped or base.layout_clipped),
        "computed_font": None,
        "glyph": None,
        "asset": None,
        "line_boxes": _raw_line_boxes(raw),
    }
    if isinstance(element, TextElement):
        fragment = fragments.get(element.content_ref)
        if fragment is None:
            raise V4RenderError("text probe references an unknown source fragment")
        raw_text = _required_raw(raw, "actual_text")
        if not isinstance(raw_text, str):
            raise V4RenderError("browser text probe is not a string")
        dom_text_measured = _required_bool(raw, "dom_text_measured")
        if not dom_text_measured:
            raise V4RenderError("browser DOM text was not measured")
        measured_text = raw_text
        evidence = plan_page.compiler_provenance.text_measurement_evidence.get(element.content_ref)
        if evidence is None:
            raise V4RenderError("text probe has no hash-bound measurement evidence")
        font_sha = plan_page.compiler_provenance.font_sha256_by_role[element.style.font_role]
        common.update(
            content_ref=element.content_ref,
            expected_text_sha256=sha256_text_v4(fragment.text),
            actual_text_sha256=sha256_text_v4(measured_text),
            actual_text=measured_text,
            dom_text_measured=dom_text_measured,
            computed_font=_make_font(
                element=element,
                raw=raw,
                tokens=tokens,
                font_sha256=font_sha,
            ),
            glyph=_make_glyph(raw=raw, actual_text=measured_text),
        )
    elif isinstance(element, ImageElement):
        binding = next(
            (
                item
                for item in plan_page.compiler_provenance.asset_binding_evidence.values()
                if item.asset_ref == element.asset_ref
            ),
            None,
        )
        asset = assets.get(element.asset_ref)
        if binding is None or asset is None:
            raise V4RenderError("image probe has no opaque asset binding")
        common.update(
            asset_ref=element.asset_ref,
            asset=_make_asset(
                element=element,
                raw=raw,
                binding=binding,
                asset_sha256=asset.sha256,
            ),
        )
    payload = dict(common)
    return RenderElementEvidenceV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def _png_dimensions(data: bytes) -> tuple[int, int]:
    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            if image.format != "PNG":
                raise ValueError
            return image.size
    except Exception:
        raise V4RenderError("rendered page is not a readable PNG") from None


def _validate_inputs(
    *,
    design_plan,
    design_plan_qa_result,
    content_atom_set,
    content_lock,
    semantic_content_model,
    page_brief_set,
    visual_direction_plan,
    asset_manifest,
    family_tokens,
) -> tuple[
    CarouselDesignPlanV4,
    DesignPlanQAResultV4,
    ContentAtomSetV4,
    ContentLock,
    SemanticContentModelV4,
    PageBriefSetV4,
    VisualDirectionPlanV4,
    AssetManifest,
    FamilyTokensV4,
]:
    plan = _coerce(CarouselDesignPlanV4, design_plan, "carousel design plan")
    aggregate = _coerce(DesignPlanQAResultV4, design_plan_qa_result, "design plan QA result")
    atoms = _coerce(ContentAtomSetV4, content_atom_set, "content atom set")
    lock = _coerce(ContentLock, content_lock, "content lock")
    semantic = _coerce(SemanticContentModelV4, semantic_content_model, "semantic content model")
    page_set = _coerce(PageBriefSetV4, page_brief_set, "page brief set")
    direction = _coerce(VisualDirectionPlanV4, visual_direction_plan, "visual direction plan")
    manifest = _coerce(AssetManifest, asset_manifest, "asset manifest")
    tokens = get_family_tokens(family_tokens) if isinstance(family_tokens, str) else _coerce(FamilyTokensV4, family_tokens, "family tokens")
    if not aggregate.passed:
        raise V4RenderError("render requires a passed aggregate Q0-Q2 result")
    if aggregate.carousel_design_plan.canonical_sha256 != plan.canonical_sha256:
        raise V4RenderError("design plan QA result is bound to a different design plan")
    if aggregate.canonical_sha256 != _coerce(DesignPlanQAResultV4, aggregate, "design plan QA result").canonical_sha256:
        raise V4RenderError("design plan QA result canonical hash is stale")
    try:
        fresh = aggregate_design_qa(
            semantic_qa=aggregate.semantic_qa,
            authoring_qa=aggregate.authoring_qa,
            carousel_design_plan=plan,
            content_atom_set=atoms,
            content_lock=lock,
            semantic_content_model=semantic,
            page_brief_set=page_set,
            visual_direction_plan=direction,
            asset_manifest=manifest,
        )
    except Exception:
        raise V4RenderError("aggregate Q0-Q2 evidence is stale or mixed") from None
    if fresh.canonical_sha256 != aggregate.canonical_sha256:
        raise V4RenderError("aggregate Q0-Q2 evidence is not the fresh result for these inputs")
    lock_hash = _lock_hash(lock)
    asset_hash = canonical_sha256_v3(manifest)
    if lock.content_atom_set_sha256 != atoms.canonical_sha256:
        raise V4RenderError("content lock is bound to a different atom set")
    if semantic.content_atom_set_sha256 != atoms.canonical_sha256:
        raise V4RenderError("semantic model is bound to a different atom set")
    expected = {
        "content_atom_set_sha256": atoms.canonical_sha256,
        "content_lock_sha256": lock_hash,
        "semantic_content_model_sha256": semantic.canonical_sha256,
        "narrative_sha256": direction.narrative_sha256,
        "page_brief_set_sha256": page_set.canonical_sha256,
        "visual_direction_plan_sha256": direction.canonical_sha256,
        "asset_manifest_sha256": asset_hash,
        "family_tokens_sha256": tokens.canonical_sha256,
    }
    for field, value in expected.items():
        if getattr(aggregate, field, None) != value:
            raise V4RenderError(f"aggregate {field} binding is stale")
        if field in {
            "content_atom_set_sha256",
            "semantic_content_model_sha256",
            "page_brief_set_sha256",
            "visual_direction_plan_sha256",
            "asset_manifest_sha256",
            "family_tokens_sha256",
        } and getattr(plan, field) != value:
            raise V4RenderError(f"design plan {field} binding is stale")
    if direction.template_family != tokens.family or page_set.template_family != tokens.family:
        raise V4RenderError("family token identity is stale")
    if (plan.run_id, plan.candidate_id) != (aggregate.run_id, aggregate.candidate_id):
        raise V4RenderError("design plan and QA identities are mixed")
    if plan.pages and tuple(page.page_id for page in plan.pages) != tuple(page.page_id for page in page_set.pages):
        raise V4RenderError("design plan page order is stale")
    return plan, aggregate, atoms, lock, semantic, page_set, direction, manifest, tokens


def _validate_paths(paths: ArtifactPaths, plan: CarouselDesignPlanV4) -> ArtifactPaths:
    if not isinstance(paths, ArtifactPaths):
        raise V4RenderError("v4 rendering requires Task 9 ArtifactPaths")
    expected_identity = (
        plan.run_id,
        plan.candidate_id,
        f"revision-{plan.revision}",
    )
    if (
        paths.identity.run_id,
        paths.identity.candidate_id,
        paths.identity.revision_id,
    ) != expected_identity:
        raise V4RenderError("artifact identity does not match the exact v4 plan")
    try:
        expected = resolve_artifact_paths(paths.base_root, paths.identity)
        for field in (
            "base_root",
            "run_root",
            "candidate_root",
            "revision_root",
            "asset_root",
            "render_root",
            "review_root",
            "artifact_root",
        ):
            if getattr(paths, field) != getattr(expected, field):
                raise V4RenderError("artifact path hierarchy drifted")
        established = paths if paths.trusted_base_identity is not None else ensure_artifact_paths(expected)
        return revalidate_artifact_paths(established)
    except V4RenderError:
        raise
    except Exception:
        raise V4RenderError("artifact path identity is stale or unsafe") from None


def _publish_staged(
    *,
    stage_root: Path,
    paths: ArtifactPaths,
    manifest: RenderManifestV4,
    page_bytes: Mapping[str, bytes],
    contact_bytes: bytes,
) -> None:
    files: list[tuple[Path, str, bytes]] = []
    for page in manifest.pages:
        relative = page.path
        source = stage_root / relative.removeprefix("render/")
        files.append((source, relative, page_bytes[page.page_id]))
    contact_source = stage_root / "contact-sheet.png"
    files.append((contact_source, manifest.contact_sheet_path, contact_bytes))
    manifest_source = stage_root / "render-manifest.json"
    manifest_bytes = canonical_json_v4(manifest).encode("utf-8")
    files.append((manifest_source, "render/render-manifest.json", manifest_bytes))
    try:
        for source, relative, body in files:
            _atomic_write_bytes(source, body)
    except Exception as error:
        raise V4RenderError("staged render artifact write failed") from error
    # One descriptor-relative directory publication keeps pages, contact sheet
    # and manifest invisible until the complete canonical tree exists.
    bind_staged_directory(
        stage_root,
        paths.render_root,
        revision_root=paths.revision_root,
    )
    for _source, relative, body in files:
        target = paths.revision_root / relative
        try:
            read_verified_artifact(
                target,
                hashlib.sha256(body).hexdigest(),
                containment_root=paths.render_root,
            )
        except ArtifactBindingError:
            raise V4RenderError("published artifact failed byte revalidation") from None


def render_v4_revision(
    *,
    design_plan: CarouselDesignPlanV4,
    design_plan_qa_result: DesignPlanQAResultV4,
    content_atom_set: ContentAtomSetV4,
    content_lock: ContentLock,
    semantic_content_model: SemanticContentModelV4,
    page_brief_set: PageBriefSetV4,
    visual_direction_plan: VisualDirectionPlanV4,
    asset_manifest: AssetManifest,
    family_tokens: FamilyTokensV4 | str,
    artifact_paths: ArtifactPaths,
    render_page_fn: RenderPageFn | None = None,
    contact_sheet_fn: ContactSheetFn | None = None,
    playwright_factory: Callable = None,
) -> V4RenderResult:
    """Render and immutably publish one exact v4 revision."""

    (
        plan,
        aggregate,
        atoms,
        lock,
        semantic,
        _page_set,
        _direction,
        manifest,
        tokens,
    ) = _validate_inputs(
        design_plan=design_plan,
        design_plan_qa_result=design_plan_qa_result,
        content_atom_set=content_atom_set,
        content_lock=content_lock,
        semantic_content_model=semantic_content_model,
        page_brief_set=page_brief_set,
        visual_direction_plan=visual_direction_plan,
        asset_manifest=asset_manifest,
        family_tokens=family_tokens,
    )
    paths = _validate_paths(artifact_paths, plan)
    fragments = _private_fragments(semantic)
    verified_asset_bytes: dict[str, bytes] = {}
    private_assets = _private_assets(
        plan, manifest, paths, verified_bytes=verified_asset_bytes
    )
    style = _private_style(tokens)
    text_options = _text_options(plan, semantic)
    font_sources = _font_sources(tokens)
    compiled_pages = [
        compile_page_scene(
            page.scene,
            fragments=fragments,
            assets=private_assets,
            style=style,
            font_face_sources=font_sources,
            text_render_options=text_options,
            asset_bytes=verified_asset_bytes,
        )
        for page in plan.pages
    ]
    stage_root = Path(tempfile.mkdtemp(prefix=".render-staging-", dir=paths.revision_root))
    stage_pages = stage_root / "pages"
    stage_pages.mkdir(mode=0o700)
    owned_renderer: _ChromiumPageRenderer | None = None
    primary: BaseException | None = None
    try:
        if render_page_fn is None:
            from playwright.sync_api import sync_playwright

            owned_renderer = _ChromiumPageRenderer(
                playwright_factory=playwright_factory or sync_playwright,
                probe_script=V4_PROBE_SCRIPT,
            )
            render_page_fn = owned_renderer.__enter__()
        sheet_fn = contact_sheet_fn or _default_contact_sheet
        pages: list[RenderPageEvidenceV4] = []
        page_bytes: dict[str, bytes] = {}
        page_paths: list[Path] = []
        all_elements: list[RenderElementEvidenceV4] = []
        for plan_page, compiled in zip(plan.pages, compiled_pages):
            try:
                draft = _render_with_retry(render_page_fn, compiled)
            except Exception as error:
                raise V4RenderError("generic renderer failed for a v4 page") from error
            if draft.page_id != plan_page.page_id:
                raise V4RenderError("renderer returned a page with mixed identity")
            width, height = _png_dimensions(draft.png_bytes)
            if (width, height) != (1080, 1440):
                raise V4RenderError("v4 renderer must produce exactly 1080x1440 PNGs")
            raw = _raw_by_id(draft.raw_probes)
            expected_ids = {element.element_id for element in plan_page.scene.elements}
            if (
                len(draft.raw_probes) != len(expected_ids)
                or len(raw) != len(expected_ids)
                or set(raw) != expected_ids
            ):
                raise V4RenderError("renderer probes do not cover the exact scene elements")
            elements = tuple(
                _element_evidence(
                    page=plan_page.scene,
                    plan_page=plan_page,
                    raw=raw[element.element_id],
                    raw_probes=list(draft.raw_probes),
                    fragments=fragments,
                    assets=private_assets,
                    tokens=tokens,
                )
                for element in sorted(plan_page.scene.elements, key=lambda item: item.layer)
            )
            all_elements.extend(elements)
            relative = f"render/pages/{plan_page.sequence:02d}-{plan_page.page_id}.png"
            page_file = stage_pages / f"{plan_page.sequence:02d}-{plan_page.page_id}.png"
            _atomic_write_bytes(page_file, draft.png_bytes)
            page_paths.append(page_file)
            page_bytes[plan_page.page_id] = draft.png_bytes
            page_payload = {
                "page_id": plan_page.page_id,
                "sequence": plan_page.sequence,
                "path": relative,
                "width": 1080,
                "height": 1440,
                "sha256": hashlib.sha256(draft.png_bytes).hexdigest(),
                "elements": elements,
            }
            pages.append(
                RenderPageEvidenceV4(
                    **page_payload,
                    canonical_sha256=canonical_sha256_v4(page_payload),
                )
            )
        try:
            contact_bytes = sheet_fn(tuple(page_paths))
        except Exception as error:
            raise V4RenderError("contact sheet renderer failed") from error
        if not isinstance(contact_bytes, bytes):
            raise V4RenderError("contact sheet seam must return PNG bytes")
        cw, ch = _png_dimensions(contact_bytes)
        if cw <= 0 or ch <= 0:
            raise V4RenderError("contact sheet dimensions are invalid")
        contact_sha = hashlib.sha256(contact_bytes).hexdigest()
        fonts_by_key: dict[tuple[str, str], RenderFontEvidenceV4] = {}
        for element in all_elements:
            if element.computed_font is not None:
                font = element.computed_font
                fonts_by_key.setdefault((font.role, font.expected_font_sha256), font)
        identity = ArtifactIdentityV4(
            run_id=plan.run_id,
            candidate_id=plan.candidate_id,
            revision_id=f"revision-{plan.revision}",
        )
        manifest_payload = {
            "workflow_version": "llm_scene_v4",
            "artifact_identity": identity,
            "run_id": plan.run_id,
            "candidate_id": plan.candidate_id,
            "revision_id": identity.revision_id,
            "revision": plan.revision,
            "design_plan_sha256": plan.canonical_sha256,
            "design_plan_qa_sha256": aggregate.canonical_sha256,
            "content_atom_set_sha256": atoms.canonical_sha256,
            "content_lock_sha256": lock.canonical_sha256,
            "semantic_content_model_sha256": semantic.canonical_sha256,
            "narrative_sha256": _direction.narrative_sha256,
            "page_brief_set_sha256": _page_set.canonical_sha256,
            "visual_direction_plan_sha256": _direction.canonical_sha256,
            "asset_manifest_sha256": canonical_sha256_v3(manifest),
            "family_tokens_sha256": tokens.canonical_sha256,
            "pages": tuple(pages),
            "contact_sheet_path": "render/contact-sheet.png",
            "contact_sheet_sha256": contact_sha,
            "font_evidence": tuple(fonts_by_key.values()),
        }
        render_manifest = RenderManifestV4(
            **manifest_payload,
            canonical_sha256=canonical_sha256_v4(manifest_payload),
        )
        _publish_staged(
            stage_root=stage_root,
            paths=paths,
            manifest=render_manifest,
            page_bytes=page_bytes,
            contact_bytes=contact_bytes,
        )
        revalidate_artifact_paths(paths)
        return V4RenderResult(manifest=render_manifest, artifact_paths=paths)
    except BaseException as error:
        primary = error
        raise
    finally:
        if owned_renderer is not None:
            owned_renderer.__exit__(*sys.exc_info())
        try:
            if stage_root.exists():
                shutil.rmtree(stage_root)
        except OSError as cleanup_error:
            if primary is not None:
                primary.add_note(f"v4 render staging cleanup failed: {cleanup_error}")
            else:
                raise V4RenderError("v4 render staging cleanup failed") from cleanup_error


__all__ = ["V4RenderError", "V4RenderResult", "render_v4_revision"]
