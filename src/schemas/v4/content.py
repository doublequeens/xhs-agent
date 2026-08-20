"""Immutable visible-copy contracts for the isolated ``llm_scene_v4`` path.

The v4 content boundary is deliberately separate from the v3 atomizer.  A
projection keeps the source field and raw code-point span for every visible
unit, while table groups preserve the structural relation that would
otherwise be lost when Markdown syntax is removed.  Every digest in this
module is derived from the complete payload immediately around it; callers
cannot supply a digest for a different payload and still obtain a valid
contract.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SourceFieldV4 = Literal["title", "cover_copy", "content"]
VisibleCopyRoleV4 = Literal[
    "title",
    "cover",
    "heading",
    "paragraph",
    "step",
    "list_item",
    "quote",
    "table_header",
    "table_cell",
]


def _jsonable(value: Any) -> Any:
    """Return JSON-compatible values without relying on object reprs."""

    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def canonical_json_v4(value: BaseModel | Mapping[str, Any] | list[Any] | tuple[Any, ...]) -> str:
    """Serialize a v4 payload using the stable UTF-8 canonical JSON form."""

    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_sha256_v4(
    value: BaseModel | Mapping[str, Any] | list[Any] | tuple[Any, ...],
) -> str:
    return hashlib.sha256(canonical_json_v4(value).encode("utf-8")).hexdigest()


def sha256_text_v4(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# The short names are useful to callers constructing fixtures, but the v4
# suffixed names remain the canonical implementation names and avoid silently
# mixing a v3 helper into a v4 contract.
canonical_sha256 = canonical_sha256_v4
sha256_text = sha256_text_v4


class _FrozenV4Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _validate_sha(value: str, field_name: str) -> str:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field_name} must be a lowercase sha256")
    return value


def _unit_sha256_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return the complete semantic/source payload for a visible unit."""

    return {key: item for key, item in value.items() if key != "sha256"}


