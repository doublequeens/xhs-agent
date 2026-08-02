import pytest
from pydantic import ValidationError

from src.schemas.content_atoms import (
    ContentAtom,
    ContentAtomSet,
    ContentFragment,
    canonical_sha256,
    sha256_text,
)


def _atom(atom_id, text, role="paragraph"):
    return ContentAtom(
        atom_id=atom_id,
        text=text,
        role=role,
        sha256=sha256_text(text),
    )


def _atom_set(*atoms):
    return ContentAtomSet(
        atoms=atoms,
        canonical_sha256=canonical_sha256(
            [atom.model_dump(mode="json") for atom in atoms]
        ),
    )


def test_content_atom_set_rejects_mutated_hash():
    atom = ContentAtom(
        atom_id="title",
        text="刺痛不是正常建立耐受",
        role="title",
        sha256=sha256_text("刺痛不是正常建立耐受"),
    )

    with pytest.raises(ValidationError, match="atom sha256"):
        ContentAtomSet(
            atoms=[atom.model_copy(update={"text": "刺痛很正常"})],
            canonical_sha256=canonical_sha256(
                [atom.model_dump(mode="json")]
            ),
        )


def test_content_atom_set_rejects_direct_nested_atom_mutation():
    atom_set = _atom_set(_atom("title", "刺痛不是正常建立耐受", role="title"))

    with pytest.raises(ValidationError, match="frozen"):
        atom_set.atoms[0].text = "刺痛很正常"


def test_content_atom_set_rejects_duplicate_atom_ids():
    first = _atom("body", "先暂停使用")
    second = _atom("body", "观察刺痛是否缓解")

    with pytest.raises(ValidationError, match="atom IDs must be unique"):
        _atom_set(first, second)


def test_fragment_validation_rejects_unknown_source_atom():
    atom_set = _atom_set(_atom("body", "先暂停使用"))
    fragments = [
        ContentFragment(
            fragment_id="fragment-1",
            source_atom_id="unknown",
            start=0,
            end=5,
            text="先暂停使用",
        )
    ]

    with pytest.raises(ValueError, match="unknown source atom"):
        atom_set.validate_complete_fragments(fragments)


def test_fragment_validation_rejects_invalid_bounds_and_text():
    atom_set = _atom_set(_atom("body", "先暂停使用"))
    invalid_bounds = [
        ContentFragment(
            fragment_id="fragment-1",
            source_atom_id="body",
            start=0,
            end=6,
            text="先暂停使用。",
        )
    ]
    invalid_text = [
        ContentFragment(
            fragment_id="fragment-2",
            source_atom_id="body",
            start=0,
            end=5,
            text="先继续使用",
        )
    ]

    with pytest.raises(ValueError, match="fragment bounds"):
        atom_set.validate_complete_fragments(invalid_bounds)
    with pytest.raises(ValueError, match="text must exactly match"):
        atom_set.validate_complete_fragments(invalid_text)


def test_fragment_validation_requires_complete_ordered_reconstruction():
    atom_set = _atom_set(
        _atom("title", "刺痛不是正常建立耐受", role="title"),
        _atom("body", "先暂停使用"),
    )
    complete = [
        ContentFragment(
            fragment_id="title-1",
            source_atom_id="title",
            start=0,
            end=2,
            text="刺痛",
        ),
        ContentFragment(
            fragment_id="body-1",
            source_atom_id="body",
            start=0,
            end=5,
            text="先暂停使用",
        ),
        ContentFragment(
            fragment_id="title-2",
            source_atom_id="title",
            start=2,
            end=10,
            text="不是正常建立耐受",
        ),
    ]

    atom_set.validate_complete_fragments(complete)


def test_fragment_validation_rejects_duplicate_fragment_ids():
    atom_set = _atom_set(_atom("body", "先暂停使用"))
    fragments = [
        ContentFragment(
            fragment_id="fragment",
            source_atom_id="body",
            start=0,
            end=2,
            text="先暂",
        ),
        ContentFragment(
            fragment_id="fragment",
            source_atom_id="body",
            start=2,
            end=5,
            text="停使用",
        ),
    ]

    with pytest.raises(ValueError, match="fragment IDs must be unique"):
        atom_set.validate_complete_fragments(fragments)
