"""Deterministic v4 Layout Compiler.

The compiler is the narrow boundary between hash-bound layout intent and the
existing flat scene graph.  It performs no LLM/provider/filesystem write or
renderer work.  Geometry is solved by one of the three registered grammar
modules and all visible copy is read from the exact semantic fragment named by
the program.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.content_atoms import canonical_sha256 as canonical_sha256_v3
from src.schemas.scene_graph import (
    Box,
    IconElement,
    ImageElement,
    PageScene,
    SceneElement,
    TextElement,
    TextStyle,
)
from src.schemas.v4.content import ContentAtomSetV4, canonical_sha256_v4
from src.schemas.v4.direction import PageBriefV4, TemplateFamilyV4
from src.schemas.v4.layout import (
    CarouselDesignPlanV4,
    CompilerProvenanceV4,
    CompiledPageV4,
    FamilyTokensV4,
    LayoutProgramV4,
)
from src.schemas.v4.semantic import SemanticContentModelV4, SemanticFragmentV4
from src.visual_design.v4.tokens import get_family_tokens
from src.visual_design.v4.typography import TextMeasurementV4, measure_text_v4, resolve_font_file_v4


CANVAS_WIDTH_V4: Final[int] = 1080
CANVAS_HEIGHT_V4: Final[int] = 1440
SAFE_MARGIN_V4: Final[int] = 80
MIN_BODY_FONT_PX_V4: Final[int] = 24
MIN_DISPLAY_FONT_PX_V4: Final[int] = 32
COMPILATION_ERROR_CODES_V4 = (
    "CONTENT_OVERFLOW",
    "DENSITY_EXCEEDED",
    "UNBALANCED_REGIONS",
    "INSUFFICIENT_WHITESPACE",
    "ASSET_ASPECT_MISMATCH",
    "TYPOGRAPHY_CONSTRAINT_CONFLICT",
)
CompilationErrorCodeV4 = Literal[
    "CONTENT_OVERFLOW",
    "DENSITY_EXCEEDED",
    "UNBALANCED_REGIONS",
    "INSUFFICIENT_WHITESPACE",
    "ASSET_ASPECT_MISMATCH",
    "TYPOGRAPHY_CONSTRAINT_CONFLICT",
]
_ELEMENT_ID_RE = re.compile(r"[^a-z0-9_-]+")


class LayoutCompilationError(ValueError):
    """A deterministic quality/geometry failure with one approved code."""

    def __init__(
        self,
        code: CompilationErrorCodeV4,
        *,
        page_id: str,
        region_id: str | None = None,
        ref: str | None = None,
        evidence: str = "deterministic layout constraint failed",
    ) -> None:
        if code not in COMPILATION_ERROR_CODES_V4:
            raise ValueError("unknown v4 layout compilation error code")
        self.code = code
        self.failure_code = code
        self.page_id = page_id
        self.region_id = region_id
        self.ref = ref
        # Evidence is structural/numeric only.  Never include visible copy,
        # local paths, providers or internal provenance in this exception.
        self.evidence = evidence
        location = ", ".join(
            item
            for item in (
                f"page={page_id}",
                f"region={region_id}" if region_id else None,
                f"ref={ref}" if ref else None,
            )
            if item
        )
        super().__init__(f"{code}: {location}: {evidence}")


class LayoutCompilerInputsV4(BaseModel):
    """Revalidated upstream objects and immutable compiler constraints."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_brief: PageBriefV4
    semantic_content_model: SemanticContentModelV4
    content_atom_set: ContentAtomSetV4
    asset_manifest: AssetManifest
    family_tokens: FamilyTokensV4 | None = None
    min_body_font_px: StrictInt = Field(default=MIN_BODY_FONT_PX_V4, ge=MIN_BODY_FONT_PX_V4)
    min_display_font_px: StrictInt = Field(
        default=MIN_DISPLAY_FONT_PX_V4,
        ge=MIN_DISPLAY_FONT_PX_V4,
    )
    safe_margin_px: StrictInt = Field(default=SAFE_MARGIN_V4, ge=SAFE_MARGIN_V4)

    @field_validator("safe_margin_px")
    @classmethod
    def validate_safe_margin(cls, value: int) -> int:
        if value != SAFE_MARGIN_V4:
            raise ValueError("v4 safe margin is canonical and cannot be reduced or changed")
        return value


