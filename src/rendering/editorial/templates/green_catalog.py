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


FAMILY: TemplateFamily = "green_catalog"
FAMILY_CSS = """
.template-green-catalog{background:#1E5A2E;color:#F3E9D2}
.template-green-catalog .template-headline,.template-green-catalog .block-heading{color:#F3E9D2}
.template-green-catalog .template-kicker,.template-green-catalog .footer-copy,.template-green-catalog .page-number{color:#E8C7A0}
.template-green-catalog .family-decoration{position:absolute;left:38px;top:-12px;width:180px;height:42px;border-radius:14px 14px 0 0;background:#E58FA0}
.template-green-catalog.variant-folder-cover .template-headline{text-align:center;font-size:96px}
.template-green-catalog.variant-folder-cover .template-body::after{content:"";width:360px;height:210px;justify-self:center;border-radius:18px;background:linear-gradient(90deg,#E58FA0 0 48%,transparent 48% 52%,#E0453A 52%)}
.template-green-catalog.variant-catalog-card .template-body{padding:52px 44px 42px;border-radius:20px;background:#F3E9D2;color:#244A26;box-shadow:0 16px 44px rgba(0,0,0,.18)}
.template-green-catalog.variant-catalog-card .block-heading{color:#244A26}
.template-green-catalog.variant-catalog-grid .content-block{padding:24px;border-radius:16px;background:#F3E9D2;color:#244A26;border-top:22px solid #C46B7D}
.template-green-catalog.variant-catalog-grid .content-block:nth-child(even){border-top-color:#B82E25}
.template-green-catalog.variant-catalog-grid .block-heading{color:#244A26}
.template-green-catalog .emphasis-chip{background:#E2D6BA;color:#244A26}
"""
_MODE_BY_VARIANT = {
    "folder-cover": "focus",
    "catalog-card": "stack",
    "catalog-grid": "grid",
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
