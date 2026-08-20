import pytest
from pydantic import ValidationError

from src.schemas.v4.content import (
    ContentAtomSetV4,
    ContentAtomV4,
    MarkdownTableGroupV4,
    VisibleCopyProjectionV4,
    VisibleCopyUnitV4,
    canonical_sha256_v4,
    sha256_text_v4,
)


def _unit_payload(**updates):
    payload = {
        "unit_id": "paragraph-001",
        "source_field": "content",
        "raw_start": 0,
        "raw_end": 2,
        "raw_slice_sha256": sha256_text_v4("好呀"),
        "text": "好呀",
        "structural_role": "paragraph",
        "sequence": 0,
    }
    payload.update(updates)
    payload["sha256"] = canonical_sha256_v4(payload)
    return payload


def _unit(**updates):
    return VisibleCopyUnitV4(**_unit_payload(**updates))


def _table_group_payload(**updates):
    payload = {
        "group_id": "table-001",
        "source_field": "content",
        "raw_start": 0,
        "raw_end": 12,
        "raw_slice_sha256": sha256_text_v4("| A | B |\n|---|---|"),
        "rows": (("A", "B"),),
        "unit_ids": ("table_header-001", "table_header-002"),
    }
    payload.update(updates)
    payload["sha256"] = canonical_sha256_v4(payload)
    return payload


def test_v4_models_are_frozen_and_reject_extra_fields():
    unit = _unit()

    with pytest.raises(ValidationError, match="frozen"):
        unit.text = "改字"
    with pytest.raises(ValidationError, match="extra"):
        VisibleCopyUnitV4(**_unit_payload(extra="拒绝"))


def test_unit_hash_binds_provenance_and_visible_copy():
    unit = _unit()
    bad = _unit_payload(raw_start=1)
    bad["sha256"] = unit.sha256

    expected_payload = _unit_payload()
    expected_payload.pop("sha256")
    assert unit.sha256 == canonical_sha256_v4(expected_payload)
    with pytest.raises(ValidationError, match="sha256"):
        VisibleCopyUnitV4(**bad)


def test_atom_hash_rejects_provenance_drift_even_with_a_valid_sha256_shape():
    payload = {
        "atom_id": "paragraph-001",
        "source_unit_id": "paragraph-001",
        "source_projection_sha256": sha256_text_v4("projection"),
        "source_field": "content",
        "raw_start": 0,
        "raw_end": 2,
        "raw_slice_sha256": sha256_text_v4("好呀"),
        "text": "好呀",
        "role": "paragraph",
    }
    atom = ContentAtomV4(**payload, sha256=canonical_sha256_v4(payload))
    drifted = {**payload, "raw_start": 1, "sha256": atom.sha256}

    with pytest.raises(ValidationError, match="atom sha256"):
        ContentAtomV4(**drifted)


def test_table_group_requires_rectangular_rows_and_matching_unit_ids():
    with pytest.raises(ValidationError, match="rectangular"):
        MarkdownTableGroupV4(
            **_table_group_payload(rows=(("A", "B"), ("C",)), unit_ids=("x", "y", "z"))
        )


def test_projection_hash_binds_all_source_hashes_and_nested_contracts():
    units = (_unit(),)
    payload = {
        "units": units,
        "table_groups": (),
        "title_sha256": sha256_text_v4("标题"),
        "cover_copy_sha256": sha256_text_v4("封面"),
        "content_sha256": sha256_text_v4("好呀"),
    }
    projection = VisibleCopyProjectionV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )

    assert projection.canonical_visible_copy_sha256 == canonical_sha256_v4(
        ({
            "sequence": units[0].sequence,
            "source_field": units[0].source_field,
            "structural_role": units[0].structural_role,
            "text": units[0].text,
        },)
    )
    assert projection.canonical_visible_copy_sha256 != projection.canonical_sha256
    with pytest.raises(ValidationError, match="canonical sha256"):
        VisibleCopyProjectionV4(
            **payload,
            canonical_sha256=sha256_text_v4("漂移"),
        )


def test_atom_requires_source_unit_span_and_projection_binding():
    projection_sha = sha256_text_v4("projection")
    payload = {
        "atom_id": "paragraph-001",
        "source_unit_id": "paragraph-001",
        "source_projection_sha256": projection_sha,
        "source_field": "content",
        "raw_start": 0,
        "raw_end": 2,
        "raw_slice_sha256": sha256_text_v4("好呀"),
        "text": "好呀",
        "role": "paragraph",
    }
    atom = ContentAtomV4(**payload, sha256=canonical_sha256_v4(payload))
    atom_set_payload = {
        "projection_sha256": projection_sha,
        "atoms": (atom,),
    }
    atom_set = ContentAtomSetV4(
        **atom_set_payload,
        canonical_sha256=canonical_sha256_v4(atom_set_payload),
    )

    assert atom_set.atoms[0].source_unit_id == "paragraph-001"
    with pytest.raises(ValidationError, match="atom sha256"):
        ContentAtomV4(**payload, sha256=sha256_text_v4("错误"))
