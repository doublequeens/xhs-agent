"""Independent Q3 verification for immutable v4 render evidence.

Task 13A deliberately stops at publishing measured browser observations.  This
module is the separate consumer: it revalidates every upstream contract,
re-reads the published bytes through the descriptor-relative artifact seam and
derives the only public ``RenderQAResultV4``.  It never trusts an adapter
boolean or a caller-supplied Q3 result.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from io import BytesIO
from pathlib import Path
from typing import Any

import regex
from PIL import Image

from src.schemas.assets import AssetManifest
from src.schemas.content_atoms import canonical_sha256 as canonical_sha256_v3
from src.schemas.content_lock import ContentLock
from src.schemas.scene_graph import ImageElement, TextElement
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
    RenderGlyphEvidenceV4,
    RenderIssueV4,
    RenderManifestV4,
    RenderPageEvidenceV4,
    RenderQAResultV4,
    RENDER_BOX_TOLERANCE_PX_V4,
)
from src.schemas.v4.semantic import SemanticContentModelV4
from src.visual_design.v4.compiler import opaque_asset_ref_v4
from src.visual_design.v4.tokens import get_family_tokens
from src.visual_design.v4.typography import (
    CANONICAL_FONT_NOMINAL_WEIGHTS_V4,
    CANONICAL_FONT_SHA256_V4,
    reconstruct_source_lines_v4,
    resolve_font_file_v4,
)
from src.visual_runtime.artifact_identity import (
    ArtifactIdentity,
    ArtifactPaths,
    read_verified_artifact,
    revalidate_artifact_paths,
    resolve_artifact_paths,
)


RENDER_BOX_DRIFT = "RENDER_BOX_DRIFT"
_ISSUE_CODES = {
    "RENDER_INPUT_STALE",
    "RENDER_IDENTITY_MISMATCH",
    "RENDER_PAGE_ORDER",
    "RENDER_PAGE_MISSING",
    "RENDER_PAGE_BYTES",
    "RENDER_CONTACT_BYTES",
    "RENDER_DIMENSIONS",
    "RENDER_BLANK_OUTPUT",
    "RENDER_DOM_TEXT",
    "RENDER_BOX_DRIFT",
    "RENDER_OVERFLOW",
    "RENDER_FONT",
    "RENDER_GLYPH",
    "RENDER_ASSET",
    "RENDER_CROP",
    "RENDER_PATH",
}
_TARGETS = {
    "RENDER_DOM_TEXT": "layout_reflow",
    "RENDER_BOX_DRIFT": "layout_reflow",
    "RENDER_OVERFLOW": "layout_reflow",
    "RENDER_FONT": "font_binding",
    "RENDER_GLYPH": "font_binding",
    "RENDER_ASSET": "asset_rebind",
    "RENDER_CROP": "asset_rebind",
    "RENDER_BLANK_OUTPUT": "renderer_retry",
    "RENDER_DIMENSIONS": "renderer_retry",
}
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_PRIVATE_TEXT_RE = re.compile(
    r"(?:provider|provenance|license|prompt|source[_ -]?path|local[_ -]?path|"
    r"api[_ -]?key|secret|password|https?://|(?:^|[/\\])(?:users|private|home|tmp)(?:[/\\]))",
    re.IGNORECASE,
)


class V4RenderQAInvariantError(ValueError):
    """Sanitized structural failure at the independent Q3 boundary."""


# Friendly aliases used by downstream callers and tests.
RenderQAInvariantErrorV4 = V4RenderQAInvariantError
V4RenderQAError = V4RenderQAInvariantError


def _fail(_reason: str = "v4 render evidence is stale or structurally invalid") -> None:
    # Deliberately discard arbitrary nested exception text.  Paths, provider
    # data and visible copy must not escape this boundary.
    raise V4RenderQAInvariantError(_reason)


def _coerce(model_type: type[Any], value: Any, _name: str):
    try:
        raw = value.model_dump(mode="python") if isinstance(value, model_type) else value
        checked = model_type.model_validate(raw)
        validate_integrity = getattr(checked, "validate_integrity", None)
        if callable(validate_integrity):
            validate_integrity()
        return checked
    except Exception:
        _fail()


def _hash(value: str) -> str:
    if type(value) is not str or not _HASH_RE.fullmatch(value):
        _fail()
    return value


def _lock_hash(lock: ContentLock) -> str:
    try:
        payload = lock.model_dump(mode="json", exclude={"canonical_sha256"})
        expected = canonical_sha256_v4(payload)
    except Exception:
        _fail()
    if lock.canonical_sha256 != expected:
        _fail()
    return lock.canonical_sha256


def _family_tokens(value: FamilyTokensV4 | str, family_name: str) -> FamilyTokensV4:
    try:
        checked = get_family_tokens(value) if isinstance(value, str) else _coerce(FamilyTokensV4, value, "family tokens")
        canonical = get_family_tokens(family_name)
        if checked.family != family_name or checked.canonical_sha256 != canonical.canonical_sha256:
            _fail()
        return checked
    except V4RenderQAInvariantError:
        raise
    except Exception:
        _fail()


def _validate_sources(
    *,
    design_plan: Any,
    design_plan_qa_result: Any,
    content_atom_set: Any,
    content_lock: Any,
    semantic_content_model: Any,
    page_brief_set: Any,
    visual_direction_plan: Any,
    asset_manifest: Any,
    family_tokens: FamilyTokensV4 | str,
):
    plan = _coerce(CarouselDesignPlanV4, design_plan, "design plan")
    aggregate = _coerce(DesignPlanQAResultV4, design_plan_qa_result, "design plan QA")
    atoms = _coerce(ContentAtomSetV4, content_atom_set, "content atom set")
    lock = _coerce(ContentLock, content_lock, "content lock")
    semantic = _coerce(SemanticContentModelV4, semantic_content_model, "semantic model")
    page_set = _coerce(PageBriefSetV4, page_brief_set, "page brief set")
    direction = _coerce(VisualDirectionPlanV4, visual_direction_plan, "direction plan")
    try:
        manifest = AssetManifest.model_validate(
            asset_manifest.model_dump(mode="python")
            if isinstance(asset_manifest, AssetManifest)
            else asset_manifest
        )
        asset_hash = canonical_sha256_v3(manifest)
    except Exception:
        _fail()
    tokens = _family_tokens(family_tokens, direction.template_family)
    lock_hash = _lock_hash(lock)

    if not aggregate.passed:
        _fail("v4 render requires passed upstream quality evidence")
    if lock.content_atom_set_sha256 != atoms.canonical_sha256:
        _fail()
    if semantic.content_atom_set_sha256 != atoms.canonical_sha256:
        _fail()
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
    if any(getattr(aggregate, key, None) != value for key, value in expected.items()):
        _fail()
    if any(getattr(plan, key, None) != value for key, value in expected.items() if key != "content_lock_sha256" and key != "narrative_sha256"):
        _fail()
    if aggregate.carousel_design_plan.canonical_sha256 != plan.canonical_sha256:
        _fail()
    if (aggregate.run_id, aggregate.candidate_id, aggregate.revision) != (
        plan.run_id,
        plan.candidate_id,
        plan.revision,
    ):
        _fail()
    if direction.template_family != tokens.family or page_set.template_family != tokens.family:
        _fail()
    if tuple((item.page_id, item.sequence) for item in page_set.pages) != tuple(
        (item.page_id, item.sequence) for item in plan.pages
    ):
        _fail()

    # Recompute Q0-Q2 from the exact source objects.  This rejects both stale
    # top-level hashes and self-consistent rehashes that no longer describe the
    # supplied semantic/authoring sources.
    try:
        # Keep the package-level v4 exports importable while avoiding a module
        # cycle: the Q2 producer imports sibling visual-design modules during
        # its own initialization.
        from src.nodes.v4.design_qa import aggregate_design_qa

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
        _fail()
    if fresh.canonical_sha256 != aggregate.canonical_sha256 or not fresh.passed:
        _fail()
    return plan, aggregate, atoms, lock, semantic, page_set, direction, manifest, tokens


def _validate_paths(paths: Any, plan: CarouselDesignPlanV4) -> ArtifactPaths:
    if not isinstance(paths, ArtifactPaths):
        _fail()
    identity = ArtifactIdentity(plan.run_id, plan.candidate_id, f"revision-{plan.revision}")
    try:
        expected = resolve_artifact_paths(paths.base_root, identity)
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
                _fail()
        if paths.trusted_base_identity is None:
            _fail()
        return revalidate_artifact_paths(paths)
    except V4RenderQAInvariantError:
        raise
    except Exception:
        _fail()


def _read(path: Path, declared_sha: str, *, root: Path) -> bytes:
    try:
        return read_verified_artifact(path, declared_sha, containment_root=root)
    except Exception:
        _fail()


def _png_facts(raw: bytes, *, page: bool) -> tuple[int, int, bool]:
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        _fail()
    try:
        with Image.open(BytesIO(raw)) as image:
            image.load()
            if image.format != "PNG":
                _fail()
            rgba = image.convert("RGBA")
            flattened = getattr(rgba, "get_flattened_data", None)
            pixels = list(flattened()) if callable(flattened) else list(rgba.getdata())
            if page and (image.width, image.height) != (1080, 1440):
                _fail()
            if not pixels or max(pixel[3] for pixel in pixels) == 0:
                return image.width, image.height, True
            # A fully opaque solid colour is a valid page (for example a
            # text-only cover); only empty/transparent output is blank.
            blank = len(set(pixels)) == 1 and pixels[0][3] == 0
            return image.width, image.height, blank
    except V4RenderQAInvariantError:
        raise
    except Exception:
        _fail()


def _issue(
    code: str,
    *,
    page_id: str,
    element_id: str | None = None,
    fragment_ref: str | None = None,
    asset_ref: str | None = None,
    actual: float | None = None,
    expected: float | None = None,
    tolerance_px: float | None = None,
    evidence: str = "deterministic render observation",
) -> RenderIssueV4:
    if code not in _ISSUE_CODES:
        _fail()
    if _PRIVATE_TEXT_RE.search(evidence) or "\n" in evidence or "\r" in evidence:
        _fail()
    payload = {
        "code": code,
        "message": f"{code.lower().replace('_', ' ')} requires deterministic render review",
        "page_id": page_id,
        "element_id": element_id,
        "fragment_ref": fragment_ref,
        "asset_ref": asset_ref,
        "actual": actual,
        "expected": expected,
        "tolerance_px": tolerance_px,
        "evidence": evidence,
        "revision_target": _TARGETS.get(code, "renderer_retry"),
    }
    return RenderIssueV4(**payload, canonical_sha256=canonical_sha256_v4(payload))


def _primary_family(value: str) -> str:
    return value.strip().strip("'\"").split(",", 1)[0].strip().strip("'\"")


def _geometry_issues(
    *, page_id: str, element_id: str, expected, actual, tolerance: float
) -> list[RenderIssueV4]:
    issues: list[RenderIssueV4] = []
    for name in ("x", "y", "width", "height"):
        left = float(getattr(actual, name))
        right = float(getattr(expected, name))
        drift = abs(left - right)
        if drift > tolerance:
            issues.append(
                _issue(
                    RENDER_BOX_DRIFT,
                    page_id=page_id,
                    element_id=element_id,
                    actual=left,
                    expected=right,
                    tolerance_px=tolerance,
                    evidence=f"box component {name} exceeds tolerance",
                )
            )
    return issues


def _text_matches(actual: str, source: str, measurement) -> bool:
    try:
        lines = reconstruct_source_lines_v4(
            source,
            explicit_break_spans=measurement.explicit_break_spans,
            inserted_break_offsets=measurement.inserted_break_offsets,
        )
    except Exception:
        _fail()
    wrapped = "\n".join(lines.lines)
    if actual == wrapped:
        return True
    # Chromium normalizes CRLF/CR in a generated text node to LF.  This is the
    # only normalization permitted here; no whitespace/copy trimming occurs.
    source_normalized = re.sub(r"\r\n|\r|\n", "\n", source)
    # A compiler-inserted break is part of the approved layout evidence.  If
    # one was recorded, the DOM must retain it; accepting the unwrapped source
    # would silently let a renderer drop a required line break.
    return not measurement.inserted_break_offsets and actual == source_normalized


def _font_issues(
    *,
    page_id: str,
    element: TextElement,
    observed: RenderFontEvidenceV4,
    provenance,
    tokens: FamilyTokensV4,
) -> list[RenderIssueV4]:
    expected_family = getattr(tokens.font_roles, element.style.font_role)
    try:
        expected_sha = CANONICAL_FONT_SHA256_V4[expected_family]
        expected_weight = CANONICAL_FONT_NOMINAL_WEIGHTS_V4[expected_family]
    except Exception:
        _fail()
    issues: list[RenderIssueV4] = []
    try:
        checked_font = resolve_font_file_v4(tokens.family, element.style.font_role)
        if checked_font.sha256 != expected_sha or provenance.font_sha256_by_role[element.style.font_role] != expected_sha:
            _fail()
    except Exception:
        _fail()
    if (
        observed.role != element.style.font_role
        or observed.expected_family != expected_family
        or _primary_family(observed.computed_family) != expected_family
        or observed.expected_font_sha256 != expected_sha
        or observed.computed_weight != expected_weight
        or observed.expected_weight != expected_weight
        or not math.isclose(observed.font_size_px, element.style.font_size, abs_tol=0.01)
        or not math.isclose(
            observed.line_height_px,
            element.style.font_size * element.style.line_height,
            abs_tol=0.01,
        )
        or not observed.font_loaded
        or observed.document_fonts_status != "loaded"
    ):
        issues.append(
            _issue(
                "RENDER_FONT",
                page_id=page_id,
                element_id=element.element_id,
                evidence="computed font does not match canonical role binding",
            )
        )
    return issues


def _glyph_issues(
    *, page_id: str, element: TextElement, actual_text: str, glyph: RenderGlyphEvidenceV4
) -> list[RenderIssueV4]:
    parts = tuple(regex.findall(r"\X", actual_text))
    coverage = glyph.coverage
    valid = (
        len(parts) == len(coverage)
        and glyph.loaded
        and glyph.visible == (bool([item for item in coverage if not item.is_whitespace]) and all(item.visible for item in coverage if not item.is_whitespace))
        and glyph.missing_codepoint_count == sum(
            1 for item in coverage if not item.is_whitespace and not item.visible
        )
    )
    if valid:
        for part, item in zip(parts, coverage):
            whitespace = bool(re.fullmatch(r"\s+", part, flags=re.UNICODE))
            if item.is_whitespace != whitespace:
                valid = False
                break
            if whitespace:
                if (
                    item.visible
                    or item.ink_pixel_count != 0
                    or item.fallback_ink_pixel_count != 0
                    or item.tofu_ink_pixel_count != 0
                    or item.raster_signature != "0" * 64
                    or item.fallback_raster_signature != "0" * 64
                    or item.tofu_raster_signature != "0" * 64
                ):
                    valid = False
                    break
            elif not (
                item.visible
                and item.face_loaded
                and item.font_check
                and item.ink_pixel_count > 0
                and item.raster_signature != "0" * 64
                and item.fallback_ink_pixel_count > 0
                and item.tofu_ink_pixel_count > 0
                and len(
                    {
                        item.raster_signature,
                        item.fallback_raster_signature,
                        item.tofu_raster_signature,
                    }
                ) == 3
            ):
                valid = False
                break
    if valid:
        return []
    return [
        _issue(
            "RENDER_GLYPH",
            page_id=page_id,
            element_id=element.element_id,
            fragment_ref=element.content_ref,
            evidence="glyph face and raster witnesses are incomplete",
        )
    ]


def _typographic_leading_px(
    *, element: TextElement, observed, measurement, actual_box
) -> float:
    """Return measured font leading allowed around strict Range rectangles.

    Chromium's ``Range.getClientRects`` may expose the font-metric line box,
    which can extend beyond the positioned DOM box when ascent+descent is
    taller than the declared CSS line-height.  That extension is safe only
    when the canonical measured painted bounds fit the reserved box and the
    strict glyph/font witnesses are valid; it is not a general overflow
    allowance.
    """

    font = observed.computed_font
    glyph = observed.glyph
    if font is None or glyph is None or not glyph.loaded or not glyph.visible:
        return 0.0
    try:
        expected_size = float(element.style.font_size)
        expected_line_height = expected_size * float(element.style.line_height)
        font_size = float(font.font_size_px)
        line_height = float(font.line_height_px)
        metrics_height = float(measurement.ascent_px) + float(measurement.descent_px)
        painted_left = (
            float(measurement.content_inset_left_px)
            + float(measurement.painted_offset_x_px)
            + float(measurement.painted_left_px)
        )
        painted_top = (
            float(measurement.content_inset_top_px)
            + float(measurement.painted_offset_y_px)
            + float(measurement.painted_top_px)
        )
        painted_right = (
            float(measurement.content_inset_left_px)
            + float(measurement.painted_offset_x_px)
            + float(measurement.painted_right_px)
        )
        painted_bottom = (
            float(measurement.content_inset_top_px)
            + float(measurement.painted_offset_y_px)
            + float(measurement.painted_bottom_px)
        )
    except (AttributeError, TypeError, ValueError):
        return 0.0
    if (
        not all(
            math.isfinite(value)
            for value in (
                expected_size,
                expected_line_height,
                font_size,
                line_height,
                metrics_height,
                painted_left,
                painted_top,
                painted_right,
                painted_bottom,
            )
        )
        or not math.isclose(font_size, expected_size, abs_tol=0.01)
        or not math.isclose(line_height, expected_line_height, abs_tol=0.01)
        or int(measurement.font_nominal_weight) != int(font.computed_weight)
        or metrics_height <= line_height
        or painted_left < 0.0
        or painted_top < 0.0
        or painted_left > float(actual_box.width)
        or painted_top > float(actual_box.height)
        or painted_right < 0.0
        or painted_right > float(actual_box.width)
        or painted_bottom < 0.0
        or painted_bottom > float(actual_box.height)
    ):
        return 0.0
    # The inline font metrics are centered in the CSS line-height.  Allow only
    # the derived half-difference on each vertical edge, with the existing
    # independent pixel tolerance applied by the caller.
    return max(0.0, (metrics_height - line_height) / 2.0)


def _asset_issues(
    *,
    page_id: str,
    element: ImageElement,
    observed: RenderAssetEvidenceV4,
    plan_page,
    asset_manifest: AssetManifest,
    paths: ArtifactPaths,
    plan: CarouselDesignPlanV4,
) -> list[RenderIssueV4]:
    by_directive = {item.directive_id: item for item in asset_manifest.items}
    binding = next(
        (
            item
            for item in plan_page.compiler_provenance.asset_binding_evidence.values()
            if item.asset_ref == element.asset_ref
        ),
        None,
    )
    item = by_directive.get(observed.directive_id)
    if binding is None or item is None:
        _fail()
    if (
        observed.directive_id != binding.directive_id
        or binding.page_id != page_id
        or item.page_id != page_id
        or item.run_id != plan.run_id
        or item.transaction_id != f"revision-{plan.revision}"
        or item.security_status != "approved"
        or item.human_decision != "pending"
    ):
        _fail()
    try:
        raw = _read(Path(item.local_path), item.sha256, root=paths.asset_root)
        with Image.open(BytesIO(raw)) as image:
            image.load()
            natural = (float(image.width), float(image.height))
    except V4RenderQAInvariantError:
        raise
    except Exception:
        _fail()
    issues: list[RenderIssueV4] = []
    expected_ref = opaque_asset_ref_v4(
        candidate_id=plan.candidate_id,
        revision=plan.revision,
        page_id=page_id,
        directive_id=binding.directive_id,
        asset_sha256=item.sha256,
    )
    expected_ratio = float(element.box.width) / float(element.box.height)
    asset_ratio = natural[0] / natural[1]
    expected_crop = max(asset_ratio / expected_ratio, expected_ratio / asset_ratio)
    rendered_ok = (
        observed.loaded
        and observed.asset_ref == expected_ref == element.asset_ref
        and observed.asset_sha256 == item.sha256 == binding.asset_sha256
        and observed.natural_width is not None
        and observed.natural_height is not None
        and math.isclose(observed.natural_width, float(item.width), abs_tol=0.01)
        and math.isclose(observed.natural_height, float(item.height), abs_tol=0.01)
        and math.isclose(observed.natural_width, natural[0], abs_tol=0.01)
        and math.isclose(observed.natural_height, natural[1], abs_tol=0.01)
        and observed.rendered_width is not None
        and observed.rendered_height is not None
        and math.isclose(observed.rendered_width, element.box.width, abs_tol=RENDER_BOX_TOLERANCE_PX_V4)
        and math.isclose(observed.rendered_height, element.box.height, abs_tol=RENDER_BOX_TOLERANCE_PX_V4)
    )
    if not rendered_ok:
        issues.append(
            _issue(
                "RENDER_ASSET",
                page_id=page_id,
                element_id=element.element_id,
                asset_ref=element.asset_ref,
                evidence="image load or opaque byte binding does not match",
            )
        )
    crop_ok = (
        observed.fit == binding.fit == element.fit
        and observed.orientation == binding.orientation
        and math.isclose(observed.box_ratio, expected_ratio, abs_tol=1e-6)
        and math.isclose(observed.crop_factor, expected_crop, abs_tol=1e-6)
        and math.isclose(binding.box_ratio, expected_ratio, abs_tol=1e-6)
        and math.isclose(binding.crop_factor, expected_crop, abs_tol=1e-6)
    )
    if not crop_ok:
        issues.append(
            _issue(
                "RENDER_CROP",
                page_id=page_id,
                element_id=element.element_id,
                asset_ref=element.asset_ref,
                evidence="image fit ratio or crop factor does not match",
            )
        )
    return issues


def _element_issues(
    *,
    plan_page,
    page_evidence: RenderPageEvidenceV4,
    semantic: SemanticContentModelV4,
    asset_manifest: AssetManifest,
    paths: ArtifactPaths,
    plan: CarouselDesignPlanV4,
    tokens: FamilyTokensV4,
) -> list[RenderIssueV4]:
    fragments = {fragment.fragment_id: fragment for fragment in semantic.fragments}
    expected_elements = tuple(sorted(plan_page.scene.elements, key=lambda item: item.layer))
    observed_elements = page_evidence.elements
    if tuple(item.element_id for item in observed_elements) != tuple(item.element_id for item in expected_elements):
        _fail()
    issues: list[RenderIssueV4] = []
    for element, observed in zip(expected_elements, observed_elements):
        if observed.kind != element.kind or observed.page_id != plan_page.page_id:
            _fail()
        if any(
            abs(float(getattr(observed.expected_box, name)) - float(getattr(element.box, name)))
            > 1e-6
            for name in ("x", "y", "width", "height")
        ):
            _fail()
        issues.extend(
            _geometry_issues(
                page_id=plan_page.page_id,
                element_id=element.element_id,
                expected=element.box,
                actual=observed.actual_box,
                tolerance=RENDER_BOX_TOLERANCE_PX_V4,
            )
        )
        if (
            observed.overflow
            or observed.clipped
            or observed.client_width <= 0
            or observed.client_height <= 0
            or observed.scroll_width > observed.client_width + 1e-6
            or observed.scroll_height > observed.client_height + 1e-6
            or observed.actual_box.x < 0.0
            or observed.actual_box.y < 0.0
            or observed.actual_box.x + observed.actual_box.width > 1080.0
            or observed.actual_box.y + observed.actual_box.height > 1440.0
        ):
            issues.append(
                _issue(
                    "RENDER_OVERFLOW",
                    page_id=plan_page.page_id,
                    element_id=element.element_id,
                    evidence="measured element exceeds its clipping or canvas bounds",
                )
            )
        if isinstance(element, TextElement):
            fragment = fragments.get(element.content_ref)
            measurement = plan_page.compiler_provenance.text_measurement_evidence.get(element.content_ref)
            if fragment is None or measurement is None:
                _fail()
            if (
                observed.content_ref != element.content_ref
                or observed.actual_text is None
                or not observed.dom_text_measured
                or observed.expected_text_sha256 != sha256_text_v4(fragment.exact_text)
                or observed.actual_text_sha256 != sha256_text_v4(observed.actual_text)
                or measurement.source_atom_id != fragment.source_atom_id
                or measurement.exact_text_sha256 != sha256_text_v4(fragment.exact_text)
            ):
                _fail()
            if not _text_matches(observed.actual_text, fragment.exact_text, measurement):
                issues.append(
                    _issue(
                        "RENDER_DOM_TEXT",
                        page_id=plan_page.page_id,
                        element_id=element.element_id,
                        fragment_ref=element.content_ref,
                        evidence="measured DOM text hash differs from semantic source",
                    )
                )
            if observed.computed_font is None or observed.glyph is None:
                _fail()
            issues.extend(
                _font_issues(
                    page_id=plan_page.page_id,
                    element=element,
                    observed=observed.computed_font,
                    provenance=plan_page.compiler_provenance,
                    tokens=tokens,
                )
            )
            issues.extend(
                _glyph_issues(
                    page_id=plan_page.page_id,
                    element=element,
                    actual_text=observed.actual_text,
                    glyph=observed.glyph,
                )
            )
            leading_px = _typographic_leading_px(
                element=element,
                observed=observed,
                measurement=measurement,
                actual_box=observed.actual_box,
            )
            for line_box in observed.line_boxes:
                if (
                    line_box.x < observed.actual_box.x - RENDER_BOX_TOLERANCE_PX_V4
                    or line_box.y
                    < observed.actual_box.y
                    - RENDER_BOX_TOLERANCE_PX_V4
                    - leading_px
                    or line_box.x + line_box.width > observed.actual_box.x + observed.actual_box.width + RENDER_BOX_TOLERANCE_PX_V4
                    or line_box.y + line_box.height
                    > observed.actual_box.y
                    + observed.actual_box.height
                    + RENDER_BOX_TOLERANCE_PX_V4
                    + leading_px
                ):
                    issues.append(
                        _issue(
                            "RENDER_OVERFLOW",
                            page_id=plan_page.page_id,
                            element_id=element.element_id,
                            evidence="measured text line box exceeds reserved bounds",
                        )
                    )
                    break
        elif isinstance(element, ImageElement):
            if observed.asset_ref != element.asset_ref or observed.asset is None:
                _fail()
            issues.extend(
                _asset_issues(
                    page_id=plan_page.page_id,
                    element=element,
                    observed=observed.asset,
                    plan_page=plan_page,
                    asset_manifest=asset_manifest,
                    paths=paths,
                    plan=plan,
                )
            )
        elif observed.content_ref is not None or observed.asset_ref is not None:
            _fail()
    return issues


def _extract_fixture(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    if args:
        if len(args) != 1:
            _fail("v4 render QA accepts one fixture or keyword inputs")
        fixture = args[0]
        if isinstance(fixture, Mapping):
            values = dict(fixture)
        else:
            try:
                values = dict(vars(fixture))
            except Exception:
                _fail("v4 render QA fixture is not a mapping")
        values.update(kwargs)
        return values
    return dict(kwargs)


def evaluate_v4_render(*args: Any, tolerance_px: float = RENDER_BOX_TOLERANCE_PX_V4, **kwargs: Any) -> RenderQAResultV4:
    """Independently evaluate one immutable v4 render revision.

    The keyword surface mirrors the adapter's source contracts.  A single
    mapping/object positional fixture is also accepted for compact offline
    tests; aliases are intentionally limited to persisted v4 names.
    """

    if isinstance(tolerance_px, bool) or not isinstance(tolerance_px, (int, float)):
        _fail()
    tolerance = float(tolerance_px)
    if not math.isfinite(tolerance) or tolerance < 0:
        _fail()
    values = _extract_fixture(args, kwargs)
    aliases = {
        "manifest": "render_manifest",
        "render_manifest_v4": "render_manifest",
        "carousel_design_plan": "design_plan",
        "carousel_design_plan_v4": "design_plan",
        "design_plan_qa": "design_plan_qa_result",
        "design_plan_qa_result_v4": "design_plan_qa_result",
        "artifact_paths_v4": "artifact_paths",
    }
    for source, target in aliases.items():
        if target not in values and source in values:
            values[target] = values[source]
    required = (
        "render_manifest",
        "design_plan",
        "design_plan_qa_result",
        "content_atom_set",
        "content_lock",
        "semantic_content_model",
        "page_brief_set",
        "visual_direction_plan",
        "asset_manifest",
        "family_tokens",
        "artifact_paths",
    )
    if any(key not in values or values[key] is None for key in required):
        _fail("v4 render QA is missing canonical source evidence")
    try:
        (
            plan,
            aggregate,
            atoms,
            lock,
            semantic,
            page_set,
            direction,
            asset_manifest,
            tokens,
        ) = _validate_sources(
            design_plan=values["design_plan"],
            design_plan_qa_result=values["design_plan_qa_result"],
            content_atom_set=values["content_atom_set"],
            content_lock=values["content_lock"],
            semantic_content_model=values["semantic_content_model"],
            page_brief_set=values["page_brief_set"],
            visual_direction_plan=values["visual_direction_plan"],
            asset_manifest=values["asset_manifest"],
            family_tokens=values["family_tokens"],
        )
        manifest = _coerce(RenderManifestV4, values["render_manifest"], "render manifest")
        paths = _validate_paths(values["artifact_paths"], plan)
    except V4RenderQAInvariantError:
        raise
    except Exception:
        _fail()

    identity = ArtifactIdentityV4(
        run_id=plan.run_id,
        candidate_id=plan.candidate_id,
        revision_id=f"revision-{plan.revision}",
    )
    if (
        manifest.artifact_identity != identity
        or manifest.run_id != plan.run_id
        or manifest.candidate_id != plan.candidate_id
        or manifest.revision_id != identity.revision_id
        or manifest.revision != plan.revision
        or manifest.design_plan_sha256 != plan.canonical_sha256
    ):
        _fail()
    if manifest.design_plan_qa_sha256 != aggregate.canonical_sha256:
        _fail()
    source_hashes = {
        "content_atom_set_sha256": atoms.canonical_sha256,
        "content_lock_sha256": lock.canonical_sha256,
        "semantic_content_model_sha256": semantic.canonical_sha256,
        "narrative_sha256": direction.narrative_sha256,
        "page_brief_set_sha256": page_set.canonical_sha256,
        "visual_direction_plan_sha256": direction.canonical_sha256,
        "asset_manifest_sha256": canonical_sha256_v3(asset_manifest),
        "family_tokens_sha256": tokens.canonical_sha256,
    }
    if any(getattr(manifest, key) != value for key, value in source_hashes.items()):
        _fail()
    if tuple((page.page_id, page.sequence) for page in manifest.pages) != tuple(
        (page.page_id, page.sequence) for page in plan.pages
    ):
        _fail()

    # The canonical manifest itself is part of the immutable render root.  A
    # caller cannot alter an in-memory manifest and trick Q3 into trusting it.
    canonical_manifest = canonical_json_v4(manifest).encode("utf-8")
    stored_manifest = _read(
        paths.revision_root / "render/render-manifest.json",
        hashlib.sha256(canonical_manifest).hexdigest(),
        root=paths.render_root,
    )
    if stored_manifest != canonical_manifest:
        _fail()

    issues: list[RenderIssueV4] = []
    page_bytes_ok = True
    contact_blank = False
    for plan_page, page in zip(plan.pages, manifest.pages):
        expected_page_path = (
            f"render/pages/{plan_page.sequence:02d}-{plan_page.page_id}.png"
        )
        if page.path != expected_page_path:
            _fail()
        page_path = paths.revision_root / page.path
        raw = _read(page_path, page.sha256, root=paths.render_root)
        width, height, blank = _png_facts(raw, page=True)
        if blank:
            issues.append(
                _issue(
                    "RENDER_BLANK_OUTPUT",
                    page_id=page.page_id,
                    evidence="published page contains no visible pixels",
                )
            )
        if (width, height) != (page.width, page.height):
            _fail()
        if hashlib.sha256(raw).hexdigest() != page.sha256:
            page_bytes_ok = False
        issues.extend(
            _element_issues(
                plan_page=plan_page,
                page_evidence=page,
                semantic=semantic,
                asset_manifest=asset_manifest,
                paths=paths,
                plan=plan,
                tokens=tokens,
            )
        )
    expected_font_keys = {
        (
            getattr(tokens.font_roles, element.style.font_role),
            plan_page.compiler_provenance.font_sha256_by_role[element.style.font_role],
        )
        for plan_page in plan.pages
        for element in plan_page.scene.elements
        if isinstance(element, TextElement)
    }
    actual_font_keys = {
        (font.expected_family, font.expected_font_sha256)
        for font in manifest.font_evidence
    }
    if actual_font_keys != expected_font_keys:
        _fail()
    contact = _read(
        paths.revision_root / manifest.contact_sheet_path,
        manifest.contact_sheet_sha256,
        root=paths.render_root,
    )
    _cw, _ch, contact_blank = _png_facts(contact, page=False)
    if contact_blank:
        issues.append(
            _issue(
                "RENDER_BLANK_OUTPUT",
                page_id="contact-sheet",
                evidence="published contact sheet contains no visible pixels",
            )
        )

    # Re-derive the aggregate attestations solely from the ordered issue list.
    content_codes = {"RENDER_DOM_TEXT"}
    geometry_codes = {"RENDER_BOX_DRIFT", "RENDER_OVERFLOW"}
    font_codes = {"RENDER_FONT", "RENDER_GLYPH"}
    asset_codes = {"RENDER_ASSET", "RENDER_CROP"}
    bytes_codes = {"RENDER_BLANK_OUTPUT", "RENDER_DIMENSIONS", "RENDER_PAGE_BYTES", "RENDER_CONTACT_BYTES"}
    payload = {
        "workflow_version": "llm_scene_v4",
        "artifact_identity": identity,
        "render_manifest_sha256": manifest.canonical_sha256,
        "design_plan_sha256": plan.canonical_sha256,
        "design_plan_qa_sha256": aggregate.canonical_sha256,
        "content_atom_set_sha256": atoms.canonical_sha256,
        "content_lock_sha256": lock.canonical_sha256,
        "semantic_content_model_sha256": semantic.canonical_sha256,
        "narrative_sha256": direction.narrative_sha256,
        "page_brief_set_sha256": page_set.canonical_sha256,
        "visual_direction_plan_sha256": direction.canonical_sha256,
        "asset_manifest_sha256": canonical_sha256_v3(asset_manifest),
        "family_tokens_sha256": tokens.canonical_sha256,
        "passed": not issues,
        "issues": tuple(issues),
        "content_attestation": not any(item.code in content_codes for item in issues),
        "geometry_attestation": not any(item.code in geometry_codes for item in issues),
        "font_attestation": not any(item.code in font_codes for item in issues),
        "asset_attestation": not any(item.code in asset_codes for item in issues),
        "bytes_attestation": page_bytes_ok and not contact_blank and not any(item.code in bytes_codes for item in issues),
    }
    try:
        result = RenderQAResultV4(
            **payload,
            canonical_sha256=canonical_sha256_v4(payload),
        )
        result.validate_integrity()
        return result
    except Exception:
        _fail()


__all__ = [
    "RENDER_BOX_DRIFT",
    "RenderQAInvariantErrorV4",
    "V4RenderQAError",
    "V4RenderQAInvariantError",
    "evaluate_v4_render",
]
