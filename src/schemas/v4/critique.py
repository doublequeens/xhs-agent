"""Frozen page-first Q4 aesthetic review contracts.

The evaluator may describe observations, never decide whether a carousel
passes.  This module owns the closed vocabulary and deterministic threshold
calculation so an attractive average cannot conceal a bad page.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator

from src.schemas.v4.content import canonical_sha256_v4


AESTHETIC_QUALITY_LINE_V4 = 70
PAGE_AESTHETIC_DIMENSIONS_V4 = (
    "hierarchy", "readability", "composition", "whitespace", "visual_focus", "asset_integration",
)
SET_AESTHETIC_DIMENSIONS_V4 = ("rhythm", "repetition", "family_consistency", "cover_body_consistency")
PageAestheticDimensionV4 = Literal["hierarchy", "readability", "composition", "whitespace", "visual_focus", "asset_integration"]
SetAestheticDimensionV4 = Literal["rhythm", "repetition", "family_consistency", "cover_body_consistency"]
AestheticDimensionV4 = Literal["hierarchy", "readability", "composition", "whitespace", "visual_focus", "asset_integration", "rhythm", "repetition", "family_consistency", "cover_body_consistency"]
AestheticSeverityV4 = Literal["minor", "major", "critical"]
CriticIndependenceV4 = Literal["independent", "degraded"]

_HASH = re.compile(r"^[0-9a-f]{64}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_PRIVATE = re.compile(r"(?:provider|provenance|licen[cs]e|authoring[_ -]?prompt|generation[_ -]?prompt|api[_ -]?key|secret|password|https?://|(?:^|[/\\])(?:users|private|home|tmp)(?:[/\\]))", re.I)
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_BLIND_METADATA = re.compile(r"(?:provider|provenance|licen[cs]e|prompt|revision|attempt|history|api[_ -]?key|secret|password|https?://)", re.I)
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
# A filename has no whitespace or path separators.  Do not maintain an
# extension allow/deny list: any safe extension is metadata rather than an
# observable visual fact.  A Unicode basename is intentional (a page reviewer
# can receive localized filenames), while the extension remains conservative.
_BARE_PATH_FILE = re.compile(r"^(?:\.[^\s/\\]+|[^\s./\\]+(?:\.[A-Za-z0-9_-]+)+)$", re.I)
_WELL_KNOWN_BARE_FILENAMES = frozenset({
    "readme", "license", "makefile", "dockerfile", "procfile", "gemfile", "rakefile",
    "pipfile", "vagrantfile", "requirements",
})


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _hash(value: str, name: str) -> str:
    if type(value) is not str or not _HASH.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase sha256")
    return value


def _ref(value: str, name: str) -> str:
    if type(value) is not str or not _REF.fullmatch(value) or _PRIVATE.search(value):
        raise ValueError(f"{name} must be a sanitized structural reference")
    return value


def validate_blind_text_v4(value: str, field_name: str) -> str:
    """Accept bounded observable prose, never metadata or path-like text."""
    if type(value) is not str or not value.strip() or len(value) > 240 or "\n" in value or "\r" in value:
        raise ValueError(f"{field_name} is not allowlisted blind text")
    value = value.strip()
    if _BLIND_METADATA.search(value) or _WINDOWS_DRIVE.match(value) or _BARE_PATH_FILE.fullmatch(value) or value.casefold() in _WELL_KNOWN_BARE_FILENAMES or value.startswith(("/", "\\")) or "\\" in value or "/" in value or ".." in value:
        raise ValueError(f"{field_name} is not allowlisted blind text")
    return value


def _payload(model: BaseModel) -> dict[str, object]:
    return model.model_dump(mode="json", exclude={"canonical_sha256"})


class AestheticIssueV4(_Frozen):
    severity: AestheticSeverityV4
    dimension: AestheticDimensionV4
    page_ids: tuple[StrictStr, ...] = Field(min_length=1)
    evidence: StrictStr = Field(min_length=8, max_length=280)
    canonical_sha256: StrictStr

    @classmethod
    def create(cls, *, severity: AestheticSeverityV4, dimension: AestheticDimensionV4, page_ids: tuple[str, ...], evidence: str) -> "AestheticIssueV4":
        payload = {"severity": severity, "dimension": dimension, "page_ids": page_ids, "evidence": evidence}
        return cls(**payload, canonical_sha256=canonical_sha256_v4(payload))

    @field_validator("page_ids")
    @classmethod
    def refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("aesthetic issue pages must be unique")
        return tuple(_ref(item, "page_id") for item in value)

    @field_validator("evidence")
    @classmethod
    def evidence_is_sanitized(cls, value: str) -> str:
        return validate_blind_text_v4(value, "aesthetic issue evidence")

    @field_validator("canonical_sha256")
    @classmethod
    def digest(cls, value: str) -> str:
        return _hash(value, "canonical_sha256")

    @model_validator(mode="after")
    def integrity(self):
        if self.canonical_sha256 != canonical_sha256_v4(_payload(self)):
            raise ValueError("aesthetic issue canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))


class AestheticPageEvaluationV4(_Frozen):
    page_id: StrictStr
    hierarchy: StrictInt = Field(ge=0, le=100)
    readability: StrictInt = Field(ge=0, le=100)
    composition: StrictInt = Field(ge=0, le=100)
    whitespace: StrictInt = Field(ge=0, le=100)
    visual_focus: StrictInt = Field(ge=0, le=100)
    asset_integration: StrictInt = Field(ge=0, le=100)
    issues: tuple[AestheticIssueV4, ...] = ()
    canonical_sha256: StrictStr

    @classmethod
    def create(cls, *, page_id: str, issues: tuple[AestheticIssueV4, ...] = (), **scores: int) -> "AestheticPageEvaluationV4":
        payload = {"page_id": page_id, **scores, "issues": issues}
        return cls(**payload, canonical_sha256=canonical_sha256_v4(payload))

    @field_validator("page_id")
    @classmethod
    def page_ref(cls, value: str) -> str:
        return _ref(value, "page_id")

    @field_validator("canonical_sha256")
    @classmethod
    def digest(cls, value: str) -> str:
        return _hash(value, "canonical_sha256")

    @model_validator(mode="after")
    def integrity(self):
        for issue in self.issues:
            issue.validate_integrity()
            if self.page_id not in issue.page_ids:
                raise ValueError("page evaluation issue must reference its page")
            if issue.dimension not in PAGE_AESTHETIC_DIMENSIONS_V4:
                raise ValueError("page evaluation issue has an invalid page dimension")
        seen = set()
        for issue in self.issues:
            key = issue.canonical_sha256
            if key in seen:
                raise ValueError("duplicate aesthetic issue")
            seen.add(key)
        for dimension in PAGE_AESTHETIC_DIMENSIONS_V4:
            if getattr(self, dimension) < AESTHETIC_QUALITY_LINE_V4 and not any(issue.dimension == dimension for issue in self.issues):
                raise ValueError("sub-quality page score requires same-dimension observable issue")
        if self.canonical_sha256 != canonical_sha256_v4(_payload(self)):
            raise ValueError("page aesthetic evaluation canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))


class AestheticIssueDraftV4(_Frozen):
    """Untrusted model observation; it cannot carry a result digest or pass bit."""
    severity: AestheticSeverityV4
    dimension: AestheticDimensionV4
    page_ids: tuple[StrictStr, ...] = Field(min_length=1)
    evidence: StrictStr = Field(min_length=8, max_length=280)

    @field_validator("page_ids")
    @classmethod
    def refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("aesthetic issue pages must be unique")
        return tuple(_ref(item, "page_id") for item in value)

    @field_validator("evidence")
    @classmethod
    def evidence_is_sanitized(cls, value: str) -> str:
        return validate_blind_text_v4(value, "aesthetic issue evidence")


class AestheticPageDraftV4(_Frozen):
    page_id: StrictStr
    hierarchy: StrictInt = Field(ge=0, le=100)
    readability: StrictInt = Field(ge=0, le=100)
    composition: StrictInt = Field(ge=0, le=100)
    whitespace: StrictInt = Field(ge=0, le=100)
    visual_focus: StrictInt = Field(ge=0, le=100)
    asset_integration: StrictInt = Field(ge=0, le=100)
    issues: tuple[AestheticIssueDraftV4, ...] = ()

    @field_validator("page_id")
    @classmethod
    def page_ref(cls, value: str) -> str:
        return _ref(value, "page_id")


class SetAestheticEvaluationV4(_Frozen):
    rhythm: StrictInt = Field(ge=0, le=100)
    repetition: StrictInt = Field(ge=0, le=100)
    family_consistency: StrictInt = Field(ge=0, le=100)
    cover_body_consistency: StrictInt = Field(ge=0, le=100)
    issues: tuple[AestheticIssueV4, ...] = ()
    canonical_sha256: StrictStr

    @classmethod
    def create(cls, *, issues: tuple[AestheticIssueV4, ...] = (), **scores: int) -> "SetAestheticEvaluationV4":
        payload = {**scores, "issues": issues}
        return cls(**payload, canonical_sha256=canonical_sha256_v4(payload))

    @field_validator("canonical_sha256")
    @classmethod
    def digest(cls, value: str) -> str:
        return _hash(value, "canonical_sha256")

    @model_validator(mode="after")
    def integrity(self):
        for issue in self.issues:
            issue.validate_integrity()
            if issue.dimension not in SET_AESTHETIC_DIMENSIONS_V4:
                raise ValueError("set evaluation issue has an invalid set dimension")
        if len({issue.canonical_sha256 for issue in self.issues}) != len(self.issues):
            raise ValueError("duplicate aesthetic issue")
        for dimension in SET_AESTHETIC_DIMENSIONS_V4:
            if getattr(self, dimension) < AESTHETIC_QUALITY_LINE_V4 and not any(issue.dimension == dimension for issue in self.issues):
                raise ValueError("sub-quality set score requires same-dimension observable issue")
        if self.canonical_sha256 != canonical_sha256_v4(_payload(self)):
            raise ValueError("set aesthetic evaluation canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))


class AestheticSetDraftV4(_Frozen):
    rhythm: StrictInt = Field(ge=0, le=100)
    repetition: StrictInt = Field(ge=0, le=100)
    family_consistency: StrictInt = Field(ge=0, le=100)
    cover_body_consistency: StrictInt = Field(ge=0, le=100)
    issues: tuple[AestheticIssueDraftV4, ...] = ()


def derive_aesthetic_passed(pages: tuple[AestheticPageEvaluationV4, ...], set_evaluation: SetAestheticEvaluationV4) -> bool:
    if any(issue.severity == "critical" for page in pages for issue in page.issues) or any(issue.severity == "critical" for issue in set_evaluation.issues):
        return False
    if any(sum(getattr(page, dimension) < AESTHETIC_QUALITY_LINE_V4 for dimension in PAGE_AESTHETIC_DIMENSIONS_V4) >= 2 for page in pages):
        return False
    return set_evaluation.rhythm >= AESTHETIC_QUALITY_LINE_V4 and set_evaluation.repetition >= AESTHETIC_QUALITY_LINE_V4


class CarouselAestheticEvaluationV4(_Frozen):
    render_manifest_sha256: StrictStr
    render_qa_result_sha256: StrictStr
    page_brief_set_sha256: StrictStr
    semantic_content_model_sha256: StrictStr
    authoring_model_identity: StrictStr | None = None
    evaluator_model_identity: StrictStr | None = None
    critic_independence: CriticIndependenceV4
    pages: tuple[AestheticPageEvaluationV4, ...] = Field(min_length=5, max_length=18)
    set_evaluation: SetAestheticEvaluationV4
    passed: bool
    canonical_sha256: StrictStr

    @classmethod
    def create(cls, *, render_manifest_sha256: str, render_qa_result_sha256: str, page_brief_set_sha256: str, semantic_content_model_sha256: str, authoring_model_identity: str | None, evaluator_model_identity: str | None, pages: tuple[AestheticPageEvaluationV4, ...], set_evaluation: SetAestheticEvaluationV4) -> "CarouselAestheticEvaluationV4":
        author = _model_identity(authoring_model_identity)
        evaluator = _model_identity(evaluator_model_identity)
        payload = {"render_manifest_sha256": render_manifest_sha256, "render_qa_result_sha256": render_qa_result_sha256, "page_brief_set_sha256": page_brief_set_sha256, "semantic_content_model_sha256": semantic_content_model_sha256, "authoring_model_identity": author, "evaluator_model_identity": evaluator, "critic_independence": "independent" if author and evaluator and author != evaluator else "degraded", "pages": pages, "set_evaluation": set_evaluation, "passed": derive_aesthetic_passed(pages, set_evaluation)}
        return cls(**payload, canonical_sha256=canonical_sha256_v4(payload))

    @field_validator("render_manifest_sha256", "render_qa_result_sha256", "page_brief_set_sha256", "semantic_content_model_sha256", "canonical_sha256")
    @classmethod
    def digests(cls, value: str, info) -> str:
        return _hash(value, info.field_name)

    @field_validator("authoring_model_identity", "evaluator_model_identity")
    @classmethod
    def identities(cls, value: str | None) -> str | None:
        return _model_identity(value)

    @model_validator(mode="after")
    def integrity(self):
        ids = tuple(page.page_id for page in self.pages)
        if len(ids) != len(set(ids)):
            raise ValueError("aesthetic pages must be unique")
        for page in self.pages:
            page.validate_integrity()
        self.set_evaluation.validate_integrity()
        issue_hashes = tuple(issue.canonical_sha256 for page in self.pages for issue in page.issues) + tuple(issue.canonical_sha256 for issue in self.set_evaluation.issues)
        if len(issue_hashes) != len(set(issue_hashes)):
            raise ValueError("duplicate aesthetic issue across critique containers")
        actual = set(ids)
        if any(page_id not in actual for page in self.pages for issue in page.issues for page_id in issue.page_ids) or any(page_id not in actual for issue in self.set_evaluation.issues for page_id in issue.page_ids):
            raise ValueError("aesthetic issue references an unknown page")
        expected_independence = "independent" if self.authoring_model_identity and self.evaluator_model_identity and self.authoring_model_identity != self.evaluator_model_identity else "degraded"
        if self.critic_independence != expected_independence:
            raise ValueError("critic independence must be application-derived")
        if self.passed != derive_aesthetic_passed(self.pages, self.set_evaluation):
            raise ValueError("aesthetic pass must be application-derived")
        if self.canonical_sha256 != canonical_sha256_v4(_payload(self)):
            raise ValueError("carousel aesthetic evaluation canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))


def _model_identity(value: str | None) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError("model identity must be a string or None")
    normalized = value.strip().lower()
    if not normalized:
        return None
    if not _MODEL.fullmatch(normalized) or _PRIVATE.search(normalized):
        raise ValueError("model identity is not sanitized")
    return normalized


class AestheticPagePassV4(_Frozen):
    pages: tuple[AestheticPageDraftV4, ...] = Field(min_length=5, max_length=18)


class AestheticSetPassV4(_Frozen):
    set_evaluation: AestheticSetDraftV4


AestheticCritiqueV4 = CarouselAestheticEvaluationV4

__all__ = [name for name in globals() if name.startswith("Aesthetic") or name.startswith("Carousel") or name.startswith("PAGE_") or name.startswith("SET_") or name in {"CriticIndependenceV4", "derive_aesthetic_passed", "validate_blind_text_v4", "AESTHETIC_QUALITY_LINE_V4"}]
