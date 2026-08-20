from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.schemas.v4.content import ContentAtomSetV4, ContentAtomV4, canonical_sha256_v4
from src.schemas.v4.semantic import (
    SEMANTIC_ROLES_V4,
    SemanticContentModelV4,
    SemanticFragmentV4,
    SemanticGroupV4,
    SemanticModelingDraftV4,
)


def make_atom_set(texts: tuple[str, ...] = ("午后补涂防晒", "步骤二")) -> ContentAtomSetV4:
    projection_sha = "1" * 64
    atoms: list[ContentAtomV4] = []
    for index, text in enumerate(texts):
        payload = {
            "atom_id": f"atom-{index}",
            "source_unit_id": f"unit-{index}",
            "source_projection_sha256": projection_sha,
            "source_field": "content",
            "raw_start": index,
            "raw_end": index + len(text),
            "raw_slice_sha256": canonical_sha256_v4({"text": text}),
            "text": text,
            "role": "step",
        }
        atoms.append(ContentAtomV4(**payload, sha256=canonical_sha256_v4(payload)))
    payload = {"projection_sha256": projection_sha, "atoms": tuple(atoms)}
    return ContentAtomSetV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def make_model(atom_set: ContentAtomSetV4) -> SemanticContentModelV4:
    fragments = (
        SemanticFragmentV4(
            fragment_id="fragment-0",
            source_atom_id="atom-0",
            start=0,
            end=2,
            exact_text=atom_set.atoms[0].text[:2],
            semantic_role="step",
            parent_fragment_id=None,
            sequence_index=0,
        ),
        SemanticFragmentV4(
            fragment_id="fragment-1",
            source_atom_id="atom-0",
            start=2,
            end=len(atom_set.atoms[0].text),
            exact_text=atom_set.atoms[0].text[2:],
            semantic_role="note",
            parent_fragment_id="fragment-0",
            sequence_index=1,
        ),
        SemanticFragmentV4(
            fragment_id="fragment-2",
            source_atom_id="atom-1",
            start=0,
            end=len(atom_set.atoms[1].text),
            exact_text=atom_set.atoms[1].text,
            semantic_role="step",
            parent_fragment_id=None,
            sequence_index=2,
        ),
    )
    groups = (
        SemanticGroupV4(
            group_id="group-0",
            group_kind="steps",
            fragment_ids=("fragment-0", "fragment-1", "fragment-2"),
            ordering=0,
        ),
    )
    payload = {
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "fragments": fragments,
        "groups": groups,
    }
    return SemanticContentModelV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def test_semantic_model_reconstructs_exact_codepoint_slices_and_is_hash_bound():
    atom_set = make_atom_set()
    model = make_model(atom_set)

    assert model.fragments[0].exact_text == atom_set.atoms[0].text[0:2]
    assert model.fragments[1].exact_text == atom_set.atoms[0].text[2:]
    assert model.content_atom_set_sha256 == atom_set.canonical_sha256
    assert model.canonical_sha256 == canonical_sha256_v4(
        model.model_dump(mode="json", exclude={"canonical_sha256"})
    )


def test_semantic_draft_has_no_visible_text_field_and_only_allows_frozen_refs():
    draft = SemanticModelingDraftV4(
        fragments=(
            {
                "fragment_id": "fragment-0",
                "source_atom_id": "atom-0",
                "start": 0,
                "end": 2,
                "semantic_role": "heading",
                "parent_fragment_id": None,
                "sequence_index": 0,
            },
        ),
        groups=(),
    )

    assert "exact_text" not in draft.model_dump(mode="json")["fragments"][0]
    with pytest.raises(ValidationError, match="extra"):
        SemanticModelingDraftV4(
            fragments=(
                {
                    "fragment_id": "fragment-0",
                    "source_atom_id": "atom-0",
                    "start": 0,
                    "end": 2,
                    "semantic_role": "heading",
                    "parent_fragment_id": None,
                    "sequence_index": 0,
                    "exact_text": "不应被采纳",
                },
            ),
            groups=(),
        )


def test_semantic_contract_rejects_non_integer_bounds_unknown_roles_and_hash_drift():
    atom_set = make_atom_set()
    with pytest.raises(ValidationError):
        SemanticFragmentV4(
            fragment_id="fragment-0",
            source_atom_id="atom-0",
            start=0.5,
            end=2,
            exact_text="午后",
            semantic_role="heading",
            sequence_index=0,
        )
    with pytest.raises(ValidationError):
        SemanticFragmentV4(
            fragment_id="fragment-0",
            source_atom_id="atom-0",
            start=0,
            end=2,
            exact_text="午后",
            semantic_role="rewrite",
            sequence_index=0,
        )
    model = make_model(atom_set)
    with pytest.raises(ValidationError, match="canonical sha256"):
        drifted = model.model_dump(mode="python")
        drifted["canonical_sha256"] = "0" * 64
        SemanticContentModelV4(
            **drifted,
        )

    assert set(
        (
            "heading",
            "paragraph",
            "step",
            "comparison_label",
            "comparison_value",
            "checklist_item",
            "warning",
            "evidence",
            "closing",
            "note",
        )
    ) <= set(SEMANTIC_ROLES_V4)
