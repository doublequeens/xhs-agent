"""Strict durable contracts for bounded v4 visual revisions.

This module intentionally carries structural references only.  It is the
boundary between hard-QA evidence and a repair route, so it never persists
visible copy, prompts, provider details, licences, provenance, or paths.
"""

from __future__ import annotations

import re
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from src.schemas.v4.content import canonical_sha256_v4
from src.schemas.v4.direction import AuthoringIssueCodeV4
from src.schemas.v4.layout import ImplementedGrammarIDV4
from src.schemas.v4.quality import QUALITY_ISSUE_CODES_V4
from src.schemas.v4.rendering import RENDER_ISSUE_CODES_V4
from src.schemas.v4.semantic import SEMANTIC_ISSUE_CODES_V4


REVISION_LAYERS_V4 = (
    "SEMANTIC", "AUTHORING", "ASSET", "COMPOSITION", "LAYOUT", "RENDER", "AESTHETIC",
)
RevisionLayerV4 = Literal[
    "SEMANTIC", "AUTHORING", "ASSET", "COMPOSITION", "LAYOUT", "RENDER", "AESTHETIC",
]
REVISION_OPERATIONS_V4 = ("REBUILD_SEMANTIC", "REFLOW", "CHANGE_GRAMMAR", "REPAGINATE", "REBIND_ASSET", "RERENDER", "REVIEW_AESTHETIC")
RevisionOperationV4 = Literal[
    "REBUILD_SEMANTIC", "REFLOW", "CHANGE_GRAMMAR", "REPAGINATE", "REBIND_ASSET", "RERENDER", "REVIEW_AESTHETIC",
]
REVISION_NODES_V4 = (
    "V4_SEMANTIC_QA", "V4_AUTHORING_QA", "V4_DESIGN_QA", "V4_RENDER_QA", "V4_VISUAL_CRITIC",
)
RevisionNodeV4 = Literal[
    "V4_SEMANTIC_QA", "V4_AUTHORING_QA", "V4_DESIGN_QA", "V4_RENDER_QA", "V4_VISUAL_CRITIC",
]
_AESTHETIC_CODES = ("AESTHETIC_REVIEW_FAILED",)
REVISION_FAILURE_CODES_V4 = tuple(
    sorted(set(SEMANTIC_ISSUE_CODES_V4 + get_args(AuthoringIssueCodeV4) + QUALITY_ISSUE_CODES_V4 + RENDER_ISSUE_CODES_V4 + _AESTHETIC_CODES))
)
RevisionFailureCodeV4 = Literal[*REVISION_FAILURE_CODES_V4]

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_FORBIDDEN = re.compile(
    r"(?:provider|provenance|license|prompt|visible|copy|source|path|api[_ -]?key|secret|password|https?://|(?:^|[/\\])(?:users|private|home|tmp)(?:[/\\]))",
    re.IGNORECASE,
)


def _sha(value: str, name: str) -> str:
    if type(value) is not str or not _HASH_RE.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase sha256")
    return value


def _ref(value: str, name: str) -> str:
    if type(value) is not str or not _REF_RE.fullmatch(value) or _FORBIDDEN.search(value):
        raise ValueError(f"{name} must be a sanitized structural reference")
    return value


def _unique(values: tuple[str, ...], name: str, *, sorted_values: bool = False) -> tuple[str, ...]:
    if not values or len(values) != len(set(values)):
        raise ValueError(f"{name} must be non-empty and unique")
    if sorted_values and values != tuple(sorted(values)):
        raise ValueError(f"{name} must be in canonical sorted order")
    return values


