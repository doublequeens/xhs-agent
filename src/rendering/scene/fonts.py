"""Deterministic font resolution for the generic scene compiler.

The compiler resolves each ``TextStyle.font_role`` against the
``FamilyStyleProfile.font_roles`` map. Resolution is deterministic: there is no
network fetch, no clock, no randomness, and no family-specific branch. Every
stack is the chosen family name followed by one universal generic CSS keyword
so Chromium can fall back predictably when a named family is unavailable.

This module is deliberately self-contained (it must not import from the
soon-to-be-deleted family-template packages under ``editorial``).
"""

from __future__ import annotations

from typing import Final

from src.schemas.visual_style import FamilyStyleProfile, FontRole

#: The single deterministic CSS generic-family keyword appended to every stack.
#: It is role-agnostic and family-agnostic on purpose: the profile gives no
#: reliable signal for serif vs. sans-serif, so picking one universal generic
#: keeps the resolver free of per-family branching.
GENERIC_FALLBACK: Final[str] = "sans-serif"

#: CSS generic-family keywords that must never be quoted when emitted.
_GENERIC_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "serif",
        "sans-serif",
        "monospace",
        "cursive",
        "fantasy",
        "system-ui",
        "ui-serif",
        "ui-sans-serif",
        "ui-monospace",
        "ui-rounded",
    }
)


class MissingFontRoleError(ValueError):
    """Raised when a required font role is absent from the family profile."""


def resolve_font_stack(
    role: FontRole, style: FamilyStyleProfile
) -> tuple[str, ...]:
    """Resolve a deterministic font-family stack for ``role``.

    The first element is the family name mapped to ``role`` in ``style``. The
    last element is always :data:`GENERIC_FALLBACK`. A missing required role
    raises :class:`MissingFontRoleError` naming the role explicitly.
    """
    font_roles = style.font_roles
    if role not in font_roles:
        raise MissingFontRoleError(
            f"family style profile is missing required font role: {role!r}"
        )
    primary = font_roles[role]
    if not isinstance(primary, str) or not primary.strip():
        raise MissingFontRoleError(
            f"family style profile has an empty font role mapping: {role!r}"
        )
    return (primary, GENERIC_FALLBACK)


def format_font_family(stack: tuple[str, ...]) -> str:
    """Render a font stack as a CSS ``font-family`` value.

    Generic keywords are emitted unquoted; every other name is wrapped in
    double quotes with any embedded backslash or quote escaped, so a
    profile-controlled name can never break out of the CSS string.
    """
    rendered: list[str] = []
    for name in stack:
        if name in _GENERIC_KEYWORDS:
            rendered.append(name)
            continue
        escaped = name.replace("\\", "\\\\").replace('"', '\\"')
        rendered.append(f'"{escaped}"')
    return ", ".join(rendered)
