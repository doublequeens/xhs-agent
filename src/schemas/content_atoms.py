import hashlib
import json
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_sha256(value: BaseModel | dict | list) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ContentAtom(StrictModel):
    atom_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    text: str = Field(min_length=1)
    role: Literal[
        "title", "cover", "heading", "paragraph", "list_item", "step", "quote"
    ]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify_hash(self):
        if self.sha256 != sha256_text(self.text):
            raise ValueError("atom sha256 does not match text")
        return self


class ContentFragment(StrictModel):
    fragment_id: str
    source_atom_id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)


class ContentAtomSet(StrictModel):
    atoms: tuple[ContentAtom, ...] = Field(min_length=1)
    canonical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify_canonical_hash(self):
        atom_ids = [atom.atom_id for atom in self.atoms]
        if len(atom_ids) != len(set(atom_ids)):
            raise ValueError("content atom set atom IDs must be unique")
        expected = canonical_sha256(
            [atom.model_dump(mode="json") for atom in self.atoms]
        )
        if self.canonical_sha256 != expected:
            raise ValueError("content atom set canonical sha256 does not match atoms")
        return self

    def validate_complete_fragments(
        self,
        fragments: Sequence[ContentFragment],
    ) -> None:
        """Validate an exact, complete visual fragmentation of every content atom."""
        atom_by_id = {atom.atom_id: atom for atom in self.atoms}
        if len(atom_by_id) != len(self.atoms):
            raise ValueError("content atom set atom IDs must be unique")

        fragment_ids = [fragment.fragment_id for fragment in fragments]
        if len(fragment_ids) != len(set(fragment_ids)):
            raise ValueError("content fragment IDs must be unique")

        fragments_by_atom: dict[str, list[ContentFragment]] = {
            atom_id: [] for atom_id in atom_by_id
        }
        for fragment in fragments:
            atom = atom_by_id.get(fragment.source_atom_id)
            if atom is None:
                raise ValueError(
                    f"content fragment has unknown source atom: {fragment.source_atom_id}"
                )
            if fragment.end > len(atom.text) or fragment.start >= fragment.end:
                raise ValueError("content fragment bounds are outside source atom text")
            if fragment.text != atom.text[fragment.start:fragment.end]:
                raise ValueError("content fragment text must exactly match source atom slice")
            fragments_by_atom[atom.atom_id].append(fragment)

        for atom in self.atoms:
            cursor = 0
            reconstructed: list[str] = []
            for fragment in fragments_by_atom[atom.atom_id]:
                if fragment.start != cursor:
                    raise ValueError(
                        "content fragments must be ordered and non-overlapping"
                    )
                cursor = fragment.end
                reconstructed.append(fragment.text)
            if cursor != len(atom.text) or "".join(reconstructed) != atom.text:
                raise ValueError(
                    "content fragments must completely reconstruct each source atom"
                )
