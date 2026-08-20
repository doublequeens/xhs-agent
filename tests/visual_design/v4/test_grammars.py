from __future__ import annotations

import pytest

from src.schemas.v4.layout import GRAMMAR_IDS_V4
from src.visual_design.v4.grammars import GRAMMARS, get_grammar
from src.visual_design.v4.tokens import FAMILY_TOKENS, get_family_tokens
from src.visual_design.style_registry import load_style_registry


@pytest.mark.parametrize("grammar_id", GRAMMAR_IDS_V4)
def test_initial_grammars_define_relationships_without_pixel_boxes(grammar_id: str):
    grammar = GRAMMARS[grammar_id]
    payload = grammar.model_dump(mode="json")
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
    }.intersection(payload)
    assert grammar.allowed_page_roles
    assert grammar.allowed_narrative_roles
    assert grammar.region_roles
    assert grammar.relationships
    assert grammar.alignment_axes
    assert grammar.constraints


def test_grammar_registry_is_exact_and_read_only() -> None:
    assert tuple(GRAMMARS) == (
        "editorial_hero",
        "comparison_grid",
        "step_flow",
    )
    with pytest.raises(TypeError):
        GRAMMARS["other"] = get_grammar("editorial_hero")  # type: ignore[index]
    with pytest.raises(Exception):
        GRAMMARS["editorial_hero"].region_roles += ()  # type: ignore[misc]


def test_family_tokens_are_exactly_the_six_style_registry_families() -> None:
    profiles = load_style_registry()
    assert set(FAMILY_TOKENS) == set(profiles)
    for family, profile in profiles.items():
        tokens = get_family_tokens(family)
        assert tokens.palette == profile.palette
        assert tokens.font_roles.model_dump() == dict(profile.font_roles)
        assert tokens.whitespace_envelope.low == profile.whitespace_range[0]
        assert tokens.whitespace_envelope.high == profile.whitespace_range[1]
        assert tokens.density_envelope.low == profile.density_range[0]
        assert tokens.density_envelope.high == profile.density_range[1]
        assert tokens.spacing_scale
        assert tokens.radii
        assert tokens.motif_rules.allowed
        assert tokens.motif_rules.prohibited


def test_family_token_envelopes_are_ordered_and_registry_is_read_only() -> None:
    for tokens in FAMILY_TOKENS.values():
        assert 0 <= tokens.whitespace_envelope.low
        assert tokens.whitespace_envelope.low <= tokens.whitespace_envelope.high <= 1
        assert 0 <= tokens.density_envelope.low
        assert tokens.density_envelope.low <= tokens.density_envelope.high <= 1
    with pytest.raises(TypeError):
        FAMILY_TOKENS["pink_red"] = get_family_tokens("pink_red")  # type: ignore[index]
