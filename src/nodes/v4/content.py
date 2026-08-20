"""Task 6 v4 visible-copy projection and immediate ContentLock construction."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.publishing.artifacts import build_content_lock
from src.schemas.v4.content import (
    ContentAtomSetV4,
    ContentAtomV4,
    MarkdownTableGroupV4,
    VisibleCopyProjectionV4,
    VisibleCopyRoleV4,
    VisibleCopyUnitV4,
    canonical_sha256_v4,
    sha256_text_v4,
)


_BLOCK_MARKERS: tuple[tuple[VisibleCopyRoleV4, re.Pattern[str]], ...] = (
    ("heading", re.compile(r"^[ \t]*#{1,6}[ \t]+")),
    ("step", re.compile(r"^[ \t]*\d+[.)][ \t]+")),
    ("list_item", re.compile(r"^[ \t]*[-+*][ \t]+")),
    ("quote", re.compile(r"^[ \t]*>[ \t]?")),
)
_THEMATIC_BREAK = re.compile(
    r"^[ \t]*(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$"
)
_EMPTY_HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]*$")
_EMPTY_QUOTE = re.compile(r"^[ \t]*>[ \t]*$")
_LINK = re.compile(r"!?(?<!\\)\[([^\]]+)\]\([^)]*\)")
_CODE_SPAN = re.compile(r"(`+)(.*?)\1", re.DOTALL)
_STRONG = re.compile(r"(?<!\\)(\*\*|__)(?=\S)(.+?)(?<=\S)\1", re.DOTALL)
_STRIKE = re.compile(r"(?<!\\)~~(?=\S)(.+?)(?<=\S)~~", re.DOTALL)
_EMPHASIS = re.compile(
    r"(?<![\\*])\*(?=\S)(.+?)(?<=\S)\*(?!\*)|"
    r"(?<![\\_\w])_(?=\S)(.+?)(?<=\S)_(?![_\w])",
    re.DOTALL,
)
_ESCAPED_MARKDOWN = re.compile(r"\\([\\`*_{}\[\]()#+.!|>~-])")


def _strip_inline_markdown(text: str) -> str:
    """Remove only deterministic Markdown syntax, preserving copy payload."""

    # Links and code spans must be handled before emphasis, since their
    # delimiters can contain characters that otherwise look like emphasis.
    while True:
        updated = _LINK.sub(lambda match: match.group(1), text)
        updated = _CODE_SPAN.sub(lambda match: match.group(2), updated)
        updated = _STRONG.sub(lambda match: match.group(2), updated)
        updated = _STRIKE.sub(lambda match: match.group(1), updated)
        updated = _EMPHASIS.sub(
            lambda match: match.group(1) if match.group(1) is not None else match.group(2),
            updated,
        )
        updated = _ESCAPED_MARKDOWN.sub(r"\1", updated)
        if updated == text:
            return updated
        text = updated


def _line_records(text: str) -> list["_Line"]:
    records: list[_Line] = []
    offset = 0
    for line_with_end in text.splitlines(keepends=True):
        line = line_with_end.rstrip("\r\n")
        records.append(_Line(line, offset, offset + len(line)))
        offset += len(line_with_end)
    if text and not records:
        records.append(_Line(text, 0, len(text)))
    return records


@dataclass(frozen=True)
class _Line:
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class _Cell:
    start: int
    end: int
    raw: str


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def _split_table_row(line: str) -> tuple[_Cell, ...] | None:
    """Split unescaped pipes while retaining offsets into the original line."""

    if "|" not in line:
        return None
    delimiters = [
        index
        for index, char in enumerate(line)
        if char == "|" and not _is_escaped(line, index)
    ]
    cells: list[_Cell] = []
    start = 0
    for delimiter in delimiters:
        cells.append(_Cell(start, delimiter, line[start:delimiter]))
        start = delimiter + 1
    cells.append(_Cell(start, len(line), line[start:]))
    if delimiters and not line[: delimiters[0]].strip() and cells:
        cells = cells[1:]
    if delimiters and not line[delimiters[-1] + 1 :].strip() and cells:
        cells = cells[:-1]
    if not cells:
        return None
    return tuple(cells)


_TABLE_SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")


def _is_table_separator(cells: tuple[_Cell, ...] | None) -> bool:
    if not cells:
        return False
    return all(_TABLE_SEPARATOR_CELL.fullmatch(cell.raw.strip()) for cell in cells)


def _visible_cell(source: str, cell: _Cell) -> tuple[str, int, int]:
    # Spaces immediately inside a pipe are Markdown table formatting.  Keep
    # every character after that boundary, including repeated internal spaces.
    left_padding = len(cell.raw) - len(cell.raw.lstrip(" \t"))
    right_padding = len(cell.raw) - len(cell.raw.rstrip(" \t"))
    start = cell.start + left_padding
    end = cell.end - right_padding
    raw = source[start:end]
    return _strip_inline_markdown(raw), start, end


def _is_empty_visible(text: str) -> bool:
    return not text or not text.strip()


def _normal_line_payload(line: _Line) -> tuple[VisibleCopyRoleV4, int] | None:
    if (
        not line.text.strip()
        or _THEMATIC_BREAK.fullmatch(line.text)
        or _EMPTY_HEADING.fullmatch(line.text)
        or _EMPTY_QUOTE.fullmatch(line.text)
    ):
        return None
    for role, marker in _BLOCK_MARKERS:
        match = marker.match(line.text)
        if match is not None:
            return role, line.start + match.end()
    return "paragraph", line.start


def _append_unit(
    *,
    units: list[VisibleCopyUnitV4],
    counters: defaultdict[str, int],
    sequence: list[int],
    source: str,
    source_field: str,
    role: VisibleCopyRoleV4,
    raw_start: int,
    raw_end: int,
    text: str,
) -> VisibleCopyUnitV4 | None:
    if _is_empty_visible(text):
        return None
    counters[role] += 1
    unit_id = f"{role}-{counters[role]:03d}"
    payload = {
        "unit_id": unit_id,
        "source_field": source_field,
        "raw_start": raw_start,
        "raw_end": raw_end,
        "raw_slice_sha256": sha256_text_v4(source[raw_start:raw_end]),
        "text": text,
        "structural_role": role,
        "sequence": sequence[0],
    }
    unit = VisibleCopyUnitV4(
        **payload,
        sha256=canonical_sha256_v4(payload),
    )
    units.append(unit)
    sequence[0] += 1
    return unit


def _append_table(
    *,
    lines: list[_Line],
    start_index: int,
    end_index: int,
    source: str,
    source_field: str,
    units: list[VisibleCopyUnitV4],
    groups: list[MarkdownTableGroupV4],
    counters: defaultdict[str, int],
    sequence: list[int],
) -> bool:
    header_cells = _split_table_row(lines[start_index].text)
    separator_cells = _split_table_row(lines[start_index + 1].text)
    if not header_cells or not _is_table_separator(separator_cells):
        return False
    if len(header_cells) != len(separator_cells or ()):
        return False

    rows: list[tuple[str, ...]] = []
    pending_cells: list[tuple[str, int, int, VisibleCopyRoleV4]] = []
    for row_index in range(start_index, end_index):
        cells = _split_table_row(lines[row_index].text)
        if cells is None or len(cells) != len(header_cells):
            return False
        if row_index == start_index + 1:
            continue
        visible_cells: list[str] = []
        for cell in cells:
            visible, raw_start, raw_end = _visible_cell(lines[row_index].text, cell)
            if _is_empty_visible(visible):
                return False
            visible_cells.append(visible)
            role: VisibleCopyRoleV4 = "table_header" if row_index == start_index else "table_cell"
            pending_cells.append(
                (
                    visible,
                    lines[row_index].start + cell.start,
                    lines[row_index].start + cell.end,
                    role,
                )
            )
        rows.append(tuple(visible_cells))

    if not rows:
        return False
    row_units: list[VisibleCopyUnitV4] = []
    for visible, raw_start, raw_end, role in pending_cells:
        unit = _append_unit(
            units=units,
            counters=counters,
            sequence=sequence,
            source=source,
            source_field=source_field,
            role=role,
            raw_start=raw_start,
            raw_end=raw_end,
            text=visible,
        )
        if unit is None:
            return False
        row_units.append(unit)
    payload = {
        "group_id": f"table-{len(groups) + 1:03d}",
        "source_field": source_field,
        "raw_start": lines[start_index].start,
        "raw_end": lines[end_index - 1].end,
        "raw_slice_sha256": sha256_text_v4(
            source[lines[start_index].start : lines[end_index - 1].end]
        ),
        "rows": tuple(rows),
        "unit_ids": tuple(unit.unit_id for unit in row_units),
    }
    groups.append(
        MarkdownTableGroupV4(
            **payload,
            sha256=canonical_sha256_v4(payload),
        )
    )
    return True


def _scan_source(
    *,
    source: str,
    source_field: str,
    units: list[VisibleCopyUnitV4],
    groups: list[MarkdownTableGroupV4],
    counters: defaultdict[str, int],
    sequence: list[int],
    forced_role: VisibleCopyRoleV4 | None = None,
) -> None:
    lines = _line_records(source)
    index = 0
    while index < len(lines):
        line = lines[index]
        if forced_role is None:
            header_cells = _split_table_row(line.text)
            separator_cells = (
                _split_table_row(lines[index + 1].text)
                if index + 1 < len(lines)
                else None
            )
            if header_cells and _is_table_separator(separator_cells):
                # Determine the contiguous candidate block before constructing
                # any units.  A malformed row remains ordinary copy rather than
                # becoming a partially-recognized table.
                candidate_end = index + 2
                width = len(header_cells)
                while candidate_end < len(lines):
                    next_cells = _split_table_row(lines[candidate_end].text)
                    if next_cells is None:
                        break
                    candidate_end += 1
                if all(
                    len(_split_table_row(lines[row_index].text) or ()) == width
                    for row_index in range(index + 2, candidate_end)
                ) and _append_table(
                    lines=lines,
                    start_index=index,
                    end_index=candidate_end,
                    source=source,
                    source_field=source_field,
                    units=units,
                    groups=groups,
                    counters=counters,
                    sequence=sequence,
                ):
                    index = candidate_end
                    continue

        payload = _normal_line_payload(line)
        if forced_role is not None:
            if line.text.strip():
                visible = _strip_inline_markdown(line.text)
                _append_unit(
                    units=units,
                    counters=counters,
                    sequence=sequence,
                    source=source,
                    source_field=source_field,
                    role=forced_role,
                    raw_start=line.start,
                    raw_end=line.end,
                    text=visible,
                )
        elif payload is not None:
            role, visible_start = payload
            _append_unit(
                units=units,
                counters=counters,
                sequence=sequence,
                source=source,
                source_field=source_field,
                role=role,
                raw_start=line.start,
                raw_end=line.end,
                text=_strip_inline_markdown(source[visible_start:line.end]),
            )
        index += 1


def project_visible_copy(
    markdown: str | None = None,
    *,
    title: str = "",
    cover_copy: str = "",
    content: str | None = None,
) -> VisibleCopyProjectionV4:
    """Project assembler copy into immutable units and table relations.

    Passing one positional string is a convenience for body-only projection
    tests and treats that string as ``content``.  The v4 node passes all three
    named assembler fields so each source digest is retained.
    """

    if content is None:
        content = "" if markdown is None else markdown
    elif markdown is not None:
        raise TypeError("project_visible_copy accepts either positional markdown or content")
    for field_name, value in (("title", title), ("cover_copy", cover_copy), ("content", content)):
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")

    units: list[VisibleCopyUnitV4] = []
    groups: list[MarkdownTableGroupV4] = []
    counters: defaultdict[str, int] = defaultdict(int)
    sequence = [0]
    _scan_source(
        source=title,
        source_field="title",
        units=units,
        groups=groups,
        counters=counters,
        sequence=sequence,
        forced_role="title",
    )
    _scan_source(
        source=cover_copy,
        source_field="cover_copy",
        units=units,
        groups=groups,
        counters=counters,
        sequence=sequence,
        forced_role="cover",
    )
    _scan_source(
        source=content,
        source_field="content",
        units=units,
        groups=groups,
        counters=counters,
        sequence=sequence,
    )
    if not units:
        raise ValueError("visible copy projection requires at least one visible unit")
    payload = {
        "units": tuple(units),
        "table_groups": tuple(groups),
        "title_sha256": sha256_text_v4(title),
        "cover_copy_sha256": sha256_text_v4(cover_copy),
        "content_sha256": sha256_text_v4(content),
    }
    return VisibleCopyProjectionV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def _build_content_atom_set(projection: VisibleCopyProjectionV4) -> ContentAtomSetV4:
    atoms: list[ContentAtomV4] = []
    for unit in projection.units:
        payload = {
            "atom_id": unit.unit_id,
            "source_unit_id": unit.unit_id,
            "source_projection_sha256": projection.canonical_sha256,
            "source_field": unit.source_field,
            "raw_start": unit.raw_start,
            "raw_end": unit.raw_end,
            "raw_slice_sha256": unit.raw_slice_sha256,
            "text": unit.text,
            "role": unit.structural_role,
        }
        atoms.append(
            ContentAtomV4(
                **payload,
                sha256=canonical_sha256_v4(payload),
            )
        )
    atom_payload = {
        "projection_sha256": projection.canonical_sha256,
        "atoms": tuple(atoms),
    }
    return ContentAtomSetV4(
        **atom_payload,
        canonical_sha256=canonical_sha256_v4(atom_payload),
    )


def _required_copy(package: Mapping[str, Any], field_name: str) -> str:
    value = package.get(field_name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"publish_package.{field_name} must be a non-empty string")
    return value


def content_atomizer_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """Produce v4 visible-copy contracts from assembler-owned package fields."""

    package = state.get("publish_package") if isinstance(state, Mapping) else None
    if not isinstance(package, Mapping):
        raise ValueError("v4 content_atomizer requires publish_package")
    title = _required_copy(package, "title")
    cover_copy = _required_copy(package, "cover_copy")
    content = _required_copy(package, "content")
    projection = project_visible_copy(
        title=title,
        cover_copy=cover_copy,
        content=content,
    )
    atom_set = _build_content_atom_set(projection)
    return {
        "visible_copy_projection": projection,
        "content_atom_set": atom_set,
        "content_atomization_route": "content_lock_builder",
        "content_atomization_issues": [],
        "current_node": "V4_CONTENT_ATOMIZER",
    }


def _validate_persisted_content(
    package: Mapping[str, Any],
    projection: VisibleCopyProjectionV4,
    atom_set: ContentAtomSetV4,
) -> None:
    title = _required_copy(package, "title")
    cover_copy = _required_copy(package, "cover_copy")
    content = _required_copy(package, "content")
    expected_source_hashes = (
        sha256_text_v4(title),
        sha256_text_v4(cover_copy),
        sha256_text_v4(content),
    )
    if projection.source_field_hashes != expected_source_hashes:
        raise ValueError("visible-copy projection source hash drifted from publish package")

    # A persisted object can have been produced with ``model_copy(update=...)``
    # without running Pydantic validators.  Re-projecting the current source
    # therefore checks both canonical contract hashes and every raw span,
    # while remaining deterministic and metadata-independent.
    expected_projection = project_visible_copy(
        title=title,
        cover_copy=cover_copy,
        content=content,
    )
    if projection != expected_projection:
        raise ValueError("persisted visible-copy projection does not match package source")

    atom_set.validate_projection(projection)
    expected_atom_set = _build_content_atom_set(expected_projection)
    if atom_set != expected_atom_set:
        raise ValueError("persisted content atom set does not match visible-copy projection")
    if len(atom_set.atoms) != len(projection.units):
        raise ValueError("content atom set does not cover the persisted projection")
    if {atom.source_unit_id for atom in atom_set.atoms} != {
        unit.unit_id for unit in projection.units
    }:
        raise ValueError("content atom set has incomplete projection unit bindings")

    package_atom_sha = package.get("content_atom_set_sha256")
    if package_atom_sha is not None and package_atom_sha != atom_set.canonical_sha256:
        raise ValueError("publish package content atom binding drifted")
    embedded = package.get("content_atom_set")
    embedded_sha = getattr(embedded, "canonical_sha256", None)
    if isinstance(embedded, Mapping):
        embedded_sha = embedded.get("canonical_sha256")
    if embedded is not None and embedded_sha != atom_set.canonical_sha256:
        raise ValueError("embedded content atom binding drifted")


def content_lock_builder_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """Build and persist this run's v4 ContentLock from persisted contracts."""

    if not isinstance(state, Mapping):
        raise ValueError("v4 content_lock_builder requires state")
    package = state.get("publish_package")
    raw_projection = state.get("visible_copy_projection")
    raw_atom_set = state.get("content_atom_set")
    if not isinstance(package, Mapping):
        raise ValueError("v4 content_lock_builder requires publish_package")
    if isinstance(raw_projection, VisibleCopyProjectionV4):
        projection = raw_projection
    elif isinstance(raw_projection, Mapping):
        projection = VisibleCopyProjectionV4.model_validate(raw_projection)
    else:
        raise ValueError("v4 content_lock_builder requires persisted visible-copy projection")
    if isinstance(raw_atom_set, ContentAtomSetV4):
        atom_set = raw_atom_set
    elif isinstance(raw_atom_set, Mapping):
        atom_set = ContentAtomSetV4.model_validate(raw_atom_set)
    else:
        raise ValueError("v4 content_lock_builder requires persisted content atom set")
    _validate_persisted_content(package, projection, atom_set)

    package_for_lock = dict(package)
    package_for_lock["content_atom_set_sha256"] = atom_set.canonical_sha256
    lock = build_content_lock(package_for_lock)
    if lock.content_atom_set_sha256 != atom_set.canonical_sha256:
        raise ValueError("ContentLock atom binding drifted during construction")
    return {
        "visible_copy_projection": projection,
        "content_atom_set": atom_set,
        "content_lock": lock,
        "current_node": "V4_CONTENT_LOCK_BUILDER",
    }


_V4_VISIBLE_COPY_ARTIFACT_KEYS = (
    "visible_copy_projection",
    "content_atom_set",
    "content_lock",
    "semantic_content_model",
    "semantic_qa_result",
    "carousel_narrative",
    "page_brief_set",
    "authoring_qa_result",
    "asset_manifest",
    "asset_resolution_result",
    "layout_programs",
    "composition_plan",
    "carousel_design_plan",
    "design_plan_qa_result",
    "design_metrics_qa_result",
    "render_manifest",
    "render_qa_result",
    "visual_critique",
    "human_review_decision",
    "final_policy_attestation",
    "revision_request",
    "visual_direction_plan",
)


def invalidate_visible_copy_artifacts(_state: Mapping[str, Any] | None = None) -> dict[str, None]:
    """Return the fail-closed patch for any visible-copy edit.

    ``publish_package`` is intentionally not included: the caller must retain
    the user's edited copy as the next R2/assembler input.
    """

    return {key: None for key in _V4_VISIBLE_COPY_ARTIFACT_KEYS}


__all__ = [
    "content_atomizer_node",
    "content_lock_builder_node",
    "invalidate_visible_copy_artifacts",
    "project_visible_copy",
]
