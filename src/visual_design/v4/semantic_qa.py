"""Deterministic Q0 semantic hard gate for the isolated v4 path."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from src.schemas.content_lock import ContentLock
from src.schemas.v4.content import (
    ContentAtomSetV4,
    VisibleCopyProjectionV4,
    canonical_sha256_v4,
)
from src.schemas.v4.semantic import (
    SemanticContentModelV4,
    SemanticFragmentV4,
    SemanticGroupV4,
    SemanticIssueV4,
    SemanticQAResultV4,
)


_ZERO_SHA256 = "0" * 64
_TABLE_GROUP_KINDS = {"table", "table_group", "comparison_table"}


def _safe_hash(value: Any) -> str:
    if isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    ):
        return value
    return _ZERO_SHA256


def _coerce(value: Any, model_type: type[Any]) -> Any | None:
    if isinstance(value, model_type):
        return value
    if isinstance(value, Mapping):
        try:
            return model_type.model_validate(value)
        except Exception:
            return None
    return None


def _issue(
    code: str,
    *,
    location: str,
    message: str,
    fragment_id: str | None = None,
    atom_id: str | None = None,
    group_id: str | None = None,
) -> SemanticIssueV4:
    """Create sanitized evidence without copying source or provider text."""

    return SemanticIssueV4(
        code=code,  # type: ignore[arg-type]
        location=location,
        message=message,
        evidence="deterministic semantic contract check",
        fragment_id=fragment_id,
        atom_id=atom_id,
        group_id=group_id,
    )


def _lock_hash(lock: ContentLock | None) -> str:
    if lock is None:
        return _ZERO_SHA256
    value = getattr(lock, "canonical_sha256", None)
    return _safe_hash(value)


def _validate_lock_hash(lock: ContentLock, issues: list[SemanticIssueV4]) -> None:
    try:
        payload = lock.model_dump(mode="json", exclude={"canonical_sha256"})
        expected = canonical_sha256_v4(payload)
    except Exception:
        expected = _ZERO_SHA256
    if lock.canonical_sha256 != expected:
        issues.append(
            _issue(
                "HASH_BINDING_MISMATCH",
                location="content_lock.canonical_sha256",
                message="content lock canonical hash does not match its complete payload",
            )
        )


def _validate_atom_set_hash(
    atom_set: ContentAtomSetV4 | None,
    issues: list[SemanticIssueV4],
) -> None:
    if atom_set is None:
        issues.append(
            _issue(
                "HASH_BINDING_MISMATCH",
                location="content_atom_set",
                message="persisted content atom set is unavailable or invalid",
            )
        )
        return
    try:
        atom_set.validate_integrity()
    except Exception:
        issues.append(
            _issue(
                "HASH_BINDING_MISMATCH",
                location="content_atom_set.canonical_sha256",
                message="content atom set canonical hash does not match its complete payload",
            )
        )


def _validate_model_hash(
    model: SemanticContentModelV4 | None,
    atom_set: ContentAtomSetV4 | None,
    issues: list[SemanticIssueV4],
) -> None:
    if model is None:
        issues.append(
            _issue(
                "HASH_BINDING_MISMATCH",
                location="semantic_content_model",
                message="semantic content model is unavailable or invalid",
            )
        )
        return
    try:
        model.validate_integrity()
    except Exception:
        issues.append(
            _issue(
                "HASH_BINDING_MISMATCH",
                location="semantic_content_model.canonical_sha256",
                message="semantic model canonical hash does not match its complete payload",
            )
        )
    if atom_set is not None and model.content_atom_set_sha256 != atom_set.canonical_sha256:
        issues.append(
            _issue(
                "HASH_BINDING_MISMATCH",
                location="semantic_content_model.content_atom_set_sha256",
                message="semantic model is bound to a different content atom set",
            )
        )


def _validate_fragments(
    atom_set: ContentAtomSetV4 | None,
    model: SemanticContentModelV4 | None,
    issues: list[SemanticIssueV4],
) -> tuple[dict[str, SemanticFragmentV4], set[str]]:
    if atom_set is None or model is None:
        return {}, set()

    atoms = {atom.atom_id: atom for atom in atom_set.atoms}
    atom_order = {atom.atom_id: index for index, atom in enumerate(atom_set.atoms)}
    fragments_by_id: dict[str, SemanticFragmentV4] = {}
    fragments_by_atom: dict[str, list[SemanticFragmentV4]] = defaultdict(list)
    verified_ids: set[str] = set()

    for fragment in model.fragments:
        fragment_id = fragment.fragment_id
        if fragment_id in fragments_by_id:
            issues.append(
                _issue(
                    "COVERAGE_DUPLICATE",
                    location=f"fragments[{fragment_id}]",
                    message="fragment ID is not unique",
                    fragment_id=fragment_id,
                )
            )
        else:
            fragments_by_id[fragment_id] = fragment

        atom = atoms.get(fragment.source_atom_id)
        if atom is None:
            issues.append(
                _issue(
                    "UNKNOWN_ATOM",
                    location=f"fragments[{fragment_id}].source_atom_id",
                    message="fragment references an unknown source atom",
                    fragment_id=fragment_id,
                    atom_id=fragment.source_atom_id,
                )
            )
            continue

        start = fragment.start
        end = fragment.end
        valid_bounds = (
            type(start) is int
            and type(end) is int
            and 0 <= start < end <= len(atom.text)
        )
        if not valid_bounds:
            issues.append(
                _issue(
                    "INVALID_BOUNDS",
                    location=f"fragments[{fragment_id}].slice",
                    message="fragment slice bounds are outside the source atom",
                    fragment_id=fragment_id,
                    atom_id=atom.atom_id,
                )
            )
            continue

        fragments_by_atom[atom.atom_id].append(fragment)
        expected_text = atom.text[start:end]
        if fragment.exact_text != expected_text:
            # This is intentionally emitted before coverage/hash issues: a
            # rewritten visible string is the primary hard-gate violation.
            issues.append(
                _issue(
                    "VISIBLE_TEXT_MUTATED",
                    location=f"fragments[{fragment_id}].exact_text",
                    message="fragment visible text differs from its persisted atom slice",
                    fragment_id=fragment_id,
                    atom_id=atom.atom_id,
                )
            )
        else:
            verified_ids.add(fragment_id)

    # Global sequence is zero-based, unique and continuous.  It is checked
    # independently of source-slice coverage so a malformed provider draft
    # always yields a deterministic hard-gate result rather than an exception.
    sequences = [fragment.sequence_index for fragment in model.fragments]
    if sequences != list(range(len(sequences))) or len(set(sequences)) != len(sequences):
        issues.append(
            _issue(
                "SEQUENCE_INVALID",
                location="fragments.sequence_index",
                message="fragment sequence indexes must be unique, continuous, and zero-based",
            )
        )

    # The atom order is an invariant in addition to the numeric sequence.  A
    # fragment may split an atom, but it cannot move a later atom ahead of an
    # earlier one.
    sequenced_known = [
        fragment
        for fragment in sorted(model.fragments, key=lambda item: (item.sequence_index, item.fragment_id))
        if fragment.source_atom_id in atom_order
    ]
    expected_known = sorted(
        sequenced_known,
        key=lambda item: (
            atom_order[item.source_atom_id],
            item.start,
            item.end,
            item.fragment_id,
        ),
    )
    if [fragment.fragment_id for fragment in sequenced_known] != [
        fragment.fragment_id for fragment in expected_known
    ]:
        issues.append(
            _issue(
                "SEQUENCE_INVALID",
                location="fragments.logical_order",
                message="fragment sequence does not preserve atom and source-slice order",
            )
        )

    # Per-atom exact coverage, including gaps, overlaps, duplicate slices and
    # atoms omitted entirely from the model.
    for atom in atom_set.atoms:
        fragments = sorted(
            fragments_by_atom.get(atom.atom_id, ()),
            key=lambda item: (item.sequence_index, item.fragment_id),
        )
        if not fragments:
            issues.append(
                _issue(
                    "COVERAGE_MISSING",
                    location=f"atoms[{atom.atom_id}]",
                    message="source atom has no semantic fragments",
                    atom_id=atom.atom_id,
                )
            )
            continue

        starts = [fragment.start for fragment in fragments]
        if starts != sorted(starts):
            issues.append(
                _issue(
                    "SEQUENCE_INVALID",
                    location=f"atoms[{atom.atom_id}].fragments",
                    message="fragments for an atom are not in source-slice order",
                    atom_id=atom.atom_id,
                )
            )

        cursor = 0
        for index, fragment in enumerate(fragments):
            if fragment.start > cursor:
                issues.append(
                    _issue(
                        "COVERAGE_GAP",
                        location=f"fragments[{fragment.fragment_id}].slice",
                        message="source atom coverage has an uncovered interval",
                        fragment_id=fragment.fragment_id,
                        atom_id=atom.atom_id,
                    )
                )
            elif fragment.start < cursor:
                previous = fragments[index - 1] if index > 0 else None
                if previous is not None and fragment.start == previous.start and fragment.end == previous.end:
                    code = "COVERAGE_DUPLICATE"
                    message = "source atom slice is duplicated"
                else:
                    code = "COVERAGE_OVERLAP"
                    message = "source atom slices overlap"
                issues.append(
                    _issue(
                        code,
                        location=f"fragments[{fragment.fragment_id}].slice",
                        message=message,
                        fragment_id=fragment.fragment_id,
                        atom_id=atom.atom_id,
                    )
                )
            cursor = max(cursor, fragment.end)
        if cursor < len(atom.text):
            issues.append(
                _issue(
                    "COVERAGE_GAP",
                    location=f"atoms[{atom.atom_id}]",
                    message="source atom is not completely covered",
                    atom_id=atom.atom_id,
                )
            )

    return fragments_by_id, verified_ids


def _validate_parent_graph(
    model: SemanticContentModelV4 | None,
    fragments_by_id: dict[str, SemanticFragmentV4],
    verified_ids: set[str],
    issues: list[SemanticIssueV4],
) -> None:
    if model is None:
        return
    parent_by_id: dict[str, str] = {}
    for fragment in model.fragments:
        parent_id = fragment.parent_fragment_id
        if parent_id is None:
            continue
        if (
            fragment.fragment_id not in verified_ids
            or parent_id not in verified_ids
            or parent_id == fragment.fragment_id
        ):
            issues.append(
                _issue(
                    "PARENT_INVALID",
                    location=f"fragments[{fragment.fragment_id}].parent_fragment_id",
                    message="parent must reference a different verified fragment",
                    fragment_id=fragment.fragment_id,
                )
            )
            continue
        parent_by_id[fragment.fragment_id] = parent_id

    visited: set[str] = set()
    cycle_reported: set[str] = set()
    for start in parent_by_id:
        if start in visited:
            continue
        path: list[str] = []
        positions: dict[str, int] = {}
        current: str | None = start
        while current is not None and current in parent_by_id and current not in visited:
            if current in positions:
                for fragment_id in path[positions[current] :]:
                    if fragment_id in cycle_reported:
                        continue
                    cycle_reported.add(fragment_id)
                    issues.append(
                        _issue(
                            "PARENT_CYCLE",
                            location=f"fragments[{fragment_id}].parent_fragment_id",
                            message="parent relationships must be acyclic",
                            fragment_id=fragment_id,
                        )
                    )
                break
            positions[current] = len(path)
            path.append(current)
            current = parent_by_id.get(current)
        visited.update(path)


def _validate_groups(
    model: SemanticContentModelV4 | None,
    fragments_by_id: dict[str, SemanticFragmentV4],
    verified_ids: set[str],
    issues: list[SemanticIssueV4],
) -> None:
    if model is None:
        return
    groups_by_id: dict[str, SemanticGroupV4] = {}
    for group in model.groups:
        if group.group_id in groups_by_id:
            issues.append(
                _issue(
                    "GROUP_INVALID",
                    location=f"groups[{group.group_id}]",
                    message="group ID is not unique",
                    group_id=group.group_id,
                )
            )
        else:
            groups_by_id[group.group_id] = group

        if not group.fragment_ids:
            issues.append(
                _issue(
                    "GROUP_INVALID",
                    location=f"groups[{group.group_id}].fragment_ids",
                    message="group must reference at least one verified fragment",
                    group_id=group.group_id,
                )
            )
        if len(set(group.fragment_ids)) != len(group.fragment_ids):
            issues.append(
                _issue(
                    "GROUP_INVALID",
                    location=f"groups[{group.group_id}].fragment_ids",
                    message="group fragment IDs must be unique",
                    group_id=group.group_id,
                )
            )
        for fragment_id in group.fragment_ids:
            if fragment_id not in fragments_by_id or fragment_id not in verified_ids:
                issues.append(
                    _issue(
                        "GROUP_INVALID",
                        location=f"groups[{group.group_id}].fragment_ids",
                        message="group references an unknown or unverified fragment",
                        group_id=group.group_id,
                        fragment_id=fragment_id,
                    )
                )
        if all(fragment_id in fragments_by_id for fragment_id in group.fragment_ids):
            sequence = [fragments_by_id[fragment_id].sequence_index for fragment_id in group.fragment_ids]
            if sequence != sorted(sequence):
                issues.append(
                    _issue(
                        "GROUP_ORDER_INVALID",
                        location=f"groups[{group.group_id}].fragment_ids",
                        message="group fragment order must follow global fragment sequence",
                        group_id=group.group_id,
                    )
                )

    orderings = [group.ordering for group in model.groups]
    if orderings != list(range(len(orderings))) or len(set(orderings)) != len(orderings):
        issues.append(
            _issue(
                "GROUP_ORDER_INVALID",
                location="groups.ordering",
                message="group ordering must be unique, continuous, and zero-based",
            )
        )


def _validate_table_relations(
    projection: VisibleCopyProjectionV4 | None,
    atom_set: ContentAtomSetV4 | None,
    model: SemanticContentModelV4 | None,
    verified_ids: set[str],
    issues: list[SemanticIssueV4],
) -> None:
    if projection is None or atom_set is None or model is None or not projection.table_groups:
        return
    atom_by_unit = {atom.source_unit_id: atom for atom in atom_set.atoms}
    for table in projection.table_groups:
        expected_atoms = [atom_by_unit.get(unit_id) for unit_id in table.unit_ids]
        if any(atom is None for atom in expected_atoms):
            issues.append(
                _issue(
                    "TABLE_RELATION_LOST",
                    location=f"table_groups[{table.group_id}]",
                    message="table source relation references an unavailable atom",
                    group_id=table.group_id,
                )
            )
            continue
        expected_fragment_ids: list[str] = []
        for atom in expected_atoms:
            assert atom is not None
            atom_fragments = sorted(
                (
                    fragment
                    for fragment in model.fragments
                    if fragment.source_atom_id == atom.atom_id
                    and fragment.fragment_id in verified_ids
                ),
                key=lambda fragment: (fragment.sequence_index, fragment.fragment_id),
            )
            expected_fragment_ids.extend(fragment.fragment_id for fragment in atom_fragments)
        matching_groups = [
            group
            for group in model.groups
            if group.group_kind.strip().lower() in _TABLE_GROUP_KINDS
            and tuple(group.fragment_ids) == tuple(expected_fragment_ids)
        ]
        if not matching_groups:
            issues.append(
                _issue(
                    "TABLE_RELATION_LOST",
                    location=f"table_groups[{table.group_id}]",
                    message="table header and row/cell fragments are missing or out of order",
                    group_id=table.group_id,
                )
            )


def evaluate_semantic_model(
    atom_set: ContentAtomSetV4 | Mapping[str, Any],
    model: SemanticContentModelV4 | Mapping[str, Any],
    content_lock: ContentLock | Mapping[str, Any] | None = None,
    projection: VisibleCopyProjectionV4 | Mapping[str, Any] | None = None,
) -> SemanticQAResultV4:
    """Evaluate the Q0 semantic hard gate deterministically.

    ``content_lock`` is optional for direct atom/model unit checks.  The v4
    node always supplies the persisted lock, making lock/hash binding a hard
    gate on the workflow path.
    """

    atom_set_obj = _coerce(atom_set, ContentAtomSetV4)
    model_obj = _coerce(model, SemanticContentModelV4)
    lock_obj = _coerce(content_lock, ContentLock) if content_lock is not None else None
    projection_obj = (
        _coerce(projection, VisibleCopyProjectionV4)
        if projection is not None
        else None
    )
    issues: list[SemanticIssueV4] = []

    _validate_atom_set_hash(atom_set_obj, issues)
    _validate_model_hash(model_obj, atom_set_obj, issues)
    if content_lock is not None and lock_obj is None:
        issues.append(
            _issue(
                "HASH_BINDING_MISMATCH",
                location="content_lock",
                message="persisted content lock is unavailable or invalid",
            )
        )
    if lock_obj is not None:
        _validate_lock_hash(lock_obj, issues)
        if atom_set_obj is not None and lock_obj.content_atom_set_sha256 != atom_set_obj.canonical_sha256:
            issues.append(
                _issue(
                    "HASH_BINDING_MISMATCH",
                    location="content_lock.content_atom_set_sha256",
                    message="content lock and atom set hashes do not match",
                )
            )
    if projection_obj is not None:
        try:
            projection_obj.validate_integrity()
        except Exception:
            issues.append(
                _issue(
                    "HASH_BINDING_MISMATCH",
                    location="visible_copy_projection.canonical_sha256",
                    message="visible-copy projection integrity check failed",
                )
            )
        if atom_set_obj is not None and atom_set_obj.projection_sha256 != projection_obj.canonical_sha256:
            issues.append(
                _issue(
                    "HASH_BINDING_MISMATCH",
                    location="content_atom_set.projection_sha256",
                    message="atom set and visible-copy projection hashes do not match",
                )
            )
        if atom_set_obj is not None:
            try:
                atom_set_obj.validate_projection(projection_obj)
            except Exception:
                issues.append(
                    _issue(
                        "HASH_BINDING_MISMATCH",
                        location="content_atom_set.projection",
                        message="content atoms do not match the persisted visible-copy projection",
                    )
                )
    elif projection is not None:
        issues.append(
            _issue(
                "HASH_BINDING_MISMATCH",
                location="visible_copy_projection",
                message="persisted visible-copy projection is unavailable or invalid",
            )
        )

    fragments_by_id, verified_ids = _validate_fragments(
        atom_set_obj, model_obj, issues
    )
    _validate_parent_graph(model_obj, fragments_by_id, verified_ids, issues)
    _validate_groups(model_obj, fragments_by_id, verified_ids, issues)
    _validate_table_relations(
        projection_obj,
        atom_set_obj,
        model_obj,
        verified_ids,
        issues,
    )

    issue_tuple = tuple(issues)
    atom_hash = _safe_hash(getattr(atom_set_obj, "canonical_sha256", None))
    lock_hash = _lock_hash(lock_obj)
    model_hash = _safe_hash(getattr(model_obj, "canonical_sha256", None))
    payload = {
        "passed": not issue_tuple,
        "issues": issue_tuple,
        "content_atom_set_sha256": atom_hash,
        "content_lock_sha256": lock_hash,
        "semantic_content_model_sha256": model_hash,
    }
    return SemanticQAResultV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def evaluate_semantic_qa(*args: Any, **kwargs: Any) -> SemanticQAResultV4:
    """Explicit Q0 alias used by future v4 graph wiring."""

    return evaluate_semantic_model(*args, **kwargs)


__all__ = ["evaluate_semantic_model", "evaluate_semantic_qa"]
