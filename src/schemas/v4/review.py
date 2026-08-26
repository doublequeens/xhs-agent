"""Strict, durable contracts for the isolated v4 Human Review boundary.

The user-facing intake is intentionally a different model from the immutable
decision record.  Intake carries only bounded intent; the node introduced in
Task 16B must derive every identity, route and digest from current artifacts.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_serializer, field_validator, model_validator

from src.schemas.v4.content import canonical_sha256_v4
from src.schemas.visual_style import deep_freeze, deep_thaw


WORKFLOW_VERSION_V4 = "llm_scene_v4"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_PAGE_PATH = re.compile(r"^pages/[0-9]{2}-[A-Za-z0-9_.-]+\.png$")
_WORKSPACE_PATH = re.compile(
    r"^(?:index\.html|contact-sheet\.png|quality-report\.json|revision-diff\.json|"
    r"pages/[0-9]{2}-[A-Za-z0-9_.-]+\.png|"
    r"overlays/[0-9]{2}-[A-Za-z0-9_.-]+\.svg|"
    r"assets/[A-Za-z0-9_.-]+\.(?:png|jpe?g|webp|gif|bin)|"
    r"previous-revision/(?:contact-sheet\.png|pages/[0-9]{2}-[A-Za-z0-9_.-]+\.png))$"
)
_ASSET_PATH = re.compile(r"^assets/[A-Za-z0-9_.-]+\.(?:png|jpe?g|webp|gif|bin)$")
_RFC3339_UTC = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)
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


def _text(
    value: str | None,
    name: str,
    *,
    max_length: int = 1000,
    required: bool = False,
) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{name} is required")
        return None
    if type(value) is not str or not value.strip() or len(value) > max_length or "\x00" in value:
        raise ValueError(f"{name} must be bounded text")
    return value.strip()


def _timestamp(value: str) -> str:
    """Validate and normalize the one timestamp representation used by v4."""

    if type(value) is not str or not _RFC3339_UTC.fullmatch(value):
        raise ValueError("decided_at must be canonical RFC3339 UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError("decided_at must be canonical RFC3339 UTC") from error
    if parsed.tzinfo != timezone.utc:
        raise ValueError("decided_at must be UTC")
    suffix = f".{parsed.microsecond:06d}".rstrip("0") if parsed.microsecond else ""
    return parsed.strftime("%Y-%m-%dT%H:%M:%S") + suffix + "Z"


def _normalized_payload(
    payload: Mapping[str, Any], *, workflow_version: str | None, workspace: bool = False
) -> dict[str, Any]:
    """Normalize factory inputs before calculating a canonical hash."""

    result = dict(payload)
    if workflow_version is not None:
        result.setdefault("workflow_version", workflow_version)
    for name, limit in (("rationale", 1000), ("feedback", 4000), ("visible_copy_payload", 20000)):
        value = result.get(name)
        if isinstance(value, str):
            result[name] = value.strip()
    if "decided_at" in result:
        result["decided_at"] = _timestamp(result["decided_at"])
    if "page_sha256" in result and isinstance(result["page_sha256"], Mapping):
        result["page_sha256"] = dict(sorted(result["page_sha256"].items()))
    if "files" in result and isinstance(result["files"], Mapping):
        result["files"] = dict(sorted(result["files"].items()))
    if workspace:
        for name in ("asset_sha256", "previous_page_sha256"):
            value = result.get(name)
            if value is None:
                result[name] = {}
            elif isinstance(value, Mapping):
                result[name] = dict(sorted(value.items()))
        result.setdefault("previous_revision_id", None)
        result.setdefault("previous_contact_sheet_sha256", None)
        result.setdefault("revision_diff_sha256", None)
    return result


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
        payload = _normalized_payload(
            {"asset_id": asset_id, "asset_sha256": asset_sha256,
             "decision": decision, "rationale": rationale},
            workflow_version=None,
        )
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
        return _text(value, "rationale", max_length=1000)

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
        limits = {"rationale": 1000, "feedback": 4000, "visible_copy_payload": 20000}
        return _text(value, info.field_name, max_length=limits[info.field_name])

    @field_validator("asset_ids")
    @classmethod
    def assets(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("asset_ids must be unique")
        return tuple(_identity(item, "asset_id") for item in value)

    @model_validator(mode="after")
    def action_semantics(self) -> "HumanReviewIntentV4":
        if self.action == "AESTHETIC_OVERRIDE" and self.rationale is None:
            raise ValueError("aesthetic override requires a rationale")
        if self.action == "REQUEST_REVISION" and self.feedback is None:
            raise ValueError("revision request requires feedback")
        if self.action == "REJECT_OR_REPLACE_ASSET" and (not self.asset_ids or self.rationale is None):
            raise ValueError("asset replacement requires asset IDs and rationale")
        if self.action == "VISIBLE_COPY_EDIT" and self.visible_copy_payload is None:
            raise ValueError("visible copy edit requires a payload")
        if self.action in {"APPROVE", "AESTHETIC_OVERRIDE"} and (
            self.feedback is not None or self.asset_ids or self.visible_copy_payload is not None
        ):
            raise ValueError("approval actions cannot carry revision, asset, or copy-edit payloads")
        if self.action == "REQUEST_REVISION" and (self.asset_ids or self.visible_copy_payload is not None):
            raise ValueError("revision requests cannot carry asset or copy-edit payloads")
        if self.action == "REJECT_OR_REPLACE_ASSET" and (
            self.feedback is not None or self.visible_copy_payload is not None
        ):
            raise ValueError("asset replacement cannot carry revision or copy-edit payloads")
        if self.action == "VISIBLE_COPY_EDIT" and (self.feedback is not None or self.asset_ids):
            raise ValueError("copy edits cannot carry revision or asset payloads")
        return self


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
        normalized = _normalized_payload(payload, workflow_version=WORKFLOW_VERSION_V4)
        return cls(**normalized, canonical_sha256=canonical_sha256_v4(normalized))

    @field_validator("decision_id", "run_id", "candidate_id", "revision_id")
    @classmethod
    def identities(cls, value: str, info) -> str:
        return _identity(value, info.field_name)

    @field_validator("decided_at")
    @classmethod
    def timestamp(cls, value: str) -> str:
        return _timestamp(value)

    @field_validator("rationale")
    @classmethod
    def decision_text(cls, value: str | None) -> str | None:
        return _text(value, "rationale", max_length=1000)

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
    asset_sha256: Mapping[StrictStr, StrictStr] = Field(default_factory=dict)
    previous_revision_id: StrictStr | None = None
    previous_contact_sheet_sha256: StrictStr | None = None
    previous_page_sha256: Mapping[StrictStr, StrictStr] = Field(default_factory=dict)
    revision_diff_sha256: StrictStr | None = None
    files: Mapping[StrictStr, StrictStr] = Field(min_length=1)
    canonical_sha256: StrictStr

    @classmethod
    def create(cls, **payload: object) -> "ReviewWorkspaceManifestV4":
        normalized = _normalized_payload(payload, workflow_version=WORKFLOW_VERSION_V4, workspace=True)
        return cls(**normalized, canonical_sha256=canonical_sha256_v4(normalized))

    @field_validator("run_id", "candidate_id", "revision_id")
    @classmethod
    def identities(cls, value: str, info) -> str:
        return _identity(value, info.field_name)

    @field_validator("content_atom_set_sha256", "semantic_content_model_sha256", "narrative_sha256", "page_brief_set_sha256", "visual_direction_plan_sha256", "content_lock_sha256", "asset_manifest_sha256", "carousel_design_plan_sha256",
                     "design_plan_qa_sha256", "render_manifest_sha256", "render_qa_sha256",
                     "visual_critique_sha256", "contact_sheet_sha256", "revision_diff_sha256", "canonical_sha256")
    @classmethod
    def hashes(cls, value: str, info) -> str:
        if value is None and info.field_name == "revision_diff_sha256":
            return None
        return _sha(value, info.field_name)

    @field_validator("page_sha256")
    @classmethod
    def pages(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        validated = HumanReviewDecisionV4.pages(value)
        return deep_freeze(dict(validated))

    @field_validator("asset_sha256")
    @classmethod
    def assets(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        validated: dict[str, str] = {}
        for path, digest in value.items():
            if type(path) is not str or not _ASSET_PATH.fullmatch(path):
                raise ValueError("asset preview paths must be canonical")
            validated[path] = _sha(digest, "asset preview sha256")
        return deep_freeze(dict(sorted(validated.items())))

    @field_validator("previous_revision_id")
    @classmethod
    def previous_identity(cls, value: str | None) -> str | None:
        return None if value is None else _identity(value, "previous_revision_id")

    @field_validator("previous_contact_sheet_sha256")
    @classmethod
    def previous_contact(cls, value: str | None) -> str | None:
        return None if value is None else _sha(value, "previous_contact_sheet_sha256")

    @field_validator("previous_page_sha256")
    @classmethod
    def previous_pages(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        validated = HumanReviewDecisionV4.pages(value) if value else {}
        return deep_freeze(dict(validated))

    @field_validator("files")
    @classmethod
    def workspace_files(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        validated = {}
        for path, digest in value.items():
            if type(path) is not str or not _WORKSPACE_PATH.fullmatch(path):
                raise ValueError("workspace file path is not canonical")
            validated[path] = _sha(digest, "workspace file sha256")
        if tuple(validated) != tuple(sorted(validated)):
            raise ValueError("workspace file paths must be in canonical order")
        return deep_freeze(validated)

    @field_serializer("page_sha256", "files", "asset_sha256", "previous_page_sha256")
    def serialize_mappings(self, value):
        return deep_thaw(value)

    @model_validator(mode="after")
    def integrity(self) -> "ReviewWorkspaceManifestV4":
        required = {"index.html", "contact-sheet.png", "quality-report.json"}
        required.update(self.page_sha256)
        required.update(
            "overlays/" + path.split("/", 1)[1].removesuffix(".png") + ".svg"
            for path in self.page_sha256
        )
        required.update(self.asset_sha256)
        if self.previous_revision_id is None:
            if self.previous_contact_sheet_sha256 or self.previous_page_sha256 or self.revision_diff_sha256:
                raise ValueError("previous revision evidence requires a previous revision identity")
        else:
            if self.previous_contact_sheet_sha256 is None or not self.previous_page_sha256 or self.revision_diff_sha256 is None:
                raise ValueError("previous revision evidence is incomplete")
            required.add("previous-revision/contact-sheet.png")
            required.update("previous-revision/" + path for path in self.previous_page_sha256)
            required.add("revision-diff.json")
        if set(self.files) != required:
            missing = required - set(self.files)
            extra = set(self.files) - required
            raise ValueError(f"workspace manifest file allowlist mismatch: missing={sorted(missing)} extra={sorted(extra)}")
        if self.files.get("contact-sheet.png") != self.contact_sheet_sha256:
            raise ValueError("workspace contact sheet is not hash-bound")
        for path, digest in self.page_sha256.items():
            if self.files.get(path) != digest:
                raise ValueError("workspace page is not hash-bound")
        for path, digest in self.asset_sha256.items():
            if self.files.get(path) != digest:
                raise ValueError("workspace asset preview is not hash-bound")
        if self.previous_revision_id is not None:
            if self.files.get("previous-revision/contact-sheet.png") != self.previous_contact_sheet_sha256:
                raise ValueError("previous contact sheet is not hash-bound")
            for path, digest in self.previous_page_sha256.items():
                if self.files.get("previous-revision/" + path) != digest:
                    raise ValueError("previous page is not hash-bound")
            if self.files.get("revision-diff.json") != self.revision_diff_sha256:
                raise ValueError("revision diff is not hash-bound")
        if self.canonical_sha256 != canonical_sha256_v4(_payload(self)):
            raise ValueError("workspace manifest canonical sha256 does not match payload")
        return self


__all__ = [
    "AssetReviewActionV4", "AssetReviewDecisionV4", "HumanReviewDecisionV4",
    "HumanReviewIntentV4", "ReviewActionV4", "ReviewWorkspaceManifestV4",
    "WORKFLOW_VERSION_V4",
]
