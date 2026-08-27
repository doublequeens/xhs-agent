"""Strict, durable contracts for the v4 Final Guard and publish attestation.

The Final Guard attestation embeds the complete terminal Human Review decision
(the reviewed authorization), and the publish attestation binds the same ten
canonical contract files as v3 plus every reviewed PNG byte.  Shadow bundles
reuse the same contract hashes but are marked non-publishable through their own
``shadow-manifest.json`` and never receive a ``publish-attestation.json``.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from src.schemas.v4.content import canonical_sha256_v4
from src.schemas.v4.review import ReviewActionV4

WORKFLOW_VERSION_V4 = "llm_scene_v4"

# The canonical contract files written to every v4 publish package, in the
# same verbatim order as the v3 publisher (``src.publishing.artifacts``).
# ``publish-attestation.json`` is written alongside as the binding attestation.
V4_CANONICAL_CONTRACT_FILES: tuple[str, ...] = (
    "content_atom_set.json",
    "visual_direction_plan.json",
    "asset_manifest.json",
    "carousel_design_plan.json",
    "design_plan_qa.json",
    "render_manifest.json",
    "render_qa.json",
    "visual_critique.json",
    "content_lock.json",
    "final_policy_attestation.json",
)

_SHA = re.compile(r"^[0-9a-f]{64}$")
_APPROVAL_ACTIONS = ("APPROVE", "AESTHETIC_OVERRIDE")


class _FrozenPublishingV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _sha_value(value: str, name: str) -> str:
    if type(value) is not str or not _SHA.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase sha256")
    return value


def _identity_value(value: str, name: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be a non-empty identity")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError(f"{name} contains a control character")
    if any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for char in value
    ):
        raise ValueError(f"{name} must contain only ASCII letters, digits, '.', '_' or '-'")
    return value


def _payload(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude={"canonical_sha256"})


class FinalPolicyAttestationV4(_FrozenPublishingV4):
    """The v4 Final Guard's recomputed, review-bound attestation.

    ``human_review_decision`` embeds the complete terminal decision payload so
    the published bundle carries exactly the reviewed authorization (action,
    every contract/page/asset hash and, for an override, its rationale).  The
    reference digests bind the append-only record and the external workspace
    anchor that authorized it.
    """

    workflow_version: Literal["llm_scene_v4"] = WORKFLOW_VERSION_V4
    attestation_version: Literal["final-policy-v4-v1"] = "final-policy-v4-v1"
    passed: StrictBool
    run_id: StrictStr
    candidate_id: StrictStr
    revision_id: StrictStr
    decision_id: StrictStr
    action: ReviewActionV4
    aesthetic_override: StrictBool
    review_status: StrictStr
    decision_canonical_sha256: StrictStr
    decision_raw_sha256: StrictStr
    decision_reference_canonical_sha256: StrictStr
    workspace_reference_canonical_sha256: StrictStr
    human_review_decision: Mapping[StrictStr, Any]
    canonical_sha256: StrictStr

    @classmethod
    def create(cls, **payload: object) -> "FinalPolicyAttestationV4":
        normalized = dict(payload)
        normalized.setdefault("workflow_version", WORKFLOW_VERSION_V4)
        normalized.setdefault(
            "attestation_version", "final-policy-v4-v1"
        )
        normalized.pop("canonical_sha256", None)
        return cls(**normalized, canonical_sha256=canonical_sha256_v4(normalized))

    @field_validator("run_id", "candidate_id", "revision_id", "decision_id")
    @classmethod
    def identities(cls, value: str, info) -> str:
        return _identity_value(value, info.field_name)

    @field_validator(
        "decision_canonical_sha256",
        "decision_raw_sha256",
        "decision_reference_canonical_sha256",
        "workspace_reference_canonical_sha256",
        "canonical_sha256",
    )
    @classmethod
    def hashes(cls, value: str, info) -> str:
        return _sha_value(value, info.field_name)

    @model_validator(mode="after")
    def integrity(self) -> "FinalPolicyAttestationV4":
        if self.passed is not True:
            raise ValueError("a persisted Final Guard attestation must have passed")
        if self.action not in _APPROVAL_ACTIONS:
            raise ValueError("Final Guard attestation requires a terminal approval action")
        if self.aesthetic_override != (self.action == "AESTHETIC_OVERRIDE"):
            raise ValueError("aesthetic override flag differs from the reviewed action")
        if self.human_review_decision.get("decision_id") != self.decision_id:
            raise ValueError("embedded decision identity differs from the attestation")
        if self.human_review_decision.get("action") != self.action:
            raise ValueError("embedded decision action differs from the attestation")
        if self.human_review_decision.get("canonical_sha256") != self.decision_canonical_sha256:
            raise ValueError("embedded decision hash differs from the attestation")
        if self.review_status != "approved":
            raise ValueError("Final Guard attestation requires an approved review")
        if self.canonical_sha256 != canonical_sha256_v4(_payload(self)):
            raise ValueError("final policy attestation canonical sha256 does not match payload")
        return self


class PublishAttestationV4(_FrozenPublishingV4):
    """Whole-bundle v4 attestation binding every contract and every PNG.

    Contract hashes are the canonical sha256 values the public review-source
    seam (``validate_review_workspace_inputs``) recomputes; ``page_sha256``
    maps package-relative PNG paths (``pages/<NN>-<page_id>.png`` and
    ``contact-sheet.png``) to file-byte sha256 digests.
    """

    workflow_version: Literal["llm_scene_v4"] = WORKFLOW_VERSION_V4
    content_atom_set_sha256: StrictStr
    visual_direction_plan_sha256: StrictStr
    asset_manifest_sha256: StrictStr
    carousel_design_plan_sha256: StrictStr
    design_plan_qa_sha256: StrictStr
    render_manifest_sha256: StrictStr
    render_qa_sha256: StrictStr
    visual_critique_sha256: StrictStr
    content_lock_sha256: StrictStr
    final_policy_attestation_sha256: StrictStr
    page_sha256: Mapping[StrictStr, StrictStr] = Field(min_length=2)

    @field_validator(
        "content_atom_set_sha256",
        "visual_direction_plan_sha256",
        "asset_manifest_sha256",
        "carousel_design_plan_sha256",
        "design_plan_qa_sha256",
        "render_manifest_sha256",
        "render_qa_sha256",
        "visual_critique_sha256",
        "content_lock_sha256",
        "final_policy_attestation_sha256",
    )
    @classmethod
    def contract_hashes(cls, value: str, info) -> str:
        return _sha_value(value, info.field_name)

    @field_validator("page_sha256")
    @classmethod
    def pages(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        if not value:
            raise ValueError("page_sha256 cannot be empty")
        for path, digest in value.items():
            if type(path) is not str or not path or path.startswith("/") or ".." in path:
                raise ValueError("page_sha256 paths must be package-relative")
            _sha_value(digest, "page_sha256 value")
        if "contact-sheet.png" not in value:
            raise ValueError("page_sha256 must cover the contact sheet")
        return value

    @model_validator(mode="after")
    def integrity(self) -> "PublishAttestationV4":
        if not any(path.startswith("pages/") for path in self.page_sha256):
            raise ValueError("page_sha256 must cover the rendered pages")
        return self


class ShadowManifestV4(_FrozenPublishingV4):
    """Non-publish evaluation bundle manifest for one v4 shadow run.

    Carries the same contract/page hashes as a publish attestation for
    comparison tooling, but is explicitly marked ``publishable=False`` with
    ``run_mode=shadow`` and never binds a Final Guard attestation.
    """

    workflow_version: Literal["llm_scene_v4"] = WORKFLOW_VERSION_V4
    manifest_version: Literal["shadow-manifest-v4-v1"] = "shadow-manifest-v4-v1"
    run_mode: Literal["shadow"] = "shadow"
    publishable: Literal[False] = False
    run_id: StrictStr
    candidate_id: StrictStr
    revision_id: StrictStr
    source_run_id: StrictStr | None = None
    contract_sha256: Mapping[StrictStr, StrictStr] = Field(min_length=1)
    page_sha256: Mapping[StrictStr, StrictStr] = Field(min_length=1)
    page_count: StrictInt
    canonical_sha256: StrictStr

    @classmethod
    def create(cls, **payload: object) -> "ShadowManifestV4":
        normalized = dict(payload)
        normalized.setdefault("workflow_version", WORKFLOW_VERSION_V4)
        normalized.setdefault("manifest_version", "shadow-manifest-v4-v1")
        normalized.setdefault("run_mode", "shadow")
        normalized.setdefault("publishable", False)
        normalized.setdefault("source_run_id", None)
        normalized.pop("canonical_sha256", None)
        return cls(**normalized, canonical_sha256=canonical_sha256_v4(normalized))

    @field_validator("run_id", "candidate_id", "revision_id")
    @classmethod
    def identities(cls, value: str, info) -> str:
        return _identity_value(value, info.field_name)

    @field_validator("source_run_id")
    @classmethod
    def source_identity(cls, value: str | None) -> str | None:
        return None if value is None else _identity_value(value, "source_run_id")

    @model_validator(mode="after")
    def integrity(self) -> "ShadowManifestV4":
        if self.publishable is not False or self.run_mode != "shadow":
            raise ValueError("a shadow manifest can never declare itself publishable")
        if self.canonical_sha256 != canonical_sha256_v4(_payload(self)):
            raise ValueError("shadow manifest canonical sha256 does not match payload")
        return self


__all__ = [
    "FinalPolicyAttestationV4",
    "PublishAttestationV4",
    "ShadowManifestV4",
    "ReviewActionV4",
    "V4_CANONICAL_CONTRACT_FILES",
    "WORKFLOW_VERSION_V4",
]
