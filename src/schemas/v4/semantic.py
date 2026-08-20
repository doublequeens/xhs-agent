"""Frozen v4 semantic-content contracts.

The semantic model is deliberately a reference graph over the persisted v4
content atoms.  It is not a second copy of the copy: ``exact_text`` is filled
by the application from an atom slice after the model response has been
validated, and Q0 proves that the value still equals that slice.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator

from src.schemas.v4.content import canonical_sha256_v4


SemanticRoleV4 = Literal[
    "title",
    "cover",
    "heading",
    "paragraph",
    "step",
    "list_item",
    "quote",
    "comparison_label",
    "comparison_value",
    "checklist_item",
    "warning",
    "evidence",
    "closing",
    "note",
    "table_header",
    "table_row",
    "table_cell",
]
SEMANTIC_ROLES_V4 = (
    "title",
    "cover",
    "heading",
    "paragraph",
    "step",
    "list_item",
    "quote",
    "comparison_label",
    "comparison_value",
    "checklist_item",
    "warning",
    "evidence",
    "closing",
    "note",
    "table_header",
    "table_row",
    "table_cell",
)


SemanticIssueCodeV4 = Literal[
    "VISIBLE_TEXT_MUTATED",
    "UNKNOWN_ATOM",
    "UNKNOWN_SOURCE_ATOM",
    "INVALID_BOUNDS",
    "COVERAGE_MISSING",
    "COVERAGE_GAP",
    "COVERAGE_OVERLAP",
    "COVERAGE_DUPLICATE",
    "SEQUENCE_INVALID",
    "PARENT_INVALID",
    "PARENT_CYCLE",
    "GROUP_INVALID",
    "GROUP_ORDER_INVALID",
    "SOURCE_ROLE_MISMATCH",
    "STEP_RELATION_LOST",
    "CHECKLIST_RELATION_LOST",
    "COMPARISON_RELATION_LOST",
    "TABLE_RELATION_LOST",
    "HASH_BINDING_MISMATCH",
]
SEMANTIC_ISSUE_CODES_V4 = (
    "VISIBLE_TEXT_MUTATED",
    "UNKNOWN_ATOM",
    "UNKNOWN_SOURCE_ATOM",
    "INVALID_BOUNDS",
    "COVERAGE_MISSING",
    "COVERAGE_GAP",
    "COVERAGE_OVERLAP",
    "COVERAGE_DUPLICATE",
    "SEQUENCE_INVALID",
    "PARENT_INVALID",
    "PARENT_CYCLE",
    "GROUP_INVALID",
    "GROUP_ORDER_INVALID",
    "SOURCE_ROLE_MISMATCH",
    "STEP_RELATION_LOST",
    "CHECKLIST_RELATION_LOST",
    "COMPARISON_RELATION_LOST",
    "TABLE_RELATION_LOST",
    "HASH_BINDING_MISMATCH",
)


def _validate_sha(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase sha256")
    return value


class _FrozenSemanticV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SemanticFragmentV4(_FrozenSemanticV4):
    """One exact Unicode-codepoint slice of one persisted source atom."""

    fragment_id: StrictStr = Field(min_length=1)
    source_atom_id: StrictStr = Field(min_length=1)
    start: StrictInt = Field(ge=0)
    end: StrictInt = Field(gt=0)
    exact_text: StrictStr
    semantic_role: SemanticRoleV4
    parent_fragment_id: StrictStr | None = None
    sequence_index: StrictInt = Field(ge=0)


class SemanticGroupV4(_FrozenSemanticV4):
    """Stable grouping relation over semantic fragment IDs."""

    group_id: StrictStr = Field(min_length=1)
    group_kind: StrictStr = Field(min_length=1)
    fragment_ids: tuple[StrictStr, ...] = ()
    ordering: StrictInt = Field(ge=0)


class SemanticContentModelV4(_FrozenSemanticV4):
    """Persisted semantic model bound to one immutable atom-set revision."""

    content_atom_set_sha256: StrictStr
    fragments: tuple[SemanticFragmentV4, ...] = ()
    groups: tuple[SemanticGroupV4, ...] = ()
    canonical_sha256: StrictStr

    @field_validator("content_atom_set_sha256", "canonical_sha256")
    @classmethod
    def validate_hash_shape(cls, value: str, info) -> str:
        return _validate_sha(value, info.field_name)

    @model_validator(mode="after")
    def validate_canonical_hash(self) -> "SemanticContentModelV4":
        payload = self.model_dump(mode="json", exclude={"canonical_sha256"})
        expected = canonical_sha256_v4(payload)
        if self.canonical_sha256 != expected:
            raise ValueError("semantic content model canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        """Re-run validation for objects restored or changed through model_copy."""

        type(self).model_validate(self.model_dump(mode="python"))


class SemanticModelingDraftFragmentV4(_FrozenSemanticV4):
    """Strict provider response fragment; intentionally contains no visible text."""

    fragment_id: StrictStr = Field(min_length=1)
    source_atom_id: StrictStr = Field(min_length=1)
    start: StrictInt = Field(ge=0)
    end: StrictInt = Field(gt=0)
    semantic_role: SemanticRoleV4
    parent_fragment_id: StrictStr | None = None
    sequence_index: StrictInt = Field(ge=0)


class SemanticModelingDraftGroupV4(_FrozenSemanticV4):
    """Strict provider response group; references only draft fragment IDs."""

    group_id: StrictStr = Field(min_length=1)
    group_kind: StrictStr = Field(min_length=1)
    fragment_ids: tuple[StrictStr, ...] = ()
    ordering: StrictInt = Field(ge=0)


class SemanticModelingDraftV4(_FrozenSemanticV4):
    """Internal LLM response schema with no field that can carry visible text."""

    fragments: tuple[SemanticModelingDraftFragmentV4, ...] = ()
    groups: tuple[SemanticModelingDraftGroupV4, ...] = ()


class SemanticIssueV4(_FrozenSemanticV4):
    """Sanitized, deterministic Q0 evidence; never stores provider output."""

    code: SemanticIssueCodeV4
    location: StrictStr = Field(default="__semantic_model__", min_length=1)
    message: StrictStr = Field(min_length=1)
    evidence: StrictStr = Field(default="deterministic contract evidence", min_length=1)
    fragment_id: StrictStr | None = None
    atom_id: StrictStr | None = None
    group_id: StrictStr | None = None


class SemanticQAResultV4(_FrozenSemanticV4):
    """Hash-bound deterministic Q0 result.

    ``passed`` is not an override: it is required to be exactly equivalent to
    the absence of issues, so callers cannot force a failed hard gate through.
    """

    passed: bool
    issues: tuple[SemanticIssueV4, ...] = ()
    content_atom_set_sha256: StrictStr
    content_lock_sha256: StrictStr
    semantic_content_model_sha256: StrictStr
    canonical_sha256: StrictStr

    @field_validator(
        "content_atom_set_sha256",
        "content_lock_sha256",
        "semantic_content_model_sha256",
        "canonical_sha256",
    )
    @classmethod
    def validate_hash_shape(cls, value: str, info) -> str:
        return _validate_sha(value, info.field_name)

    @model_validator(mode="after")
    def validate_gate_and_hash(self) -> "SemanticQAResultV4":
        if self.passed != (not self.issues):
            raise ValueError("semantic QA passed must be equivalent to issues being empty")
        payload = self.model_dump(mode="json", exclude={"canonical_sha256"})
        expected = canonical_sha256_v4(payload)
        if self.canonical_sha256 != expected:
            raise ValueError("semantic QA canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))


# Friendly aliases keep the isolated v4 module discoverable without importing
# any v3 content contracts.
SemanticFragment = SemanticFragmentV4
SemanticGroup = SemanticGroupV4
SemanticContentModel = SemanticContentModelV4
SemanticModelingDraft = SemanticModelingDraftV4
SemanticQAResult = SemanticQAResultV4
SemanticContentDraftV4 = SemanticModelingDraftV4
SemanticModelingResponseV4 = SemanticModelingDraftV4


__all__ = [
    "SEMANTIC_ISSUE_CODES_V4",
    "SEMANTIC_ROLES_V4",
    "SemanticContentModel",
    "SemanticContentModelV4",
    "SemanticContentDraftV4",
    "SemanticFragment",
    "SemanticFragmentV4",
    "SemanticGroup",
    "SemanticGroupV4",
    "SemanticIssueV4",
    "SemanticModelingDraft",
    "SemanticModelingDraftFragmentV4",
    "SemanticModelingDraftGroupV4",
    "SemanticModelingDraftV4",
    "SemanticModelingResponseV4",
    "SemanticQAResult",
    "SemanticQAResultV4",
    "SemanticRoleV4",
    "SemanticIssueCodeV4",
    "canonical_sha256_v4",
]
