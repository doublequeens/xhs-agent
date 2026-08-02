import pytest
from pydantic import ValidationError

from src.schemas.content_atoms import (
    ContentAtom,
    ContentAtomSet,
    ContentFragment,
    canonical_sha256,
    sha256_text,
)
from src.schemas.visual_director import PageDirection, VisualDirectionPlan
from src.schemas.visual_style import FamilyStyleProfile


SHA_A = "a" * 64


def make_atom_set() -> ContentAtomSet:
    atoms = tuple(
        ContentAtom(
            atom_id=f"atom-{index}",
            text=text,
            role="paragraph",
            sha256=sha256_text(text),
        )
        for index, text in enumerate(
            ("先温和清洁。", "再充分保湿。", "白天注意防晒。", "观察皮肤反应。", "持续记录变化。"),
            start=1,
        )
    )
    return ContentAtomSet(
        atoms=atoms,
        canonical_sha256=canonical_sha256(
            [atom.model_dump(mode="json") for atom in atoms]
        ),
    )


def make_fragments(atom_set: ContentAtomSet) -> tuple[ContentFragment, ...]:
    return tuple(
        ContentFragment(
            fragment_id=f"fragment-{index}",
            source_atom_id=atom.atom_id,
            start=0,
            end=len(atom.text),
            text=atom.text,
        )
        for index, atom in enumerate(atom_set.atoms, start=1)
    )


def make_pages(page_count: int = 5) -> tuple[PageDirection, ...]:
    return tuple(
        PageDirection(
            page_id=f"page-{index}",
            sequence=index,
            purpose=f"purpose-{index}",
            visual_job=f"job-{index}",
            fragment_ids=(f"fragment-{index}",),
        )
        for index in range(1, page_count + 1)
    )


def make_family_profile() -> FamilyStyleProfile:
    return FamilyStyleProfile(
        family="pink_red",
        reference_image_paths=("assets/reference.png",),
        palette=("#FFF0F3", "#C9184A", "#590D22"),
        font_roles={
            "display": "Display Font",
            "heading": "Heading Font",
            "body": "Body Font",
            "caption": "Caption Font",
        },
        composition_principles=("strong hierarchy", "generous margins"),
        whitespace_range=(0.2, 0.5),
        density_range=(0.3, 0.7),
        allowed_motifs=("sparkle", "bracket"),
        prohibited_patterns=("fixed grid",),
    )


def make_direction_plan(**updates) -> VisualDirectionPlan:
    atom_set = make_atom_set()
    payload = {
        "template_family": "pink_red",
        "page_count": 5,
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "art_direction": "Warm editorial skincare guide",
        "palette": ("#FFF0F3", "#C9184A"),
        "typography_direction": {
            "display": "high contrast",
            "body": "quiet and readable",
        },
        "motifs": ("sparkle",),
        "content_fragments": make_fragments(atom_set),
        "page_sequence": make_pages(),
        "asset_directives": (),
        "recent_visual_context": (),
    }
    payload.update(updates)
    return VisualDirectionPlan.model_validate(payload)


@pytest.mark.parametrize("page_count", [4, 19])
def test_direction_rejects_out_of_range_page_count(page_count):
    pages = tuple(
        PageDirection(
            page_id=f"page-{index}",
            sequence=index,
            purpose=f"purpose-{index}",
            visual_job=f"job-{index}",
            fragment_ids=(f"fragment-{index}",),
        )
        for index in range(1, page_count + 1)
    )
    with pytest.raises(ValidationError):
        make_direction_plan(page_count=page_count, page_sequence=pages)


def test_fragments_reconstruct_atoms_character_for_character():
    atom_set = make_atom_set()
    fragments = list(make_fragments(atom_set))
    fragments[0] = fragments[0].model_copy(update={"text": "先过度清洁。"})
    plan = make_direction_plan(content_fragments=tuple(fragments))

    with pytest.raises(
        ValueError,
        match="content fragment text must exactly match source atom slice",
    ):
        plan.validate_against(atom_set, make_family_profile())


@pytest.mark.parametrize(
    ("page_update", "message"),
    [
        ({"fragment_ids": ()}, "each page must own at least one content fragment"),
        ({"visual_job": "job-1"}, "page visual jobs must be unique"),
    ],
)
def test_page_requires_content_and_unique_visual_job(page_update, message):
    pages = list(make_pages())
    pages[1] = pages[1].model_copy(update=page_update)

    with pytest.raises(ValidationError, match=message):
        make_direction_plan(page_sequence=tuple(pages))


def test_direction_rejects_family_values_outside_profile():
    plan = make_direction_plan(palette=("#FFF0F3", "#000000"))

    with pytest.raises(ValueError, match="palette must be a subset of family profile"):
        plan.validate_against(make_atom_set(), make_family_profile())


def test_visual_contracts_reject_scalar_coercion():
    with pytest.raises(ValidationError) as exc_info:
        make_direction_plan(page_count="5")

    error = exc_info.value.errors()[0]
    assert error["loc"] == ("page_count",)
    assert error["type"] == "int_type"


def test_direction_and_family_mappings_are_deeply_immutable_and_serializable():
    profile = make_family_profile()
    plan = make_direction_plan()

    with pytest.raises(
        TypeError,
        match="'mappingproxy' object does not support item assignment",
    ):
        profile.font_roles["display"] = "Mutated Font"
    with pytest.raises(
        TypeError,
        match="'mappingproxy' object does not support item assignment",
    ):
        plan.typography_direction["display"] = "mutated"

    assert profile.model_dump(mode="json")["font_roles"]["display"] == "Display Font"
    assert (
        plan.model_dump(mode="json")["typography_direction"]["display"]
        == "high contrast"
    )
