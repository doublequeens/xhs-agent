"""Durable narrative and page-brief contracts for the isolated v4 path.

The authoring boundary chooses semantic responsibilities only.  It does not
contain visible copy or executable layout.  Coordinates, boxes, HTML, CSS and
DOM are deliberately absent from these models; the later composition and
compiler stages own those concerns.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from src.schemas.v4.content import canonical_sha256_v4
from src.schemas.v4.semantic import SemanticContentModelV4


TEMPLATE_FAMILIES_V4 = (
    "pink_red",
    "deep_teal",
    "soft_pink",
    "coral_impact",
    "green_catalog",
    "white_quote",
)
TemplateFamilyV4 = Literal[
    "pink_red",
    "deep_teal",
    "soft_pink",
    "coral_impact",
    "green_catalog",
    "white_quote",
]

DENSITY_LEVELS_V4 = ("low", "medium", "high")
DensityLevelV4 = Literal["low", "medium", "high"]

ALLOWED_COMPOSITIONS_V4 = (
    "editorial_hero",
    "comparison_grid",
    "step_flow",
    "diagnostic_matrix",
    "checklist",
    "evidence_card",
    "image_annotation",
    "summary_closing",
)
CompositionIDV4 = Literal[
    "editorial_hero",
    "comparison_grid",
    "step_flow",
    "diagnostic_matrix",
    "checklist",
    "evidence_card",
    "image_annotation",
    "summary_closing",
]

ASSET_SOURCES_V4 = (
    "search",
    "generate",
    "either",
    "none",
    "licensed_search",
    "llm_generation",
    "search_then_generate",
    "generate_then_search",
)
AssetSourceV4 = Literal[
    "search",
    "generate",
    "either",
    "none",
    "licensed_search",
    "llm_generation",
    "search_then_generate",
    "generate_then_search",
]
AssetOrientationV4 = Literal["portrait", "landscape", "square", "any"]

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_SYSTEM_COPY = re.compile(
    r"(?:免责声明|仅供参考|示意图|AI\s*(?:生成|生成的|标注|标签)|人工智能\s*(?:生成|标注))",
    re.IGNORECASE,
)
_VISIBLE_COPY_REQUEST = re.compile(
    r"\b(?:add|include|show|render|overlay|embed|write|display|put|insert)"
    r"[^.]{0,32}\b(?:text|caption|label|word|words)\b|"
    r"(?:嵌入|添加|加入|写上|显示|叠加|覆盖).{0,16}(?:文字|文本|标签|字样)",
    re.IGNORECASE,
)


def contains_forbidden_visible_copy(value: str) -> bool:
    """Whether an authoring/asset string requests system or visible copy."""

    return bool(
        _FORBIDDEN_SYSTEM_COPY.search(value)
        or _VISIBLE_COPY_REQUEST.search(value)
    )


def _validate_hash(value: str, field_name: str) -> str:
    if not _HASH_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase sha256")
    return value


def _non_empty_strings(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"{field_name} must contain only non-empty strings")
    return tuple(values)


def canonical_direction_payload_v4(
    value: BaseModel,
    *,
    exclude_none: bool = False,
) -> dict[str, object]:
    """Return the canonical model payload shared by every direction hash."""

    return value.model_dump(
        mode="json",
        exclude={"canonical_sha256"},
        exclude_none=exclude_none,
    )


def canonical_direction_sha256_v4(
    value: BaseModel,
    *,
    exclude_none: bool = False,
) -> str:
    return canonical_sha256_v4(
        canonical_direction_payload_v4(value, exclude_none=exclude_none)
    )


class _FrozenDirectionV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AssetDirectiveV4(_FrozenDirectionV4):
    """A semantic request for an asset; it is not a resolved asset."""

    directive_id: StrictStr = Field(min_length=1)
    page_id: StrictStr = Field(min_length=1)
    role: StrictStr = Field(min_length=1)
    required: StrictBool = False
    preferred_source: AssetSourceV4 = "none"
    fallback_source: AssetSourceV4 = "none"
    # ``source`` is a compatibility spelling accepted at this boundary.  The
    # canonical durable field remains ``preferred_source``.
    source: AssetSourceV4 | None = None
    query_or_prompt: StrictStr | None = None
    negative_constraints: tuple[StrictStr, ...] = ()
    orientation: AssetOrientationV4 = "any"
    min_width: StrictInt = Field(default=1080, ge=1)
    min_height: StrictInt = Field(default=1440, ge=1)
    resolution: tuple[StrictInt, StrictInt] | None = None

    @field_validator("negative_constraints")
    @classmethod
    def validate_negative_constraints(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _non_empty_strings(value, "negative_constraints")

    @field_validator("query_or_prompt")
    @classmethod
    def validate_query_or_prompt(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("query_or_prompt must be non-empty when provided")
        # Asset prompts may say that an image must be text-free, but may not
        # request system labels or put visible copy into the image.
        if value is not None and contains_forbidden_visible_copy(value):
            raise ValueError("asset query_or_prompt contains forbidden system copy")
        return value

    @model_validator(mode="after")
    def validate_source_and_resolution(self) -> "AssetDirectiveV4":
        if self.source is not None:
            if self.preferred_source != "none" and self.preferred_source != self.source:
                raise ValueError("source and preferred_source disagree")
            object.__setattr__(self, "preferred_source", self.source)
        # Keep the compatibility spelling readable on the durable object as
        # well as accepted on input; both spellings are bound to one value.
        object.__setattr__(self, "source", self.preferred_source)

        if self.resolution is not None:
            width, height = self.resolution
            if type(width) is not int or type(height) is not int or width < 1 or height < 1:
                raise ValueError("resolution must contain positive integers")
            object.__setattr__(self, "min_width", width)
            object.__setattr__(self, "min_height", height)
        else:
            object.__setattr__(self, "resolution", (self.min_width, self.min_height))

        if self.preferred_source == "none":
            if self.required:
                raise ValueError("a required asset cannot use source none")
            if self.query_or_prompt is not None:
                raise ValueError("a no-asset directive cannot contain a query or prompt")
            if self.fallback_source != "none":
                raise ValueError("a no-asset directive cannot declare a fallback")
        elif self.query_or_prompt is None:
            raise ValueError("asset directives with a source require query_or_prompt")
        return self

    @property
    def preferred_resolution(self) -> tuple[int, int]:
        return self.min_width, self.min_height

    @property
    def source_strategy(self) -> AssetSourceV4:
        return self.preferred_source

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))


class CarouselNarrativeV4(_FrozenDirectionV4):
    """The one-family, page-count and rhythm decision for a carousel."""

    template_family: TemplateFamilyV4
    page_count: StrictInt = Field(ge=5, le=18)
    beats: tuple[StrictStr, ...] = ()
    density_curve: tuple[DensityLevelV4, ...] = ()
    variation_strategy: StrictStr = Field(min_length=1)
    continuity_strategy: StrictStr = Field(min_length=1)
    art_direction: StrictStr = Field(min_length=1)
    content_atom_set_sha256: StrictStr | None = None
    canonical_sha256: StrictStr

    @field_validator("content_atom_set_sha256")
    @classmethod
    def validate_content_hash(cls, value: str | None) -> str | None:
        return None if value is None else _validate_hash(value, "content_atom_set_sha256")

    @field_validator("beats")
    @classmethod
    def validate_beats(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _non_empty_strings(value, "beats")

    @field_validator("canonical_sha256")
    @classmethod
    def validate_canonical_shape(cls, value: str) -> str:
        return _validate_hash(value, "canonical_sha256")

    @model_validator(mode="after")
    def validate_rhythm_and_hash(self) -> "CarouselNarrativeV4":
        if len(self.beats) != self.page_count:
            raise ValueError("beats length must equal page_count")
        if len(self.density_curve) != self.page_count:
            raise ValueError("density_curve length must equal page_count")
        expected = canonical_direction_sha256_v4(self, exclude_none=True)
        if self.canonical_sha256 != expected:
            raise ValueError("narrative canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))


class PageBriefV4(_FrozenDirectionV4):
    """One page's semantic job and candidate information organizations."""

    page_id: StrictStr = Field(min_length=1)
    sequence: StrictInt = Field(ge=1)
    narrative_role: StrictStr
    fragment_refs: tuple[StrictStr, ...] = ()
    visual_priority: tuple[StrictStr, ...] = ()
    density_budget: DensityLevelV4
    preferred_compositions: tuple[CompositionIDV4, ...] = ()
    forbidden_patterns: tuple[StrictStr, ...] = ()
    asset_directives: tuple[AssetDirectiveV4, ...] = ()
    continuity_with_previous: StrictStr = "none"
    canonical_sha256: StrictStr

    @field_validator("fragment_refs", "visual_priority", "forbidden_patterns")
    @classmethod
    def validate_string_refs(cls, value: tuple[str, ...], info) -> tuple[str, ...]:
        return _non_empty_strings(value, info.field_name)

    @field_validator("preferred_compositions")
    @classmethod
    def validate_compositions(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("preferred_compositions IDs must be unique")
        return _non_empty_strings(value, "preferred_compositions")

    @field_validator("continuity_with_previous")
    @classmethod
    def validate_text_fields(cls, value: str, info) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value

    @field_validator("canonical_sha256")
    @classmethod
    def validate_canonical_shape(cls, value: str) -> str:
        return _validate_hash(value, "canonical_sha256")

    @model_validator(mode="after")
    def validate_hash(self) -> "PageBriefV4":
        expected = canonical_direction_sha256_v4(self)
        if self.canonical_sha256 != expected:
            raise ValueError("page brief canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))


class PageBriefSetV4(_FrozenDirectionV4):
    """Ordered page briefs, with optional family/hash context for QA."""

    page_count: StrictInt
    pages: tuple[PageBriefV4, ...]
    template_family: TemplateFamilyV4 | None = None
    content_atom_set_sha256: StrictStr | None = None
    semantic_content_model_sha256: StrictStr | None = None
    canonical_sha256: StrictStr

    @field_validator("content_atom_set_sha256", "semantic_content_model_sha256")
    @classmethod
    def validate_optional_hash(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _validate_hash(value, info.field_name)

    @field_validator("canonical_sha256")
    @classmethod
    def validate_canonical_shape(cls, value: str) -> str:
        return _validate_hash(value, "canonical_sha256")

    @model_validator(mode="after")
    def validate_page_identity_and_hash(self) -> "PageBriefSetV4":
        page_ids = [page.page_id for page in self.pages]
        if len(page_ids) != len(set(page_ids)):
            raise ValueError("page IDs must be unique")
        expected = canonical_direction_sha256_v4(self, exclude_none=True)
        if self.canonical_sha256 != expected:
            raise ValueError("page brief set canonical sha256 does not match payload")
        return self

    @property
    def asset_directives(self) -> tuple[AssetDirectiveV4, ...]:
        return tuple(
            directive
            for page in self.pages
            for directive in page.asset_directives
        )

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))


class AssetDirectiveDraftV4(_FrozenDirectionV4):
    """Provider-side asset semantics; no hashes or resolved paths."""

    directive_id: StrictStr = Field(min_length=1)
    page_id: StrictStr = Field(min_length=1)
    role: StrictStr = Field(min_length=1)
    required: StrictBool = False
    preferred_source: AssetSourceV4 = "none"
    fallback_source: AssetSourceV4 = "none"
    query_or_prompt: StrictStr | None = None
    negative_constraints: tuple[StrictStr, ...] = ()
    orientation: AssetOrientationV4 = "any"
    min_width: StrictInt = Field(default=1080, ge=1)
    min_height: StrictInt = Field(default=1440, ge=1)
    resolution: tuple[StrictInt, StrictInt] | None = None

    @model_validator(mode="after")
    def validate_draft_resolution(self) -> "AssetDirectiveDraftV4":
        if self.resolution is not None:
            width, height = self.resolution
            if width < 1 or height < 1:
                raise ValueError("resolution must contain positive integers")
        return self


class CarouselNarrativeDraftV4(_FrozenDirectionV4):
    """Untrusted provider narrative; source and canonical hashes are absent."""

    template_family: TemplateFamilyV4
    page_count: StrictInt = Field(ge=5, le=18)
    beats: tuple[StrictStr, ...]
    density_curve: tuple[DensityLevelV4, ...]
    variation_strategy: StrictStr = Field(min_length=1)
    continuity_strategy: StrictStr = Field(min_length=1)
    art_direction: StrictStr = Field(min_length=1)

    @field_validator("beats")
    @classmethod
    def validate_draft_beats(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _non_empty_strings(value, "beats")


class PageBriefDraftV4(_FrozenDirectionV4):
    """Untrusted provider page semantics with references checked locally later."""

    page_id: StrictStr = Field(min_length=1)
    sequence: StrictInt = Field(ge=1)
    narrative_role: StrictStr = Field(min_length=1)
    fragment_refs: tuple[StrictStr, ...] = ()
    visual_priority: tuple[StrictStr, ...] = ()
    density_budget: DensityLevelV4
    preferred_compositions: tuple[CompositionIDV4, ...] = ()
    forbidden_patterns: tuple[StrictStr, ...] = ()
    asset_directives: tuple[AssetDirectiveDraftV4, ...] = ()
    continuity_with_previous: StrictStr = "none"


class PageBriefSetDraftV4(_FrozenDirectionV4):
    pages: tuple[PageBriefDraftV4, ...]


class VisualAuthoringDraftV4(_FrozenDirectionV4):
    """The only structured shape accepted from the authoring provider."""

    narrative: CarouselNarrativeDraftV4
    page_brief_set: PageBriefSetDraftV4


class VisualDirectionPlanV4(_FrozenDirectionV4):
    """Durable v4 authoring result bound to one semantic-model revision."""

    semantic_content_model: SemanticContentModelV4
    narrative: CarouselNarrativeV4
    page_brief_set: PageBriefSetV4
    template_family: TemplateFamilyV4
    page_count: StrictInt = Field(ge=5, le=18)
    content_atom_set_sha256: StrictStr
    semantic_content_model_sha256: StrictStr
    narrative_sha256: StrictStr
    page_brief_set_sha256: StrictStr
    canonical_sha256: StrictStr

    @field_validator(
        "content_atom_set_sha256",
        "semantic_content_model_sha256",
        "narrative_sha256",
        "page_brief_set_sha256",
        "canonical_sha256",
    )
    @classmethod
    def validate_hashes(cls, value: str, info) -> str:
        return _validate_hash(value, info.field_name)

    @model_validator(mode="after")
    def validate_bindings(self) -> "VisualDirectionPlanV4":
        self.semantic_content_model.validate_integrity()
        self.narrative.validate_integrity()
        self.page_brief_set.validate_integrity()
        if self.template_family != self.narrative.template_family:
            raise ValueError("plan family does not match narrative family")
        if (
            self.page_brief_set.template_family is not None
            and self.page_brief_set.template_family != self.template_family
        ):
            raise ValueError("plan family does not match page brief set family")
        if self.page_count != self.narrative.page_count:
            raise ValueError("plan page_count does not match narrative")
        if self.page_count != self.page_brief_set.page_count:
            raise ValueError("plan page_count does not match page brief set")
        if self.page_count != len(self.page_brief_set.pages):
            raise ValueError("plan page_count does not match page brief length")
        if self.content_atom_set_sha256 != self.semantic_content_model.content_atom_set_sha256:
            raise ValueError("plan atom hash does not match semantic model")
        if (
            self.narrative.content_atom_set_sha256 is not None
            and self.narrative.content_atom_set_sha256 != self.content_atom_set_sha256
        ):
            raise ValueError("narrative atom hash does not match plan")
        if self.semantic_content_model_sha256 != self.semantic_content_model.canonical_sha256:
            raise ValueError("plan semantic model hash does not match model")
        if self.narrative_sha256 != self.narrative.canonical_sha256:
            raise ValueError("plan narrative hash does not match narrative")
        if self.page_brief_set_sha256 != self.page_brief_set.canonical_sha256:
            raise ValueError("plan page brief set hash does not match page briefs")
        if (
            self.page_brief_set.content_atom_set_sha256 is not None
            and self.page_brief_set.content_atom_set_sha256
            != self.content_atom_set_sha256
        ):
            raise ValueError("page brief set atom hash does not match plan")
        if (
            self.page_brief_set.semantic_content_model_sha256 is not None
            and self.page_brief_set.semantic_content_model_sha256
            != self.semantic_content_model_sha256
        ):
            raise ValueError("page brief set semantic hash does not match plan")
        expected = canonical_direction_sha256_v4(self)
        if self.canonical_sha256 != expected:
            raise ValueError("visual direction plan canonical sha256 does not match payload")
        return self

    @property
    def carousel_narrative(self) -> CarouselNarrativeV4:
        return self.narrative

    @property
    def semantic_model(self) -> SemanticContentModelV4:
        return self.semantic_content_model

    @property
    def pages(self) -> tuple[PageBriefV4, ...]:
        return self.page_brief_set.pages

    @property
    def asset_directives(self) -> tuple[AssetDirectiveV4, ...]:
        return self.page_brief_set.asset_directives

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))


