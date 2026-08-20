"""Immutable v4 design tokens derived from the approved style registry.

The existing ``style_registry`` remains the sole authority for family palette,
font roles, motifs and density/whitespace envelopes.  This module only
projects those values into the v4 structural token contract and adds abstract
scale names consumed by the future deterministic compiler.
"""

from __future__ import annotations

from types import MappingProxyType

from src.schemas.v4.content import canonical_sha256_v4
from src.schemas.v4.layout import (
    ABSTRACT_RADII_V4,
    ABSTRACT_SPACING_SCALE_V4,
    FamilyTokensV4,
    MotifRulesV4,
    OrderedEnvelopeV4,
    TypographyRolesV4,
)
from src.visual_design.style_registry import load_style_registry


def _from_profile(profile) -> FamilyTokensV4:
    payload = {
        "family": profile.family,
        "palette": profile.palette,
        "font_roles": TypographyRolesV4.model_validate(profile.font_roles),
        "spacing_scale": ABSTRACT_SPACING_SCALE_V4,
        "radii": ABSTRACT_RADII_V4,
        "motif_rules": MotifRulesV4(
            allowed=profile.allowed_motifs,
            prohibited=profile.prohibited_patterns,
        ),
        "whitespace_envelope": OrderedEnvelopeV4(
            low=profile.whitespace_range[0],
            high=profile.whitespace_range[1],
        ),
        "density_envelope": OrderedEnvelopeV4(
            low=profile.density_range[0],
            high=profile.density_range[1],
        ),
        "composition_principles": profile.composition_principles,
    }
    # Build the digest from the fully normalized model payload so every
    # canonical registry entry has one deterministic revision identity.
    normalized = FamilyTokensV4.model_construct(
        **payload,
        canonical_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"canonical_sha256"})
    return FamilyTokensV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(normalized),
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
