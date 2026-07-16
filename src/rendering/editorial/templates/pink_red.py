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


FAMILY: TemplateFamily = "pink_red"
FAMILY_CSS = """
.template-pink-red{background:#F4A7BF;color:#35151D}
.template-pink-red .template-kicker{color:#A8172A}
.template-pink-red .family-decoration{position:absolute;right:22px;top:12px;width:120px;height:120px;border-radius:50%;background:#DC2333;opacity:.12}
.template-pink-red.variant-centered-number .template-headline{font-size:92px;text-align:center;color:#DC2333}
.template-pink-red.variant-centered-number .template-body{justify-items:center}
.template-pink-red.variant-red-panel{background:#DC2333;color:#FFF}
.template-pink-red.variant-red-panel .template-headline,.template-pink-red.variant-red-panel .block-heading,.template-pink-red.variant-red-panel .emphasis-chip{color:#FFF}
.template-pink-red.variant-red-panel .template-kicker,.template-pink-red.variant-red-panel .footer-copy,.template-pink-red.variant-red-panel .page-number{color:#F4A7BF}
.template-pink-red.variant-white-card .template-body{padding:48px;border-radius:30px;background:#FFF;box-shadow:0 18px 50px rgba(122,18,34,.18)}
.template-pink-red.variant-split-card .content-block{padding:26px;border-radius:22px;background:#FFF}
"""
_MODE_BY_VARIANT = {
    "centered-number": "focus",
    "red-panel": "stack",
    "white-card": "stack",
    "split-card": "split",
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