AuthoringIssueCodeV4 = Literal[
    "SCHEMA_INVALID",
    "FRAGMENT_OWNERSHIP_MISSING",
    "FRAGMENT_OWNERSHIP_UNKNOWN",
    "FRAGMENT_OWNERSHIP_DUPLICATED",
    "PAGE_COUNT_INVALID",
    "PAGE_COUNT_MISMATCH",
    "PAGE_SEQUENCE_INVALID",
    "FAMILY_MISMATCH",
    "HASH_BINDING_MISMATCH",
    "NARRATIVE_ROLE_EMPTY",
    "NARRATIVE_ROLE_REPEATED",
    "PAGE_BRIEF_DUPLICATE_SIGNATURE",
    "DENSITY_CURVE_MISMATCH",
    "DENSITY_CURVE_UNBALANCED",
    "COMPOSITION_REPEATED",
    "VISUAL_PRIORITY_UNKNOWN",
    "NOTES_CANNOT_BE_PRIMARY",
    "ASSET_DIRECTIVE_OWNERSHIP_MISSING",
    "ASSET_DIRECTIVE_OWNERSHIP_UNKNOWN",
    "ASSET_DIRECTIVE_OWNERSHIP_DUPLICATED",
    "ASSET_DIRECTIVE_PAGE_MISMATCH",
    "ASSET_DIRECTIVE_MISMATCH",
    "FORBIDDEN_VISIBLE_COPY",
]