def _tupleize(value):
    if isinstance(value, dict):
        return {key: _tupleize(item) for key, item in value.items()}
    if isinstance(value, list):
        return tuple(_tupleize(item) for item in value)
    return value


def _coerce_program(value: LayoutProgramV4 | dict) -> LayoutProgramV4:
    raw = value.model_dump(mode="python") if isinstance(value, LayoutProgramV4) else value
    if not isinstance(raw, dict):
        raise TypeError("compile_layout requires a LayoutProgramV4")
    try:
        program = LayoutProgramV4.model_validate(_tupleize(raw))
        program.validate_integrity()
    except Exception as exc:
        raise ValueError("layout program is stale or has an invalid canonical hash") from exc
    return program


def _coerce_inputs(value: LayoutCompilerInputsV4 | dict) -> LayoutCompilerInputsV4:
    raw = value.model_dump(mode="python") if isinstance(value, LayoutCompilerInputsV4) else value
    if not isinstance(raw, dict):
        raise TypeError("compile_layout requires LayoutCompilerInputsV4")
    # Keep the public boundary narrow while accepting the two descriptive
    # spellings already used by adjacent v4 nodes.
    raw = dict(raw)
    for canonical, aliases in {
        "semantic_content_model": ("semantic_model",),
        "content_atom_set": ("atom_set",),
        "asset_manifest": ("assets",),
    }.items():
        if canonical not in raw:
            for alias in aliases:
                if alias in raw:
                    raw[canonical] = raw.pop(alias)
                    break
        else:
            for alias in aliases:
                raw.pop(alias, None)
    try:
        inputs = LayoutCompilerInputsV4.model_validate(_tupleize(raw))
        inputs.page_brief.validate_integrity()
        inputs.semantic_content_model.validate_integrity()
        inputs.content_atom_set.validate_integrity()
        AssetManifest.model_validate(inputs.asset_manifest.model_dump(mode="python"))
        if inputs.family_tokens is not None:
            inputs.family_tokens.validate_integrity()
    except Exception as exc:
        raise ValueError(f"layout compiler inputs are stale or invalid: {exc}") from exc
    return inputs


def _finite(value: float) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _slug(value: str, fallback: str) -> str:
    lowered = value.lower()
    cleaned = _ELEMENT_ID_RE.sub("-", lowered).strip("-")
    return (cleaned or fallback)[:42]


@dataclass
class _PlacedBox:
    x: float
    y: float
    width: float
    height: float
    element_id: str


