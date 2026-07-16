from __future__ import annotations

from collections.abc import Sequence

from src.schemas.assets import AssetManifestItem
from src.schemas.editorial_templates import ResolvedVariant, TemplateFamily
from src.schemas.storyboard import CarouselFrame

from ..primitives import (
    archetype_renderer_map,
    render_card_shell,
    render_composed_body,
)


FAMILY: TemplateFamily = "soft_pink"
FAMILY_CSS = """
.template-soft-pink{background:#F8DADA;color:#432A31}
.template-soft-pink .template-headline,.template-soft-pink .block-heading{color:#EE5C5C}
.template-soft-pink .template-kicker,.template-soft-pink .footer-copy,.template-soft-pink .page-number{color:#A86570}
.template-soft-pink .family-decoration{position:absolute;right:34px;top:4px;width:180px;height:180px;border-radius:52% 48% 58% 42%;background:#FFF;opacity:.55}
.template-soft-pink.variant-offset-cover .template-header{padding-left:210px}
.template-soft-pink.variant-floating-card .template-body{padding:46px;border-radius:34px;background:#FFF;box-shadow:0 16px 46px rgba(216,68,76,.15)}
.template-soft-pink.variant-soft-grid .content-block{padding:24px;border-radius:24px;background:rgba(255,255,255,.72)}
.template-soft-pink .emphasis-chip{background:#FDEAEC;color:#D8444C}
"""
_MODE_BY_VARIANT = {
    "offset-cover": "focus",
    "floating-card": "stack",
    "soft-grid": "grid",
}


def _render(
    frame: CarouselFrame,
    assets: Sequence[AssetManifestItem],
    variant: ResolvedVariant,
    semantic_kind: str,
) -> str:
    body = render_composed_body(
        frame,
        assets,
        mode=_MODE_BY_VARIANT[variant.composition_variant],
        marker_style="dot",
        semantic_kind=semantic_kind,
    )
    return f"<style>{FAMILY_CSS}</style>{render_card_shell(FAMILY, frame, variant, body)}"


def _focus(
    frame: CarouselFrame,
    assets: Sequence[AssetManifestItem],
    variant: ResolvedVariant,
) -> str:
    return _render(frame, assets, variant, "focus")


def _narrative(
    frame: CarouselFrame,
    assets: Sequence[AssetManifestItem],
    variant: ResolvedVariant,
) -> str:
    return _render(frame, assets, variant, "narrative")


def _structured(
    frame: CarouselFrame,
    assets: Sequence[AssetManifestItem],
    variant: ResolvedVariant,
) -> str:
    return _render(frame, assets, variant, "structured")


ARCHETYPE_RENDERERS = archetype_renderer_map(
    _focus,
    _narrative,
    _structured,
)


def render_frame(
    frame: CarouselFrame,
    assets: Sequence[AssetManifestItem],
    variant: ResolvedVariant,
) -> str:
    return ARCHETYPE_RENDERERS[frame.page_archetype](
        frame,
        assets,
        variant,
    )
