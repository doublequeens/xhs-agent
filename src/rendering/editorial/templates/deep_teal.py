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


FAMILY: TemplateFamily = "deep_teal"
FAMILY_CSS = """
.template-deep-teal{background:#0E5A5A;color:#FFF}
.template-deep-teal .template-headline,.template-deep-teal .block-heading{color:#FFF}
.template-deep-teal .template-kicker,.template-deep-teal .footer-copy,.template-deep-teal .page-number{color:#7FD6D6}
.template-deep-teal .family-decoration{position:absolute;left:0;right:0;top:16px;height:2px;background:rgba(255,255,255,.28)}
.template-deep-teal.variant-centered-minimal .template-headline{text-align:center;font-size:88px}
.template-deep-teal.variant-numbered-column .content-block{padding:20px 0;border-top:2px solid rgba(255,255,255,.32)}
.template-deep-teal.variant-rule-grid .content-block{padding:24px;border:2px solid rgba(255,255,255,.4)}
.template-deep-teal .emphasis-chip{border:1px solid rgba(255,255,255,.5);background:transparent;color:#FFF}
"""
_MODE_BY_VARIANT = {
    "centered-minimal": "focus",
    "numbered-column": "stack",
    "rule-grid": "grid",
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