class AuthoringIssueV4(_FrozenDirectionV4):
    """Sanitized deterministic Q1 evidence; never provider output."""

    code: AuthoringIssueCodeV4
    location: StrictStr = Field(min_length=1)
    message: StrictStr = Field(min_length=1)
    evidence: StrictStr = Field(default="deterministic authoring contract check", min_length=1)
    page_id: StrictStr | None = None
    fragment_id: StrictStr | None = None
    directive_id: StrictStr | None = None


class AuthoringQAResultV4(_FrozenDirectionV4):
    """Hash-bound Q1 result whose pass bit cannot be forced by a caller."""

    passed: StrictBool
    issues: tuple[AuthoringIssueV4, ...] = ()
    content_atom_set_sha256: StrictStr
    content_lock_sha256: StrictStr
    semantic_content_model_sha256: StrictStr
    narrative_sha256: StrictStr
    page_brief_set_sha256: StrictStr
    visual_direction_plan_sha256: StrictStr
    canonical_sha256: StrictStr

    @field_validator(
        "content_atom_set_sha256",
        "content_lock_sha256",
        "semantic_content_model_sha256",
        "narrative_sha256",
        "page_brief_set_sha256",
        "visual_direction_plan_sha256",
        "canonical_sha256",
    )
    @classmethod
    def validate_result_hashes(cls, value: str, info) -> str:
        return _validate_hash(value, info.field_name)

    @model_validator(mode="after")
    def validate_result(self) -> "AuthoringQAResultV4":
        if self.passed != (not self.issues):
            raise ValueError("authoring QA passed must be equivalent to issues being empty")
        expected = canonical_direction_sha256_v4(self)
        if self.canonical_sha256 != expected:
            raise ValueError("authoring QA canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))


# Discoverable short aliases mirror Task 7's naming convention without
# coupling v4 callers to v3's VisualDirectionPlan.
CarouselNarrative = CarouselNarrativeV4
PageBrief = PageBriefV4
PageBriefSet = PageBriefSetV4
VisualDirectionPlan = VisualDirectionPlanV4
AssetDirective = AssetDirectiveV4
AssetDirectiveContractV4 = AssetDirectiveV4
AuthoringAssetDirectiveV4 = AssetDirectiveV4
VisualAuthoringDraft = VisualAuthoringDraftV4
AuthoringDraftV4 = VisualAuthoringDraftV4
CarouselNarrativeDraft = CarouselNarrativeDraftV4
PageBriefDraft = PageBriefDraftV4
PageBriefSetDraft = PageBriefSetDraftV4
AuthoringIssue = AuthoringIssueV4
AuthoringQAResult = AuthoringQAResultV4


__all__ = [
    "ALLOWED_COMPOSITIONS_V4",
    "ASSET_SOURCES_V4",
    "AssetDirective",
    "AssetDirectiveContractV4",
    "AssetDirectiveDraftV4",
    "AssetDirectiveV4",
    "AuthoringAssetDirectiveV4",
    "AuthoringDraftV4",
    "AssetOrientationV4",
    "AssetSourceV4",
    "AuthoringIssue",
    "AuthoringIssueCodeV4",
    "AuthoringIssueV4",
    "AuthoringQAResult",
    "AuthoringQAResultV4",
    "CarouselNarrative",
    "CarouselNarrativeDraftV4",
    "CarouselNarrativeDraft",
    "CarouselNarrativeV4",
    "canonical_direction_payload_v4",
    "canonical_direction_sha256_v4",
    "contains_forbidden_visible_copy",
    "CompositionIDV4",
    "DENSITY_LEVELS_V4",
    "DensityLevelV4",
    "PageBrief",
    "PageBriefDraftV4",
    "PageBriefDraft",
    "PageBriefSet",
    "PageBriefSetDraftV4",
    "PageBriefSetDraft",
    "PageBriefSetV4",
    "PageBriefV4",
    "TEMPLATE_FAMILIES_V4",
    "TemplateFamilyV4",
    "VisualAuthoringDraft",
    "VisualAuthoringDraftV4",
    "VisualDirectionPlan",
    "VisualDirectionPlanV4",
]
