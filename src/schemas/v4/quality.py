"""Immutable Q2 design-quality contracts for the isolated v4 path.

The quality layer is deliberately a reporting contract.  It does not contain
renderer output, provider metadata, prompts or visible copy.  Numeric evidence
is bound to the exact compiled page, the selected versioned policy and all
upstream source hashes so a caller cannot make a stale result look current by
changing a boolean or re-hashing only the outer payload.
"""

from __future__ import annotations

import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, field_validator, model_validator

from src.schemas.v4.content import canonical_sha256_v4
from src.schemas.v4.direction import AuthoringQAResultV4, NarrativeTaskKindV4
from src.schemas.v4.layout import (
    CarouselDesignPlanV4,
    ImplementedGrammarIDV4,
    PageRoleV4,
    TASK_KIND_TO_PAGE_ROLE_V4,
)
from src.schemas.v4.semantic import SemanticQAResultV4


QUALITY_POLICY_VERSION_V4 = "v4-design-quality-policy-1"

QUALITY_METRIC_KINDS_V4 = (
    "safe_margin_compliance",
    "unintended_overlap",
    "minimum_font_size",
    "contrast",
    "whitespace_ratio",
    "largest_text_block_ratio",
    "regional_information_density",
    "alignment_axis_deviation",
    "paired_column_balance",
    "spacing_consistency",
    "heading_body_hierarchy_ratio",
    "visual_center_offset",
    "emphasis_count",
    "line_length",
    "orphan_line",
    "orphan_heading",
    "image_text_area_ratio",
)
QualityMetricKindV4 = Literal[
    "safe_margin_compliance",
    "unintended_overlap",
    "minimum_font_size",
    "contrast",
    "whitespace_ratio",
    "largest_text_block_ratio",
    "regional_information_density",
    "alignment_axis_deviation",
    "paired_column_balance",
    "spacing_consistency",
    "heading_body_hierarchy_ratio",
    "visual_center_offset",
    "emphasis_count",
    "line_length",
    "orphan_line",
    "orphan_heading",
    "image_text_area_ratio",
]

QUALITY_COMPARATORS_V4 = ("gte", "lte", "eq", "within")
QualityComparatorV4 = Literal["gte", "lte", "eq", "within"]
REVISION_TARGETS_V4 = ("layout_reflow", "grammar_fallback", "authoring_repaginate")
RevisionTargetV4 = Literal["layout_reflow", "grammar_fallback", "authoring_repaginate"]

QUALITY_ISSUE_CODES_V4 = (
    "SAFE_MARGIN_NONCOMPLIANT",
    "UNINTENDED_OVERLAP",
    "MINIMUM_FONT_SIZE",
    "LOW_CONTRAST",
    "WHITESPACE_RATIO",
    "LARGEST_TEXT_BLOCK_RATIO",
    "REGIONAL_INFORMATION_DENSITY",
    "ALIGNMENT_AXIS_DEVIATION",
    "PAIRED_COLUMN_BALANCE",
    "SPACING_CONSISTENCY",
    "HEADING_BODY_HIERARCHY_RATIO",
    "VISUAL_CENTER_OFFSET",
    "EMPHASIS_COUNT",
    "LINE_LENGTH",
    "ORPHAN_LINE",
    "ORPHAN_HEADING",
    "IMAGE_TEXT_AREA_RATIO",
    "Q0_FAILED",
    "Q1_FAILED",
)
QualityIssueCodeV4 = Literal[
    "SAFE_MARGIN_NONCOMPLIANT",
    "UNINTENDED_OVERLAP",
    "MINIMUM_FONT_SIZE",
    "LOW_CONTRAST",
    "WHITESPACE_RATIO",
    "LARGEST_TEXT_BLOCK_RATIO",
    "REGIONAL_INFORMATION_DENSITY",
    "ALIGNMENT_AXIS_DEVIATION",
    "PAIRED_COLUMN_BALANCE",
    "SPACING_CONSISTENCY",
    "HEADING_BODY_HIERARCHY_RATIO",
    "VISUAL_CENTER_OFFSET",
    "EMPHASIS_COUNT",
    "LINE_LENGTH",
    "ORPHAN_LINE",
    "ORPHAN_HEADING",
    "IMAGE_TEXT_AREA_RATIO",
    "Q0_FAILED",
    "Q1_FAILED",
]

