"""Tests for the generic scene-graph font resolver (Task 10)."""

from __future__ import annotations

import pytest

from src.rendering.scene.fonts import (
    GENERIC_FALLBACK,
    MissingFontRoleError,
    format_font_family,
    resolve_font_stack,
)
from src.schemas.visual_style import FamilyStyleProfile, FontRole

# Bring in the TemplateFamily literal values for completeness.
SIX_FAMILIES = (
    "pink_red",
    "deep_teal",
    "soft_pink",
    "coral_impact",
    "green_catalog",
    "white_quote",
)

ALL_ROLES: tuple[FontRole, ...] = ("display", "heading", "body", "caption")


def _style(family: str = "pink_red") -> FamilyStyleProfile:
    return FamilyStyleProfile(
        family=family,
        reference_image_paths=("assets/visual-families/dummy.png",),
        palette=("#F4A7BF", "#DC2333", "#FFF7F8"),
        font_roles={
            "display": "Source Han Serif SC",
            "heading": "Source Han Serif SC",
            "body": "Source Han Sans SC",
            "caption": "Source Han Sans SC",
        },
        composition_principles=("hierarchy", "rhythm"),
        whitespace_range=(0.18, 0.42),
        density_range=(0.45, 0.82),
        allowed_motifs=("oversized type",),
        prohibited_patterns=("thin low-contrast copy",),
    )


@pytest.mark.parametrize("role", ALL_ROLES)
def test_resolve_font_stack_returns_primary_first(role: FontRole):
    style = _style()
    stack = resolve_font_stack(role, style)
    assert isinstance(stack, tuple)
    assert stack[0] == style.font_roles[role]


@pytest.mark.parametrize("role", ALL_ROLES)
def test_resolve_font_stack_appends_deterministic_generic_fallback(role: FontRole):
    style = _style()
    stack = resolve_font_stack(role, style)
    assert stack[-1] == GENERIC_FALLBACK
    # Deterministic length: primary + one generic fallback, no random ordering.
    assert len(stack) == 2


def test_resolve_font_stack_is_deterministic_across_calls():
    style = _style()
    first = [resolve_font_stack(role, style) for role in ALL_ROLES]
    second = [resolve_font_stack(role, style) for role in ALL_ROLES]
    assert first == second


@pytest.mark.parametrize("family", SIX_FAMILIES)
def test_resolve_font_stack_works_for_all_six_families(family: str):
    """All six families share the same generic resolver (no family branch)."""
    style = _style(family=family)
    for role in ALL_ROLES:
        stack = resolve_font_stack(role, style)
        assert stack[0] == style.font_roles[role]


def test_missing_required_font_role_raises_clear_error_naming_role():
    """A missing required font role must fail clearly, naming the role."""
    base = _style()
    broken_roles = {key: value for key, value in base.font_roles.items() if key != "display"}
    # model_construct bypasses the profile validator so we can simulate a
    # caller that hands the compiler a profile missing a required role.
    broken = FamilyStyleProfile.model_construct(
        family=base.family,
        reference_image_paths=base.reference_image_paths,
        palette=base.palette,
        font_roles=broken_roles,
        composition_principles=base.composition_principles,
        whitespace_range=base.whitespace_range,
        density_range=base.density_range,
        allowed_motifs=base.allowed_motifs,
        prohibited_patterns=base.prohibited_patterns,
    )
    with pytest.raises(MissingFontRoleError) as info:
        resolve_font_stack("display", broken)
    assert "display" in str(info.value)


def test_format_font_family_quotes_named_families_and_leaves_generic_unquoted():
    css_value = format_font_family(("Source Han Sans SC", "sans-serif"))
    assert css_value == '"Source Han Sans SC", sans-serif'


def test_format_font_family_escapes_embedded_quotes():
    # A profile-controlled family name should still not be able to break the
    # CSS declaration if it ever contained a quote.
    css_value = format_font_family(('Evil"Name', "sans-serif"))
    assert css_value == '"Evil\\"Name", sans-serif'


def test_format_font_family_is_deterministic():
    stack = ("Source Han Serif SC", "sans-serif")
    assert format_font_family(stack) == format_font_family(stack)
