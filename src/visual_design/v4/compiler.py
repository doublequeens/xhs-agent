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
from src.schemas.v4.direction import PageBriefV4, TemplateFamilyV4, VisualDirectionPlanV4
from src.schemas.v4.layout import (
    AssetBindingEvidenceV4,
    CarouselDesignPlanV4,
    CompilerProvenanceV4,
    CompiledPageV4,
    FamilyTokensV4,
    LayoutProgramV4,
    TextMeasurementEvidenceV4,
)
from src.schemas.v4.semantic import SemanticContentModelV4, SemanticFragmentV4
from src.visual_design.v4.tokens import get_family_tokens, resolve_semantic_colors_v4
from src.visual_design.v4.typography import (
    TEXT_WRAP_POLICY_V4,
    TextMeasurementV4,
    measure_text_v4,
    resolve_font_file_v4,
)


CANVAS_WIDTH_V4: Final[int] = 1080
CANVAS_HEIGHT_V4: Final[int] = 1440
SAFE_MARGIN_V4: Final[int] = 80
MIN_BODY_FONT_PX_V4: Final[int] = 24
MIN_DISPLAY_FONT_PX_V4: Final[int] = 32
COMPILER_VERSION_V4: Final[str] = "v4-layout-compiler-2"
CONTRAST_POLICY_VERSION_V4: Final[str] = "wcag-semantic-ink-v1"
ACCESSIBILITY_INK_V4: Final[tuple[str, str]] = ("#111111", "#FFFFFF")
ASSET_CROP_THRESHOLD_V4: Final[float] = 3.0
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
    candidate_id: str = Field(min_length=1)
    revision: StrictInt = Field(ge=0)
    run_id: str | None = None
    visual_direction_plan: VisualDirectionPlanV4 | None = None
    family_tokens: FamilyTokensV4 | None = None
    min_body_font_px: StrictInt = Field(default=MIN_BODY_FONT_PX_V4, ge=MIN_BODY_FONT_PX_V4)
    min_display_font_px: StrictInt = Field(
        default=MIN_DISPLAY_FONT_PX_V4,
        ge=MIN_DISPLAY_FONT_PX_V4,
    )
    safe_margin_px: StrictInt = Field(default=SAFE_MARGIN_V4, ge=SAFE_MARGIN_V4)

    @field_validator("candidate_id")
    @classmethod
    def validate_candidate_id(cls, value: str) -> str:
        if not value.strip() or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value):
            raise ValueError("v4 candidate_id must be a structural identifier")
        return value

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
    except Exception:
        raise ValueError("layout program is stale or has an invalid canonical hash") from None
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
    except Exception:
        raise ValueError("layout compiler inputs are stale or invalid") from None
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
    text_measurement_evidence: dict[str, TextMeasurementEvidenceV4]
    asset_binding_evidence: dict[str, AssetBindingEvidenceV4]
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
        return self.resolve_color("accent")

    @staticmethod
    def _luminance(color: str) -> float:
        channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            channel / 12.92
            if channel <= 0.04045
            else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    @classmethod
    def _contrast_ratio(cls, foreground: str, background: str) -> float:
        brighter, darker = sorted(
            (cls._luminance(foreground), cls._luminance(background)),
            reverse=True,
        )
        return (brighter + 0.05) / (darker + 0.05)

    def resolve_color(self, semantic_role: str) -> str:
        try:
            return resolve_semantic_colors_v4(self.tokens)[semantic_role]
        except (KeyError, ValueError):
            threshold = 3.0 if semantic_role in {"display", "heading", "accent"} else 4.5
            raise LayoutCompilationError(
                "TYPOGRAPHY_CONSTRAINT_CONFLICT",
                page_id=self.page_id,
                evidence=f"contrast ratio below threshold={threshold:.2f}",
            ) from None

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
                    "CONTENT_OVERFLOW",
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
                        "CONTENT_OVERFLOW",
                        page_id=self.page_id,
                        region_id=region_id,
                        ref=ref,
                        evidence="unbreakable grapheme exceeds text region",
                    ) from None
                raise
            if measurement.height_px <= max_height:
                return size, measurement
        if not self._font_ladder(role):
            raise LayoutCompilationError(
                "TYPOGRAPHY_CONSTRAINT_CONFLICT",
                page_id=self.page_id,
                region_id=region_id,
                ref=ref,
                evidence="minimum font floor has no legal face size",
            )
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
        size, measurement = self.fit_text(
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
        weight = measurement.font_nominal_weight
        self.text_measurement_evidence[ref] = TextMeasurementEvidenceV4(
            fragment_ref=ref,
            font_role=role,
            font_sha256=measurement.font_sha256,
            font_size_px=measurement.font_size_px,
            line_count=measurement.line_count,
            break_offsets=measurement.break_offsets,
            measurement_sha256=measurement.measurement_sha256,
        )
        return TextElement(
            element_id=element_id,
            layer=20,
            box=box,
            content_ref=ref,
            style=TextStyle(
                font_role=role,
                font_size=float(size),
                line_height=1.15 if role in {"display", "heading"} else 1.25,
                color=self.resolve_color(role),
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
        crop_factor = max(asset_ratio / box_ratio, box_ratio / asset_ratio)
        if crop_factor > ASSET_CROP_THRESHOLD_V4:
            raise LayoutCompilationError(
                "ASSET_ASPECT_MISMATCH",
                page_id=self.page_id,
                region_id=region_id,
                ref=directive_id,
                evidence=f"crop_factor={crop_factor:.3f}; threshold={ASSET_CROP_THRESHOLD_V4:.3f}",
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
        self.asset_binding_evidence[directive_id] = AssetBindingEvidenceV4(
            directive_id=directive_id,
            asset_id=asset.asset_id,
            asset_sha256=asset.sha256,
            orientation=orientation,
            fit="cover",
        )
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
    except Exception:
        raise ValueError("asset manifest is stale or invalid") from None
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
    if checked_program.density_target != brief.density_budget:
        raise ValueError("layout program density target does not match exact page brief")
    try:
        tokens = get_family_tokens(checked_program.template_family)
    except Exception:
        raise ValueError("layout program family is not canonical") from None
    if checked_program.family_tokens_sha256 != tokens.canonical_sha256:
        raise ValueError("layout program family token hash is stale")
    if inputs.family_tokens is not None:
        if inputs.family_tokens.family != checked_program.template_family:
            raise ValueError("compiler inputs family token ID does not match program")
        if inputs.family_tokens.canonical_sha256 != tokens.canonical_sha256:
            raise ValueError("compiler inputs family token hash is stale")
    if inputs.visual_direction_plan is not None:
        plan = inputs.visual_direction_plan
        try:
            plan.validate_integrity()
        except Exception:
            raise ValueError("visual direction plan is stale or invalid") from None
        durable_page_set = plan.page_brief_set
        if durable_page_set.content_atom_set_sha256 is None or durable_page_set.semantic_content_model_sha256 is None:
            raise ValueError("durable page brief set must bind atom and semantic hashes")
        if plan.content_atom_set_sha256 != inputs.content_atom_set.canonical_sha256:
            raise ValueError("visual direction plan atom hash does not match compiler inputs")
        if plan.semantic_content_model_sha256 != inputs.semantic_content_model.canonical_sha256:
            raise ValueError("visual direction plan semantic hash does not match compiler inputs")
        if plan.template_family != checked_program.template_family:
            raise ValueError("visual direction plan family does not match layout program")
        if plan.narrative_sha256 != checked_program.carousel_narrative_sha256:
            raise ValueError("layout program narrative hash does not match visual direction plan")
        if plan.page_brief_set_sha256 != durable_page_set.canonical_sha256:
            raise ValueError("visual direction plan page brief hash is stale")
        if durable_page_set.content_atom_set_sha256 != plan.content_atom_set_sha256:
            raise ValueError("durable page brief set atom hash does not match visual direction plan")
        if durable_page_set.semantic_content_model_sha256 != plan.semantic_content_model_sha256:
            raise ValueError("durable page brief set semantic hash does not match visual direction plan")
        plan_brief = next((item for item in durable_page_set.pages if item.page_id == checked_program.page_id), None)
        if plan_brief is None or plan_brief.canonical_sha256 != inputs.page_brief.canonical_sha256:
            raise ValueError("compiler page brief is not the exact visual direction plan brief")

    from src.visual_design.v4.grammars import get_grammar

    grammar = get_grammar(checked_program.grammar_id)
    expected_regions = tuple(
        (item.region_id, item.role, index)
        for index, item in enumerate(grammar.region_roles)
    )
    actual_regions = tuple(
        (item.region_id, item.role, item.order)
        for item in checked_program.regions
    )
    if actual_regions != expected_regions:
        raise ValueError("layout program regions do not exactly match canonical grammar")
    expected_axes = tuple(
        (axis.axis_id, axis.orientation, tuple(axis.region_ids))
        for axis in grammar.alignment_axes
    )
    actual_axes = tuple(
        (axis.axis_id, axis.orientation, tuple(axis.region_ids))
        for axis in checked_program.alignment_axes
    )
    if actual_axes != expected_axes:
        raise ValueError("layout program alignment axes do not exactly match canonical grammar")
    expected_constraints = tuple(
        (constraint.constraint_id, constraint.kind, tuple(constraint.region_ids), tuple(constraint.axis_ids), constraint.behavior)
        for constraint in grammar.constraints
    )
    actual_constraints = tuple(
        (constraint.constraint_id, constraint.kind, tuple(constraint.region_ids), tuple(constraint.axis_ids), constraint.behavior)
        for constraint in checked_program.responsive_constraints
    )
    if actual_constraints != expected_constraints:
        raise ValueError("layout program responsive constraints do not exactly match canonical grammar")
    if checked_program.grammar_id == "editorial_hero" and checked_program.fragment_placements[0].region_id == "accent":
        raise LayoutCompilationError(
            "UNBALANCED_REGIONS",
            page_id=checked_program.page_id,
            region_id="accent",
            ref=checked_program.fragment_placements[0].fragment_ref,
            evidence="primary_focus_region_count=0",
        )
    region_counts: dict[str, int] = {}
    for placement in checked_program.fragment_placements:
        region_counts[placement.region_id] = region_counts.get(placement.region_id, 0) + 1
    if checked_program.grammar_id == "comparison_grid":
        left_count = region_counts.get("left", 0)
        right_count = region_counts.get("right", 0)
        if (left_count or right_count) and left_count != right_count:
            raise LayoutCompilationError(
                "UNBALANCED_REGIONS",
                page_id=checked_program.page_id,
                region_id="left" if left_count < right_count else "right",
                evidence=f"left_count={left_count}; right_count={right_count}",
            )
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


def _make_provenance(
    program: LayoutProgramV4,
    inputs: LayoutCompilerInputsV4,
    hashes: dict[str, str],
    *,
    text_measurement_evidence: dict[str, TextMeasurementEvidenceV4],
    asset_binding_evidence: dict[str, AssetBindingEvidenceV4],
) -> CompilerProvenanceV4:
    asset_manifest_hash = canonical_sha256_v3(inputs.asset_manifest)
    plan = inputs.visual_direction_plan
    payload = {
        "compiler_version": COMPILER_VERSION_V4,
        "grammar_id": program.grammar_id,
        "template_family": program.template_family,
        "program_sha256": program.canonical_sha256,
        "content_atom_set_sha256": inputs.content_atom_set.canonical_sha256,
        "semantic_content_model_sha256": inputs.semantic_content_model.canonical_sha256,
        "page_brief_sha256": inputs.page_brief.canonical_sha256,
        "page_brief_set_sha256": plan.page_brief_set_sha256 if plan is not None else None,
        "visual_direction_plan_sha256": plan.canonical_sha256 if plan is not None else None,
        "asset_manifest_sha256": asset_manifest_hash,
        "family_tokens_sha256": program.family_tokens_sha256,
        "font_sha256_by_role": hashes,
        "candidate_id": inputs.candidate_id,
        "revision": inputs.revision,
        "run_id": inputs.run_id,
        "canvas_width": CANVAS_WIDTH_V4,
        "canvas_height": CANVAS_HEIGHT_V4,
        "safe_margin_px": SAFE_MARGIN_V4,
        "min_body_font_px": inputs.min_body_font_px,
        "min_display_font_px": inputs.min_display_font_px,
        "text_wrap_policy": TEXT_WRAP_POLICY_V4,
        "contrast_policy_version": CONTRAST_POLICY_VERSION_V4,
        "accessibility_ink": ACCESSIBILITY_INK_V4[0],
        "text_measurement_evidence": text_measurement_evidence,
        "asset_binding_evidence": asset_binding_evidence,
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
        text_measurement_evidence={},
        asset_binding_evidence={},
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
    if checked_program.density_target == "high":
        occupied = sum(
            element.box.width * element.box.height
            for element in elements
            if hasattr(element, "box")
        )
        inner_area = float((CANVAS_WIDTH_V4 - 2 * SAFE_MARGIN_V4) * (CANVAS_HEIGHT_V4 - 2 * SAFE_MARGIN_V4))
        occupied_ratio = occupied / inner_area
        if occupied_ratio < 0.45:
            raise LayoutCompilationError(
                "INSUFFICIENT_WHITESPACE",
                page_id=checked_program.page_id,
                evidence=f"occupied_ratio={occupied_ratio:.3f}; required=0.450",
            )
    scene = PageScene(
        page_id=checked_program.page_id,
        sequence=checked_inputs.page_brief.sequence,
        background=tokens.palette[-1],
        elements=elements,
    )
    hashes = _font_hashes(checked_program.template_family)
    provenance = _make_provenance(
        checked_program,
        checked_inputs,
        hashes,
        text_measurement_evidence=context.text_measurement_evidence,
        asset_binding_evidence=context.asset_binding_evidence,
    )
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
