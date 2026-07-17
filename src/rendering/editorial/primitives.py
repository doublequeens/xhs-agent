from __future__ import annotations

from html import escape
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Sequence, get_args

import regex

from src.schemas.assets import AssetManifestItem
from src.schemas.editorial_templates import (
    PageArchetype,
    ResolvedVariant,
    TemplateFamily,
)
from src.schemas.storyboard import CarouselFrame, ContentBlock

from .template_registry import TEMPLATE_REGISTRY


TemplateRenderer = Callable[
    [CarouselFrame, Sequence[AssetManifestItem], ResolvedVariant],
    str,
]


_BASE_TEMPLATE_CSS = """
*{box-sizing:border-box}
.template-card{position:relative;isolation:isolate;width:1080px;height:1440px;overflow:hidden;padding:84px;background:var(--template-bg);color:var(--template-ink);display:grid;grid-template-rows:auto minmax(0,1fr) auto;gap:34px;font-family:var(--template-body),"Noto Color Emoji";font-weight:400}
.template-card::before{content:"";position:absolute;inset:28px;border:1px solid color-mix(in srgb,var(--template-primary) 30%,transparent);pointer-events:none}
.template-header{position:relative;z-index:1;display:grid;gap:14px;min-width:0}
.template-kicker{font-size:25px;line-height:1.3;font-weight:700;letter-spacing:.14em;color:var(--template-secondary)}
.template-headline{margin:0;max-width:920px;font-family:var(--template-display),"Noto Color Emoji";font-size:68px;line-height:1.12;letter-spacing:-.035em;overflow-wrap:anywhere;color:var(--template-primary)}
.template-body{position:relative;z-index:1;min-width:0;min-height:0;display:grid;gap:24px;overflow:hidden}
.copy-grid{min-width:0;min-height:0;display:grid;gap:18px;align-content:center}
.content-block{min-width:0;display:grid;gap:11px;align-content:start}
.block-heading{margin:0;font-size:28px;line-height:1.3;font-weight:700;color:var(--template-primary)}
.block-body{margin:0;font-size:29px;line-height:1.45;overflow-wrap:anywhere}
.block-items{list-style:none;margin:0;padding:0;display:grid;gap:10px}
.block-item{min-width:0;display:grid;grid-template-columns:38px minmax(0,1fr);gap:10px;align-items:baseline}
.item-marker{font-family:var(--template-display);font-size:20px;line-height:1;color:var(--template-secondary)}
.item-copy{min-width:0;font-size:26px;line-height:1.42;overflow-wrap:anywhere}
.emphasis-list{display:flex;flex-wrap:wrap;gap:10px;margin-top:4px}
.emphasis-chip{padding:8px 16px;border-radius:999px;background:color-mix(in srgb,var(--template-secondary) 22%,transparent);font-size:22px;line-height:1.3;font-weight:700;color:var(--template-primary)}
.asset-gallery{min-width:0;min-height:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;place-items:center}
.asset-figure{width:100%;height:100%;min-height:0;margin:0;display:grid;place-items:center;overflow:hidden}
.asset-figure img{display:block;max-width:100%;max-height:100%;object-fit:contain}
.composition-focus{place-content:center;text-align:center}
.composition-focus .copy-grid{justify-items:center}
.composition-stack{grid-template-columns:minmax(0,1fr);align-content:center}
.composition-grid{grid-template-columns:repeat(2,minmax(0,1fr));align-content:center}
.composition-grid .asset-gallery{grid-column:1/-1;max-height:300px}
.composition-split{grid-template-columns:repeat(2,minmax(0,1fr));align-content:stretch}
.composition-split .copy-grid{grid-template-columns:repeat(2,minmax(0,1fr));grid-column:1/-1}
.composition-split .asset-gallery{grid-column:1/-1;max-height:280px}
.density-sparse .template-headline{font-size:78px}
.density-dense .template-headline{font-size:58px}
.density-dense .block-body{font-size:25px}
.density-dense .item-copy{font-size:23px}
.template-footer{position:relative;z-index:1;display:flex;justify-content:space-between;align-items:baseline;gap:24px;border-top:1px solid color-mix(in srgb,var(--template-primary) 32%,transparent);padding-top:16px}
.footer-copy{font-size:22px;line-height:1.35;color:var(--template-secondary)}
.page-number{margin-left:auto;font-family:var(--template-display);font-size:24px;color:var(--template-secondary)}
.font-probes{position:absolute;opacity:0;pointer-events:none}
.font-probe-display{font-family:var(--template-display)}
.font-probe-body{font-family:var(--template-body)}
.font-probe-emoji{font-family:"Noto Color Emoji"}
.emoji-grapheme{font-family:"Noto Color Emoji";font-style:normal;font-weight:400}
"""