@dataclass
class CompilerContextV4:
    """Shared validated context consumed by the three grammar solvers."""

    program: LayoutProgramV4
    inputs: LayoutCompilerInputsV4
    tokens: FamilyTokensV4
    fragments: dict[str, SemanticFragmentV4]
    assets_by_directive: dict[str, AssetManifestItem]
    directives_by_id: dict[str, object]
    used_boxes: list[_PlacedBox]
    element_counter: int = 0

    @property
    def page_id(self) -> str:
        return self.program.page_id

    @property
    def width(self) -> float:
        return CANVAS_WIDTH_V4 - (2 * SAFE_MARGIN_V4)

    @property
    def top(self) -> float:
        return float(SAFE_MARGIN_V4)

    @property
    def bottom(self) -> float:
        return float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4)

    @property
    def palette_primary(self) -> str:
        return self.tokens.palette[0]

    def fragment_text(self, ref: str) -> str:
        fragment = self.fragments.get(ref)
        if fragment is None:
            raise ValueError(f"unknown semantic fragment reference: {ref}")
        return fragment.exact_text

    def role_for_fragment(self, ref: str) -> str:
        role = self.fragments[ref].semantic_role
        if role in {"title", "cover", "heading"}:
            return "display"
        if role in {"note", "caption"}:
            return "caption"
        return "body"

    def _next_id(self, kind: str, ref: str | None = None) -> str:
        suffix = _slug(ref, f"{self.element_counter:02d}") if ref else f"{self.element_counter:02d}"
        element_id = f"v4-{kind}-{suffix}-{self.element_counter}"
        self.element_counter += 1
        return element_id[:64]

    def _safe_box(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        element_id: str,
        region_id: str | None,
        ref: str | None,
    ) -> Box:
        values = (x, y, width, height)
        if not all(_finite(float(value)) for value in values):
            raise LayoutCompilationError(
                "CONTENT_OVERFLOW",
                page_id=self.page_id,
                region_id=region_id,
                ref=ref,
                evidence="non-finite geometry",
            )
        if width <= 0 or height <= 0:
            raise LayoutCompilationError(
                "CONTENT_OVERFLOW",
                page_id=self.page_id,
                region_id=region_id,
                ref=ref,
                evidence="non-positive geometry",
            )
        if (
            x < SAFE_MARGIN_V4
            or y < SAFE_MARGIN_V4
            or x + width > CANVAS_WIDTH_V4 - SAFE_MARGIN_V4
            or y + height > CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4
        ):
            raise LayoutCompilationError(
                "CONTENT_OVERFLOW",
                page_id=self.page_id,
                region_id=region_id,
                ref=ref,
                evidence="geometry exceeds safe margin",
            )
        for previous in self.used_boxes:
            if (
                x < previous.x + previous.width
                and x + width > previous.x
                and y < previous.y + previous.height
                and y + height > previous.y
            ):
                raise LayoutCompilationError(
                    "UNBALANCED_REGIONS",
                    page_id=self.page_id,
                    region_id=region_id,
                    ref=ref,
                    evidence="unintentional region overlap",
                )
        self.used_boxes.append(_PlacedBox(x, y, width, height, element_id))
        return Box(x=x, y=y, width=width, height=height)

    def _font_ladder(self, role: str) -> tuple[int, ...]:
        if role == "display":
            floor = self.inputs.min_display_font_px
            return tuple(size for size in (88, 80, 72, 64, 56, 48, 40, 32) if size >= floor)
        if role == "heading":
            floor = self.inputs.min_display_font_px
            return tuple(size for size in (64, 56, 48, 40, 36, 32) if size >= floor)
        if role == "caption":
            floor = self.inputs.min_body_font_px
            return tuple(size for size in (32, 28, 24) if size >= floor)
        floor = self.inputs.min_body_font_px
        return tuple(size for size in (40, 36, 32, 28, 24) if size >= floor)

    def fit_text(
        self,
        ref: str,
        *,
        width: float,
        max_height: float,
        region_id: str,
    ) -> tuple[int, TextMeasurementV4]:
        role = self.role_for_fragment(ref)
        if not _finite(width) or not _finite(max_height) or width <= 0 or max_height <= 0:
            raise LayoutCompilationError(
                "CONTENT_OVERFLOW",
                page_id=self.page_id,
                region_id=region_id,
                ref=ref,
                evidence="invalid text region geometry",
            )
        for size in self._font_ladder(role):
            try:
                measurement = measure_text_v4(
                    self.fragment_text(ref),
                    family=self.program.template_family,
                    role=role,
                    font_size_px=size,
                    max_width_px=width,
                    line_height=1.25 if role in {"body", "caption"} else 1.15,
                )
            except ValueError as exc:
                if "grapheme cluster" in str(exc) or "width" in str(exc):
                    raise LayoutCompilationError(
                        "TYPOGRAPHY_CONSTRAINT_CONFLICT",
                        page_id=self.page_id,
                        region_id=region_id,
                        ref=ref,
                        evidence="unbreakable grapheme exceeds text region",
                    ) from exc
                raise
            if measurement.height_px <= max_height:
                return size, measurement
        raise LayoutCompilationError(
            "DENSITY_EXCEEDED",
            page_id=self.page_id,
            region_id=region_id,
            ref=ref,
            evidence="text cannot fit above the minimum font floor",
        )

    def text_element(
        self,
        ref: str,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        region_id: str,
        align: str = "left",
    ) -> TextElement:
        role = self.role_for_fragment(ref)
        size, _measurement = self.fit_text(
            ref,
            width=width,
            max_height=height,
            region_id=region_id,
        )
        element_id = self._next_id("text", ref)
        box = self._safe_box(
            x=x,
            y=y,
            width=width,
            height=height,
            element_id=element_id,
            region_id=region_id,
            ref=ref,
        )
        weight = 800 if role == "display" else 700 if role == "heading" else 500
        return TextElement(
            element_id=element_id,
            layer=20,
            box=box,
            content_ref=ref,
            style=TextStyle(
                font_role=role,
                font_size=float(size),
                line_height=1.15 if role in {"display", "heading"} else 1.25,
                color=self.palette_primary,
                align=align,  # type: ignore[arg-type]
                weight=weight,
            ),
        )

    def image_element(
        self,
        directive_id: str,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        region_id: str,
    ) -> ImageElement:
        asset = self.assets_by_directive.get(directive_id)
        directive = self.directives_by_id.get(directive_id)
        if asset is None or directive is None:
            raise ValueError(f"asset placement has no exact approved directive binding: {directive_id}")
        if asset.directive_id != directive_id or asset.page_id != self.page_id:
            raise ValueError(f"asset placement page/directive binding is invalid: {directive_id}")
        if asset.security_status != "approved":
            raise ValueError(f"asset placement is not security-approved: {directive_id}")
        asset_ratio = asset.width / asset.height
        box_ratio = width / height
        orientation = getattr(directive, "orientation", "any")
        if orientation == "portrait" and asset_ratio > 1.25:
            raise LayoutCompilationError(
                "ASSET_ASPECT_MISMATCH",
                page_id=self.page_id,
                region_id=region_id,
                ref=directive_id,
                evidence="approved asset orientation conflicts with directive",
            )
        if orientation == "landscape" and asset_ratio < 0.8:
            raise LayoutCompilationError(
                "ASSET_ASPECT_MISMATCH",
                page_id=self.page_id,
                region_id=region_id,
                ref=directive_id,
                evidence="approved asset orientation conflicts with directive",
            )
        if orientation == "square" and not 0.6 <= asset_ratio <= 1.7:
            raise LayoutCompilationError(
                "ASSET_ASPECT_MISMATCH",
                page_id=self.page_id,
                region_id=region_id,
                ref=directive_id,
                evidence="approved asset aspect ratio is not square-compatible",
            )
        element_id = self._next_id("image", directive_id)
        box = self._safe_box(
            x=x,
            y=y,
            width=width,
            height=height,
            element_id=element_id,
            region_id=region_id,
            ref=directive_id,
        )
        focal = asset.subject_focal_point
        return ImageElement(
            element_id=element_id,
            layer=10,
            box=box,
            asset_ref=asset.asset_id,
            fit="cover",
            focal_point=(float(focal[0]), float(focal[1])),
            corner_radius=24,
        )


