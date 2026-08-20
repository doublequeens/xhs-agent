from __future__ import annotations

from copy import deepcopy

from src.nodes.v4.content import content_atomizer_node, content_lock_builder_node
from src.schemas.v4.content import ContentAtomSetV4, canonical_sha256_v4
from src.schemas.v4.semantic import (
    SemanticContentModelV4,
    SemanticFragmentV4,
    SemanticGroupV4,
)
from src.visual_design.v4.semantic_qa import evaluate_semantic_model


TABLE_PACKAGE = {
    "focus_keyword": "防晒",
    "topic": "防晒时机",
    "topic_id": "topic-1",
    "angle": "按时机判断",
    "angle_id": "angle-1",
    "target_group": "护肤人群",
    "core_pain": "不知道什么时候补涂",
    "title": "防晒怎么补",
    "cover_copy": "看时机",
    "first_screen_promise": "看表格就能判断",
    "content": "| 时刻 | 做法 |\n|---|---|\n| 午后 | 补涂 |",
    "hashtags": ["#防晒"],
}


def atomized_table() -> tuple[ContentAtomSetV4, object, object]:
    atomized = content_atomizer_node({"publish_package": deepcopy(TABLE_PACKAGE)})
    locked = content_lock_builder_node(
        {**atomized, "publish_package": deepcopy(TABLE_PACKAGE)}
    )
    return (
        locked["content_atom_set"],
        locked["content_lock"],
        locked["visible_copy_projection"],
    )


def atomized_structured() -> tuple[ContentAtomSetV4, object, object]:
    package = deepcopy(TABLE_PACKAGE)
    package["content"] = "1. 做第一步\n- 勾选这一项\n普通说明"
    atomized = content_atomizer_node({"publish_package": package})
    locked = content_lock_builder_node({**atomized, "publish_package": package})
    return (
        locked["content_atom_set"],
        locked["content_lock"],
        locked["visible_copy_projection"],
    )


_SEMANTIC_ROLE_FOR_SOURCE = {
    "title": "title",
    "cover": "cover",
    "heading": "heading",
    "paragraph": "paragraph",
    "step": "step",
    "list_item": "checklist_item",
    "quote": "quote",
    "table_header": "table_header",
    "table_cell": "table_cell",
}
def model_for_atoms(
    atom_set: ContentAtomSetV4,
    *,
    parent_fragment_id: str | None = None,
    groups: tuple[SemanticGroupV4, ...] | None = None,
    starts_ends: tuple[tuple[int, int], ...] | None = None,
    source_ids: tuple[str, ...] | None = None,
    exact_texts: tuple[str, ...] | None = None,
    fragment_ids: tuple[str, ...] | None = None,
) -> SemanticContentModelV4:
    starts_ends = starts_ends or tuple((0, len(atom.text)) for atom in atom_set.atoms)
    if source_ids is None:
        source_ids = (
            tuple(atom.atom_id for atom in atom_set.atoms)
            if len(starts_ends) == len(atom_set.atoms)
            else (atom_set.atoms[0].atom_id,) * len(starts_ends)
        )
    exact_texts = exact_texts or tuple(
        next(atom.text for atom in atom_set.atoms if atom.atom_id == source_ids[index])[start:end]
        for index, (start, end) in enumerate(starts_ends)
    )
    fragment_ids = fragment_ids or tuple(
        f"fragment-{index}" for index in range(len(starts_ends))
    )
    fragments = tuple(
        SemanticFragmentV4(
            fragment_id=fragment_ids[index],
            source_atom_id=source_ids[index],
            start=start,
            end=end,
            exact_text=exact_texts[index],
            semantic_role=_SEMANTIC_ROLE_FOR_SOURCE[
                next(atom.role for atom in atom_set.atoms if atom.atom_id == source_ids[index])
            ],
            parent_fragment_id=(parent_fragment_id if index == 0 else None),
            sequence_index=index,
        )
        for index, (start, end) in enumerate(starts_ends)
    )
    groups = groups if groups is not None else ()
    payload = {
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "fragments": fragments,
        "groups": groups,
    }
    return SemanticContentModelV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def table_model(atom_set: ContentAtomSetV4, projection: object) -> SemanticContentModelV4:
    fragments = tuple(
        SemanticFragmentV4(
            fragment_id=f"fragment-{index}",
            source_atom_id=atom.atom_id,
            start=0,
            end=len(atom.text),
            exact_text=atom.text,
            semantic_role=_SEMANTIC_ROLE_FOR_SOURCE[atom.role],
            sequence_index=index,
        )
        for index, atom in enumerate(atom_set.atoms)
    )
    table_atom_ids = {
        atom_id
        for group in projection.table_groups
        for atom_id in group.unit_ids
        for atom in atom_set.atoms
        if atom.source_unit_id == atom_id
    }
    table_ids = tuple(
        fragment.fragment_id
        for fragment in fragments
        if fragment.source_atom_id in table_atom_ids
    )
    width = len(projection.table_groups[0].rows[0])
    header_ids = table_ids[:width]
    row_ids = [
        table_ids[offset : offset + width]
        for offset in range(width, len(table_ids), width)
    ]
    groups = [
        SemanticGroupV4(
            group_id="table-header-0",
            group_kind="table_header",
            fragment_ids=header_ids,
            ordering=0,
        )
    ]
    for index, row in enumerate(row_ids):
        groups.append(
            SemanticGroupV4(
                group_id=f"table-row-{index}",
                group_kind="table_row",
                fragment_ids=row,
                ordering=index + 1,
            )
        )
    groups.append(
        SemanticGroupV4(
            group_id="table-0",
            group_kind="table",
            fragment_ids=table_ids,
            ordering=len(groups),
        )
    )
    payload = {
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "fragments": fragments,
        "groups": tuple(groups),
    }
    return SemanticContentModelV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def recanonicalize(model: SemanticContentModelV4, **updates: object) -> SemanticContentModelV4:
    payload = model.model_dump(mode="python")
    payload.update(updates)
    payload.pop("canonical_sha256", None)
    return SemanticContentModelV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def test_semantic_fragments_exactly_reconstruct_each_atom():
    atom_set, _, _ = atomized_table()
    model = model_for_atoms(atom_set)

    result = evaluate_semantic_model(atom_set, model)

    assert result.passed is True
    assert result.issues == ()


