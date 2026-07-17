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


FAMILY: TemplateFamily = "white_quote"
FAMILY_CSS = """
.template-white-quote{background:#FFF;color:#2A4A8C}
.template-white-quote .template-headline{color:#2A4A8C;font-family:var(--template-display)}
.template-white-quote .block-heading{color:#2A4A8C}
.template-white-quote .template-kicker,.template-white-quote .footer-copy,.template-white-quote .page-number{color:#4A66A0}
.template-white-quote .family-decoration{position:absolute;left:50%;top:8px;width:160px;height:1px;transform:translateX(-50%);background:#9FB0CC}
.template-white-quote.variant-centered-focus .template-headline{font-size:82px;line-height:1.45;text-align:center}
.template-white-quote.variant-editorial-column .template-body{max-width:760px;width:100%;justify-self:center}
.template-white-quote.variant-quiet-grid .content-block{padding:26px;border:1px solid #D7DFEE}
.template-white-quote .block-body,.template-white-quote .item-copy{line-height:1.5}
.template-white-quote .emphasis-chip{border:1px solid #D7DFEE;background:#FFF;color:#2A4A8C}
"""
_MODE_BY_VARIANT = {
    "centered-focus": "focus",
    "editorial-column": "stack",
    "quiet-grid": "grid",
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
        marker_style="dash",
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