def _atom_sha256_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return the complete provenance payload for a content atom."""

    return {key: item for key, item in value.items() if key != "sha256"}


def _visible_copy_payload(units: tuple[Any, ...]) -> tuple[dict[str, Any], ...]:
    """Return the ordered projected payload without source provenance."""

    return tuple(
        {
            "sequence": unit.sequence,
            "source_field": unit.source_field,
            "structural_role": unit.structural_role,
            "text": unit.text,
        }
        for unit in units
    )


class VisibleCopyUnitV4(_FrozenV4Model):
    """One visible source unit and the exact source span that produced it."""

    unit_id: str = Field(min_length=1)
    source_field: SourceFieldV4
    raw_start: int = Field(ge=0)
    raw_end: int = Field(gt=0)
    raw_slice_sha256: str
    text: str = Field(min_length=1)
    structural_role: VisibleCopyRoleV4
    sequence: int = Field(ge=0)
    sha256: str

    @field_validator("raw_slice_sha256", "sha256")
    @classmethod
    def validate_hash_shape(cls, value: str, info) -> str:
        return _validate_sha(value, info.field_name)

    @model_validator(mode="after")
    def validate_span_and_hash(self) -> "VisibleCopyUnitV4":
        if self.raw_end <= self.raw_start:
            raise ValueError("raw_end must be greater than raw_start")
        expected = canonical_sha256_v4(
            _unit_sha256_payload(self.model_dump(mode="json"))
        )
        if self.sha256 != expected:
            raise ValueError("unit sha256 does not match semantic/source payload")
        return self

    def validate_integrity(self) -> None:
        """Re-run validation for objects restored through ``model_copy``.

        Pydantic's ``model_copy(update=...)`` intentionally does not invoke
        validators.  Persisted contracts therefore need an explicit boundary
        check before a downstream node consumes them.
        """

        type(self).model_validate(self.model_dump(mode="python"))

    @property
    def unit_sha256(self) -> str:
        """Descriptive alias for consumers that distinguish unit from atom."""

        return self.sha256

    @property
    def raw_span(self) -> tuple[int, int]:
        return self.raw_start, self.raw_end


class MarkdownTableGroupV4(_FrozenV4Model):
    """A rectangular Markdown table block and its row-major visible units."""

    group_id: str = Field(min_length=1)
    source_field: SourceFieldV4
    raw_start: int = Field(ge=0)
    raw_end: int = Field(gt=0)
    raw_slice_sha256: str
    rows: tuple[tuple[str, ...], ...] = Field(min_length=1)
    unit_ids: tuple[str, ...] = Field(min_length=1)
    sha256: str

    @field_validator("raw_slice_sha256", "sha256")
    @classmethod
    def validate_hash_shape(cls, value: str, info) -> str:
        return _validate_sha(value, info.field_name)

    @model_validator(mode="after")
    def validate_table_shape_and_hash(self) -> "MarkdownTableGroupV4":
        if self.raw_end <= self.raw_start:
            raise ValueError("table raw_end must be greater than raw_start")
        width = len(self.rows[0])
        if width == 0 or any(len(row) != width for row in self.rows):
            raise ValueError("table rows must be rectangular")
        expected_unit_count = len(self.rows) * width
        if len(self.unit_ids) != expected_unit_count:
            raise ValueError("table unit IDs must match rectangular rows")
        if len(set(self.unit_ids)) != len(self.unit_ids):
            raise ValueError("table unit IDs must be unique")
        if any(not cell for row in self.rows for cell in row):
            raise ValueError("table cells must contain visible text")
        expected = canonical_sha256_v4(
            self.model_dump(mode="json", exclude={"sha256"})
        )
        if self.sha256 != expected:
            raise ValueError("table group sha256 does not match canonical payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))

    @property
    def raw_span(self) -> tuple[int, int]:
        return self.raw_start, self.raw_end

    @property
    def row_unit_ids(self) -> tuple[tuple[str, ...], ...]:
        width = len(self.rows[0])
        return tuple(
            tuple(self.unit_ids[index : index + width])
            for index in range(0, len(self.unit_ids), width)
        )


class VisibleCopyProjectionV4(_FrozenV4Model):
    """Deterministic Markdown projection of assembler-owned visible copy."""

    units: tuple[VisibleCopyUnitV4, ...] = Field(min_length=1)
    table_groups: tuple[MarkdownTableGroupV4, ...] = ()
    title_sha256: str
    cover_copy_sha256: str
    content_sha256: str
    canonical_sha256: str
    canonical_visible_copy_sha256: str | None = None

    @field_validator(
        "title_sha256",
        "cover_copy_sha256",
        "content_sha256",
        "canonical_sha256",
        "canonical_visible_copy_sha256",
    )
    @classmethod
    def validate_hash_shape(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _validate_sha(value, info.field_name)

    @model_validator(mode="after")
    def validate_relations_and_hash(self) -> "VisibleCopyProjectionV4":
        for unit in self.units:
            unit.validate_integrity()
        for group in self.table_groups:
            group.validate_integrity()

        unit_by_id = {unit.unit_id: unit for unit in self.units}
        if len(unit_by_id) != len(self.units):
            raise ValueError("visible-copy unit IDs must be unique")
        sequences = [unit.sequence for unit in self.units]
        if len(set(sequences)) != len(sequences):
            raise ValueError("visible-copy unit sequences must be unique")

        group_ids = [group.group_id for group in self.table_groups]
        if len(set(group_ids)) != len(group_ids):
            raise ValueError("table group IDs must be unique")
        for group in self.table_groups:
            group_units = []
            for unit_id in group.unit_ids:
                unit = unit_by_id.get(unit_id)
                if unit is None:
                    raise ValueError("table group references an unknown unit")
                if unit.source_field != group.source_field:
                    raise ValueError("table group unit source field does not match")
                group_units.append(unit)
            expected_text = tuple(unit.text for unit in group_units)
            actual_text = tuple(cell for row in group.rows for cell in row)
            if expected_text != actual_text:
                raise ValueError("table group rows must match referenced unit text")
            if any(unit.structural_role not in {"table_header", "table_cell"} for unit in group_units):
                raise ValueError("table group can reference only table units")
            header_width = len(group.rows[0])
            if any(
                unit.structural_role != "table_header"
                for unit in group_units[:header_width]
            ):
                raise ValueError("table group must start with table header units")
            if any(
                unit.structural_role != "table_cell"
                for unit in group_units[header_width:]
            ):
                raise ValueError("table group data rows must use table cell units")
            if any(
                unit.raw_start < group.raw_start or unit.raw_end > group.raw_end
                for unit in group_units
            ):
                raise ValueError("table group raw span must contain its units")

        visible_payload = _visible_copy_payload(self.units)
        expected_visible = canonical_sha256_v4(visible_payload)
        if self.canonical_visible_copy_sha256 is None:
            object.__setattr__(self, "canonical_visible_copy_sha256", expected_visible)
        elif self.canonical_visible_copy_sha256 != expected_visible:
            raise ValueError(
                "projection canonical visible-copy sha256 does not match visible units"
            )

        payload = self.model_dump(
            mode="json",
            exclude={"canonical_sha256", "canonical_visible_copy_sha256"},
        )
        expected = canonical_sha256_v4(payload)
        if self.canonical_sha256 != expected:
            raise ValueError("projection canonical sha256 does not match canonical payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))

    @property
    def source_field_hashes(self) -> tuple[str, str, str]:
        return self.title_sha256, self.cover_copy_sha256, self.content_sha256


class ContentAtomV4(_FrozenV4Model):
    """Immutable visible atom retaining source-unit and projection provenance."""

    atom_id: str = Field(min_length=1)
    source_unit_id: str = Field(min_length=1)
    source_projection_sha256: str
    source_field: SourceFieldV4
    raw_start: int = Field(ge=0)
    raw_end: int = Field(gt=0)
    raw_slice_sha256: str
    text: str = Field(min_length=1)
    role: VisibleCopyRoleV4
    sha256: str

    @field_validator("source_projection_sha256", "raw_slice_sha256", "sha256")
    @classmethod
    def validate_hash_shape(cls, value: str, info) -> str:
        return _validate_sha(value, info.field_name)

    @model_validator(mode="after")
    def validate_span_and_hash(self) -> "ContentAtomV4":
        if self.raw_end <= self.raw_start:
            raise ValueError("atom raw_end must be greater than raw_start")
        expected = canonical_sha256_v4(
            _atom_sha256_payload(self.model_dump(mode="json"))
        )
        if self.sha256 != expected:
            raise ValueError("atom sha256 does not match provenance payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))

    @property
    def raw_span(self) -> tuple[int, int]:
        return self.raw_start, self.raw_end


class ContentAtomSetV4(_FrozenV4Model):
    """The complete immutable atom set produced by the v4 projection."""

    projection_sha256: str
    atoms: tuple[ContentAtomV4, ...] = Field(min_length=1)
    canonical_sha256: str

    @field_validator("projection_sha256", "canonical_sha256")
    @classmethod
    def validate_hash_shape(cls, value: str, info) -> str:
        return _validate_sha(value, info.field_name)

    @model_validator(mode="after")
    def validate_atoms_and_hash(self) -> "ContentAtomSetV4":
        for atom in self.atoms:
            atom.validate_integrity()

        atom_ids = [atom.atom_id for atom in self.atoms]
        if len(set(atom_ids)) != len(atom_ids):
            raise ValueError("content atom IDs must be unique")
        source_unit_ids = [atom.source_unit_id for atom in self.atoms]
        if len(set(source_unit_ids)) != len(source_unit_ids):
            raise ValueError("content atom source unit IDs must be unique")
        if any(atom.source_projection_sha256 != self.projection_sha256 for atom in self.atoms):
            raise ValueError("atom source projection binding does not match atom set")
        payload = self.model_dump(mode="json", exclude={"canonical_sha256"})
        expected = canonical_sha256_v4(payload)
        if self.canonical_sha256 != expected:
            raise ValueError("atom set canonical sha256 does not match atoms")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))

    def validate_projection(self, projection: VisibleCopyProjectionV4) -> None:
        """Fail closed if any atom no longer points at this exact projection."""

        self.validate_integrity()
        projection.validate_integrity()
        if self.projection_sha256 != projection.canonical_sha256:
            raise ValueError("content atom set projection binding drifted")
        units = {unit.unit_id: unit for unit in projection.units}
        for atom in self.atoms:
            unit = units.get(atom.source_unit_id)
            if unit is None:
                raise ValueError("content atom references an unknown projection unit")
            if (
                atom.source_field != unit.source_field
                or atom.raw_start != unit.raw_start
                or atom.raw_end != unit.raw_end
                or atom.raw_slice_sha256 != unit.raw_slice_sha256
                or atom.text != unit.text
                or atom.role != unit.structural_role
            ):
                raise ValueError("content atom source unit binding drifted")

    @property
    def visible_copy_projection_sha256(self) -> str:
        return self.projection_sha256


__all__ = [
    "ContentAtomSetV4",
    "ContentAtomV4",
    "MarkdownTableGroupV4",
    "SourceFieldV4",
    "VisibleCopyProjectionV4",
    "VisibleCopyRoleV4",
    "VisibleCopyUnitV4",
    "canonical_json_v4",
    "canonical_sha256",
    "canonical_sha256_v4",
    "sha256_text",
    "sha256_text_v4",
]
