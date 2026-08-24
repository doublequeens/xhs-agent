"""Frozen, hash-bound render evidence for the isolated v4 path.

The generic renderer is intentionally allowed to use private v3-compatible
objects while it is executing.  This module is the durable boundary on the
other side of that seam: only revision-relative paths, opaque asset refs,
byte hashes, and measured browser evidence may cross it.  Provider metadata,
absolute paths, prompts and provenance are deliberately not modelled.
"""

from __future__ import annotations

import math
import re
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from src.schemas.scene_graph import Box
from src.schemas.v4.content import canonical_sha256_v4, sha256_text_v4


WORKFLOW_VERSION_V4 = "llm_scene_v4"
CANVAS_WIDTH_V4 = 1080
CANVAS_HEIGHT_V4 = 1440
RENDER_BOX_TOLERANCE_PX_V4 = 2.0

RENDER_ISSUE_CODES_V4 = (
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
)
RenderIssueCodeV4 = Literal[
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
]

RENDER_REVISION_TARGETS_V4 = (
    "layout_reflow",
    "font_binding",
    "asset_rebind",
    "renderer_retry",
)
RenderRevisionTargetV4 = Literal[
    "layout_reflow",
    "font_binding",
    "asset_rebind",
    "renderer_retry",
]

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_PATH_RE = re.compile(r"^render/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+$")
_OPAQUE_ASSET_RE = re.compile(r"^v4-asset-[0-9a-f]{64}$")
_PRIVATE_TEXT_RE = re.compile(
    r"(?:provider|provenance|license|prompt|source[_ -]?path|local[_ -]?path|"
    r"api[_ -]?key|secret|password|https?://|(?:^|[/\\])(?:users|private|home|tmp)(?:[/\\]))",
    re.IGNORECASE,
)


def _sha(value: str, field_name: str) -> str:
    if type(value) is not str or not _HASH_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase sha256")
    return value


def _identifier(value: str, field_name: str) -> str:
    if type(value) is not str or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a structural identifier")
    return value