QUALITY_ISSUE_CODE_BY_METRIC_V4 = {
    "safe_margin_compliance": "SAFE_MARGIN_NONCOMPLIANT",
    "unintended_overlap": "UNINTENDED_OVERLAP",
    "minimum_font_size": "MINIMUM_FONT_SIZE",
    "contrast": "LOW_CONTRAST",
    "whitespace_ratio": "WHITESPACE_RATIO",
    "largest_text_block_ratio": "LARGEST_TEXT_BLOCK_RATIO",
    "regional_information_density": "REGIONAL_INFORMATION_DENSITY",
    "alignment_axis_deviation": "ALIGNMENT_AXIS_DEVIATION",
    "paired_column_balance": "PAIRED_COLUMN_BALANCE",
    "spacing_consistency": "SPACING_CONSISTENCY",
    "heading_body_hierarchy_ratio": "HEADING_BODY_HIERARCHY_RATIO",
    "visual_center_offset": "VISUAL_CENTER_OFFSET",
    "emphasis_count": "EMPHASIS_COUNT",
    "line_length": "LINE_LENGTH",
    "orphan_line": "ORPHAN_LINE",
    "orphan_heading": "ORPHAN_HEADING",
    "image_text_area_ratio": "IMAGE_TEXT_AREA_RATIO",
}

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ZERO_SHA256 = "0" * 64
_SANITIZED_FORBIDDEN = re.compile(
    r"(?:provider|provenance|license|prompt|source|internal|path|api[_ -]?key|secret|password|"
    r"(?:^|[/\\])(?:users|private|tmp|home)(?:[/\\])|https?://|asset_id)",
    re.IGNORECASE,
)
_STRUCTURAL_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_CANONICAL_ISSUE_MESSAGES = {
    metric: f"{metric} is outside its typed quality threshold"
    for metric in QUALITY_METRIC_KINDS_V4
}
_CANONICAL_ISSUE_MESSAGES.update(
    {
        "Q0_FAILED": "semantic QA failed",
        "Q1_FAILED": "authoring QA failed",
    }
)