def _validate_boundary(
    program: LayoutProgramV4,
    inputs: LayoutCompilerInputsV4,
) -> tuple[LayoutProgramV4, LayoutCompilerInputsV4, FamilyTokensV4, dict[str, SemanticFragmentV4], dict[str, AssetManifestItem], dict[str, object]]:
    inputs.page_brief.validate_integrity()
    inputs.semantic_content_model.validate_integrity()
    inputs.content_atom_set.validate_integrity()
    try:
        manifest = AssetManifest.model_validate(inputs.asset_manifest.model_dump(mode="python"))
    except Exception as exc:
        raise ValueError("asset manifest is stale or invalid") from exc
    if inputs.semantic_content_model.content_atom_set_sha256 != inputs.content_atom_set.canonical_sha256:
        raise ValueError("semantic model is bound to a different content atom set")
    try:
        checked_program = _coerce_program(program)
    except Exception:
        raise
    brief = inputs.page_brief
    if checked_program.page_id != brief.page_id:
        raise ValueError("layout program page ID does not match exact page brief")
    if checked_program.page_brief_sha256 != brief.canonical_sha256:
        raise ValueError("layout program page brief hash does not match exact page brief")
    if checked_program.beat_ref != brief.beat_ref:
        raise ValueError("layout program beat binding does not match exact page brief")
    try:
        tokens = get_family_tokens(checked_program.template_family)
    except Exception as exc:
        raise ValueError("layout program family is not canonical") from exc
    if checked_program.family_tokens_sha256 != tokens.canonical_sha256:
        raise ValueError("layout program family token hash is stale")
    if inputs.family_tokens is not None:
        if inputs.family_tokens.family != checked_program.template_family:
            raise ValueError("compiler inputs family token ID does not match program")
        if inputs.family_tokens.canonical_sha256 != tokens.canonical_sha256:
            raise ValueError("compiler inputs family token hash is stale")
    brief_fragment_refs = tuple(brief.fragment_refs)
    program_fragment_refs = tuple(item.fragment_ref for item in checked_program.fragment_placements)
    if len(set(brief_fragment_refs)) != len(brief_fragment_refs):
        raise ValueError("page brief fragment references must be unique")
    if program_fragment_refs != brief_fragment_refs:
        raise ValueError("layout program fragments do not exactly match page brief")
    brief_directives = tuple(brief.asset_directives)
    directive_ids = tuple(item.directive_id for item in brief_directives)
    program_directive_ids = tuple(item.directive_id for item in checked_program.asset_placements)
    if len(set(directive_ids)) != len(directive_ids):
        raise ValueError("page brief asset directives must be unique")
    if program_directive_ids != directive_ids:
        raise ValueError("layout program assets do not exactly match page brief directives")
    fragments = {fragment.fragment_id: fragment for fragment in inputs.semantic_content_model.fragments}
    if len(fragments) != len(inputs.semantic_content_model.fragments):
        raise ValueError("semantic model fragment IDs must be unique")
    atom_by_id = {atom.atom_id: atom for atom in inputs.content_atom_set.atoms}
    for ref in brief_fragment_refs:
        fragment = fragments.get(ref)
        if fragment is None:
            raise ValueError(f"page brief references an unknown semantic fragment: {ref}")
        atom = atom_by_id.get(fragment.source_atom_id)
        if atom is None:
            raise ValueError(f"semantic fragment references an unknown source atom: {ref}")
        if not 0 <= fragment.start < fragment.end <= len(atom.text):
            raise ValueError(f"semantic fragment bounds are invalid: {ref}")
        if fragment.exact_text != atom.text[fragment.start : fragment.end]:
            raise ValueError(f"semantic fragment exact_text is not the source slice: {ref}")
    assets_by_directive = {item.directive_id: item for item in manifest.items}
    if len(assets_by_directive) != len(manifest.items):
        raise ValueError("asset manifest directive IDs must be unique")
    directives_by_id = {item.directive_id: item for item in brief_directives}
    for placement in checked_program.asset_placements:
        asset = assets_by_directive.get(placement.directive_id)
        directive = directives_by_id.get(placement.directive_id)
        if directive is None or asset is None:
            raise ValueError(
                "layout program asset placement has no exact page directive and manifest item"
            )
        if asset.directive_id != placement.directive_id or asset.page_id != brief.page_id:
            raise ValueError("layout program asset placement has a cross-page binding")
        if asset.security_status != "approved":
            raise ValueError("layout program asset placement is not security-approved")
    for directive_id, asset in assets_by_directive.items():
        if directive_id in directives_by_id:
            if asset.page_id != brief.page_id:
                raise ValueError("asset manifest item belongs to a different page")
            if asset.security_status != "approved":
                raise ValueError("asset manifest item is not security-approved")
    return checked_program, inputs, tokens, fragments, assets_by_directive, directives_by_id


