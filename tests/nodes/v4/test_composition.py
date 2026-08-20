from __future__ import annotations

import pytest

from src.nodes.v4.composition import build_layout_program
from src.schemas.v4.content import canonical_sha256_v4
from src.schemas.v4.direction import AssetDirectiveV4, PageBriefV4


def _page_brief(
    *,
    preferred: tuple[str, ...] = ("editorial_hero",),
    with_asset: bool = True,
) -> PageBriefV4:
    directives = ()
    if with_asset:
        directive = AssetDirectiveV4(
            directive_id="asset-1",
            page_id="page-1",
            role="evidence_example",
            purpose="evidence",
            supports_fragment_refs=("fragment-1",),
            required=True,
            preferred_source="search",
            query_or_prompt="text-free skincare evidence photo",
        )
        directives = (directive,)
    payload = {
        "page_id": "page-1",
        "sequence": 1,
        "narrative_role": "opening",
        "beat_ref": "beat-1",
        "fragment_refs": ("fragment-1", "fragment-2"),
        "visual_priority": ("fragment-1",),
        "density_budget": "medium",
        "preferred_compositions": preferred,
        "forbidden_patterns": (),
        "asset_directives": directives,
        "continuity_with_previous": "none",
    }
    return PageBriefV4(**payload, canonical_sha256=canonical_sha256_v4(payload))


def test_composition_rejects_grammar_not_allowed_by_page_brief() -> None:
    with pytest.raises(ValueError, match="preferred compositions"):
        build_layout_program(
            _page_brief(preferred=("step_flow",)),
            grammar_id="comparison_grid",
        )


def test_composition_rejects_allowed_but_not_yet_implemented_grammar() -> None:
    with pytest.raises(ValueError, match="implemented"):
        build_layout_program(
            _page_brief(preferred=("diagnostic_matrix",)),
            grammar_id="diagnostic_matrix",
        )


def test_composition_owns_each_fragment_and_page_asset_once() -> None:
    program = build_layout_program(_page_brief(), grammar_id="editorial_hero")
    assert tuple(item.fragment_ref for item in program.fragment_placements) == (
        "fragment-1",
        "fragment-2",
    )
    assert tuple(item.directive_id for item in program.asset_placements) == ("asset-1",)
    assert program.page_brief_sha256 == _page_brief().canonical_sha256
    serialized = program.model_dump(mode="json")
    assert not {
        "x",
        "y",
        "w",
        "h",
        "width",
        "height",
        "coordinates",
        "html",
        "css",
        "dom",
        "provider",
        "local_path",
        "provenance",
    }.intersection(serialized)


def test_composition_is_deterministic_and_binds_exact_brief_hash() -> None:
    page = _page_brief(with_asset=False)
    first = build_layout_program(page, grammar_id="editorial_hero", family="pink_red")
    second = build_layout_program(page, grammar_id="editorial_hero", family="pink_red")
    assert first.model_dump_json() == second.model_dump_json()
    assert first.canonical_sha256 == second.canonical_sha256

    tampered = page.model_copy(update={"narrative_role": "changed"})
    with pytest.raises(ValueError, match="page brief|canonical"):
        build_layout_program(tampered, grammar_id="editorial_hero")


def test_composition_revalidates_json_persisted_page_brief() -> None:
    page = _page_brief(with_asset=False)
    program = build_layout_program(
        page.model_dump(mode="json"),
        grammar_id="editorial_hero",
    )
    assert program.page_brief_sha256 == page.canonical_sha256


def test_composition_rejects_dangling_or_duplicate_asset_ownership() -> None:
    page = _page_brief()
    raw = page.model_dump(mode="python")
    raw["asset_directives"] = (
        page.asset_directives[0].model_copy(update={"directive_id": "asset-1"}),
        page.asset_directives[0].model_copy(update={"directive_id": "asset-1"}),
    )
    raw.pop("canonical_sha256")
    with pytest.raises(ValueError, match="asset|directive|canonical"):
        build_layout_program(
            PageBriefV4(**raw, canonical_sha256=canonical_sha256_v4(raw)),
            grammar_id="editorial_hero",
        )