def test_semantic_qa_rejects_rewritten_fragment_with_primary_code():
    atom_set, _, _ = atomized_table()
    exact_texts = tuple(atom.text for atom in atom_set.atoms)
    exact_texts = ("午后重新涂", *exact_texts[1:])
    model = model_for_atoms(
        atom_set,
        exact_texts=exact_texts,
    )

    result = evaluate_semantic_model(atom_set, model)

    assert result.passed is False
    assert result.issues[0].code == "VISIBLE_TEXT_MUTATED"
    assert result.issues[0].fragment_id == "fragment-0"


def test_semantic_qa_reports_gap_overlap_and_duplicate_coverage():
    atom_set, _, _ = atomized_table()
    atom_set = ContentAtomSetV4(
        projection_sha256=atom_set.projection_sha256,
        atoms=(atom_set.atoms[-1],),
        canonical_sha256=canonical_sha256_v4(
            {"projection_sha256": atom_set.projection_sha256, "atoms": (atom_set.atoms[-1],)}
        ),
    )
    gap = model_for_atoms(
        atom_set,
        starts_ends=((0, 1), (2, len(atom_set.atoms[0].text))),
    )
    overlap = model_for_atoms(
        atom_set,
        starts_ends=((0, 2), (1, len(atom_set.atoms[0].text))),
    )
    duplicate = model_for_atoms(
        atom_set,
        starts_ends=((0, len(atom_set.atoms[0].text)), (0, len(atom_set.atoms[0].text))),
        source_ids=(atom_set.atoms[0].atom_id, atom_set.atoms[0].atom_id),
        fragment_ids=("fragment-0", "fragment-0"),
        exact_texts=(atom_set.atoms[0].text, atom_set.atoms[0].text),
    )

    assert "COVERAGE_GAP" in {issue.code for issue in evaluate_semantic_model(atom_set, gap).issues}
    assert "COVERAGE_OVERLAP" in {issue.code for issue in evaluate_semantic_model(atom_set, overlap).issues}
    assert "COVERAGE_DUPLICATE" in {issue.code for issue in evaluate_semantic_model(atom_set, duplicate).issues}


