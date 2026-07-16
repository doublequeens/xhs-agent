from __future__ import annotations

from html import escape
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

from src.schemas.assets import AssetManifestItem, LayoutName
from src.schemas.storyboard import CarouselFrame, ContentBlock


LayoutRenderer = Callable[[CarouselFrame, Sequence[AssetManifestItem]], str]


def _copy(
    value: str,
    *,
    role: str,
    class_name: str,
    tag: str = "div",
) -> str:
    return (
        f'<{tag} class="{class_name}" data-card-copy '
        f'data-copy-role="{escape(role, quote=True)}">'
        f"{escape(value, quote=True)}</{tag}>"
    )


def _header(frame: CarouselFrame) -> str:
    kicker = (
        _copy(frame.kicker, role="kicker", class_name="kicker")
        if frame.kicker
        else ""
    )
    return "".join(
        (
            '<header class="editorial-header">',
            kicker,
            _copy(
                frame.headline,
                role="headline",
                class_name="headline",
                tag="h1",
            ),
            "</header>",
        )
    )


def _block(block: ContentBlock, index: int) -> str:
    heading = (
        _copy(
            block.heading,
            role=f"content_blocks[{index}].heading",
            class_name="block-heading",
            tag="h2",
        )
        if block.heading
        else ""
    )
    body = (
        _copy(
            block.body,
            role=f"content_blocks[{index}].body",
            class_name="block-body",
            tag="p",
        )
        if block.body
        else ""
    )
    items = "".join(
        "".join(
            (
                '<li class="block-item">',
                '<span class="item-marker numeral" aria-hidden="true">'
                f"{item_index + 1:02d}</span>",
                _copy(
                    item,
                    role=f"content_blocks[{index}].items[{item_index}]",
                    class_name="item-copy",
                    tag="span",
                ),
                "</li>",
            )
        )
        for item_index, item in enumerate(block.items)
    )
    item_list = f'<ol class="block-items">{items}</ol>' if items else ""
    return (
        f'<section class="content-block block-{escape(block.block_type, quote=True)}" '
        f'data-block-type="{escape(block.block_type, quote=True)}">'
        f"{heading}{body}{item_list}</section>"
    )


def _blocks(frame: CarouselFrame) -> str:
    return "".join(_block(block, index) for index, block in enumerate(frame.content_blocks))


def _asset_gallery(assets: Sequence[AssetManifestItem], class_name: str) -> str:
    images: list[str] = []
    for asset in assets:
        if "://" in asset.path:
            raise ValueError(f"asset path must be local: {asset.slot_id}")
        path = Path(asset.path)
        if not path.is_absolute() or not path.is_file():
            raise ValueError(f"asset path must be a resolved local file: {asset.slot_id}")
        images.append(
            "".join(
                (
                    '<figure class="asset-figure">',
                    f'<img src="{escape(path.as_uri(), quote=True)}" '
                    f'alt="{escape(asset.role, quote=True)}" '
                    f'data-asset-slot="{escape(asset.slot_id, quote=True)}">',
                    "</figure>",
                )
            )
        )
    if not images:
        images.append('<div class="asset-placeholder" aria-hidden="true"></div>')
    return f'<div class="asset-gallery {class_name}">{"".join(images)}</div>'


def _footer(frame: CarouselFrame) -> str:
    footer = (
        _copy(frame.footer, role="footer", class_name="footer-copy", tag="span")
        if frame.footer
        else '<span class="footer-copy" aria-hidden="true"></span>'
    )
    return (
        '<footer class="editorial-footer">'
        f"{footer}"
        '<span class="page-number numeral" aria-hidden="true">01</span>'
        "</footer>"
    )


def _card(frame: CarouselFrame, body: str) -> str:
    return "".join(
        (
            f'<main class="card" data-layout="{escape(frame.page_archetype, quote=True)}" '
            f'data-frame-role="{escape(frame.role, quote=True)}" '
            f'data-frame-id="{escape(frame.frame_id, quote=True)}">',
            '<div class="font-probes" aria-hidden="true">'
            '<span class="font-probe-display">字</span>'
            '<span class="font-probe-body">字</span>'
            '<span class="font-probe-numeral">01</span>'
            "</div>",
            _header(frame),
            body,
            _footer(frame),
            "</main>",
        )
    )


def render_editorial_cover(
    frame: CarouselFrame, assets: Sequence[AssetManifestItem]
) -> str:
    return _card(
        frame,
        '<section class="layout-body layout-editorial-cover">'
        '<div class="cover-copy">'
        f"{_blocks(frame)}"
        '<div class="cover-rule" aria-hidden="true"></div>'
        "</div>"
        f'{_asset_gallery(assets, "cover-visual")}'
        "</section>",
    )


def render_texture_baseline(
    frame: CarouselFrame, assets: Sequence[AssetManifestItem]
) -> str:
    return _card(
        frame,
        '<section class="layout-body layout-texture-baseline">'
        f'{_asset_gallery(assets, "texture-visual")}'
        f'<div class="baseline-notes">{_blocks(frame)}</div>'
        "</section>",
    )


