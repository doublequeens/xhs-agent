"""Immutable v4 design tokens derived from the approved style registry.

The existing ``style_registry`` remains the sole authority for family palette,
font roles, motifs and density/whitespace envelopes.  This module only
projects those values into the v4 structural token contract and adds abstract
scale names consumed by the future deterministic compiler.
"""

from __future__ import annotations

from types import MappingProxyType

from src.schemas.v4.layout import FamilyTokensV4, MotifRulesV4, OrderedEnvelopeV4, TypographyRolesV4
from src.visual_design.style_registry import load_style_registry


_ABSTRACT_SPACING_SCALE = ("none", "xs", "sm", "md", "lg", "xl", "xxl")
_ABSTRACT_RADII = ("none", "sm", "md", "lg", "pill")


def _from_profile(profile) -> FamilyTokensV4:
    return FamilyTokensV4(
        family=profile.family,
        palette=profile.palette,
        font_roles=TypographyRolesV4.model_validate(profile.font_roles),
        spacing_scale=_ABSTRACT_SPACING_SCALE,
        radii=_ABSTRACT_RADII,
        motif_rules=MotifRulesV4(
            allowed=profile.allowed_motifs,
            prohibited=profile.prohibited_patterns,
        ),
        whitespace_envelope=OrderedEnvelopeV4(
            low=profile.whitespace_range[0],
            high=profile.whitespace_range[1],
        ),
        density_envelope=OrderedEnvelopeV4(
            low=profile.density_range[0],
            high=profile.density_range[1],
        ),
        composition_principles=profile.composition_principles,
    )


def _build_registry() -> MappingProxyType[str, FamilyTokensV4]:
    profiles = load_style_registry()
    tokens = {_family: _from_profile(profile) for _family, profile in profiles.items()}
    if len(tokens) != 6:
        raise ValueError("v4 family token registry must contain exactly six families")
    return MappingProxyType(tokens)


FAMILY_TOKENS = _build_registry()
TOKENS = FAMILY_TOKENS
FAMILY_TOKEN_REGISTRY = FAMILY_TOKENS


def get_family_tokens(family: str) -> FamilyTokensV4:
    try:
        return FAMILY_TOKENS[family]
    except KeyError as exc:
        raise ValueError(f"unknown v4 template family: {family}") from exc


def load_family_tokens() -> MappingProxyType[str, FamilyTokensV4]:
    """Return the read-only token registry."""

    return FAMILY_TOKENS


__all__ = [
    "FAMILY_TOKENS",
    "FAMILY_TOKEN_REGISTRY",
    "TOKENS",
    "get_family_tokens",
    "load_family_tokens",
]
