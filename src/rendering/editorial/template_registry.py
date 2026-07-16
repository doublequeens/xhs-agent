from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, get_args

from src.schemas.editorial_templates import PageArchetype, TemplateFamily


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_FONT_ROOT = REPOSITORY_ROOT / "assets/fonts/templates"
EDITORIAL_V1_FONT_ROOT = (
    REPOSITORY_ROOT / "assets/fonts/beauty-editorial-v1"
)
EDITORIAL_V2_FONT_ROOT = (
    REPOSITORY_ROOT / "assets/fonts/beauty-editorial-v2"
)
EMOJI_FONT_PATH = EDITORIAL_V2_FONT_ROOT / "NotoColorEmoji.ttf"
EMOJI_LICENSE_PATH = (
    EDITORIAL_V2_FONT_ROOT / "LICENSE-Noto-Emoji.txt"
)


@dataclass(frozen=True)
class ArchetypeCapability:
    composition_variants: tuple[str, ...]
    sparse_max_graphemes: int
    standard_max_graphemes: int
    dense_max_graphemes: int
    min_font_px: int


@dataclass(frozen=True)
class TemplateDefinition:
    family: TemplateFamily
    colors: Mapping[str, str]
    fonts: Mapping[str, Path]
    archetypes: Mapping[PageArchetype, ArchetypeCapability]


FAMILY_COMPOSITION_VARIANTS: Mapping[
    TemplateFamily, tuple[str, ...]
] = MappingProxyType(
    {
        "pink_red": (
            "centered-number",
            "red-panel",
            "white-card",
            "split-card",
        ),
        "deep_teal": (
            "centered-minimal",
            "numbered-column",
            "rule-grid",
        ),
        "soft_pink": ("offset-cover", "floating-card", "soft-grid"),
        "coral_impact": (
            "impact-cover",
            "stacked-impact",
            "contrast-impact",
        ),
        "green_catalog": (
            "folder-cover",
            "catalog-card",
            "catalog-grid",
        ),
        "white_quote": (
            "centered-focus",
            "editorial-column",
            "quiet-grid",
        ),
    }
)


_COLORS: Mapping[TemplateFamily, Mapping[str, str]] = MappingProxyType(
    {
        "pink_red": {
            "background": "#FFF4F5",
            "primary": "#E6284F",
            "secondary": "#F4A6B8",
            "ink": "#35151D",
        },
        "deep_teal": {
            "background": "#0C3F43",
            "primary": "#F4E8D0",
            "secondary": "#73B6AD",
            "ink": "#F8F4E9",
        },
        "soft_pink": {
            "background": "#F8E4E8",
            "primary": "#A65369",
            "secondary": "#F2B8C5",
            "ink": "#432A31",
        },
        "coral_impact": {
            "background": "#FF6F61",
            "primary": "#7B1730",
            "secondary": "#FFD4C8",
            "ink": "#2F1118",
        },
        "green_catalog": {
            "background": "#F3E9D2",
            "primary": "#1E5A2E",
            "secondary": "#D84A68",
            "ink": "#17351E",
        },
        "white_quote": {
            "background": "#FFFEFA",
            "primary": "#202020",
            "secondary": "#A98D73",
            "ink": "#202020",
        },
    }
)


def _fonts(
    *,
    display: Path,
    body: Path,
    body_bold: Path,
) -> Mapping[str, Path]:
    return MappingProxyType(
        {
            "display": display,
            "body": body,
            "body_bold": body_bold,
            "emoji": EMOJI_FONT_PATH,
        }
    )


_FONTS: Mapping[TemplateFamily, Mapping[str, Path]] = MappingProxyType(
    {
        "pink_red": _fonts(
            display=TEMPLATE_FONT_ROOT / "Alibaba-PuHuiTi-Heavy.ttf",
            body=TEMPLATE_FONT_ROOT / "HarmonyOS_Sans_SC_Regular.ttf",
            body_bold=TEMPLATE_FONT_ROOT / "HarmonyOS_Sans_SC_Bold.ttf",
        ),
        "deep_teal": _fonts(
            display=TEMPLATE_FONT_ROOT / "HarmonyOS_Sans_SC_Black.ttf",
            body=TEMPLATE_FONT_ROOT / "HarmonyOS_Sans_SC_Regular.ttf",
            body_bold=TEMPLATE_FONT_ROOT / "HarmonyOS_Sans_SC_Bold.ttf",
        ),
        "soft_pink": _fonts(
            display=TEMPLATE_FONT_ROOT / "HarmonyOS_Sans_SC_Bold.ttf",
            body=TEMPLATE_FONT_ROOT / "HarmonyOS_Sans_SC_Regular.ttf",
            body_bold=TEMPLATE_FONT_ROOT / "HarmonyOS_Sans_SC_Medium.ttf",
        ),
        "coral_impact": _fonts(
            display=TEMPLATE_FONT_ROOT / "Alibaba-PuHuiTi-Heavy.ttf",
            body=TEMPLATE_FONT_ROOT / "HarmonyOS_Sans_SC_Regular.ttf",
            body_bold=TEMPLATE_FONT_ROOT / "HarmonyOS_Sans_SC_Bold.ttf",
        ),
        "green_catalog": _fonts(
            display=TEMPLATE_FONT_ROOT / "HarmonyOS_Sans_SC_Black.ttf",
            body=TEMPLATE_FONT_ROOT / "HarmonyOS_Sans_SC_Regular.ttf",
            body_bold=TEMPLATE_FONT_ROOT / "HarmonyOS_Sans_SC_Bold.ttf",
        ),
        "white_quote": _fonts(
            display=EDITORIAL_V1_FONT_ROOT / "LXGWWenKai-Medium.ttf",
            body=EDITORIAL_V1_FONT_ROOT / "LXGWWenKai-Regular.ttf",
            body_bold=EDITORIAL_V1_FONT_ROOT / "LXGWWenKai-Medium.ttf",
        ),
    }
)


_COLLECTION_ARCHETYPES = frozenset(
    {"checklist", "comparison", "item_collection", "save"}
)
_FOCUS_ARCHETYPES = frozenset({"cover", "thesis", "quote", "closing"})


def _capability(
    family: TemplateFamily,
    archetype: PageArchetype,
) -> ArchetypeCapability:
    if archetype in _COLLECTION_ARCHETYPES:
        thresholds = (60, 120, 220, 22)
    elif archetype in _FOCUS_ARCHETYPES:
        thresholds = (48, 90, 150, 30)
    else:
        thresholds = (56, 110, 190, 24)
    sparse, standard, dense, min_font = thresholds
    return ArchetypeCapability(
        composition_variants=FAMILY_COMPOSITION_VARIANTS[family],
        sparse_max_graphemes=sparse,
        standard_max_graphemes=standard,
        dense_max_graphemes=dense,
        min_font_px=min_font,
    )


def _definition(family: TemplateFamily) -> TemplateDefinition:
    return TemplateDefinition(
        family=family,
        colors=MappingProxyType(dict(_COLORS[family])),
        fonts=_FONTS[family],
        archetypes=MappingProxyType(
            {
                archetype: _capability(family, archetype)
                for archetype in get_args(PageArchetype)
            }
        ),
    )


TEMPLATE_REGISTRY: Mapping[
    TemplateFamily, TemplateDefinition
] = MappingProxyType(
    {
        family: _definition(family)
        for family in get_args(TemplateFamily)
    }
)
