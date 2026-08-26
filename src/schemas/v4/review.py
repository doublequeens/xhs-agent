"""Strict, durable contracts for the isolated v4 Human Review boundary.

The user-facing intake is intentionally a different model from the immutable
decision record.  Intake carries only bounded intent; the node introduced in
Task 16B must derive every identity, route and digest from current artifacts.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_serializer, field_validator, model_validator

from src.schemas.v4.content import canonical_sha256_v4
from src.schemas.visual_style import deep_freeze, deep_thaw


WORKFLOW_VERSION_V4 = "llm_scene_v4"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_PAGE_PATH = re.compile(r"^pages/[0-9]{2}-[A-Za-z0-9_.-]+\.png$")
_WORKSPACE_PATH = re.compile(r"^(?:index\.html|contact-sheet\.png|quality-report\.json|workspace-manifest\.json|pages/[0-9]{2}-[A-Za-z0-9_.-]+\.png|overlays/[0-9]{2}-[A-Za-z0-9_.-]+\.svg|assets/[A-Za-z0-9_.-]+\.bin|previous-revision/(?:contact-sheet\.png|pages/[0-9]{2}-[A-Za-z0-9_.-]+\.png))$")
_ACTIONS = (
    "APPROVE", "AESTHETIC_OVERRIDE", "REQUEST_REVISION",
    "REJECT_OR_REPLACE_ASSET", "VISIBLE_COPY_EDIT",
)
ReviewActionV4 = Literal[
    "APPROVE", "AESTHETIC_OVERRIDE", "REQUEST_REVISION",
    "REJECT_OR_REPLACE_ASSET", "VISIBLE_COPY_EDIT",
]
AssetReviewActionV4 = Literal["approved", "rejected"]


class _FrozenReviewV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _sha(value: str, name: str) -> str:
    if type(value) is not str or not _SHA.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase sha256")
    return value


def _identity(value: str, name: str) -> str:
    if type(value) is not str or not _IDENTITY.fullmatch(value):
        raise ValueError(f"{name} must be a structural identity")
    return value


def _text(value: str | None, name: str, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{name} is required")
        return None
    if type(value) is not str or not value.strip() or len(value) > 1000 or "\x00" in value:
        raise ValueError(f"{name} must be bounded text")
    return value.strip()


def _payload(model: BaseModel) -> dict[str, object]:
    return model.model_dump(mode="json", exclude={"canonical_sha256"})


class AssetReviewDecisionV4(_FrozenReviewV4):
    """One immutable human outcome for one byte-verified rendered asset."""

    asset_id: StrictStr = Field(min_length=1, max_length=160)
    asset_sha256: StrictStr
    decision: AssetReviewActionV4
    rationale: StrictStr | None = Field(default=None, max_length=1000)
    canonical_sha256: StrictStr

    @classmethod
    def create(cls, *, asset_id: str, asset_sha256: str, decision: AssetReviewActionV4,
               rationale: str | None = None) -> "AssetReviewDecisionV4":
        payload = {"asset_id": asset_id, "asset_sha256": asset_sha256,
                   "decision": decision, "rationale": rationale}
        return cls(**payload, canonical_sha256=canonical_sha256_v4(payload))

    @field_validator("asset_id")
    @classmethod
    def asset_identity(cls, value: str) -> str:
        return _identity(value, "asset_id")

    @field_validator("asset_sha256", "canonical_sha256")
    @classmethod
    def hashes(cls, value: str, info) -> str:
        return _sha(value, info.field_name)

    @field_validator("rationale")
    @classmethod
    def rationale_text(cls, value: str | None) -> str | None:
        return _text(value, "rationale")

    @model_validator(mode="after")
    def integrity(self) -> "AssetReviewDecisionV4":
        if self.decision == "rejected" and self.rationale is None:
            raise ValueError("rejected asset decision requires a rationale")
        if self.canonical_sha256 != canonical_sha256_v4(_payload(self)):
            raise ValueError("asset review decision canonical sha256 does not match payload")
        return self


class HumanReviewIntentV4(_FrozenReviewV4):
    """Untrusted, bounded user intent.  It deliberately has no hash or route fields."""

    action: ReviewActionV4
    rationale: StrictStr | None = Field(default=None, max_length=1000)
    feedback: StrictStr | None = Field(default=None, max_length=4000)
    asset_ids: tuple[StrictStr, ...] = ()
    visible_copy_payload: StrictStr | None = Field(default=None, max_length=20000)

    @field_validator("rationale", "feedback", "visible_copy_payload")
    @classmethod
    def intent_text(cls, value: str | None, info) -> str | None:
        return _text(value, info.field_name)

    @field_validator("asset_ids")
    @classmethod
    def assets(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("asset_ids must be unique")
        return tuple(_identity(item, "asset_id") for item in value)


class HumanReviewDecisionV4(_FrozenReviewV4):
    """Canonical immutable approval/revision record, built only by application code."""

    decision_id: StrictStr
    decided_at: StrictStr
    workflow_version: Literal["llm_scene_v4"] = WORKFLOW_VERSION_V4
    run_id: StrictStr
    candidate_id: StrictStr
    revision_id: StrictStr
    action: ReviewActionV4
    rationale: StrictStr | None = Field(default=None, max_length=1000)
    content_lock_sha256: StrictStr
    asset_manifest_sha256: StrictStr
    carousel_design_plan_sha256: StrictStr
    design_plan_qa_sha256: StrictStr
    render_manifest_sha256: StrictStr
    render_qa_sha256: StrictStr
    visual_critique_sha256: StrictStr
    page_sha256: Mapping[StrictStr, StrictStr] = Field(min_length=1)
    contact_sheet_sha256: StrictStr
    asset_decisions: tuple[AssetReviewDecisionV4, ...] = ()
    canonical_sha256: StrictStr

    @classmethod
    def create(cls, **payload: object) -> "HumanReviewDecisionV4":
        payload.setdefault("workflow_version", WORKFLOW_VERSION_V4)
        return cls(**payload, canonical_sha256=canonical_sha256_v4(payload))

    @field_validator("decision_id", "run_id", "candidate_id", "revision_id")
    @classmethod
    def identities(cls, value: str, info) -> str:
        return _identity(value, info.field_name)

    @field_validator("decided_at")
    @classmethod
    def timestamp(cls, value: str) -> str:
        if not value.endswith("Z") or "T" not in value:
            raise ValueError("decided_at must be an explicit UTC timestamp")
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        except ValueError as error:
            raise ValueError("decided_at must be RFC3339 UTC") from error
        if parsed.tzinfo != timezone.utc:
            raise ValueError("decided_at must be UTC")
        return value

    @field_validator("rationale")
    @classmethod
    def decision_text(cls, value: str | None) -> str | None:
        return _text(value, "rationale")

    @field_validator("content_lock_sha256", "asset_manifest_sha256", "carousel_design_plan_sha256",
                     "design_plan_qa_sha256", "render_manifest_sha256", "render_qa_sha256",
                     "visual_critique_sha256", "contact_sheet_sha256", "canonical_sha256")
    @classmethod
    def hashes(cls, value: str, info) -> str:
        return _sha(value, info.field_name)

    @field_validator("page_sha256")
    @classmethod
    def pages(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        if not value:
            raise ValueError("page_sha256 cannot be empty")
        validated = {}
        for path, digest in value.items():
            if type(path) is not str or not _PAGE_PATH.fullmatch(path):
                raise ValueError("review page paths must be canonical revision-relative POSIX paths")
            validated[path] = _sha(digest, "page sha256")
        if tuple(validated) != tuple(sorted(validated)):
            raise ValueError("review page paths must be in canonical order")
        return deep_freeze(validated)

    @field_serializer("page_sha256")
    def serialize_pages(self, value):
        return deep_thaw(value)

    @model_validator(mode="after")
    def integrity(self) -> "HumanReviewDecisionV4":
        assets = tuple(item.asset_id for item in self.asset_decisions)
        if len(assets) != len(set(assets)):
            raise ValueError("asset decisions must be unique")
        if self.action == "AESTHETIC_OVERRIDE" and self.rationale is None:
            raise ValueError("aesthetic override requires a rationale")
        if self.canonical_sha256 != canonical_sha256_v4(_payload(self)):
            raise ValueError("human review decision canonical sha256 does not match payload")
        return self


class ReviewWorkspaceManifestV4(_FrozenReviewV4):
    """The complete offline workspace, bound to the reviewed source contracts."""

    workflow_version: Literal["llm_scene_v4"] = WORKFLOW_VERSION_V4
    run_id: StrictStr
    candidate_id: StrictStr
    revision_id: StrictStr
    content_atom_set_sha256: StrictStr
    semantic_content_model_sha256: StrictStr
    narrative_sha256: StrictStr
    page_brief_set_sha256: StrictStr
    visual_direction_plan_sha256: StrictStr
    content_lock_sha256: StrictStr
    asset_manifest_sha256: StrictStr
    carousel_design_plan_sha256: StrictStr
    design_plan_qa_sha256: StrictStr
    render_manifest_sha256: StrictStr
    render_qa_sha256: StrictStr
    visual_critique_sha256: StrictStr
    page_sha256: Mapping[StrictStr, StrictStr] = Field(min_length=1)
    contact_sheet_sha256: StrictStr
    files: Mapping[StrictStr, StrictStr] = Field(min_length=1)
    canonical_sha256: StrictStr

    @classmethod
    def create(cls, **payload: object) -> "ReviewWorkspaceManifestV4":
        payload.setdefault("workflow_version", WORKFLOW_VERSION_V4)
        return cls(**payload, canonical_sha256=canonical_sha256_v4(payload))

    @field_validator("run_id", "candidate_id", "revision_id")
    @classmethod
    def identities(cls, value: str, info) -> str:
        return _identity(value, info.field_name)

    @field_validator("content_atom_set_sha256", "semantic_content_model_sha256", "narrative_sha256", "page_brief_set_sha256", "visual_direction_plan_sha256", "content_lock_sha256", "asset_manifest_sha256", "carousel_design_plan_sha256",
                     "design_plan_qa_sha256", "render_manifest_sha256", "render_qa_sha256",
                     "visual_critique_sha256", "contact_sheet_sha256", "canonical_sha256")
    @classmethod
    def hashes(cls, value: str, info) -> str:
        return _sha(value, info.field_name)

    @field_validator("page_sha256")
    @classmethod
    def pages(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        validated = HumanReviewDecisionV4.pages(value)
        return deep_freeze(dict(validated))

    @field_validator("files")
    @classmethod
    def workspace_files(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        validated = {}
        for path, digest in value.items():
            if type(path) is not str or not _WORKSPACE_PATH.fullmatch(path):
                raise ValueError("workspace file path is not canonical")
            validated[path] = _sha(digest, "workspace file sha256")
        return deep_freeze(validated)

    @field_serializer("page_sha256", "files")
    def serialize_mappings(self, value):
        return deep_thaw(value)

    @model_validator(mode="after")
    def integrity(self) -> "ReviewWorkspaceManifestV4":
        if "index.html" not in self.files:
            raise ValueError("workspace manifest must list index.html")
        if set(self.page_sha256) - set(self.files):
            raise ValueError("workspace manifest is missing copied page files")
        if self.files.get("contact-sheet.png") != self.contact_sheet_sha256:
            raise ValueError("workspace contact sheet is not hash-bound")
        if self.canonical_sha256 != canonical_sha256_v4(_payload(self)):
            raise ValueError("workspace manifest canonical sha256 does not match payload")
        return self


__all__ = [
    "AssetReviewActionV4", "AssetReviewDecisionV4", "HumanReviewDecisionV4",
    "HumanReviewIntentV4", "ReviewActionV4", "ReviewWorkspaceManifestV4",
    "WORKFLOW_VERSION_V4",
]
