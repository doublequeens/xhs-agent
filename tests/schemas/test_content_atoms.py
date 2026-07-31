import pytest
from pydantic import ValidationError

from src.schemas.content_atoms import (
    ContentAtom,
    ContentAtomSet,
    canonical_sha256,
    sha256_text,
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