_GRAPHEME_RE = regex.compile(r"\X")
_EMOJI_RE = regex.compile(r"\p{Extended_Pictographic}")


def _render_copy_value(value: str) -> str:
    return "".join(
        (
            '<span class="emoji-grapheme" '
            f'data-emoji-grapheme="{escape(grapheme, quote=True)}">'
            f"{escape(grapheme, quote=True)}</span>"
            if _EMOJI_RE.search(grapheme)
            else escape(grapheme, quote=True)
        )
        for grapheme in _GRAPHEME_RE.findall(value)
    )


def copy_atom(
    value: str,
    *,
    role: str,
    class_name: str,
    tag: str = "div",
) -> str:
    return (
        f'<{tag} class="{escape(class_name, quote=True)}" data-card-copy '
        f'data-copy-role="{escape(role, quote=True)}">'
        f"{_render_copy_value(value)}</{tag}>"
    )


def render_header(frame: CarouselFrame) -> str:
    kicker = (
        copy_atom(
            frame.kicker,
            role="kicker",
            class_name="template-kicker",
        )
        if frame.kicker
        else ""
    )
    return (
        '<header class="template-header">'
        f"{kicker}"
        f"{copy_atom(frame.headline, role='headline', class_name='template-headline', tag='h1')}"
        "</header>"
    )


def _marker(marker_style: str, index: int) -> str:
    if marker_style == "check":
        return "✓"
    if marker_style == "dot":
        return "•"
    if marker_style == "dash":
        return "—"
    return f"{index + 1:02d}"


def _render_block(
    block: ContentBlock,
    index: int,
    marker_style: str,
) -> str:
    heading = (
        copy_atom(
            block.heading,
            role=f"content_blocks[{index}].heading",
            class_name="block-heading",
            tag="h2",
        )
        if block.heading
        else ""
    )
    body = (
        copy_atom(
            block.body,
            role=f"content_blocks[{index}].body",
            class_name="block-body",
            tag="p",
        )
        if block.body
        else ""
    )
    items = "".join(
        (
            '<li class="block-item">'
            f'<span class="item-marker" aria-hidden="true">{_marker(marker_style, item_index)}</span>'
            f"{copy_atom(item, role=f'content_blocks[{index}].items[{item_index}]', class_name='item-copy', tag='span')}"
            "</li>"
        )
        for item_index, item in enumerate(block.items)
    )
    item_list = f'<ol class="block-items">{items}</ol>' if items else ""
    return (
        f'<section class="content-block block-{escape(block.block_type, quote=True)}" '
        f'data-block-type="{escape(block.block_type, quote=True)}">'
        f"{heading}{body}{item_list}</section>"
    )


def render_blocks(frame: CarouselFrame, marker_style: str) -> str:
    blocks = "".join(
        _render_block(block, index, marker_style)
        for index, block in enumerate(frame.content_blocks)
    )
    emphasis = "".join(
        copy_atom(
            value,
            role=f"emphasis[{index}]",
            class_name="emphasis-chip",
            tag="span",
        )
        for index, value in enumerate(frame.emphasis)
    )
    emphasis_list = (
        f'<div class="emphasis-list">{emphasis}</div>'
        if emphasis
        else ""
    )
    return f'<div class="copy-grid">{blocks}{emphasis_list}</div>'


def render_footer(frame: CarouselFrame) -> str:
    footer = (
        copy_atom(
            frame.footer,
            role="footer",
            class_name="footer-copy",
            tag="span",
        )
        if frame.footer
        else ""
    )
    return (
        '<footer class="template-footer">'
        f"{footer}"
        '<span class="page-number" aria-hidden="true">01</span>'
        "</footer>"
    )