def test_semantic_qa_rejects_unknown_atom_parent_and_group_references():
    atom_set, _, _ = atomized_table()
    fragments = (
        SemanticFragmentV4(
            fragment_id="fragment-0",
            source_atom_id="atom-does-not-exist",
            start=0,
            end=1,
            exact_text="x",
            semantic_role="note",
            parent_fragment_id="fragment-does-not-exist",
            sequence_index=0,
        ),
        SemanticFragmentV4(
            fragment_id="fragment-1",
            source_atom_id=atom_set.atoms[1].atom_id,
            start=0,
            end=len(atom_set.atoms[1].text),
            exact_text=atom_set.atoms[1].text,
            semantic_role="note",
            sequence_index=1,
        ),
    )
    groups = (
        SemanticGroupV4(
            group_id="group-0",
            group_kind="steps",
            fragment_ids=("fragment-0", "group-fragment-does-not-exist"),
            ordering=0,
        ),
    )
    payload = {
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "fragments": fragments,
        "groups": groups,
    }
    model = SemanticContentModelV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )

    result = evaluate_semantic_model(atom_set, model)
    codes = {issue.code for issue in result.issues}
    assert {"UNKNOWN_ATOM", "PARENT_INVALID", "GROUP_INVALID"} <= codes


def test_semantic_qa_rejects_hash_and_lock_mismatch():
    atom_set, lock, _ = atomized_table()
    model = model_for_atoms(atom_set)
    drifted_model = model.model_copy(
        update={"content_atom_set_sha256": "2" * 64}
    )

    result = evaluate_semantic_model(atom_set, drifted_model, content_lock=lock)

    assert result.passed is False
    assert "HASH_BINDING_MISMATCH" in {issue.code for issue in result.issues}


def test_semantic_qa_prioritizes_visible_mutation_before_stale_model_hash():
    atom_set, _, _ = atomized_table()
    model = model_for_atoms(atom_set)
    fragments = list(model.fragments)
    fragments[0] = fragments[0].model_copy(update={"exact_text": "改写后的文字"})
    stale_model = model.model_copy(update={"fragments": tuple(fragments)})

    result = evaluate_semantic_model(atom_set, stale_model)

    assert result.passed is False
    assert result.issues[0].code == "VISIBLE_TEXT_MUTATED"


def test_semantic_qa_returns_deterministic_failure_for_tampered_nested_model():
    atom_set, _, _ = atomized_table()
    model = model_for_atoms(atom_set)
    tampered = model.model_copy(update={"fragments": ({"bad": "fragment"},)})

    result = evaluate_semantic_model(atom_set, tampered)

    assert result.passed is False
    assert result.issues
    assert all(issue.code == "HASH_BINDING_MISMATCH" for issue in result.issues)


def test_semantic_qa_preserves_table_header_and_row_cell_order():
    atom_set, _, projection = atomized_table()
    valid = evaluate_semantic_model(
        atom_set,
        table_model(atom_set, projection),
        projection=projection,
    )
    missing_table_group = evaluate_semantic_model(
        atom_set,
        model_for_atoms(atom_set),
        projection=projection,
    )

    assert valid.passed is True
    assert "TABLE_RELATION_LOST" in {
        issue.code for issue in missing_table_group.issues
    }


def test_semantic_qa_rejects_table_source_role_mutation_and_missing_row_boundary():
    atom_set, _, projection = atomized_table()
    valid = table_model(atom_set, projection)
    fragments = list(valid.fragments)
    table_fragment_index = next(
        index
        for index, fragment in enumerate(fragments)
        if fragment.source_atom_id == projection.table_groups[0].unit_ids[0]
    )
    fragments[table_fragment_index] = fragments[table_fragment_index].model_copy(
        update={"semantic_role": "heading"}
    )
    wrong_role = recanonicalize(valid, fragments=tuple(fragments))
    missing_row = recanonicalize(
        valid,
        groups=tuple(group for group in valid.groups if group.group_kind != "table_row"),
    )

    wrong_codes = {
        issue.code for issue in evaluate_semantic_model(atom_set, wrong_role, projection=projection).issues
    }
    missing_codes = {
        issue.code for issue in evaluate_semantic_model(atom_set, missing_row, projection=projection).issues
    }
    assert "SOURCE_ROLE_MISMATCH" in wrong_codes
    assert "TABLE_RELATION_LOST" in missing_codes


