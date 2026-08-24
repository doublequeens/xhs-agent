"""Pure, deterministic Q2 metrics for compiled v4 scene plans.

This module intentionally has no renderer, browser, LLM, provider, clock or
filesystem dependency.  It consumes only the already validated compiled scene,
its compiler evidence, canonical family tokens and the exact page brief.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, field_validator, model_validator

from src.schemas.scene_graph import ImageElement, LineElement, TextElement
from src.schemas.v4.content import canonical_sha256_v4, sha256_text_v4
from src.schemas.v4.direction import (
    NarrativeTaskKindV4,
    PageBriefSetV4,
)
from src.schemas.v4.layout import (
    CarouselDesignPlanV4,
    CompiledPageV4,
    ImplementedGrammarIDV4,
    PAGE_ROLES_V4,
    PageRoleV4,
    TASK_KIND_TO_PAGE_ROLE_V4,
)
from src.schemas.v4.quality import (
    DesignMetricEvidenceV4,
    DesignMetricsQAResultV4,
    DesignQualityIssueV4,
    LINE_LENGTH_METRIC_UNIT_V4,
    LINE_LENGTH_METRIC_VERSION_V4,
    QUALITY_METRIC_UNIT_V4,
    QUALITY_METRIC_VERSION_V4,
    QUALITY_ISSUE_CODE_BY_METRIC_V4,
    QUALITY_METRIC_KINDS_V4,
    QUALITY_POLICY_VERSION_V4,
)
from src.schemas.v4.semantic import SemanticContentModelV4
from src.visual_design.v4.tokens import get_family_tokens
from src.visual_design.v4.typography import (
    SourceLineMetricsV4,
    reconstruct_source_lines_v4,
)


CANVAS_WIDTH_V4 = 1080.0
CANVAS_HEIGHT_V4 = 1440.0
SAFE_MARGIN_V4 = 80.0
INNER_WIDTH_V4 = CANVAS_WIDTH_V4 - 2 * SAFE_MARGIN_V4
INNER_HEIGHT_V4 = CANVAS_HEIGHT_V4 - 2 * SAFE_MARGIN_V4
INNER_AREA_V4 = INNER_WIDTH_V4 * INNER_HEIGHT_V4


class DesignMetricsInvariantError(ValueError):
    """Structural or integrity failure at the Q2 consumption boundary."""


class QualityPolicyV4(BaseModel):
    """Versioned typed thresholds; the complete payload is policy-bound."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    policy_version: StrictStr = QUALITY_POLICY_VERSION_V4
    grammar_id: ImplementedGrammarIDV4
    page_role: PageRoleV4
    narrative_role: NarrativeTaskKindV4
    safe_margin_px: StrictFloat = SAFE_MARGIN_V4
    minimum_font_px: StrictFloat
    contrast_min: StrictFloat
    whitespace_min: StrictFloat
    largest_text_block_max: StrictFloat
    regional_density_max: StrictFloat
    alignment_axis_deviation_max: StrictFloat
    paired_column_balance_max: StrictFloat
    spacing_consistency_max: StrictFloat
    heading_body_hierarchy_min: StrictFloat
    visual_center_offset_max: StrictFloat
    emphasis_count_max: StrictFloat
    line_length_max: StrictFloat
    line_length_metric_unit: StrictStr = LINE_LENGTH_METRIC_UNIT_V4
    line_length_metric_version: StrictStr = LINE_LENGTH_METRIC_VERSION_V4
    orphan_line_max: StrictFloat
    orphan_heading_max: StrictFloat
    image_text_area_ratio_max: StrictFloat
    canonical_sha256: StrictStr

    @field_validator(
        "safe_margin_px",
        "minimum_font_px",
        "contrast_min",
        "whitespace_min",
        "largest_text_block_max",
        "regional_density_max",
        "alignment_axis_deviation_max",
        "paired_column_balance_max",
        "spacing_consistency_max",
        "heading_body_hierarchy_min",
        "visual_center_offset_max",
        "emphasis_count_max",
        "line_length_max",
        "orphan_line_max",
        "orphan_heading_max",
        "image_text_area_ratio_max",
    )
    @classmethod
    def validate_finite_policy(cls, value: float, info) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"quality policy {info.field_name} must be finite")
        return float(value)

    @field_validator("canonical_sha256")
    @classmethod
    def validate_policy_hash_shape(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("quality policy canonical sha256 must be lowercase sha256")
        return value

    @model_validator(mode="after")
    def validate_policy(self) -> "QualityPolicyV4":
        if self.policy_version != QUALITY_POLICY_VERSION_V4:
            raise ValueError("quality policy version is not canonical")
        if self.safe_margin_px != SAFE_MARGIN_V4:
            raise ValueError("quality policy safe margin is not canonical")
        for field_name in (
            "whitespace_min",
            "largest_text_block_max",
            "regional_density_max",
            "paired_column_balance_max",
            "heading_body_hierarchy_min",
        ):
            value = getattr(self, field_name)
            if not 0 <= value <= 1.5:
                raise ValueError(f"quality policy {field_name} is outside the controlled range")
        if self.regional_density_max >= 1.0:
            raise ValueError("quality policy regional density threshold must be below one")
        if self.line_length_max >= 920.0:
            raise ValueError("quality policy line length threshold must be below legal width")
        if self.line_length_metric_unit != LINE_LENGTH_METRIC_UNIT_V4:
            raise ValueError("quality policy line length metric unit is not canonical")
        if self.line_length_metric_version != LINE_LENGTH_METRIC_VERSION_V4:
            raise ValueError("quality policy line length metric version is not canonical")
        payload = self.model_dump(mode="json", exclude={"canonical_sha256"})
        if self.canonical_sha256 != canonical_sha256_v4(payload):
            raise ValueError("quality policy canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))

    @property
    def policy_sha256(self) -> str:
        return self.canonical_sha256


_POLICY_VALUES: dict[str, dict[str, float]] = {
    # Hero pages deliberately tolerate more controlled breathing room and a
    # larger single focus block than dense information grammars.
    "editorial_hero": {
        # The canonical hero+asset compiler fixture measures 0.394.  Cover's
        # typed role adds 0.02, leaving a small 0.014 margin while retaining a
        # meaningful fail boundary for denser hero compositions.
        "whitespace_min": 0.36,
        "largest_text_block_max": 0.46,
        "regional_density_max": 0.85,
        "alignment_axis_deviation_max": 140.0,
        "paired_column_balance_max": 0.20,
        "spacing_consistency_max": 48.0,
        "heading_body_hierarchy_min": 1.10,
        "visual_center_offset_max": 400.0,
        "emphasis_count_max": 3.0,
        "line_length_max": 900.0,
        "orphan_line_max": 0.0,
        "orphan_heading_max": 0.0,
        "image_text_area_ratio_max": 3.0,
    },
    "comparison_grid": {
        "whitespace_min": 0.18,
        "largest_text_block_max": 0.38,
        "regional_density_max": 0.85,
        "alignment_axis_deviation_max": 260.0,
        "paired_column_balance_max": 0.20,
        "spacing_consistency_max": 260.0,
        "heading_body_hierarchy_min": 1.05,
        "visual_center_offset_max": 280.0,
        "emphasis_count_max": 4.0,
        "line_length_max": 900.0,
        "orphan_line_max": 0.0,
        "orphan_heading_max": 0.0,
        "image_text_area_ratio_max": 2.5,
    },
    "step_flow": {
        "whitespace_min": 0.20,
        "largest_text_block_max": 0.44,
        "regional_density_max": 0.85,
        "alignment_axis_deviation_max": 260.0,
        "paired_column_balance_max": 0.30,
        "spacing_consistency_max": 36.0,
        "heading_body_hierarchy_min": 1.05,
        "visual_center_offset_max": 600.0,
        "emphasis_count_max": 6.0,
        "line_length_max": 900.0,
        "orphan_line_max": 0.0,
        "orphan_heading_max": 0.0,
        "image_text_area_ratio_max": 2.5,
    },
}

_GRAMMAR_TASKS: dict[str, tuple[str, ...]] = {
    "editorial_hero": ("cover_hook", "context", "summary", "closing"),
    "comparison_grid": ("diagnosis", "comparison", "evidence"),
    "step_flow": ("step", "checklist"),
}


def _policy_payload(grammar_id: str, page_role: str, narrative_role: str) -> dict[str, object]:
    if grammar_id not in _POLICY_VALUES:
        raise DesignMetricsInvariantError("quality policy grammar is unknown or not implemented")
    if page_role not in PAGE_ROLES_V4:
        raise DesignMetricsInvariantError("quality policy page role is not controlled")
    if narrative_role not in _GRAMMAR_TASKS[grammar_id]:
        raise DesignMetricsInvariantError("quality policy narrative role is incompatible with grammar")
    # The page role is derived from the typed beat task.  Never let a caller
    # select the more permissive cover/closing envelope for a body beat (or
    # otherwise widen a policy by passing an unrelated role).
    if page_role != derive_page_role_v4(narrative_role):
        raise DesignMetricsInvariantError("quality policy page role is not derived from narrative role")
    values = dict(_POLICY_VALUES[grammar_id])
    # Typed page roles are part of the policy identity, not free-form copy.
    if page_role == "cover" and grammar_id == "editorial_hero":
        values["whitespace_min"] += 0.02
    elif page_role == "closing" and grammar_id == "editorial_hero":
        values["whitespace_min"] += 0.01
    return {
        "policy_version": QUALITY_POLICY_VERSION_V4,
        "grammar_id": grammar_id,
        "page_role": page_role,
        "narrative_role": narrative_role,
        "safe_margin_px": SAFE_MARGIN_V4,
        "minimum_font_px": 24.0,
        "contrast_min": 4.5,
        "line_length_metric_unit": LINE_LENGTH_METRIC_UNIT_V4,
        "line_length_metric_version": LINE_LENGTH_METRIC_VERSION_V4,
        **values,
    }


def get_quality_policy(
    grammar_id: str,
    page_role: str,
    narrative_role: str,
) -> QualityPolicyV4:
    """Return the immutable policy selected by typed grammar and page roles."""

    payload = _policy_payload(grammar_id, page_role, narrative_role)
    return QualityPolicyV4(**payload, canonical_sha256=canonical_sha256_v4(payload))


_POLICY_FIELD_BY_METRIC = {
    "safe_margin_compliance": "safe_margin_px",
    "unintended_overlap": None,
    "minimum_font_size": "minimum_font_px",
    "contrast": "contrast_min",
    "whitespace_ratio": "whitespace_min",
    "largest_text_block_ratio": "largest_text_block_max",
    "regional_information_density": "regional_density_max",
    "alignment_axis_deviation": "alignment_axis_deviation_max",
    "paired_column_balance": "paired_column_balance_max",
    "spacing_consistency": "spacing_consistency_max",
    "heading_body_hierarchy_ratio": "heading_body_hierarchy_min",
    "visual_center_offset": "visual_center_offset_max",
    "emphasis_count": "emphasis_count_max",
    "line_length": "line_length_max",
    "orphan_line": "orphan_line_max",
    "orphan_heading": "orphan_heading_max",
    "image_text_area_ratio": "image_text_area_ratio_max",
}


def threshold_for_metric_v4(policy: QualityPolicyV4, metric: str) -> float:
    """Return the one canonical threshold for a known metric kind."""

    if metric not in _POLICY_FIELD_BY_METRIC:
        raise DesignMetricsInvariantError("metric kind is unknown to the quality policy")
    field_name = _POLICY_FIELD_BY_METRIC[metric]
    if field_name is None:
        return 0.0
    return float(getattr(policy, field_name))


def derive_page_role_v4(task_kind: str) -> PageRoleV4:
    try:
        role = TASK_KIND_TO_PAGE_ROLE_V4[task_kind]
    except KeyError:
        raise DesignMetricsInvariantError("page role must come from a controlled beat task kind") from None
    return role  # type: ignore[return-value]


def _coerce(model_type, value, name: str):
    try:
        raw = value.model_dump(mode="python") if isinstance(value, model_type) else value
        checked = model_type.model_validate(raw)
        if hasattr(checked, "validate_integrity"):
            checked.validate_integrity()
        return checked
    except Exception:
        raise DesignMetricsInvariantError(f"{name} is stale or structurally invalid") from None


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise DesignMetricsInvariantError(f"metric {name} is non-finite")
    return float(value)


_Box = tuple[float, float, float, float]


def _box(element) -> _Box:
    if isinstance(element, LineElement):
        left = min(float(element.start[0]), float(element.end[0]))
        top = min(float(element.start[1]), float(element.end[1]))
        right = max(float(element.start[0]), float(element.end[0]))
        bottom = max(float(element.start[1]), float(element.end[1]))
        return left, top, max(1.0, right - left), max(1.0, bottom - top)
    value = element.box
    return float(value.x), float(value.y), float(value.width), float(value.height)


def _intersects(left: _Box, right: _Box) -> bool:
    return (
        left[0] < right[0] + right[2]
        and left[0] + left[2] > right[0]
        and left[1] < right[1] + right[3]
        and left[1] + left[3] > right[1]
    )


def _union_area(boxes: Sequence[_Box]) -> float:
    """Exact deterministic rectangle union area using x-slab clipping."""

    if not boxes:
        return 0.0
    xs = sorted({x for box in boxes for x in (box[0], box[0] + box[2])})
    area = 0.0
    for left, right in zip(xs, xs[1:]):
        if right <= left:
            continue
        intervals = sorted(
            (box[1], box[1] + box[3])
            for box in boxes
            if box[0] < right and box[0] + box[2] > left
        )
        covered = 0.0
        current_top = current_bottom = None
        for top, bottom in intervals:
            if current_top is None:
                current_top, current_bottom = top, bottom
            elif top > current_bottom:
                covered += current_bottom - current_top
                current_top, current_bottom = top, bottom
            else:
                current_bottom = max(current_bottom, bottom)
        if current_top is not None:
            covered += current_bottom - current_top
        area += (right - left) * covered
    return area


def _luminance(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255.0 for index in (1, 3, 5)]
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: str, second: str) -> float:
    brighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (brighter + 0.05) / (darker + 0.05)


def _painted_box(page: CompiledPageV4, element) -> _Box:
    box = _box(element)
    if not isinstance(element, TextElement):
        return box
    evidence = page.compiler_provenance.text_measurement_evidence[element.content_ref]
    left = box[0] + evidence.content_inset_left_px + evidence.painted_offset_x_px + evidence.painted_left_px
    top = box[1] + evidence.content_inset_top_px + evidence.painted_offset_y_px + evidence.painted_top_px
    right = box[0] + evidence.content_inset_left_px + evidence.painted_offset_x_px + evidence.painted_right_px
    bottom = box[1] + evidence.content_inset_top_px + evidence.painted_offset_y_px + evidence.painted_bottom_px
    return float(left), float(top), float(max(0.0, right - left)), float(max(0.0, bottom - top))


def _metric(
    *,
    metric: str,
    page_id: str,
    actual: float,
    threshold: float,
    comparator: Literal["gte", "lte", "eq", "within"],
    policy: QualityPolicyV4,
    region_id: str | None = None,
    element_id: str | None = None,
    fragment_ref: str | None = None,
) -> DesignMetricEvidenceV4:
    actual = _finite(actual, metric)
    threshold = _finite(threshold, f"{metric}.threshold")
    if comparator == "gte":
        passed = actual >= threshold
    elif comparator == "lte":
        passed = actual <= threshold
    elif comparator == "eq":
        passed = math.isclose(actual, threshold, rel_tol=0.0, abs_tol=1e-9)
    else:
        passed = actual <= threshold
    payload = {
        "metric": metric,
        "page_id": page_id,
        "actual": actual,
        "threshold": threshold,
        "comparator": comparator,
        "passed": passed,
        "metric_unit": (
            LINE_LENGTH_METRIC_UNIT_V4
            if metric == "line_length"
            else QUALITY_METRIC_UNIT_V4
        ),
        "metric_version": (
            LINE_LENGTH_METRIC_VERSION_V4
            if metric == "line_length"
            else QUALITY_METRIC_VERSION_V4
        ),
        "policy_sha256": policy.canonical_sha256,
        "region_id": region_id,
        "element_id": element_id,
        "fragment_ref": fragment_ref,
    }
    return DesignMetricEvidenceV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def _source_line_metrics_by_ref(
    page: CompiledPageV4,
    semantic_content_model: SemanticContentModelV4,
) -> dict[str, SourceLineMetricsV4]:
    """Validate every compiled text evidence against exact semantic source."""

    if (
        page.compiler_provenance.semantic_content_model_sha256
        != semantic_content_model.canonical_sha256
    ):
        raise DesignMetricsInvariantError(
            "compiled page semantic source binding is stale"
        )
    fragments = {fragment.fragment_id: fragment for fragment in semantic_content_model.fragments}
    if len(fragments) != len(semantic_content_model.fragments):
        raise DesignMetricsInvariantError("semantic fragment identity is not unique")
    result: dict[str, SourceLineMetricsV4] = {}
    for element in page.scene.elements:
        if not isinstance(element, TextElement):
            continue
        fragment = fragments.get(element.content_ref)
        evidence = page.compiler_provenance.text_measurement_evidence.get(element.content_ref)
        if fragment is None or evidence is None:
            raise DesignMetricsInvariantError(
                "compiled page text is not bound to an exact semantic fragment"
            )
        if evidence.fragment_ref != fragment.fragment_id:
            raise DesignMetricsInvariantError("text measurement fragment binding is stale")
        if evidence.source_atom_id != fragment.source_atom_id:
            raise DesignMetricsInvariantError("text measurement source binding is stale")
        if evidence.exact_text_sha256 != sha256_text_v4(fragment.exact_text):
            raise DesignMetricsInvariantError(
                "text measurement exact source hash is stale"
            )
        try:
            source_metrics = reconstruct_source_lines_v4(
                fragment.exact_text,
                explicit_break_spans=evidence.explicit_break_spans,
                inserted_break_offsets=evidence.inserted_break_offsets,
            )
        except (TypeError, ValueError):
            raise DesignMetricsInvariantError(
                "text measurement source line structure is invalid"
            ) from None
        if (
            len(source_metrics.lines) != evidence.line_count
            or source_metrics.codepoint_counts != evidence.line_codepoint_counts
            or source_metrics.grapheme_counts != evidence.line_grapheme_counts
        ):
            raise DesignMetricsInvariantError(
                "text measurement line counts do not match semantic source"
            )
        result[element.content_ref] = source_metrics
    return result


_ISSUE_TARGET = {
    "safe_margin_compliance": "layout_reflow",
    "unintended_overlap": "layout_reflow",
    "minimum_font_size": "layout_reflow",
    "contrast": "layout_reflow",
    "whitespace_ratio": "layout_reflow",
    "largest_text_block_ratio": "layout_reflow",
    "regional_information_density": "layout_reflow",
    "alignment_axis_deviation": "layout_reflow",
    "paired_column_balance": "grammar_fallback",
    "spacing_consistency": "layout_reflow",
    "heading_body_hierarchy_ratio": "layout_reflow",
    "visual_center_offset": "layout_reflow",
    "emphasis_count": "grammar_fallback",
    "line_length": "layout_reflow",
    "orphan_line": "authoring_repaginate",
    "orphan_heading": "authoring_repaginate",
    "image_text_area_ratio": "grammar_fallback",
}


def _issue(
    evidence: DesignMetricEvidenceV4,
    *,
    region_id: str | None = None,
    element_id: str | None = None,
    fragment_ref: str | None = None,
) -> DesignQualityIssueV4:
    metric = evidence.metric
    payload = {
        "code": QUALITY_ISSUE_CODE_BY_METRIC_V4[metric],
        "metric": metric,
        "page_id": evidence.page_id,
        "actual": evidence.actual,
        "threshold": evidence.threshold,
        "comparator": evidence.comparator,
        "revision_target": _ISSUE_TARGET[metric],
        "message": f"{metric} is outside its typed quality threshold",
        "region_id": region_id if region_id is not None else evidence.region_id,
        "element_id": element_id if element_id is not None else evidence.element_id,
        "fragment_ref": fragment_ref if fragment_ref is not None else evidence.fragment_ref,
        "policy_sha256": evidence.policy_sha256,
    }
    return DesignQualityIssueV4(**payload, canonical_sha256=canonical_sha256_v4(payload))


def _region_boxes(page: CompiledPageV4) -> dict[str, _Box]:
    return {
        region_id: (
            float(evidence.x),
            float(evidence.y),
            float(evidence.width),
            float(evidence.height),
        )
        for region_id, evidence in page.compiler_provenance.region_geometry_evidence.items()
    }


def _region_for_element(page: CompiledPageV4, element_id: str) -> str:
    try:
        return page.compiler_provenance.element_region_bindings[element_id]
    except KeyError:
        raise DesignMetricsInvariantError("scene element has no canonical region binding") from None


def _make_metric_set(
    page: CompiledPageV4,
    policy: QualityPolicyV4,
    semantic_content_model: SemanticContentModelV4,
) -> tuple[DesignMetricEvidenceV4, ...]:
    elements = tuple(page.scene.elements)
    boxes = tuple(_box(element) for element in elements)
    region_boxes = _region_boxes(page)
    source_line_metrics = _source_line_metrics_by_ref(page, semantic_content_model)

    # Every metric evidence location is derived from a canonical scene
    # element/region/ref.  Global page metrics still point at the worst
    # measured element so a revision can act on a concrete lane.
    def _location(element):
        return (
            _region_for_element(page, element.element_id),
            element.element_id,
            element.content_ref if isinstance(element, TextElement) else None,
        )

    min_margin = math.inf
    margin_location: tuple[str | None, str | None, str | None] = (None, None, None)

    def _consider_margin(
        value: float,
        element,
    ) -> None:
        nonlocal min_margin, margin_location
        value = _finite(value, "safe_margin_compliance")
        if value < min_margin:
            min_margin = value
            margin_location = _location(element)

    for element, box in zip(elements, boxes):
        if isinstance(element, LineElement):
            points = (element.start, element.end)
            for x, y in points:
                _consider_margin(float(x), element)
                _consider_margin(float(y), element)
                _consider_margin(CANVAS_WIDTH_V4 - float(x), element)
                _consider_margin(CANVAS_HEIGHT_V4 - float(y), element)
        else:
            _consider_margin(box[0], element)
            _consider_margin(box[1], element)
            _consider_margin(CANVAS_WIDTH_V4 - box[0] - box[2], element)
            _consider_margin(CANVAS_HEIGHT_V4 - box[1] - box[3], element)
        if isinstance(element, TextElement):
            ink = _painted_box(page, element)
            _consider_margin(ink[0], element)
            _consider_margin(ink[1], element)
            _consider_margin(CANVAS_WIDTH_V4 - ink[0] - ink[2], element)
            _consider_margin(CANVAS_HEIGHT_V4 - ink[1] - ink[3], element)
    if not math.isfinite(min_margin):
        raise DesignMetricsInvariantError("page has no measurable scene geometry")

    overlap_count = 0
    overlap_location: tuple[str | None, str | None, str | None, str | None] = (
        None,
        None,
        None,
        None,
    )
    for index, (left_element, left_box) in enumerate(zip(elements, boxes)):
        for right_element, right_box in zip(elements[index + 1 :], boxes[index + 1 :]):
            if _intersects(left_box, right_box):
                allowed = set(left_element.intentional_overlap_with) | set(right_element.intentional_overlap_with)
                if left_element.element_id not in allowed and right_element.element_id not in allowed:
                    overlap_count += 1
                    if overlap_location[0] is None:
                        overlap_location = (
                            _region_for_element(page, left_element.element_id),
                            left_element.element_id,
                            left_element.content_ref if isinstance(left_element, TextElement) else None,
                            right_element.element_id,
                        )

    text_elements = tuple(element for element in elements if isinstance(element, TextElement))
    image_elements = tuple(element for element in elements if isinstance(element, ImageElement))
    if not text_elements:
        raise DesignMetricsInvariantError("page has no measurable text elements")

    min_font = min(float(element.style.font_size) for element in text_elements)
    min_font_element = next(
        (element for element in text_elements if element.style.font_size == min_font),
        None,
    )
    contrast_values = tuple(
        (_contrast(element.style.color, page.scene.background), element)
        for element in text_elements
    )
    min_contrast, contrast_element = min(
        contrast_values,
        key=lambda item: (item[0], item[1].element_id),
    )

    whitespace = 1.0 - _union_area(boxes) / INNER_AREA_V4
    text_block_element, text_block_box = max(
        ((element, box) for element, box in zip(elements, boxes) if isinstance(element, TextElement)),
        key=lambda item: (item[1][2] * item[1][3], item[0].element_id),
    )
    text_block_ratio = text_block_box[2] * text_block_box[3] / INNER_AREA_V4
    region_density_values: list[tuple[float, str]] = []
    for region_id, region_box in region_boxes.items():
        denominator = region_box[2] * region_box[3]
        if not math.isfinite(denominator) or denominator <= 0:
            raise DesignMetricsInvariantError("quality region has an impossible area denominator")
        occupied = [
            _painted_box(page, element) if isinstance(element, TextElement) else box
            for element, box in zip(elements, boxes)
            if _region_for_element(page, element.element_id) == region_id
        ]
        region_density_values.append(
            ((_union_area(occupied) / denominator) if occupied else 0.0, region_id)
        )
    if not region_density_values:
        raise DesignMetricsInvariantError("page has no canonical quality regions")
    region_density, region_density_region = max(
        region_density_values,
        key=lambda item: (item[0], item[1]),
    )

    alignment_deviation = 0.0
    alignment_region = None
    for axis in page.layout_program.alignment_axes:
        occupied_by_region: dict[str, list[_Box]] = {
            region_id: [
                box
                for element, box in zip(elements, boxes)
                if _region_for_element(page, element.element_id) == region_id
            ]
            for region_id in axis.region_ids
        }
        axis_boxes = []
        axis_regions = []
        for region_id in axis.region_ids:
            occupied = occupied_by_region[region_id]
            if not occupied:
                continue
            axis_boxes.append(
                (
                    min(box[0] for box in occupied),
                    min(box[1] for box in occupied),
                    max(box[0] + box[2] for box in occupied) - min(box[0] for box in occupied),
                    max(box[1] + box[3] for box in occupied) - min(box[1] for box in occupied),
                )
            )
            axis_regions.append(region_id)
        if len(axis_boxes) < 2:
            continue
        # An inline axis is executable only for regions occupying the same
        # horizontal band.  A flow axis may name a later support region for
        # ordering, but comparing its vertical centre to the sequence lane
        # would turn intentional stacking into an alignment failure.
        if axis.orientation == "inline":
            active_region_boxes = [
                region_boxes[region_id]
                for region_id in axis_regions
            ]
            if not any(
                left[1] < right[1] + right[3] and right[1] < left[1] + left[3]
                for index, left in enumerate(active_region_boxes)
                for right in active_region_boxes[index + 1 :]
            ):
                continue
        if axis.orientation == "inline":
            reference = sum(box[1] + box[3] / 2 for box in axis_boxes) / len(axis_boxes)
            deviation = max(abs((box[1] + box[3] / 2) - reference) for box in axis_boxes)
        elif axis.orientation == "block":
            reference = sum(box[0] + box[2] / 2 for box in axis_boxes) / len(axis_boxes)
            deviation = max(abs((box[0] + box[2] / 2) - reference) for box in axis_boxes)
        else:
            deviation = 0.0
        if deviation > alignment_deviation:
            alignment_deviation, alignment_region = deviation, axis_regions[0]

    paired_balance = 0.0
    paired_region = None
    if page.layout_program.grammar_id == "comparison_grid":
        left = region_boxes.get("left")
        right = region_boxes.get("right")
        if left is None or right is None or left[2] <= 0 or right[2] <= 0:
            raise DesignMetricsInvariantError("comparison metric requires canonical paired regions")
        paired_balance = abs(left[2] - right[2]) / max(left[2], right[2])
        paired_region = "left"

    # Compare only sibling rows/cards within the same canonical region.  A
    # step icon and its text are first unioned into one row, so they cannot
    # manufacture a false page-wide spacing spread.
    rows_by_region: dict[str, list[tuple[_Box, tuple[object, ...]]]] = {}
    for region_id in region_boxes:
        members = sorted(
            [
                (element, box)
                for element, box in zip(elements, boxes)
                if _region_for_element(page, element.element_id) == region_id
            ],
            key=lambda item: (item[1][1], item[1][0], item[0].element_id),
        )
        rows: list[tuple[_Box, tuple[object, ...]]] = []
        for element, box in members:
            overlapping_index = next(
                (
                    index
                    for index, (row_box, _row_members) in enumerate(rows)
                    if box[1] < row_box[1] + row_box[3] and row_box[1] < box[1] + box[3]
                ),
                None,
            )
            if overlapping_index is None:
                rows.append((box, (element,)))
                continue
            row_box, row_members = rows[overlapping_index]
            left = min(row_box[0], box[0])
            top = min(row_box[1], box[1])
            right = max(row_box[0] + row_box[2], box[0] + box[2])
            bottom = max(row_box[1] + row_box[3], box[1] + box[3])
            rows[overlapping_index] = ((left, top, right - left, bottom - top), (*row_members, element))
        rows_by_region[region_id] = sorted(rows, key=lambda item: (item[0][1], item[0][0]))

    region_gap_values: dict[str, list[tuple[float, object]]] = {}
    for region_id, rows in rows_by_region.items():
        gaps_for_region: list[tuple[float, object]] = []
        for previous, current in zip(rows, rows[1:]):
            gaps_for_region.append(
                (current[0][1] - (previous[0][1] + previous[0][3]), previous[1][0])
            )
        if gaps_for_region:
            region_gap_values[region_id] = gaps_for_region
    if not region_gap_values:
        spacing_consistency = 0.0
        spacing_location = _location(elements[0])
    else:
        region_spreads = {
            region_id: max(gap for gap, _element in values)
            - min(gap for gap, _element in values)
            for region_id, values in region_gap_values.items()
        }
        spacing_consistency = max(region_spreads.values())
        spread_region = max(
            region_spreads,
            key=lambda region_id: (region_spreads[region_id], region_id),
        )
        spacing_gap = max(
            region_gap_values[spread_region],
            key=lambda item: (item[0], item[1].element_id),
        )
        spacing_location = _location(spacing_gap[1])

    headings = tuple(element for element in text_elements if element.style.font_role in {"display", "heading"})
    bodies = tuple(element for element in text_elements if element.style.font_role in {"body", "caption"})
    if not headings:
        raise DesignMetricsInvariantError("page has no measurable heading hierarchy")
    largest_heading = max(headings, key=lambda element: (element.style.font_size, element.element_id))
    if bodies:
        smallest_body = min(bodies, key=lambda element: (element.style.font_size, element.element_id))
        hierarchy = float(largest_heading.style.font_size) / float(smallest_body.style.font_size)
    else:
        # Hero/cover pages may intentionally contain only a title.  In that
        # case the canonical body floor is the only honest denominator; it is
        # still derived from the measured heading and versioned policy.
        hierarchy = float(largest_heading.style.font_size) / policy.minimum_font_px

    centers = []
    weighted_boxes = []
    for element, box in zip(elements, boxes):
        centers.append((box[0] + box[2] / 2, box[1] + box[3] / 2))
        weighted_boxes.append((element, box[2] * box[3]))
    weights = [weight for _element, weight in weighted_boxes]
    if weights and sum(weights) > 0:
        center_x = sum(center[0] * weight for center, weight in zip(centers, weights)) / sum(weights)
        center_y = sum(center[1] * weight for center, weight in zip(centers, weights)) / sum(weights)
        visual_center_offset = math.hypot(center_x - CANVAS_WIDTH_V4 / 2, center_y - CANVAS_HEIGHT_V4 / 2)
    else:
        raise DesignMetricsInvariantError("visual-center metric has an impossible area denominator")
    center_element = max(
        weighted_boxes,
        key=lambda item: (item[1], item[0].element_id),
    )[0]
    emphasis_count = sum(len(element.style.emphasis_ranges) for element in text_elements) + len(page.layout_program.emphasis_rules)
    emphasis_element = max(
        text_elements,
        key=lambda element: (len(element.style.emphasis_ranges), element.element_id),
    )
    def _line_length_actual(element: TextElement) -> float:
        evidence = page.compiler_provenance.text_measurement_evidence[element.content_ref]
        source = source_line_metrics[element.content_ref]
        source_upper_bound = max(
            (count * float(element.style.font_size) for count in source.grapheme_counts),
            default=0.0,
        )
        pillow_width = max(evidence.line_widths_px)
        # Pillow remains useful drift evidence, but source-derived width is a
        # hard lower bound so forged narrow Pillow values cannot lower Q2.
        return max(float(pillow_width), float(source_upper_bound))

    line_length_element = max(
        text_elements,
        key=lambda element: (_line_length_actual(element), element.element_id),
    )
    line_length = _line_length_actual(line_length_element)
    orphan_line = 0
    orphan_heading = 0
    orphan_element = None
    for element in text_elements:
        evidence = page.compiler_provenance.text_measurement_evidence[element.content_ref]
        # Orphan detection uses only source-derived grapheme counts.  Persisted
        # Pillow counts were checked against this source immediately above.
        source = source_line_metrics[element.content_ref]
        if len(source.lines) > 1 and any(count <= 1 for count in source.grapheme_counts):
            orphan_line += 1
            if element.style.font_role in {"display", "heading"}:
                orphan_heading += 1
            orphan_element = element
    text_area = sum(box[2] * box[3] for element, box in zip(elements, boxes) if isinstance(element, TextElement))
    image_area = sum(box[2] * box[3] for element, box in zip(elements, boxes) if isinstance(element, ImageElement))
    if not math.isfinite(text_area) or text_area <= 0:
        raise DesignMetricsInvariantError("image/text metric has an impossible text-area denominator")
    image_text_ratio = image_area / text_area

    primary_element = max(
        zip(elements, boxes),
        key=lambda item: (item[1][2] * item[1][3], item[0].element_id),
    )[0]
    primary_location = _location(primary_element)
    orphan_location = _location(orphan_element) if orphan_element is not None else (None, None, None)
    image_location = _location(max(image_elements, key=lambda element: (_box(element)[2] * _box(element)[3], element.element_id))) if image_elements else primary_location

    values: dict[str, tuple[float, float, Literal["gte", "lte", "eq", "within"], str | None, str | None, str | None]] = {
        "safe_margin_compliance": (min_margin, policy.safe_margin_px, "gte", *margin_location),
        "unintended_overlap": (float(overlap_count), 0.0, "eq", overlap_location[0], overlap_location[1], overlap_location[2]),
        "minimum_font_size": (min_font, policy.minimum_font_px, "gte", *_location(min_font_element)),
        "contrast": (min_contrast, policy.contrast_min, "gte", *_location(contrast_element)),
        "whitespace_ratio": (whitespace, policy.whitespace_min, "gte", *primary_location),
        "largest_text_block_ratio": (text_block_ratio, policy.largest_text_block_max, "lte", *_location(text_block_element)),
        "regional_information_density": (region_density, policy.regional_density_max, "lte", region_density_region, None, None),
        "alignment_axis_deviation": (alignment_deviation, policy.alignment_axis_deviation_max, "lte", alignment_region or primary_location[0], None, None),
        "paired_column_balance": (paired_balance, policy.paired_column_balance_max, "lte", paired_region or primary_location[0], None, None),
        "spacing_consistency": (spacing_consistency, policy.spacing_consistency_max, "lte", *spacing_location),
        "heading_body_hierarchy_ratio": (hierarchy, policy.heading_body_hierarchy_min, "gte", *_location(largest_heading)),
        "visual_center_offset": (visual_center_offset, policy.visual_center_offset_max, "lte", *primary_location),
        "emphasis_count": (float(emphasis_count), policy.emphasis_count_max, "lte", *_location(emphasis_element)),
        "line_length": (line_length, policy.line_length_max, "lte", *_location(line_length_element)),
        "orphan_line": (float(orphan_line), policy.orphan_line_max, "eq", *orphan_location),
        "orphan_heading": (float(orphan_heading), policy.orphan_heading_max, "eq", *orphan_location),
        "image_text_area_ratio": (image_text_ratio, policy.image_text_area_ratio_max, "lte", *image_location),
    }
    return tuple(
        _metric(
            metric=metric,
            page_id=page.page_id,
            actual=actual,
            threshold=threshold,
            comparator=comparator,
            policy=policy,
            region_id=region_id,
            element_id=element_id,
            fragment_ref=fragment_ref,
        )
        for metric, (actual, threshold, comparator, region_id, element_id, fragment_ref) in values.items()
    )


def evaluate_page_metrics(
    page: CompiledPageV4 | Mapping[str, object],
    *,
    page_brief_set: PageBriefSetV4 | Mapping[str, object],
    semantic_content_model: SemanticContentModelV4 | Mapping[str, object],
) -> DesignMetricsQAResultV4:
    """Evaluate one page without mutating or repairing its scene."""

    checked_page = _coerce(CompiledPageV4, page, "compiled page")
    checked_set = _coerce(PageBriefSetV4, page_brief_set, "page brief set")
    checked_semantic = _coerce(
        SemanticContentModelV4,
        semantic_content_model,
        "semantic content model",
    )
    checked_brief = next((item for item in checked_set.pages if item.page_id == checked_page.page_id), None)
    if checked_brief is None:
        raise DesignMetricsInvariantError("compiled page is absent from exact page brief set")
    selected_grammar = checked_page.layout_program.grammar_id
    typed_narrative_role = checked_page.layout_program.beat_task_kind
    typed_page_role = derive_page_role_v4(typed_narrative_role)
    if checked_brief.sequence != checked_page.sequence:
        raise DesignMetricsInvariantError("compiled page identity does not match exact page brief")
    if checked_brief.beat_ref != checked_page.layout_program.beat_ref:
        raise DesignMetricsInvariantError("compiled page beat binding does not match exact page brief")
    if checked_brief.canonical_sha256 != checked_page.compiler_provenance.page_brief_sha256:
        raise DesignMetricsInvariantError("compiled page brief hash is not bound to exact page brief")
    if selected_grammar not in checked_brief.preferred_compositions:
        raise DesignMetricsInvariantError("metric grammar is not an approved page composition")
    if checked_set.canonical_sha256 != checked_page.compiler_provenance.page_brief_set_sha256:
        raise DesignMetricsInvariantError("compiled page brief-set hash is not bound to exact page brief set")
    canonical_family = get_family_tokens(checked_page.layout_program.template_family)
    if canonical_family.canonical_sha256 != checked_page.compiler_provenance.family_tokens_sha256:
        raise DesignMetricsInvariantError("compiled page family token hash is not canonical")
    policy = get_quality_policy(selected_grammar, typed_page_role, typed_narrative_role)
    metrics = _make_metric_set(checked_page, policy, checked_semantic)
    issues = tuple(_issue(metric) for metric in metrics if not metric.passed)
    provenance = checked_page.compiler_provenance
    payload = {
        "passed": not issues and all(metric.passed for metric in metrics),
        "page_id": checked_page.page_id,
        "sequence": checked_page.sequence,
        "grammar_id": selected_grammar,
        "page_role": typed_page_role,
        "narrative_role": typed_narrative_role,
        "policy_sha256": policy.canonical_sha256,
        "metrics": metrics,
        "issues": issues,
        "compiled_page_sha256": checked_page.canonical_sha256,
        "layout_program_sha256": checked_page.layout_program.canonical_sha256,
        "content_atom_set_sha256": provenance.content_atom_set_sha256,
        "semantic_content_model_sha256": provenance.semantic_content_model_sha256,
        "page_brief_sha256": provenance.page_brief_sha256,
        "page_brief_set_sha256": provenance.page_brief_set_sha256,
        "visual_direction_plan_sha256": provenance.visual_direction_plan_sha256,
        "asset_manifest_sha256": provenance.asset_manifest_sha256,
        "family_tokens_sha256": provenance.family_tokens_sha256,
        "candidate_id": provenance.candidate_id,
        "revision": provenance.revision,
        "run_id": provenance.run_id,
    }
    return DesignMetricsQAResultV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def evaluate_design_plan_metrics(
    plan: CarouselDesignPlanV4 | Mapping[str, object],
    *,
    page_brief_set: PageBriefSetV4 | Mapping[str, object],
    semantic_content_model: SemanticContentModelV4 | Mapping[str, object],
) -> tuple[DesignMetricsQAResultV4, ...]:
    """Recompute Q2 for every page of one exact compiled design plan."""

    checked_plan = _coerce(CarouselDesignPlanV4, plan, "carousel design plan")
    checked_set = _coerce(PageBriefSetV4, page_brief_set, "page brief set")
    checked_semantic = _coerce(
        SemanticContentModelV4,
        semantic_content_model,
        "semantic content model",
    )
    if tuple(page.page_id for page in checked_plan.pages) != tuple(
        brief.page_id for brief in checked_set.pages
    ):
        raise DesignMetricsInvariantError("design plan and page brief set order does not match")
    return tuple(
        evaluate_page_metrics(
            page,
            page_brief_set=checked_set,
            semantic_content_model=checked_semantic,
        )
        for page in checked_plan.pages
    )


__all__ = [
    "CANVAS_HEIGHT_V4",
    "CANVAS_WIDTH_V4",
    "DesignMetricsInvariantError",
    "QualityPolicyV4",
    "derive_page_role_v4",
    "evaluate_design_plan_metrics",
    "evaluate_page_metrics",
    "get_quality_policy",
    "threshold_for_metric_v4",
]