def render_front_face_zone(
    frame: CarouselFrame, assets: Sequence[AssetManifestItem]
) -> str:
    return _card(
        frame,
        '<section class="layout-body layout-front-face-zone">'
        f'<div class="zone-visual zone-front">{_asset_gallery(assets, "face-visual")}'
        '<span class="zone-marker marker-one" aria-hidden="true"></span>'
        '<span class="zone-marker marker-two" aria-hidden="true"></span></div>'
        f'<div class="zone-notes">{_blocks(frame)}</div>'
        "</section>",
    )


def render_three_quarter_face_zone(
    frame: CarouselFrame, assets: Sequence[AssetManifestItem]
) -> str:
    return _card(
        frame,
        '<section class="layout-body layout-three-quarter-face-zone">'
        f'<div class="zone-notes">{_blocks(frame)}</div>'
        f'<div class="zone-visual zone-three-quarter">{_asset_gallery(assets, "face-visual")}'
        '<span class="zone-bracket" aria-hidden="true"></span></div>'
        "</section>",
    )


def render_step_timeline(
    frame: CarouselFrame, assets: Sequence[AssetManifestItem]
) -> str:
    return _card(
        frame,
        '<section class="layout-body layout-step-timeline">'
        f'<div class="timeline-rail">{_blocks(frame)}</div>'
        f'{_asset_gallery(assets, "timeline-visual")}'
        "</section>",
    )


def render_morning_evening_flow(
    frame: CarouselFrame, assets: Sequence[AssetManifestItem]
) -> str:
    blocks = list(frame.content_blocks)
    midpoint = max(1, (len(blocks) + 1) // 2)
    morning = "".join(_block(block, index) for index, block in enumerate(blocks[:midpoint]))
    evening = "".join(
        _block(block, index + midpoint)
        for index, block in enumerate(blocks[midpoint:])
    )
    return _card(
        frame,
        '<section class="layout-body layout-morning-evening-flow">'
        f'<div class="flow-panel morning-panel"><div class="flow-label numeral">AM</div>{morning}</div>'
        '<div class="flow-divider" aria-hidden="true"></div>'
        f'<div class="flow-panel evening-panel"><div class="flow-label numeral">PM</div>{evening}</div>'
        f'{_asset_gallery(assets, "flow-visual")}'
        "</section>",
    )


def render_left_right_comparison(
    frame: CarouselFrame, assets: Sequence[AssetManifestItem]
) -> str:
    blocks = list(frame.content_blocks)
    midpoint = max(1, (len(blocks) + 1) // 2)
    left = "".join(_block(block, index) for index, block in enumerate(blocks[:midpoint]))
    right = "".join(
        _block(block, index + midpoint)
        for index, block in enumerate(blocks[midpoint:])
    )
    return _card(
        frame,
        '<section class="layout-body layout-left-right-comparison">'
        f'<div class="comparison-panel comparison-left"><div class="panel-label">观察</div>{left}</div>'
        f'<div class="comparison-panel comparison-right"><div class="panel-label">调整</div>{right}</div>'
        f'{_asset_gallery(assets, "comparison-visual")}'
        "</section>",
    )


def render_three_state_diagnostic(
    frame: CarouselFrame, assets: Sequence[AssetManifestItem]
) -> str:
    return _card(
        frame,
        '<section class="layout-body layout-three-state-diagnostic">'
        '<div class="state-grid">'
        f"{_blocks(frame)}"
        "</div>"
        f'{_asset_gallery(assets, "diagnostic-visual")}'
        "</section>",
    )


def render_decision_tree(
    frame: CarouselFrame, assets: Sequence[AssetManifestItem]
) -> str:
    return _card(
        frame,
        '<section class="layout-body layout-decision-tree">'
        '<div class="tree-root"><span class="numeral">IF</span></div>'
        f'<div class="tree-branches">{_blocks(frame)}</div>'
        f'{_asset_gallery(assets, "tree-visual")}'
        "</section>",
    )


def render_saveable_checklist(
    frame: CarouselFrame, assets: Sequence[AssetManifestItem]
) -> str:
    return _card(
        frame,
        '<section class="layout-body layout-saveable-checklist">'
        '<div class="save-label">SAVE / CHECK</div>'
        f'<div class="checklist-sheet">{_blocks(frame)}</div>'
        f'{_asset_gallery(assets, "checklist-visual")}'
        "</section>",
    )


def render_saveable_reference(
    frame: CarouselFrame, assets: Sequence[AssetManifestItem]
) -> str:
    return _card(
        frame,
        '<section class="layout-body layout-saveable-reference">'
        '<aside class="reference-index numeral">01<br>02<br>03</aside>'
        f'<div class="reference-sheet">{_blocks(frame)}</div>'
        f'{_asset_gallery(assets, "reference-visual")}'
        "</section>",
    )


LAYOUT_RENDERERS: Mapping[LayoutName, LayoutRenderer] = MappingProxyType(
    {
        "editorial_cover": render_editorial_cover,
        "texture_baseline": render_texture_baseline,
        "front_face_zone": render_front_face_zone,
        "three_quarter_face_zone": render_three_quarter_face_zone,
        "step_timeline": render_step_timeline,
        "morning_evening_flow": render_morning_evening_flow,
        "left_right_comparison": render_left_right_comparison,
        "three_state_diagnostic": render_three_state_diagnostic,
        "decision_tree": render_decision_tree,
        "saveable_checklist": render_saveable_checklist,
        "saveable_reference": render_saveable_reference,
    }
)