class _FrozenRevisionV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class FailureFingerprintV4(_FrozenRevisionV4):
    """A normalized durable failure identity derived, never caller-digested."""

    node: RevisionNodeV4
    page_id: StrictStr = Field(min_length=1)
    failure_code: RevisionFailureCodeV4
    affected_fragment_ids: tuple[StrictStr, ...] = ()
    geometry_region: StrictStr | None = None
    canonical_sha256: StrictStr

    @classmethod
    def create(
        cls,
        *,
        node: RevisionNodeV4,
        page_id: str,
        failure_code: RevisionFailureCodeV4,
        affected_fragment_ids: tuple[str, ...] | list[str] = (),
        geometry_region: str | None,
    ) -> "FailureFingerprintV4":
        payload = {
            "node": node,
            "page_id": page_id,
            "failure_code": failure_code,
            "affected_fragment_ids": tuple(sorted(set(affected_fragment_ids))),
            "geometry_region": geometry_region,
        }
        return cls(**payload, canonical_sha256=canonical_sha256_v4(payload))

    @field_validator("page_id", "geometry_region")
    @classmethod
    def validate_refs(cls, value: str | None, info) -> str | None:
        return None if value is None else _ref(value, info.field_name)

    @field_validator("affected_fragment_ids")
    @classmethod
    def validate_fragments(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or value != tuple(sorted(value)):
            raise ValueError("affected_fragment_ids must be sorted and unique")
        return tuple(_ref(item, "affected_fragment_ids") for item in value)

    @field_validator("canonical_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha(value, "canonical_sha256")

    @model_validator(mode="after")
    def validate_integrity(self) -> "FailureFingerprintV4":
        payload = self.model_dump(mode="json", exclude={"canonical_sha256"})
        if self.canonical_sha256 != canonical_sha256_v4(payload):
            raise ValueError("failure fingerprint canonical sha256 does not match payload")
        return self

    def validate_contract(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))

class NormalizedFailureV4(_FrozenRevisionV4):
    """Strict non-copy-bearing input to the revision router."""

    fingerprint: FailureFingerprintV4
    page_id: StrictStr = Field(min_length=1)
    failure_code: RevisionFailureCodeV4
    sanitized_evidence: Literal["typed_contract_issue"] = "typed_contract_issue"
    canonical_sha256: StrictStr

    @classmethod
    def from_fingerprint(cls, fingerprint: FailureFingerprintV4) -> "NormalizedFailureV4":
        fingerprint.validate_contract()
        payload = {
            "fingerprint": fingerprint,
            "page_id": fingerprint.page_id,
            "failure_code": fingerprint.failure_code,
            "sanitized_evidence": "typed_contract_issue",
        }
        return cls(**payload, canonical_sha256=canonical_sha256_v4(payload))

    @field_validator("page_id")
    @classmethod
    def validate_page(cls, value: str) -> str:
        return _ref(value, "page_id")

    @field_validator("canonical_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha(value, "canonical_sha256")

    @model_validator(mode="after")
    def validate_integrity(self) -> "NormalizedFailureV4":
        self.fingerprint.validate_contract()
        if (self.page_id, self.failure_code) != (self.fingerprint.page_id, self.fingerprint.failure_code):
            raise ValueError("normalized failure does not match fingerprint")
        payload = self.model_dump(mode="json", exclude={"canonical_sha256"})
        if self.canonical_sha256 != canonical_sha256_v4(payload):
            raise ValueError("normalized failure canonical sha256 does not match payload")
        return self

    def validate_contract(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))


class RevisionInvalidationV4(_FrozenRevisionV4):
    """Exact downstream invalidation; content contracts never occur here."""

    invalidate_whole_set: StrictBool
    rebuild_page_ids: tuple[StrictStr, ...] = ()
    downstream_contracts: tuple[StrictStr, ...] = Field(min_length=1)
    canonical_sha256: StrictStr

    @field_validator("rebuild_page_ids", "downstream_contracts")
    @classmethod
    def validate_values(cls, value: tuple[str, ...], info) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError(f"{info.field_name} must be unique")
        return tuple(_ref(item, info.field_name) for item in value)

    @field_validator("canonical_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha(value, "canonical_sha256")

    @model_validator(mode="after")
    def validate_integrity(self) -> "RevisionInvalidationV4":
        forbidden = {"content_lock", "content_atom_set"}
        if forbidden.intersection(self.downstream_contracts):
            raise ValueError("revision invalidation must not mutate content contracts")
        if self.invalidate_whole_set and self.rebuild_page_ids:
            raise ValueError("whole-set invalidation must not claim a partial rebuild")
        if not self.invalidate_whole_set and not self.rebuild_page_ids:
            raise ValueError("page-level invalidation requires exact page ids")
        payload = self.model_dump(mode="json", exclude={"canonical_sha256"})
        if self.canonical_sha256 != canonical_sha256_v4(payload):
            raise ValueError("revision invalidation canonical sha256 does not match payload")
        return self

    @classmethod
    def create(cls, *, invalidate_whole_set: bool, rebuild_page_ids: tuple[str, ...], downstream_contracts: tuple[str, ...]) -> "RevisionInvalidationV4":
        payload = {
            "invalidate_whole_set": invalidate_whole_set,
            "rebuild_page_ids": rebuild_page_ids,
            "downstream_contracts": downstream_contracts,
        }
        return cls(**payload, canonical_sha256=canonical_sha256_v4(payload))


class ApprovedGrammarAlternativeV4(_FrozenRevisionV4):
    """One page-local, Page-Brief-approved alternative to the current grammar."""

    page_id: StrictStr = Field(min_length=1)
    grammar_id: ImplementedGrammarIDV4
    canonical_sha256: StrictStr

    @classmethod
    def create(cls, *, page_id: str, grammar_id: ImplementedGrammarIDV4) -> "ApprovedGrammarAlternativeV4":
        payload = {"page_id": page_id, "grammar_id": grammar_id}
        return cls(**payload, canonical_sha256=canonical_sha256_v4(payload))

    @field_validator("page_id")
    @classmethod
    def validate_page(cls, value: str) -> str:
        return _ref(value, "page_id")

    @field_validator("canonical_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha(value, "canonical_sha256")

    @model_validator(mode="after")
    def validate_integrity(self) -> "ApprovedGrammarAlternativeV4":
        payload = self.model_dump(mode="json", exclude={"canonical_sha256"})
        if self.canonical_sha256 != canonical_sha256_v4(payload):
            raise ValueError("approved grammar alternative canonical sha256 does not match payload")
        return self


class RevisionRequestV4(_FrozenRevisionV4):
    """One constrained repair command; operations are derived by the router."""

    target_layer: RevisionLayerV4
    affected_pages: tuple[StrictStr, ...] = Field(min_length=1)
    failure_codes: tuple[RevisionFailureCodeV4, ...] = Field(min_length=1)
    failure_fingerprints: tuple[StrictStr, ...] = Field(min_length=1)
    sanitized_evidence: tuple[Literal["typed_contract_issue"], ...] = Field(min_length=1)
    permitted_operations: tuple[RevisionOperationV4, ...] = Field(min_length=1)
    forbidden_operations: tuple[RevisionOperationV4, ...] = ()
    prior_revision_id: StrictStr | None = None
    page_brief_set_sha256: StrictStr | None = None
    carousel_design_plan_sha256: StrictStr | None = None
    approved_grammar_alternatives: tuple[ApprovedGrammarAlternativeV4, ...] = ()
    invalidation: RevisionInvalidationV4
    canonical_sha256: StrictStr

    @field_validator("affected_pages", "failure_codes", "failure_fingerprints", "permitted_operations", "forbidden_operations")
    @classmethod
    def validate_unique(cls, value: tuple, info):
        if info.field_name == "forbidden_operations" and not value:
            return value
        return _unique(value, info.field_name, sorted_values=info.field_name in {"failure_codes", "failure_fingerprints"})

    @field_validator("affected_pages", "prior_revision_id")
    @classmethod
    def validate_refs(cls, value: str | tuple[str, ...] | None, info):
        if value is None:
            return None
        if isinstance(value, tuple):
            return tuple(_ref(item, info.field_name) for item in value)
        return _ref(value, info.field_name)

    @field_validator("failure_fingerprints")
    @classmethod
    def validate_fingerprints(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_sha(item, "failure_fingerprints") for item in value)

    @field_validator("page_brief_set_sha256", "carousel_design_plan_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if value is None:
            return None
        return _sha(value, "routing source sha256")

    @field_validator("canonical_sha256")
    @classmethod
    def validate_canonical_hash(cls, value: str) -> str:
        return _sha(value, "canonical_sha256")

    @model_validator(mode="after")
    def validate_integrity(self) -> "RevisionRequestV4":
        if set(self.permitted_operations).intersection(self.forbidden_operations):
            raise ValueError("revision operations cannot be both permitted and forbidden")
        has_context = self.page_brief_set_sha256 is not None or self.carousel_design_plan_sha256 is not None
        if has_context != bool(self.approved_grammar_alternatives):
            raise ValueError("grammar alternatives require both source hashes and vice versa")
        if has_context and (self.page_brief_set_sha256 is None or self.carousel_design_plan_sha256 is None):
            raise ValueError("grammar alternatives require both source hashes")
        if self.target_layer == "LAYOUT" and self.permitted_operations == ("CHANGE_GRAMMAR",):
            if not self.approved_grammar_alternatives:
                raise ValueError("grammar change requires approved alternatives")
            if {item.page_id for item in self.approved_grammar_alternatives} != set(self.affected_pages):
                raise ValueError("grammar alternatives must cover exactly affected pages")
        elif self.approved_grammar_alternatives:
            raise ValueError("only grammar change may carry approved alternatives")
        for alternative in self.approved_grammar_alternatives:
            alternative.validate_integrity()
        self.invalidation.validate_integrity()
        payload = self.model_dump(mode="json", exclude={"canonical_sha256"})
        if self.canonical_sha256 != canonical_sha256_v4(payload):
            raise ValueError("revision request canonical sha256 does not match payload")
        return self

    def validate_contract(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))

    @property
    def invalidate_whole_set(self) -> bool:
        """Convenience projection for graph routing without duplicate state."""
        return self.invalidation.invalidate_whole_set


class RevisionEventV4(_FrozenRevisionV4):
    """Append-only consumed repair budget for one exact failure occurrence."""

    candidate_id: StrictStr = Field(min_length=1)
    revision_id: StrictStr = Field(min_length=1)
    prior_revision_id: StrictStr | None = None
    fingerprints: tuple[FailureFingerprintV4, ...] = Field(min_length=1)
    target_layer: RevisionLayerV4
    affected_pages: tuple[StrictStr, ...] = Field(min_length=1)
    operation: RevisionOperationV4
    canonical_sha256: StrictStr

    @classmethod
    def create(cls, **payload) -> "RevisionEventV4":
        raw = dict(payload)
        if "fingerprints" not in raw:
            raw["fingerprints"] = (raw.pop("fingerprint"),)
        elif "fingerprint" in raw:
            raise ValueError("revision event cannot mix single and batch fingerprints")
        fingerprints = raw["fingerprints"]
        if not isinstance(fingerprints, tuple) or not fingerprints or any(type(item) is not FailureFingerprintV4 for item in fingerprints):
            raise ValueError("revision event requires exact failure fingerprints")
        for fingerprint in fingerprints:
            fingerprint.validate_contract()
        raw["affected_pages"] = tuple(raw["affected_pages"])
        return cls(**raw, canonical_sha256=canonical_sha256_v4(raw))

    @field_validator("candidate_id", "revision_id", "prior_revision_id")
    @classmethod
    def validate_refs(cls, value: str | None, info) -> str | None:
        return None if value is None else _ref(value, info.field_name)

    @field_validator("affected_pages")
    @classmethod
    def validate_pages(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        _unique(value, "affected_pages")
        return tuple(_ref(item, "affected_pages") for item in value)

    @field_validator("fingerprints")
    @classmethod
    def validate_fingerprints(cls, value: tuple[FailureFingerprintV4, ...]) -> tuple[FailureFingerprintV4, ...]:
        hashes = tuple(item.canonical_sha256 for item in value)
        if hashes != tuple(sorted(hashes)) or len(hashes) != len(set(hashes)):
            raise ValueError("revision event fingerprints must be sorted and unique")
        return value

    @field_validator("canonical_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha(value, "canonical_sha256")

    @model_validator(mode="after")
    def validate_integrity(self) -> "RevisionEventV4":
        for fingerprint in self.fingerprints:
            fingerprint.validate_contract()
        payload = self.model_dump(mode="json", exclude={"canonical_sha256"})
        if self.canonical_sha256 != canonical_sha256_v4(payload):
            raise ValueError("revision event canonical sha256 does not match payload")
        return self

    def validate_contract(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))

    @property
    def fingerprint(self) -> FailureFingerprintV4:
        """Compatibility projection for single-failure callers."""
        return self.fingerprints[0]

    @property
    def failure_fingerprints(self) -> tuple[str, ...]:
        return tuple(item.canonical_sha256 for item in self.fingerprints)


class VisualExecutionInterrupted(RuntimeError):
    """Durable exhaustion signal; callers must checkpoint but cannot reroute it."""

    execution_state = "INTERRUPTED_EXHAUSTED"

    def __init__(self, *, failure_node: RevisionNodeV4, candidate_id: str, revision_id: str | None, repeated_fingerprints: tuple[str, ...], consumed_budget: int, recovery_action: Literal["START_NEW_CANDIDATE"]) -> None:
        self.failure_node = failure_node
        self.candidate_id = _ref(candidate_id, "candidate_id")
        self.revision_id = None if revision_id is None else _ref(revision_id, "revision_id")
        self.repeated_fingerprints = tuple(_sha(item, "repeated_fingerprints") for item in repeated_fingerprints)
        self.consumed_budget = consumed_budget
        self.recovery_action = recovery_action
        super().__init__("v4 visual candidate revision budget exhausted")


__all__ = [
    "ApprovedGrammarAlternativeV4", "FailureFingerprintV4", "NormalizedFailureV4", "RevisionEventV4", "RevisionInvalidationV4", "RevisionRequestV4", "VisualExecutionInterrupted",
    "REVISION_FAILURE_CODES_V4", "REVISION_LAYERS_V4", "REVISION_NODES_V4", "REVISION_OPERATIONS_V4",
]
