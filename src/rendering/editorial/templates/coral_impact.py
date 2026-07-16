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


FAMILY: TemplateFamily = "coral_impact"
FAMILY_CSS = """
.template-coral-impact{background:#F45A5A;color:#FFF}
.template-coral-impact .template-headline,.template-coral-impact .block-heading{color:#FFF}
.template-coral-impact .template-kicker,.template-coral-impact .footer-copy,.template-coral-impact .page-number{color:#FFE3E3}
.template-coral-impact .family-decoration{position:absolute;left:-80px;bottom:-70px;width:330px;height:330px;border-radius:50%;background:#7B1730;opacity:.28}
.template-coral-impact.variant-impact-cover .template-headline{font-size:112px;line-height:1.02;text-transform:uppercase}
.template-coral-impact.variant-stacked-impact .content-block{padding:22px 0;border-bottom:5px solid rgba(255,255,255,.72)}
.template-coral-impact.variant-contrast-impact .content-block{padding:26px;background:#FFF;color:#7B1730}
.template-coral-impact.variant-contrast-impact .block-heading{color:#F45A5A}
.template-coral-impact .emphasis-chip{background:rgba(255,255,255,.18);color:#FFF}
"""
_MODE_BY_VARIANT = {
    "impact-cover": "focus",
    "stacked-impact": "stack",
    "contrast-impact": "split",
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
        marker_style="number",
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