def render_assets(assets: Sequence[AssetManifestItem]) -> str:
    if not assets:
        return ""
    images: list[str] = []
    for asset in assets:
        if "://" in asset.path:
            raise ValueError(f"asset path must be local: {asset.slot_id}")
        path = Path(asset.path)
        if not path.is_absolute() or not path.is_file():
            raise ValueError(
                f"asset path must be a resolved local file: {asset.slot_id}"
            )
        images.append(
            '<figure class="asset-figure">'
            f'<img src="{escape(path.as_uri(), quote=True)}" '
            f'alt="{escape(asset.role, quote=True)}" '
            f'data-asset-slot="{escape(asset.slot_id, quote=True)}">'
            "</figure>"
        )
    return f'<div class="asset-gallery">{"".join(images)}</div>'


def render_composed_body(
    frame: CarouselFrame,
    assets: Sequence[AssetManifestItem],
    *,
    mode: str,
    marker_style: str,
    semantic_kind: str,
) -> str:
    if mode not in {"focus", "stack", "grid", "split"}:
        raise ValueError(f"unsupported template composition mode: {mode}")
    return (
        f'<section class="template-body composition-{mode} '
        f'semantic-{escape(semantic_kind, quote=True)}">'
        '<span class="family-decoration" aria-hidden="true"></span>'
        f"{render_blocks(frame, marker_style)}"
        f"{render_assets(assets)}"
        "</section>"
    )


def render_card_shell(
    family: TemplateFamily,
    frame: CarouselFrame,
    variant: ResolvedVariant,
    body: str,
) -> str:
    definition = TEMPLATE_REGISTRY[family]
    family_class = f"template-{family.replace('_', '-')}"
    variant_class = (
        f"variant-{variant.composition_variant.replace('_', '-')}"
    )
    style = (
        f"--template-bg:{definition.colors['background']};"
        f"--template-primary:{definition.colors['primary']};"
        f"--template-secondary:{definition.colors['secondary']};"
        f"--template-ink:{definition.colors['ink']};"
        f"--template-display:'{family_class}-display';"
        f"--template-body:'{family_class}-body';"
    )
    display_font = f"{family_class}-display"
    body_font = f"{family_class}-body"
    return (
        f"<style>{_BASE_TEMPLATE_CSS}</style>"
        f'<main class="card template-card {family_class} density-{variant.density} '
        f"{variant_class} archetype-{frame.page_archetype}\" "
        f'data-template-family="{family}" '
        f'data-page-archetype="{frame.page_archetype}" '
        f'data-density="{variant.density}" '
        f'data-composition-variant="{escape(variant.composition_variant, quote=True)}" '
        f'data-display-font-family="{display_font}" '
        f'data-body-font-family="{body_font}" '
        'data-emoji-font-family="Noto Color Emoji" '
        f'data-frame-role="{escape(frame.role, quote=True)}" '
        f'data-frame-id="{escape(frame.frame_id, quote=True)}" '
        f'style="{style}">'
        '<div class="font-probes" aria-hidden="true">'
        '<span class="font-probe-display">字</span>'
        '<span class="font-probe-body">字</span>'
        '<span class="font-probe-emoji">✨</span>'
        "</div>"
        f"{render_header(frame)}{body}{render_footer(frame)}"
        "</main>"
    )


_FOCUS_ARCHETYPES = frozenset({"cover", "thesis", "quote", "closing"})
_STRUCTURED_ARCHETYPES = frozenset(
    {
        "steps",
        "checklist",
        "comparison",
        "diagnostic",
        "qa",
        "item_collection",
        "save",
    }
)


def archetype_renderer_map(
    focus: TemplateRenderer,
    narrative: TemplateRenderer,
    structured: TemplateRenderer,
) -> Mapping[PageArchetype, TemplateRenderer]:
    return MappingProxyType(
        {
            archetype: (
                focus
                if archetype in _FOCUS_ARCHETYPES
                else structured
                if archetype in _STRUCTURED_ARCHETYPES
                else narrative
            )
            for archetype in get_args(PageArchetype)
        }
    )