def _sha(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase sha256")
    return value


def _finite(value: float, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{field_name} must be finite")
    return float(value)


class _FrozenQualityV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class DesignMetricEvidenceV4(_FrozenQualityV4):
    """One deterministic metric and its policy-bound numeric evidence."""

    metric: QualityMetricKindV4
    page_id: StrictStr = Field(min_length=1)
    actual: StrictFloat
    threshold: StrictFloat
    comparator: QualityComparatorV4
    passed: StrictBool
    policy_sha256: StrictStr
    region_id: StrictStr | None = None
    element_id: StrictStr | None = None
    fragment_ref: StrictStr | None = None
    canonical_sha256: StrictStr

    @field_validator("actual", "threshold")
    @classmethod
    def validate_numbers(cls, value: float, info) -> float:
        return _finite(value, info.field_name)

    @field_validator("policy_sha256", "canonical_sha256")
    @classmethod
    def validate_hashes(cls, value: str, info) -> str:
        return _sha(value, info.field_name)

    @field_validator("page_id", "region_id", "element_id", "fragment_ref")
    @classmethod
    def validate_refs(cls, value: str | None, info) -> str | None:
        if value is not None and (
            not value.strip()
            or not _STRUCTURAL_REF_RE.fullmatch(value)
            or _SANITIZED_FORBIDDEN.search(value)
        ):
            raise ValueError(f"{info.field_name} must be a structural reference")
        return value

    @model_validator(mode="after")
    def validate_result_and_hash(self) -> "DesignMetricEvidenceV4":
        if self.comparator == "gte":
            expected = self.actual >= self.threshold
        elif self.comparator == "lte":
            expected = self.actual <= self.threshold
        elif self.comparator == "eq":
            expected = math.isclose(self.actual, self.threshold, rel_tol=0.0, abs_tol=1e-9)
        else:
            expected = self.actual <= self.threshold
        if self.passed != expected:
            raise ValueError("metric passed must be derived from actual, threshold and comparator")
        payload = self.model_dump(mode="json", exclude={"canonical_sha256"})
        if self.canonical_sha256 != canonical_sha256_v4(payload):
            raise ValueError("metric evidence canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))


class DesignQualityIssueV4(_FrozenQualityV4):
    """Closed, actionable and sanitized evidence for one metric miss."""

    code: QualityIssueCodeV4
    metric: QualityMetricKindV4 | None = None
    page_id: StrictStr = Field(min_length=1)
    actual: StrictFloat = 0.0
    threshold: StrictFloat = 0.0
    comparator: QualityComparatorV4 = "eq"
    revision_target: RevisionTargetV4
    message: StrictStr = Field(min_length=1, max_length=160)
    region_id: StrictStr | None = None
    element_id: StrictStr | None = None
    fragment_ref: StrictStr | None = None
    policy_sha256: StrictStr | None = None
    canonical_sha256: StrictStr

    @field_validator("actual", "threshold")
    @classmethod
    def validate_issue_numbers(cls, value: float, info) -> float:
        return _finite(value, info.field_name)

    @field_validator("policy_sha256", "canonical_sha256")
    @classmethod
    def validate_issue_hashes(cls, value: str | None, info) -> str | None:
        return None if value is None else _sha(value, info.field_name)

    @field_validator("message")
    @classmethod
    def sanitize_message(cls, value: str) -> str:
        if _SANITIZED_FORBIDDEN.search(value):
            raise ValueError("quality issue message contains forbidden sensitive evidence")
        return " ".join(value.split())

    @field_validator("page_id", "region_id", "element_id", "fragment_ref")
    @classmethod
    def validate_issue_refs(cls, value: str | None, info) -> str | None:
        if value is not None and (
            not value.strip()
            or not _STRUCTURAL_REF_RE.fullmatch(value)
            or _SANITIZED_FORBIDDEN.search(value)
        ):
            raise ValueError(f"{info.field_name} must be a structural reference")
        return value

    @model_validator(mode="after")
    def validate_issue_hash(self) -> "DesignQualityIssueV4":
        if self.code not in {"Q0_FAILED", "Q1_FAILED"} and self.metric is None:
            raise ValueError("metric issues must identify a metric kind")
        if self.code in {"Q0_FAILED", "Q1_FAILED"} and self.metric is not None:
            raise ValueError("aggregate gate issues cannot carry a metric kind")
        expected_message = _CANONICAL_ISSUE_MESSAGES.get(self.metric or self.code)
        allowed_messages = {
            expected_message,
            f"{self.metric} is below the typed threshold" if self.metric else None,
            f"{self.metric} is above the typed threshold" if self.metric else None,
            f"{self.metric} exceeds the typed threshold" if self.metric else None,
            (
                f"{self.metric.replace('_', ' ')} is below the typed threshold"
                if self.metric
                else None
            ),
            (
                f"{self.metric.replace('_', ' ')} is above the typed threshold"
                if self.metric
                else None
            ),
            (
                f"{self.metric.replace('_', ' ')} exceeds the typed threshold"
                if self.metric
                else None
            ),
            (
                f"{self.metric.replace('_', ' ')} is outside the typed quality threshold"
                if self.metric
                else None
            ),
            (
                f"{self.metric.replace('_', ' ')} is below the typed quality threshold"
                if self.metric
                else None
            ),
            (
                f"{self.metric.replace('_', ' ')} is above the typed quality threshold"
                if self.metric
                else None
            ),
        }
        if expected_message is None or self.message not in allowed_messages:
            raise ValueError("quality issue message is not the canonical sanitized message")
        payload = self.model_dump(mode="json", exclude={"canonical_sha256"})
        if self.canonical_sha256 != canonical_sha256_v4(payload):
            raise ValueError("quality issue canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))


class DesignMetricsQAResultV4(_FrozenQualityV4):
    """Hash-bound Q2 result for exactly one compiled page."""

    passed: StrictBool
    page_id: StrictStr = Field(min_length=1)
    sequence: StrictInt = Field(ge=1)
    grammar_id: ImplementedGrammarIDV4
    page_role: PageRoleV4
    narrative_role: NarrativeTaskKindV4
    policy_sha256: StrictStr
    metrics: tuple[DesignMetricEvidenceV4, ...] = Field(min_length=len(QUALITY_METRIC_KINDS_V4))
    issues: tuple[DesignQualityIssueV4, ...] = ()
    compiled_page_sha256: StrictStr
    layout_program_sha256: StrictStr
    content_atom_set_sha256: StrictStr
    semantic_content_model_sha256: StrictStr
    page_brief_sha256: StrictStr
    page_brief_set_sha256: StrictStr
    visual_direction_plan_sha256: StrictStr
    asset_manifest_sha256: StrictStr
    family_tokens_sha256: StrictStr
    candidate_id: StrictStr = Field(min_length=1)
    revision: StrictInt = Field(ge=0)
    run_id: StrictStr = Field(min_length=1)
    canonical_sha256: StrictStr

    @field_validator(
        "policy_sha256",
        "compiled_page_sha256",
        "layout_program_sha256",
        "content_atom_set_sha256",
        "semantic_content_model_sha256",
        "page_brief_sha256",
        "page_brief_set_sha256",
        "visual_direction_plan_sha256",
        "asset_manifest_sha256",
        "family_tokens_sha256",
        "canonical_sha256",
    )
    @classmethod
    def validate_result_hashes(cls, value: str, info) -> str:
        return _sha(value, info.field_name)

    @model_validator(mode="after")
    def validate_page_result(self) -> "DesignMetricsQAResultV4":
        if len({metric.metric for metric in self.metrics}) != len(self.metrics):
            raise ValueError("Q2 metric kinds must be unique per page")
        if {metric.metric for metric in self.metrics} != set(QUALITY_METRIC_KINDS_V4):
            raise ValueError("Q2 page result must include the complete metric set")
        for metric in self.metrics:
            metric.validate_integrity()
            if metric.page_id != self.page_id or metric.policy_sha256 != self.policy_sha256:
                raise ValueError("Q2 metric evidence is not bound to this page or policy")
        failed_metrics = {metric.metric for metric in self.metrics if not metric.passed}
        if len(self.issues) != len(failed_metrics) or {
            issue.metric for issue in self.issues
        } != failed_metrics:
            raise ValueError("every failed Q2 metric must have exactly one actionable issue")
        for issue in self.issues:
            issue.validate_integrity()
            if issue.page_id != self.page_id:
                raise ValueError("Q2 issue page binding does not match page result")
            if issue.policy_sha256 != self.policy_sha256:
                raise ValueError("Q2 issue policy binding does not match page result")
            matching = next(metric for metric in self.metrics if metric.metric == issue.metric)
            if (
                issue.code != QUALITY_ISSUE_CODE_BY_METRIC_V4[matching.metric]
                or issue.actual != matching.actual
                or issue.threshold != matching.threshold
                or issue.comparator != matching.comparator
                or issue.region_id != matching.region_id
                or issue.element_id != matching.element_id
                or issue.fragment_ref != matching.fragment_ref
            ):
                raise ValueError("Q2 issue evidence does not match its failed metric")
        expected_passed = not self.issues and all(metric.passed for metric in self.metrics)
        if self.passed != expected_passed:
            raise ValueError("Q2 page passed must be derived from metrics and issues")
        payload = self.model_dump(mode="json", exclude={"canonical_sha256"})
        if self.canonical_sha256 != canonical_sha256_v4(payload):
            raise ValueError("Q2 page result canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))

    @property
    def page_metrics(self) -> tuple[DesignMetricEvidenceV4, ...]:
        return self.metrics


class DesignPlanQAResultV4(_FrozenQualityV4):
    """Standalone durable aggregate of Q0, Q1, exact Q2 pages and design plan."""

    passed: StrictBool
    semantic_qa: SemanticQAResultV4
    authoring_qa: AuthoringQAResultV4
    page_metrics: tuple[DesignMetricsQAResultV4, ...] = Field(min_length=5, max_length=18)
    carousel_design_plan: CarouselDesignPlanV4
    issues: tuple[DesignQualityIssueV4, ...] = ()
    content_atom_set_sha256: StrictStr
    content_lock_sha256: StrictStr
    semantic_content_model_sha256: StrictStr
    narrative_sha256: StrictStr
    page_brief_set_sha256: StrictStr
    visual_direction_plan_sha256: StrictStr
    asset_manifest_sha256: StrictStr
    family_tokens_sha256: StrictStr
    candidate_id: StrictStr = Field(min_length=1)
    revision: StrictInt = Field(ge=0)
    run_id: StrictStr = Field(min_length=1)
    canonical_sha256: StrictStr

    @field_validator(
        "content_atom_set_sha256",
        "content_lock_sha256",
        "semantic_content_model_sha256",
        "narrative_sha256",
        "page_brief_set_sha256",
        "visual_direction_plan_sha256",
        "asset_manifest_sha256",
        "family_tokens_sha256",
        "canonical_sha256",
    )
    @classmethod
    def validate_aggregate_hashes(cls, value: str, info) -> str:
        return _sha(value, info.field_name)

    @model_validator(mode="after")
    def validate_aggregate(self) -> "DesignPlanQAResultV4":
        self.semantic_qa.validate_integrity()
        self.authoring_qa.validate_integrity()
        self.carousel_design_plan.validate_integrity()
        for page in self.page_metrics:
            page.validate_integrity()

        q0_hashes = (
            self.semantic_qa.content_atom_set_sha256,
            self.semantic_qa.content_lock_sha256,
            self.semantic_qa.semantic_content_model_sha256,
        )
        q1_hashes = (
            self.authoring_qa.content_atom_set_sha256,
            self.authoring_qa.content_lock_sha256,
            self.authoring_qa.semantic_content_model_sha256,
            self.authoring_qa.narrative_sha256,
            self.authoring_qa.page_brief_set_sha256,
            self.authoring_qa.visual_direction_plan_sha256,
        )
        expected_q0 = (
            self.content_atom_set_sha256,
            self.content_lock_sha256,
            self.semantic_content_model_sha256,
        )
        if q0_hashes != expected_q0 or any(value == _ZERO_SHA256 for value in q0_hashes):
            raise ValueError("Q0 hashes are missing or not bound to aggregate sources")
        expected_q1 = (
            self.content_atom_set_sha256,
            self.content_lock_sha256,
            self.semantic_content_model_sha256,
            self.narrative_sha256,
            self.page_brief_set_sha256,
            self.visual_direction_plan_sha256,
        )
        if q1_hashes != expected_q1 or self.authoring_qa.candidate_sha256 is not None:
            raise ValueError("Q1 durable hashes are missing or candidate preflight leaked")

        plan = self.carousel_design_plan
        plan_hashes = (
            plan.content_atom_set_sha256,
            plan.semantic_content_model_sha256,
            plan.page_brief_set_sha256,
            plan.asset_manifest_sha256,
            plan.family_tokens_sha256,
            plan.visual_direction_plan_sha256,
        )
        expected_plan = (
            self.content_atom_set_sha256,
            self.semantic_content_model_sha256,
            self.page_brief_set_sha256,
            self.asset_manifest_sha256,
            self.family_tokens_sha256,
            self.visual_direction_plan_sha256,
        )
        if plan_hashes != expected_plan:
            raise ValueError("design plan hashes are not transitively bound to aggregate")
        if plan.candidate_id != self.candidate_id or plan.revision != self.revision or plan.run_id != self.run_id:
            raise ValueError("design plan identity does not match aggregate identity")
        page_ids = tuple(page.page_id for page in plan.pages)
        metric_ids = tuple(page.page_id for page in self.page_metrics)
        if metric_ids != page_ids:
            raise ValueError("Q2 page metrics must follow the exact design plan order")
        for metric, plan_page in zip(self.page_metrics, plan.pages):
            if metric.compiled_page_sha256 != plan_page.canonical_sha256:
                raise ValueError("Q2 page metric compiled-page binding is stale")
            if metric.layout_program_sha256 != plan_page.layout_program.canonical_sha256:
                raise ValueError("Q2 page metric layout-program binding is stale")
            if metric.page_brief_sha256 != plan_page.layout_program.page_brief_sha256:
                raise ValueError("Q2 page metric page-brief binding is stale")
            if metric.sequence != plan_page.sequence:
                raise ValueError("Q2 page metric sequence is not plan-bound")
            if metric.grammar_id != plan_page.layout_program.grammar_id:
                raise ValueError("Q2 page metric grammar is not plan-bound")
            if metric.narrative_role != plan_page.layout_program.beat_task_kind:
                raise ValueError("Q2 page metric narrative role is not plan-bound")
            expected_page_role = TASK_KIND_TO_PAGE_ROLE_V4[plan_page.layout_program.beat_task_kind]
            if metric.page_role != expected_page_role:
                raise ValueError("Q2 page metric page role is not plan-bound")
            if (
                metric.content_atom_set_sha256,
                metric.semantic_content_model_sha256,
                metric.page_brief_set_sha256,
                metric.visual_direction_plan_sha256,
                metric.asset_manifest_sha256,
                metric.family_tokens_sha256,
                metric.candidate_id,
                metric.revision,
                metric.run_id,
                ) != (
                self.content_atom_set_sha256,
                self.semantic_content_model_sha256,
                self.page_brief_set_sha256,
                self.visual_direction_plan_sha256,
                self.asset_manifest_sha256,
                self.family_tokens_sha256,
                self.candidate_id,
                self.revision,
                self.run_id,
                ):
                raise ValueError("Q2 page metric has stale or mixed source binding")
            try:
                from src.visual_design.v4.design_metrics import (
                    derive_page_role_v4,
                    get_quality_policy,
                    threshold_for_metric_v4,
                )

                expected_policy = get_quality_policy(
                    plan_page.layout_program.grammar_id,
                    derive_page_role_v4(plan_page.layout_program.beat_task_kind),
                    plan_page.layout_program.beat_task_kind,
                )
            except Exception:
                raise ValueError("Q2 page metric policy cannot be resolved canonically") from None
            if metric.policy_sha256 != expected_policy.canonical_sha256:
                raise ValueError("Q2 page metric policy is not canonical")
            for evidence in metric.metrics:
                if evidence.policy_sha256 != expected_policy.canonical_sha256:
                    raise ValueError("Q2 metric evidence policy is not canonical")
                if abs(
                    evidence.threshold
                    - threshold_for_metric_v4(expected_policy, evidence.metric)
                ) > 1e-9:
                    raise ValueError("Q2 metric evidence threshold is not canonical")
        for issue in self.issues:
            issue.validate_integrity()
        expected_passed = (
            self.semantic_qa.passed
            and self.authoring_qa.passed
            and all(page.passed for page in self.page_metrics)
            and not self.issues
        )
        if self.passed != expected_passed:
            raise ValueError("Design Plan QA passed must be derived from Q0, Q1, Q2 and issues")
        payload = self.model_dump(mode="json", exclude={"canonical_sha256"})
        if self.canonical_sha256 != canonical_sha256_v4(payload):
            raise ValueError("Design Plan QA canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))

__all__ = [
    "DesignMetricEvidenceV4",
    "DesignMetricsQAResultV4",
    "DesignPlanQAResultV4",
    "DesignQualityIssueV4",
    "QUALITY_COMPARATORS_V4",
    "QUALITY_ISSUE_CODES_V4",
    "QUALITY_ISSUE_CODE_BY_METRIC_V4",
    "QUALITY_METRIC_KINDS_V4",
    "QUALITY_POLICY_VERSION_V4",
    "QualityComparatorV4",
    "QualityIssueCodeV4",
    "QualityMetricKindV4",
    "REVISION_TARGETS_V4",
    "RevisionTargetV4",
]