def test_semantic_qa_requires_step_and_checklist_groups():
    atom_set, _, _ = atomized_structured()
    ungrouped = model_for_atoms(atom_set)
    fragments = ungrouped.fragments
    required_groups = (
        SemanticGroupV4(
            group_id="steps",
            group_kind="steps",
            fragment_ids=tuple(
                fragment.fragment_id
                for fragment in fragments
                if fragment.semantic_role == "step"
            ),
            ordering=0,
        ),
        SemanticGroupV4(
            group_id="checklist",
            group_kind="checklist",
            fragment_ids=tuple(
                fragment.fragment_id
                for fragment in fragments
                if fragment.semantic_role == "checklist_item"
            ),
            ordering=1,
        ),
    )
    grouped = recanonicalize(ungrouped, groups=required_groups)

    missing_codes = {issue.code for issue in evaluate_semantic_model(atom_set, ungrouped).issues}
    assert "STEP_RELATION_LOST" in missing_codes
    assert "CHECKLIST_RELATION_LOST" in missing_codes
    assert evaluate_semantic_model(atom_set, grouped).passed is True


def test_semantic_qa_requires_paired_comparison_label_and_value():
    atom_set, _, _ = atomized_structured()
    fragments = list(model_for_atoms(atom_set).fragments)
    comparison_indexes = [
        index
        for index, fragment in enumerate(fragments)
        if fragment.semantic_role == "paragraph"
    ]
    assert len(comparison_indexes) >= 1
    label_index = comparison_indexes[0]
    fragments[label_index] = fragments[label_index].model_copy(
        update={"semantic_role": "comparison_label"}
    )
    orphan = recanonicalize(model_for_atoms(atom_set), fragments=tuple(fragments))

    orphan_codes = {issue.code for issue in evaluate_semantic_model(atom_set, orphan).issues}
    assert "COMPARISON_RELATION_LOST" in orphan_codes


def test_semantic_qa_rejects_parent_cycles_and_unordered_groups():
    atom_set, _, _ = atomized_table()
    base = model_for_atoms(atom_set)
    fragments = list(base.fragments)
    fragments[0] = fragments[0].model_copy(update={"parent_fragment_id": "fragment-1"})
    fragments[1] = fragments[1].model_copy(update={"parent_fragment_id": "fragment-0"})
    cycle = recanonicalize(base, fragments=tuple(fragments))

    groups = (
        SemanticGroupV4(
            group_id="group-1",
            group_kind="steps",
            fragment_ids=tuple(fragment.fragment_id for fragment in base.fragments),
            ordering=1,
        ),
        SemanticGroupV4(
            group_id="group-0",
            group_kind="steps",
            fragment_ids=(base.fragments[0].fragment_id,),
            ordering=0,
        ),
    )
    unordered_groups = recanonicalize(base, groups=groups)

    cycle_codes = {issue.code for issue in evaluate_semantic_model(atom_set, cycle).issues}
    group_codes = {issue.code for issue in evaluate_semantic_model(atom_set, unordered_groups).issues}
    assert "PARENT_CYCLE" in cycle_codes
    assert "GROUP_ORDER_INVALID" in group_codes


def test_semantic_qa_rejects_table_fragment_reordering_and_noncontinuous_sequence():
    atom_set, _, projection = atomized_table()
    valid = table_model(atom_set, projection)
    table_group = valid.groups[0]
    reversed_group = table_group.model_copy(
        update={"fragment_ids": tuple(reversed(table_group.fragment_ids))}
    )
    fragments = list(valid.fragments)
    fragments[0] = fragments[0].model_copy(update={"sequence_index": 8})
    malformed = recanonicalize(
        valid,
        fragments=tuple(fragments),
        groups=(reversed_group,),
    )

    result = evaluate_semantic_model(atom_set, malformed, projection=projection)
    codes = {issue.code for issue in result.issues}
    assert "TABLE_RELATION_LOST" in codes
    assert "SEQUENCE_INVALID" in codes