def _font_hashes(family: TemplateFamilyV4) -> dict[str, str]:
    return {
        role: resolve_font_file_v4(family, role).sha256
        for role in ("display", "heading", "body", "caption")
    }


def _make_provenance(program: LayoutProgramV4, hashes: dict[str, str]) -> CompilerProvenanceV4:
    payload = {
        "compiler_version": "v4-layout-compiler-1",
        "grammar_id": program.grammar_id,
        "program_sha256": program.canonical_sha256,
        "font_sha256_by_role": hashes,
        "canvas_width": CANVAS_WIDTH_V4,
        "canvas_height": CANVAS_HEIGHT_V4,
        "safe_margin_px": SAFE_MARGIN_V4,
    }
    return CompilerProvenanceV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def _make_compiled_page(
    program: LayoutProgramV4,
    scene: PageScene,
    provenance: CompilerProvenanceV4,
) -> CompiledPageV4:
    payload = {
        "page_id": program.page_id,
        "sequence": scene.sequence,
        "layout_program": program,
        "scene": scene,
        "compiler_provenance": provenance,
    }
    return CompiledPageV4(**payload, canonical_sha256=canonical_sha256_v4(payload))


def compile_layout(
    program: LayoutProgramV4 | dict,
    inputs: LayoutCompilerInputsV4 | dict,
) -> CompiledPageV4:
    """Compile exactly one page through one of the three v4 grammar solvers."""

    checked_program = _coerce_program(program)
    checked_inputs = _coerce_inputs(inputs)
    (
        checked_program,
        checked_inputs,
        tokens,
        fragments,
        assets_by_directive,
        directives_by_id,
    ) = _validate_boundary(checked_program, checked_inputs)
    context = CompilerContextV4(
        program=checked_program,
        inputs=checked_inputs,
        tokens=tokens,
        fragments=fragments,
        assets_by_directive=assets_by_directive,
        directives_by_id=directives_by_id,
        used_boxes=[],
    )
    # Import only after the validated context exists so each grammar module is
    # a separate deterministic dispatch target and cannot bypass the boundary.
    from src.visual_design.v4.grammar_compilers import get_grammar_compiler

    solver = get_grammar_compiler(checked_program.grammar_id)
    elements = tuple(solver(context))
    if not elements:
        raise LayoutCompilationError(
            "DENSITY_EXCEEDED",
            page_id=checked_program.page_id,
            evidence="grammar produced no scene elements",
        )
    text_refs = tuple(element.content_ref for element in elements if isinstance(element, TextElement))
    if text_refs != tuple(item.fragment_ref for item in checked_program.fragment_placements):
        raise ValueError("compiled scene does not represent every exact fragment placement")
    asset_refs = {element.asset_ref for element in elements if isinstance(element, ImageElement)}
    expected_assets = set(assets_by_directive[item.directive_id].asset_id for item in checked_program.asset_placements)
    if asset_refs != expected_assets:
        raise ValueError("compiled scene asset references do not match approved placements")
    scene = PageScene(
        page_id=checked_program.page_id,
        sequence=checked_inputs.page_brief.sequence,
        background=tokens.palette[-1],
        elements=elements,
    )
    hashes = _font_hashes(checked_program.template_family)
    provenance = _make_provenance(checked_program, hashes)
    return _make_compiled_page(checked_program, scene, provenance)


# Discoverable aliases used by v4 callers.
compile_page_layout = compile_layout
LayoutCompilerInputs = LayoutCompilerInputsV4
LayoutCompilerInputV4 = LayoutCompilerInputsV4


__all__ = [
    "CANVAS_HEIGHT_V4",
    "CANVAS_WIDTH_V4",
    "COMPILATION_ERROR_CODES_V4",
    "CompilerContextV4",
    "LayoutCompilationError",
    "LayoutCompilerInputs",
    "LayoutCompilerInputV4",
    "LayoutCompilerInputsV4",
    "MIN_BODY_FONT_PX_V4",
    "MIN_DISPLAY_FONT_PX_V4",
    "SAFE_MARGIN_V4",
    "compile_layout",
    "compile_page_layout",
]