def _finite(value: float, field_name: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be finite")
    value = float(value)
    if not math.isfinite(value) or value < minimum:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return value


def _canonical_payload(value: BaseModel) -> dict[str, object]:
    return value.model_dump(mode="json", exclude={"canonical_sha256"})


class _FrozenRenderingV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ArtifactIdentityV4(_FrozenRenderingV4):
    """The public identity bridge for one immutable revision."""

    run_id: StrictStr = Field(min_length=1)
    candidate_id: StrictStr = Field(min_length=1)
    revision_id: StrictStr = Field(min_length=1)

    @field_validator("run_id", "candidate_id", "revision_id")
    @classmethod
    def validate_components(cls, value: str, info) -> str:
        return _identifier(value, info.field_name)


class RenderGlyphEvidenceV4(_FrozenRenderingV4):
    """Measured glyph visibility for one text element."""

    visible: StrictBool
    loaded: StrictBool
    missing_codepoint_count: StrictInt = Field(ge=0)
    canonical_sha256: StrictStr

    @field_validator("canonical_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha(value, "canonical_sha256")

    @model_validator(mode="after")
    def validate_canonical(self) -> "RenderGlyphEvidenceV4":
        # A visible fallback glyph or a partially missing grapheme is valid
        # measured failure evidence.  Q3 owns the policy decision; this
        # contract must retain the browser observation instead of rejecting it
        # before an actionable RENDER_GLYPH issue can be published.
        if self.canonical_sha256 != canonical_sha256_v4(_canonical_payload(self)):
            raise ValueError("glyph evidence canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))


class RenderFontEvidenceV4(_FrozenRenderingV4):
    """Computed browser font evidence bound to a checked-in font digest."""

    role: Literal["display", "heading", "body", "caption"]
    expected_family: StrictStr = Field(min_length=1)
    computed_family: StrictStr = Field(min_length=1)
    expected_font_sha256: StrictStr
    computed_weight: StrictInt = Field(ge=1, le=1000)
    expected_weight: StrictInt = Field(ge=1, le=1000)
    font_size_px: StrictFloat = Field(gt=0)
    line_height_px: StrictFloat = Field(gt=0)
    font_loaded: StrictBool
    document_fonts_status: Literal["loaded", "loading", "unloaded", "error", "unknown"]
    canonical_sha256: StrictStr

    @field_validator("expected_font_sha256", "canonical_sha256")
    @classmethod
    def validate_hashes(cls, value: str, info) -> str:
        return _sha(value, info.field_name)

    @field_validator("expected_family", "computed_family")
    @classmethod
    def validate_family(cls, value: str, info) -> str:
        if _PRIVATE_TEXT_RE.search(value) or "\n" in value or "\r" in value:
            raise ValueError(f"{info.field_name} contains private data")
        return value

    @model_validator(mode="after")
    def validate_font(self) -> "RenderFontEvidenceV4":
        if self.font_loaded and self.document_fonts_status != "loaded":
            raise ValueError("loaded font evidence must report document.fonts loaded")
        if self.canonical_sha256 != canonical_sha256_v4(_canonical_payload(self)):
            raise ValueError("font evidence canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))


class RenderAssetEvidenceV4(_FrozenRenderingV4):
    """Provider-neutral image load and crop evidence."""

    directive_id: StrictStr = Field(min_length=1)
    asset_ref: StrictStr = Field(pattern=r"^v4-asset-[0-9a-f]{64}$")
    asset_sha256: StrictStr
    fit: Literal["cover", "contain"]
    orientation: Literal["any", "portrait", "landscape", "square"]
    loaded: StrictBool
    natural_width: StrictFloat | None = Field(default=None, ge=0)
    natural_height: StrictFloat | None = Field(default=None, ge=0)
    rendered_width: StrictFloat | None = Field(default=None, ge=0)
    rendered_height: StrictFloat | None = Field(default=None, ge=0)
    box_ratio: StrictFloat = Field(gt=0)
    crop_factor: StrictFloat = Field(ge=1)
    canonical_sha256: StrictStr

    @field_validator("directive_id")
    @classmethod
    def validate_directive(cls, value: str) -> str:
        return _identifier(value, "directive_id")

    @field_validator("asset_sha256", "canonical_sha256")
    @classmethod
    def validate_hashes(cls, value: str, info) -> str:
        return _sha(value, info.field_name)

    @field_validator(
        "natural_width",
        "natural_height",
        "rendered_width",
        "rendered_height",
        "box_ratio",
        "crop_factor",
    )
    @classmethod
    def validate_finite(cls, value, info):
        if value is None:
            return value
        return _finite(value, info.field_name, minimum=0 if info.field_name != "crop_factor" else 1)

    @model_validator(mode="after")
    def validate_asset(self) -> "RenderAssetEvidenceV4":
        if self.loaded and (
            self.natural_width is None
            or self.natural_height is None
            or self.natural_width <= 0
            or self.natural_height <= 0
        ):
            raise ValueError("loaded image evidence requires intrinsic dimensions")
        if self.canonical_sha256 != canonical_sha256_v4(_canonical_payload(self)):
            raise ValueError("asset evidence canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))


class RenderElementEvidenceV4(_FrozenRenderingV4):
    """One measured DOM element, retaining expected and actual geometry."""

    page_id: StrictStr = Field(min_length=1)
    element_id: StrictStr = Field(min_length=1)
    kind: Literal["text", "image", "shape", "line", "icon"]
    content_ref: StrictStr | None = None
    asset_ref: StrictStr | None = None
    expected_text_sha256: StrictStr | None = None
    actual_text_sha256: StrictStr | None = None
    actual_text: StrictStr | None = None
    dom_text_measured: StrictBool = False
    expected_box: Box
    actual_box: Box
    scroll_width: StrictFloat = Field(ge=0)
    scroll_height: StrictFloat = Field(ge=0)
    client_width: StrictFloat = Field(ge=0)
    client_height: StrictFloat = Field(ge=0)
    overflow: StrictBool
    clipped: StrictBool
    computed_font: RenderFontEvidenceV4 | None = None
    glyph: RenderGlyphEvidenceV4 | None = None
    asset: RenderAssetEvidenceV4 | None = None
    line_boxes: tuple[Box, ...] = ()
    canonical_sha256: StrictStr

    @field_validator("page_id", "element_id")
    @classmethod
    def validate_refs(cls, value: str, info) -> str:
        return _identifier(value, info.field_name)

    @field_validator("content_ref")
    @classmethod
    def validate_content_ref(cls, value: str | None) -> str | None:
        return None if value is None else _identifier(value, "content_ref")

    @field_validator("asset_ref")
    @classmethod
    def validate_asset_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _OPAQUE_ASSET_RE.fullmatch(value):
            raise ValueError("asset_ref must be an opaque v4 asset reference")
        return value

    @field_validator(
        "expected_text_sha256",
        "actual_text_sha256",
        "canonical_sha256",
    )
    @classmethod
    def validate_optional_hashes(cls, value: str | None, info) -> str | None:
        return None if value is None else _sha(value, info.field_name)

    @field_validator("scroll_width", "scroll_height", "client_width", "client_height")
    @classmethod
    def validate_geometry_numbers(cls, value: float, info) -> float:
        return _finite(value, info.field_name)

    @model_validator(mode="after")
    def validate_kind_evidence(self) -> "RenderElementEvidenceV4":
        if self.kind == "text":
            if self.content_ref is None or self.expected_text_sha256 is None:
                raise ValueError("text evidence requires content and expected hash")
            if self.actual_text_sha256 is None or self.computed_font is None or self.glyph is None:
                raise ValueError("text evidence requires actual text, font and glyph evidence")
            if self.asset_ref is not None or self.asset is not None:
                raise ValueError("text evidence cannot carry asset evidence")
            if self.actual_text is not None and self.actual_text_sha256 != sha256_text_v4(self.actual_text):
                raise ValueError("text evidence actual text hash does not match")
        elif self.kind == "image":
            if self.asset_ref is None or self.asset is None:
                raise ValueError("image evidence requires an opaque asset binding")
            if self.content_ref is not None or self.computed_font is not None or self.glyph is not None:
                raise ValueError("image evidence cannot carry text evidence")
        else:
            if any(value is not None for value in (self.content_ref, self.asset_ref, self.asset, self.computed_font, self.glyph)):
                raise ValueError("non-text/image evidence contains an unrelated binding")
        if self.canonical_sha256 != canonical_sha256_v4(_canonical_payload(self)):
            raise ValueError("element evidence canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))


class RenderPageEvidenceV4(_FrozenRenderingV4):
    """One immutable page PNG and its complete browser evidence."""

    page_id: StrictStr = Field(min_length=1)
    sequence: StrictInt = Field(ge=1)
    path: StrictStr = Field(min_length=1)
    width: Literal[1080] = CANVAS_WIDTH_V4
    height: Literal[1440] = CANVAS_HEIGHT_V4
    sha256: StrictStr
    elements: tuple[RenderElementEvidenceV4, ...] = Field(min_length=1)
    canonical_sha256: StrictStr

    @field_validator("page_id")
    @classmethod
    def validate_page_id(cls, value: str) -> str:
        return _identifier(value, "page_id")

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if not _PATH_RE.fullmatch(value) or value == "render/contact-sheet.png":
            raise ValueError("render page path must be revision-relative under render/")
        return value

    @field_validator("sha256", "canonical_sha256")
    @classmethod
    def validate_hashes(cls, value: str, info) -> str:
        return _sha(value, info.field_name)

    @model_validator(mode="after")
    def validate_page(self) -> "RenderPageEvidenceV4":
        ids = tuple(element.element_id for element in self.elements)
        if len(ids) != len(set(ids)):
            raise ValueError("render page element IDs must be unique")
        for element in self.elements:
            if element.page_id != self.page_id:
                raise ValueError("render element evidence page binding is stale")
            element.validate_integrity()
        if self.canonical_sha256 != canonical_sha256_v4(_canonical_payload(self)):
            raise ValueError("render page canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))

    @property
    def probes(self) -> tuple[RenderElementEvidenceV4, ...]:
        """Compatibility spelling for Q3 consumers."""

        return self.elements


class RenderManifestV4(_FrozenRenderingV4):
    """Canonical render evidence bound to one exact v4 source graph."""

    workflow_version: Literal["llm_scene_v4"] = WORKFLOW_VERSION_V4
    artifact_identity: ArtifactIdentityV4
    run_id: StrictStr = Field(min_length=1)
    candidate_id: StrictStr = Field(min_length=1)
    revision_id: StrictStr = Field(min_length=1)
    revision: StrictInt = Field(ge=0)
    design_plan_sha256: StrictStr
    design_plan_qa_sha256: StrictStr
    content_atom_set_sha256: StrictStr
    content_lock_sha256: StrictStr
    semantic_content_model_sha256: StrictStr
    narrative_sha256: StrictStr
    page_brief_set_sha256: StrictStr
    visual_direction_plan_sha256: StrictStr
    asset_manifest_sha256: StrictStr
    family_tokens_sha256: StrictStr
    pages: tuple[RenderPageEvidenceV4, ...] = Field(min_length=5, max_length=18)
    contact_sheet_path: StrictStr = "render/contact-sheet.png"
    contact_sheet_sha256: StrictStr
    font_evidence: tuple[RenderFontEvidenceV4, ...] = ()
    canonical_sha256: StrictStr

    @field_validator(
        "design_plan_sha256",
        "design_plan_qa_sha256",
        "content_atom_set_sha256",
        "content_lock_sha256",
        "semantic_content_model_sha256",
        "narrative_sha256",
        "page_brief_set_sha256",
        "visual_direction_plan_sha256",
        "asset_manifest_sha256",
        "family_tokens_sha256",
        "contact_sheet_sha256",
        "canonical_sha256",
    )
    @classmethod
    def validate_hashes(cls, value: str, info) -> str:
        return _sha(value, info.field_name)

    @field_validator("run_id", "candidate_id", "revision_id")
    @classmethod
    def validate_identity_fields(cls, value: str, info) -> str:
        return _identifier(value, info.field_name)

    @field_validator("contact_sheet_path")
    @classmethod
    def validate_contact_path(cls, value: str) -> str:
        if value != "render/contact-sheet.png":
            raise ValueError("contact sheet path is not canonical")
        return value

    @model_validator(mode="after")
    def validate_manifest(self) -> "RenderManifestV4":
        identity = self.artifact_identity
        if (self.run_id, self.candidate_id, self.revision_id) != (
            identity.run_id,
            identity.candidate_id,
            identity.revision_id,
        ):
            raise ValueError("render manifest identity fields do not match artifact identity")
        ids = tuple(page.page_id for page in self.pages)
        sequences = tuple(page.sequence for page in self.pages)
        if sequences != tuple(range(1, len(self.pages) + 1)):
            raise ValueError("render manifest pages must be contiguous and ordered")
        if len(ids) != len(set(ids)):
            raise ValueError("render manifest page IDs must be unique")
        for page in self.pages:
            page.validate_integrity()
        font_keys = tuple((item.role, item.expected_font_sha256) for item in self.font_evidence)
        if len(font_keys) != len(set(font_keys)):
            raise ValueError("render manifest font evidence must be unique")
        for item in self.font_evidence:
            item.validate_integrity()
        if self.canonical_sha256 != canonical_sha256_v4(_canonical_payload(self)):
            raise ValueError("render manifest canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))

    @property
    def page_ids(self) -> tuple[str, ...]:
        return tuple(page.page_id for page in self.pages)


_ISSUE_MESSAGES = {
    code: f"{code.lower().replace('_', ' ')} requires deterministic render review"
    for code in RENDER_ISSUE_CODES_V4
}


class RenderIssueV4(_FrozenRenderingV4):
    """Closed, sanitized Q3 issue evidence."""

    code: RenderIssueCodeV4
    message: StrictStr = Field(min_length=1)
    page_id: StrictStr | None = None
    element_id: StrictStr | None = None
    fragment_ref: StrictStr | None = None
    asset_ref: StrictStr | None = None
    actual: StrictFloat | None = None
    expected: StrictFloat | None = None
    tolerance_px: StrictFloat | None = Field(default=None, ge=0)
    evidence: StrictStr = Field(min_length=1)
    revision_target: RenderRevisionTargetV4
    canonical_sha256: StrictStr

    @field_validator("page_id", "element_id", "fragment_ref")
    @classmethod
    def validate_structural_refs(cls, value: str | None, info) -> str | None:
        return None if value is None else _identifier(value, info.field_name)

    @field_validator("asset_ref")
    @classmethod
    def validate_opaque_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _OPAQUE_ASSET_RE.fullmatch(value):
            raise ValueError("render issue asset ref must be opaque")
        return value

    @field_validator("actual", "expected")
    @classmethod
    def validate_numeric(cls, value: float | None, info) -> float | None:
        return None if value is None else _finite(value, info.field_name)

    @field_validator("evidence")
    @classmethod
    def validate_evidence(cls, value: str) -> str:
        if _PRIVATE_TEXT_RE.search(value) or "\n" in value or "\r" in value:
            raise ValueError("render issue evidence contains private data")
        return value

    @field_validator("canonical_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha(value, "canonical_sha256")

    @model_validator(mode="after")
    def validate_issue(self) -> "RenderIssueV4":
        if self.page_id is None and self.element_id is None and self.fragment_ref is None and self.asset_ref is None:
            raise ValueError("render issue requires a structural location")
        if self.message != _ISSUE_MESSAGES[self.code]:
            raise ValueError("render issue message is not canonical")
        if self.canonical_sha256 != canonical_sha256_v4(_canonical_payload(self)):
            raise ValueError("render issue canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))


class RenderQAResultV4(_FrozenRenderingV4):
    """Hash-bound Q3 result; hard-pass is derived from typed attestations."""

    workflow_version: Literal["llm_scene_v4"] = WORKFLOW_VERSION_V4
    artifact_identity: ArtifactIdentityV4
    render_manifest_sha256: StrictStr
    design_plan_sha256: StrictStr
    design_plan_qa_sha256: StrictStr
    passed: StrictBool
    issues: tuple[RenderIssueV4, ...] = ()
    content_attestation: StrictBool
    geometry_attestation: StrictBool
    font_attestation: StrictBool
    asset_attestation: StrictBool
    bytes_attestation: StrictBool
    canonical_sha256: StrictStr

    @field_validator(
        "render_manifest_sha256",
        "design_plan_sha256",
        "design_plan_qa_sha256",
        "canonical_sha256",
    )
    @classmethod
    def validate_hashes(cls, value: str, info) -> str:
        return _sha(value, info.field_name)

    @model_validator(mode="after")
    def validate_result(self) -> "RenderQAResultV4":
        for issue in self.issues:
            issue.validate_integrity()
        expected = (
            not self.issues
            and self.content_attestation
            and self.geometry_attestation
            and self.font_attestation
            and self.asset_attestation
            and self.bytes_attestation
        )
        if self.passed != expected:
            raise ValueError("render QA passed must be derived from attestations and issues")
        if self.canonical_sha256 != canonical_sha256_v4(_canonical_payload(self)):
            raise ValueError("render QA canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))


# Friendly names for downstream Q3 and review consumers.
RenderArtifactIdentityV4 = ArtifactIdentityV4
RenderPageV4 = RenderPageEvidenceV4
RenderedPageV4 = RenderPageEvidenceV4
RenderElementProbeV4 = RenderElementEvidenceV4
RenderedElementProbeV4 = RenderElementEvidenceV4
FontEvidenceV4 = RenderFontEvidenceV4
FontLoadEvidenceV4 = RenderFontEvidenceV4
GlyphEvidenceV4 = RenderGlyphEvidenceV4
AssetCropEvidenceV4 = RenderAssetEvidenceV4
RenderIssueEvidenceV4 = RenderIssueV4


__all__ = [
    "ArtifactIdentityV4",
    "AssetCropEvidenceV4",
    "FontEvidenceV4",
    "FontLoadEvidenceV4",
    "GlyphEvidenceV4",
    "RENDER_BOX_TOLERANCE_PX_V4",
    "RENDER_ISSUE_CODES_V4",
    "RENDER_REVISION_TARGETS_V4",
    "RenderArtifactIdentityV4",
    "RenderAssetEvidenceV4",
    "RenderElementEvidenceV4",
    "RenderElementProbeV4",
    "RenderFontEvidenceV4",
    "RenderGlyphEvidenceV4",
    "RenderIssueEvidenceV4",
    "RenderIssueV4",
    "RenderManifestV4",
    "RenderPageEvidenceV4",
    "RenderPageV4",
    "RenderedElementProbeV4",
    "RenderedPageV4",
    "RenderQAResultV4",
    "RenderRevisionTargetV4",
    "WORKFLOW_VERSION_V4",
]
