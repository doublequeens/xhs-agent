from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest
from pydantic import ValidationError

from src.schemas.v4.content import canonical_sha256_v4
from src.schemas.v4.layout import GRAMMAR_IDS_V4, FamilyTokensV4
from src.visual_design.v4.grammars import GRAMMARS, get_grammar
from src.visual_design.v4.tokens import FAMILY_TOKENS, get_family_tokens
from src.visual_design.style_registry import load_style_registry


@pytest.mark.parametrize("grammar_id", GRAMMAR_IDS_V4)
def test_initial_grammars_define_relationships_without_pixel_boxes(grammar_id: str):
    grammar = GRAMMARS[grammar_id]
    payload = grammar.model_dump(mode="json")
    _assert_no_render_payload(payload)
    assert grammar.allowed_page_roles
    assert grammar.allowed_narrative_roles
    assert grammar.region_roles
    assert grammar.relationships
    assert grammar.alignment_axes
    assert grammar.constraints


def _assert_no_render_payload(value: object) -> None:
    banned_keys = {
        "x", "y", "w", "h", "width", "height", "coordinates", "coordinate",
        "box", "scene_box", "html", "css", "dom", "script", "provider",
        "url", "path", "local_path", "provenance", "visible_copy", "visible_text",
    }
    if isinstance(value, Mapping):
        for key, item in value.items():
            assert str(key).lower() not in banned_keys
            _assert_no_render_payload(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            _assert_no_render_payload(item)
        return
    if isinstance(value, str):
        lowered = value.lower()
        for marker in ("<html", "<script", "javascript:", "http://", "https://", "file://", "../"):
            assert marker not in lowered


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


def test_family_tokens_have_canonical_hash_and_reject_executable_principles() -> None:
    for tokens in FAMILY_TOKENS.values():
        assert len(tokens.canonical_sha256) == 64
        _assert_no_render_payload(tokens.model_dump(mode="json"))
        payload = tokens.model_dump(mode="python")
        payload["composition_principles"] = ("<script>run()</script>",)
        with pytest.raises(ValidationError):
            FamilyTokensV4.model_validate(payload)


@pytest.mark.parametrize(
    "principle",
    ("<div>layout</div>", "/tmp/layout.py", "eval('layout')", "__import__('os')"),
)
def test_family_tokens_reject_nested_principle_payloads_even_with_recomputed_hash(
    principle: str,
) -> None:
    payload = FAMILY_TOKENS["pink_red"].model_dump(mode="python")
    payload["composition_principles"] = (principle,)
    payload["canonical_sha256"] = canonical_sha256_v4(
        {key: value for key, value in payload.items() if key != "canonical_sha256"}
    )
    with pytest.raises(ValidationError, match="principles|markup|paths"):
        FamilyTokensV4.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("composition_principles", "display:grid;color:red"),
        ("motif_rules.allowed", "document.body.innerHTML='owned'"),
        ("motif_rules.prohibited", "provider=pexels provenance=ai"),
        ("font_roles.display", "onclick=owned()"),
        ("font_roles.heading", "<script>alert(1)</script>"),
        ("font_roles.body", "https://evil.example/font"),
        ("font_roles.caption", "/tmp/font.ttf"),
    ),
)
def test_all_family_style_text_uses_an_allowlist_even_with_recomputed_hash(
    field: str,
    value: str,
) -> None:
    payload = FAMILY_TOKENS["pink_red"].model_dump(mode="python")
    if field == "composition_principles":
        payload[field] = (value,)
    elif field.startswith("motif_rules."):
        motif_field = field.split(".", 1)[1]
        payload["motif_rules"][motif_field] = (value,)
    else:
        font_field = field.split(".", 1)[1]
        payload["font_roles"][font_field] = value
    payload["canonical_sha256"] = canonical_sha256_v4(
        {key: item for key, item in payload.items() if key != "canonical_sha256"}
    )
    with pytest.raises(ValidationError, match="allowlist|style|font|token"):
        FamilyTokensV4.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("composition_principles", "provider pexels provenance ai"),
        ("motif_rules.allowed", "javascript alert"),
        ("motif_rules.prohibited", "dom html css"),
        ("font_roles.display", "onclick owned"),
    ),
)
def test_semantic_style_tokens_are_rejected_without_punctuation_even_with_hash(
    field: str,
    value: str,
) -> None:
    payload = FAMILY_TOKENS["pink_red"].model_dump(mode="python")
    if field == "composition_principles":
        payload[field] = (value,)
    elif field.startswith("motif_rules."):
        motif_field = field.split(".", 1)[1]
        payload["motif_rules"][motif_field] = (value,)
    else:
        font_field = field.split(".", 1)[1]
        payload["font_roles"][font_field] = value
    payload["canonical_sha256"] = canonical_sha256_v4(
        {key: item for key, item in payload.items() if key != "canonical_sha256"}
    )
    with pytest.raises(ValidationError, match="forbidden|semantic|token"):
        FamilyTokensV4.model_validate(payload)


def test_grammar_roles_are_typed_and_family_neutral() -> None:
    assert GRAMMARS["editorial_hero"].allowed_page_roles == ("cover", "body", "closing")
    assert GRAMMARS["editorial_hero"].allowed_narrative_roles == (
        "cover_hook", "context", "summary", "closing"
    )
    assert GRAMMARS["comparison_grid"].allowed_page_roles == ("body",)
    assert GRAMMARS["comparison_grid"].allowed_narrative_roles == (
        "diagnosis", "comparison", "evidence"
    )
    assert GRAMMARS["step_flow"].allowed_page_roles == ("body",)
    assert GRAMMARS["step_flow"].allowed_narrative_roles == ("step", "checklist")
