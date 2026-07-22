from __future__ import annotations

from collections.abc import Sequence

from src.schemas.assets import AssetManifestItem
from src.schemas.editorial_templates import ResolvedVariant, TemplateFamily
from src.schemas.storyboard import CarouselFrame

from ..primitives import (
    _render_block,
    _render_copy_value,
    archetype_renderer_map,
    copy_atom,
    render_assets,
    render_card_shell,
    render_composed_body,
)


FAMILY: TemplateFamily = "green_catalog"

# Archetypes that get the bespoke green_catalog composition (墨绿「本月好物」:
# green field with cream folder/catalog cards, win/lose comparison, centered
# save). Cover handled separately. All visible copy flows through copy_atom /
# render_blocks / render_assets so every content_blocks field, emphasis chip and
# asset slot is emitted with the probe's expected roles and order; only
# structure/CSS are bespoke. Archetypes outside this set fall through to generic
# (still with the persona footer rendered).
_BESPOKE_ARCHETYPES = frozenset({"item_collection", "comparison", "save", "scene"})

_SECTION_CLASS = {
    "item_collection": "gc-catalog",
    "comparison": "gc-compare",
    "save": "gc-save",
    "scene": "gc-scene",
}

# Decorative eyebrow label per content-block type (aria-hidden — not copy).
_PANEL_LABEL = {
    "text": "说明",
    "bullets": "要点",
    "labels": "要点",
    "checklist": "清单",
    "comparison": "对照",
    "steps": "步骤",
    "diagnostic": "诊断",
    "qa": "问答",
    "item_collection": "好物",
    "decision_tree": "判断",
}

# Decorative topbar brand label (aria-hidden — not copy).
_BRAND = "FAVORITES 2026"

FAMILY_CSS = """
/* green_catalog card: GREEN field (mockup page bg) with cream cards — the
   production _COLORS background is cream, but the mockup is green-field, so the
   card is overridden to green here. Compound selector beats the base .template-card. */
.template-card.template-green-catalog{background:#1E5A2E;color:#F3E9D2;padding:84px 88px;gap:0}
.template-card.template-green-catalog::before{display:none}
.template-green-catalog .template-footer{border-top:none;padding-top:0}
.template-green-catalog .page-number{display:none}
/* bespoke body section becomes the layout root (flex column, overflow:visible) */
.template-green-catalog .template-body.composition-gc-cover{
  display:flex;flex-direction:column;justify-content:space-between;min-height:0;overflow:visible}
.template-green-catalog .template-body.composition-gc-catalog,
.template-green-catalog .template-body.composition-gc-compare,
.template-green-catalog .template-body.composition-gc-scene{
  display:flex;flex-direction:column;justify-content:flex-start;min-height:0;overflow:visible}
.template-green-catalog .template-body.composition-gc-save{
  display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;min-height:0;overflow:visible}
/* persona handle: bottom-left, one copy atom, body family for the probe */
.template-green-catalog .gc-handle{
  position:absolute;left:88px;bottom:54px;font-size:26px;line-height:1.3;
  color:#C9B088;letter-spacing:.04em;font-weight:700;white-space:nowrap}
/* headline atom — HarmonyOS Sans Medium (display family); 2-line via <br> */
.template-green-catalog .gc-q{
  font-family:var(--template-display);font-weight:700;color:#F3E9D2;
  letter-spacing:.02em;overflow-wrap:anywhere}
.template-green-catalog .gc-topbar{
  display:flex;justify-content:space-between;font-size:24px;line-height:1.3;
  font-weight:700;letter-spacing:.14em;color:#E8C7A0;text-transform:uppercase}
.template-green-catalog .gc-topbar-kicker{font-size:24px;line-height:1.3}
.template-green-catalog .gc-block-h{font-size:34px;line-height:1.4;color:#F3E9D2;font-weight:700;margin:0 0 12px}
.template-green-catalog .gc-sub{
  font-size:36px;line-height:1.55;color:#E8C7A0;overflow-wrap:anywhere}
.template-green-catalog .gc-keys{display:flex;flex-wrap:wrap;gap:12px;justify-content:flex-end;margin-top:18px}
.template-green-catalog .gc-chip{
  font-size:26px;line-height:1.3;color:#244a26;background:#E2D6BA;font-weight:700;
  padding:10px 22px;border-radius:999px}
/* generic-fallback (non-bespoke archetypes) scaled up + cream cards */
.template-green-catalog .composition-focus,.template-green-catalog .composition-stack,.template-green-catalog .composition-grid{align-content:flex-start}
.template-green-catalog .block-heading{font-size:40px;line-height:1.3;color:#F3E9D2}
.template-green-catalog .block-body{font-size:32px;line-height:1.5;color:#E8C7A0}
.template-green-catalog .item-copy{font-size:30px;line-height:1.5;color:#F3E9D2}
.template-green-catalog .item-marker{font-size:30px;line-height:1;color:#E8C7A0}
.template-green-catalog .emphasis-chip{font-size:28px;line-height:1.3;padding:12px 26px;background:#E2D6BA;color:#244a26}
/* ===== COVER (green field + centered title + decorative folders) ===== */
.template-green-catalog .composition-gc-cover .gc-hero{
  flex:1;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;gap:42px}
.template-green-catalog .composition-gc-cover .gc-q{font-size:104px;line-height:1.06}
.template-green-catalog .gc-folders{display:flex;gap:32px}
.template-green-catalog .gc-folder{width:230px;display:flex;flex-direction:column;align-items:flex-start}
.template-green-catalog .gc-folder-tab{height:32px;width:62%;border-radius:14px 14px 0 0}
.template-green-catalog .gc-folder-body{height:170px;width:100%;border-radius:18px;display:flex;align-items:center;justify-content:center;font-family:var(--template-display);font-weight:700;font-size:44px;color:#fff}
.template-green-catalog .gc-folder.pink .gc-folder-body{background:#E58FA0}
.template-green-catalog .gc-folder.pink .gc-folder-tab{background:#C46B7D}
.template-green-catalog .gc-folder.red .gc-folder-body{background:#E0453A}
.template-green-catalog .gc-folder.red .gc-folder-tab{background:#B82E25}
/* ===== ITEM_COLLECTION (cream catalog grid) ===== */
.template-green-catalog .composition-gc-catalog .gc-q{font-size:64px;line-height:1.14;margin-top:18px}
.template-green-catalog .gc-grid{flex:1;display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:24px;align-content:start}
.template-green-catalog .gc-cell{
  background:#F3E9D2;border-top:24px solid #C46B7D;border-radius:16px;padding:30px 28px;
  display:flex;flex-direction:column;gap:12px;color:#244a26;box-shadow:0 12px 36px rgba(0,0,0,.18)}
.template-green-catalog .gc-cell:nth-child(even){border-top-color:#B82E25}
.template-green-catalog .gc-cell-copy{display:flex;flex-direction:column;gap:8px;min-width:0;font-size:28px;line-height:1.5}
.template-green-catalog .gc-cell-h{font-family:var(--template-display);font-weight:700;font-size:38px;line-height:1.2;color:#244a26}
.template-green-catalog .gc-cell-p{font-size:28px;line-height:1.5;color:#5a4632}
.template-green-catalog .gc-sep{display:none}
/* ===== COMPARISON (win/lose rows) ===== */
.template-green-catalog .composition-gc-compare .gc-q{font-size:64px;line-height:1.14;margin-top:18px;color:#F3E9D2}
.template-green-catalog .gc-rows{flex:1;display:flex;flex-direction:column;gap:16px;margin-top:24px}
.template-green-catalog .gc-cmp-row-copy{display:grid;grid-template-columns:1fr 1fr;gap:18px;font-size:26px;line-height:1.45}
.template-green-catalog .gc-cmp-side{padding:24px 26px;border-radius:18px;display:flex;flex-direction:column;gap:6px;min-width:0;font-size:26px;line-height:1.45}
.template-green-catalog .gc-cmp-win{background:#F3E9D2;color:#244a26}
.template-green-catalog .gc-cmp-lose{background:rgba(243,233,210,.14);color:#F3E9D2;border:1px solid rgba(243,233,210,.4)}
/* ===== SAVE (centered) ===== */
.template-green-catalog .composition-gc-save .gc-q{font-size:96px;line-height:1.14;color:#F3E9D2}
.template-green-catalog .composition-gc-save .gc-sub{
  font-size:36px;line-height:1.55;color:#E8C7A0;font-weight:700;margin-top:22px;max-width:760px}
/* ===== SCENE (cream bento cards filling the page, content centered) ===== */
.template-green-catalog .composition-gc-scene .gc-q{font-size:60px;line-height:1.14;margin-top:18px}
.template-green-catalog .gc-scene-cards{
  flex:1;display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:24px;align-content:stretch;min-height:0}
.template-green-catalog .gc-scene-cards .gc-scene-card:only-child{grid-column:1/-1}
.template-green-catalog .gc-scene-cards .gc-scene-card:last-child:nth-child(odd){grid-column:1/-1}
.template-green-catalog .gc-scene-card{
  background:#F3E9D2;border-top:24px solid #C46B7D;border-radius:16px;padding:36px;
  display:flex;flex-direction:column;justify-content:center;gap:16px;min-width:0;overflow:hidden;
  color:#244a26;box-shadow:0 12px 36px rgba(0,0,0,.18)}
.template-green-catalog .gc-scene-cards .gc-scene-card:nth-child(even){border-top-color:#B82E25}
.template-green-catalog .gc-scene-eyebrow{
  font-size:22px;line-height:1.3;color:#C46B7D;letter-spacing:.2em;font-weight:700;text-transform:uppercase}
.template-green-catalog .gc-scene-h{margin:0;font-size:38px;line-height:1.2;color:#244a26;font-weight:700}
.template-green-catalog .gc-scene-b{margin:0;font-size:28px;line-height:1.55;color:#5a4632}
.template-green-catalog .gc-scene-items{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:12px}
.template-green-catalog .gc-scene-item{display:flex;gap:14px;align-items:center}
.template-green-catalog .gc-scene-dot{width:10px;height:10px;border-radius:50%;background:#C46B7D;opacity:.8;flex:0 0 auto}
.template-green-catalog .gc-scene-item-copy{font-size:28px;line-height:1.5;color:#5a4632}
"""

_MODE_BY_VARIANT = {
    "folder-cover": "focus",
    "catalog-card": "stack",
    "catalog-grid": "grid",
}


def _two_line_value(text: str) -> str:
    if not text:
        return ""
    idx = text.find("，")
    if idx < 0 or idx >= len(text) - 1:
        idx = (len(text) - 1) // 2
    line1, line2 = text[: idx + 1], text[idx + 1:]
    if not line2.strip():
        return _render_copy_value(text)
    return _render_copy_value(line1) + "<br>" + _render_copy_value(line2)


def _two_line_atom(value: str, *, role: str, class_name: str, tag: str = "div") -> str:
    return (
        f'<{tag} class="{class_name}" data-card-copy data-copy-role="{role}">'
        f"{_two_line_value(value)}</{tag}>"
    )


def _persona_atom(frame: CarouselFrame) -> str:
    if not frame.persona:
        return ""
    return copy_atom(frame.persona, role="persona", class_name="gc-handle", tag="div")


def _headline_atom(frame: CarouselFrame, *, cls: str = "gc-q") -> str:
    return _two_line_atom(frame.headline, role="headline", class_name=cls, tag="div")


def _topbar(frame: CarouselFrame) -> str:
    kicker = (
        copy_atom(frame.kicker, role="kicker", class_name="gc-topbar-kicker", tag="span")
        if frame.kicker else ""
    )
    return (
        f'<div class="gc-topbar"><span aria-hidden="true">{_render_copy_value(_BRAND)}</span>'
        f"{kicker}</div>"
    )


def _emphasis_atoms(frame: CarouselFrame) -> str:
    if not frame.emphasis:
        return ""
    return "".join(
        copy_atom(value, role=f"emphasis[{i}]", class_name="gc-chip", tag="span")
        for i, value in enumerate(frame.emphasis)
    )


def _extra_blocks(frame: CarouselFrame, start: int) -> str:
    if len(frame.content_blocks) <= start:
        return ""
    return "".join(
        _render_block(b, i, "number")
        for i, b in enumerate(frame.content_blocks[start:], start=start)
    )


def _catalog_grid(frame: CarouselFrame) -> str:
    """block 0 items → cream catalog cells (colored top border + name/desc).
    Each item split on ｜ into name + desc; one copy atom per item."""
    block = frame.content_blocks[0] if frame.content_blocks else None
    if not block:
        return ""
    heading = (
        copy_atom(block.heading, role="content_blocks[0].heading", class_name="gc-block-h", tag="div")
        if block.heading else ""
    )
    body = (
        copy_atom(block.body, role="content_blocks[0].body", class_name="gc-cell-p", tag="div")
        if block.body else ""
    )
    cells = ""
    for i, item in enumerate(block.items or []):
        segs = item.split("｜")
        if len(segs) == 1:
            inner = f'<span class="gc-cell-h">{_render_copy_value(segs[0])}</span>'
        else:
            inner = (
                f'<span class="gc-cell-h">{_render_copy_value(segs[0])}</span>'
                f'<span class="gc-sep">｜</span>'
                f'<span class="gc-cell-p">{_render_copy_value(segs[1])}</span>'
            )
        cells += (
            f'<div class="gc-cell"><span class="gc-cell-copy" data-card-copy '
            f'data-copy-role="content_blocks[0].items[{i}]">{inner}</span></div>'
        )
    grid = f'<div class="gc-grid">{cells}</div>' if cells else ""
    extra = _extra_blocks(frame, 1)
    return f"{heading}{body}{grid}{extra}"


def _compare_rows(frame: CarouselFrame) -> str:
    """block 0 items → win/lose rows. Each item split on ｜ into [win, lose];
    one copy atom per item, rendered as a 2-column win/lose row."""
    block = frame.content_blocks[0] if frame.content_blocks else None
    if not block:
        return ""
    heading = (
        copy_atom(block.heading, role="content_blocks[0].heading", class_name="gc-block-h", tag="div")
        if block.heading else ""
    )
    body = (
        copy_atom(block.body, role="content_blocks[0].body", class_name="gc-cell-p", tag="div")
        if block.body else ""
    )
    rows = ""
    for i, item in enumerate(block.items or []):
        segs = item.split("｜", 1)
        win = _render_copy_value(segs[0])
        lose = _render_copy_value(segs[1]) if len(segs) > 1 else ""
        inner = (
            f'<span class="gc-cmp-side gc-cmp-win">{win}</span>'
            + (f'<span class="gc-sep">｜</span><span class="gc-cmp-side gc-cmp-lose">{lose}</span>' if lose else "")
        )
        rows += (
            f'<div class="gc-cmp-row-copy" data-card-copy '
            f'data-copy-role="content_blocks[0].items[{i}]">{inner}</div>'
        )
    list_html = f'<div class="gc-rows">{rows}</div>' if rows else ""
    extra = _extra_blocks(frame, 1)
    return f"{heading}{body}{list_html}{extra}"


def _scene_card(idx_blocks: list, card_num: int) -> str:
    """One cream bento card. ``idx_blocks`` is a list of (block_index, block) —
    usually one block; the tail blocks merge into the 4th card when content
    exceeds 4 blocks so the grid never exceeds 2×2 while every block's
    heading/body/items still carry their contract roles in order."""
    label = _PANEL_LABEL.get(getattr(idx_blocks[0][1], "block_type", "") or "", "要点")
    eyebrow = f'<div class="gc-scene-eyebrow" aria-hidden="true">{card_num:02d} · {label}</div>'
    inner = ""
    for i, block in idx_blocks:
        heading = (
            copy_atom(block.heading, role=f"content_blocks[{i}].heading", class_name="gc-scene-h", tag="div")
            if block.heading else ""
        )
        body = (
            copy_atom(block.body, role=f"content_blocks[{i}].body", class_name="gc-scene-b", tag="div")
            if block.body else ""
        )
        items = ""
        if block.items:
            lis = "".join(
                f'<li class="gc-scene-item"><span class="gc-scene-dot" aria-hidden="true"></span>'
                f'{copy_atom(item, role=f"content_blocks[{i}].items[{j}]", class_name="gc-scene-item-copy", tag="span")}'
                "</li>"
                for j, item in enumerate(block.items)
            )
            items = f'<ul class="gc-scene-items">{lis}</ul>'
        inner += heading + body + items
    return f'<div class="gc-scene-card">{eyebrow}{inner}</div>'


def _scene_panels(frame: CarouselFrame) -> str:
    """Scene page = a 2-column grid of cream cards (1–4 cards) filling the page
    height with content centered in each card. Each content block is one card;
    >4 blocks merge into the 4th card."""
    blocks = list(enumerate(frame.content_blocks))
    if not blocks:
        return ""
    if len(blocks) <= 4:
        groups = [[blocks[k]] for k in range(len(blocks))]
    else:
        groups = [[blocks[k]] for k in range(3)] + [blocks[3:]]
    cards = "".join(_scene_card(g, n + 1) for n, g in enumerate(groups))
    return f'<div class="gc-scene-cards">{cards}</div>'


def _cover_body(frame: CarouselFrame, assets: Sequence[AssetManifestItem]) -> str:
    topbar = _topbar(frame)
    headline = _headline_atom(frame, cls="gc-q")
    extra = _extra_blocks(frame, 0)
    folders = (
        '<div class="gc-folders" aria-hidden="true">'
        '<div class="gc-folder pink"><div class="gc-folder-tab"></div><div class="gc-folder-body">洁面</div></div>'
        '<div class="gc-folder red"><div class="gc-folder-tab"></div><div class="gc-folder-body">防晒</div></div>'
        '</div>'
    )
    assets_html = render_assets(assets)
    sub = "".join(
        copy_atom(value, role=f"emphasis[{i}]", class_name="gc-sub", tag="div")
        for i, value in enumerate(frame.emphasis)
    )
    hero = f'<div class="gc-hero">{headline}{extra}{sub}{folders}</div>{assets_html}'
    inner = f"{topbar}{hero}"
    return f'<section class="template-body composition-gc-cover">{inner}</section>'


def _bespoke_body(
    frame: CarouselFrame, assets: Sequence[AssetManifestItem], archetype: str
) -> str:
    section_cls = _SECTION_CLASS[archetype]
    topbar = _topbar(frame)
    headline = _headline_atom(frame)
    assets_html = render_assets(assets)
    emph = _emphasis_atoms(frame)
    emph_html = f'<div class="gc-keys">{emph}</div>' if emph else ""

    if archetype == "item_collection":
        grid = _catalog_grid(frame)
        inner = f"{topbar}{headline}{grid}{emph_html}{assets_html}"
    elif archetype == "comparison":
        rows = _compare_rows(frame)
        inner = f"{topbar}{headline}{rows}{emph_html}{assets_html}"
    elif archetype == "scene":
        cards = _scene_panels(frame)
        inner = f"{topbar}{headline}{cards}{emph_html}{assets_html}"
    else:  # save
        block = frame.content_blocks[0] if frame.content_blocks else None
        block0 = ""
        if block:
            block0 = (
                copy_atom(block.heading, role="content_blocks[0].heading", class_name="gc-sub", tag="div")
                if block.heading else ""
            )
            # Body before items matches the probe's expected copy order
            # (heading -> body -> items), same as the canonical _render_block;
            # emitting body after items made the probe reject save pages whose
            # block 0 has both a body and items.
            if block.body:
                block0 += copy_atom(
                    block.body, role="content_blocks[0].body", class_name="gc-sub", tag="div"
                )
            for i, item in enumerate(block.items or []):
                block0 += copy_atom(item, role=f"content_blocks[0].items[{i}]", class_name="gc-sub", tag="div")
        extra = _extra_blocks(frame, 1)
        inner = f"{topbar}{headline}{block0}{extra}{emph_html}{assets_html}"
    return f'<section class="template-body composition-{section_cls}">{inner}</section>'


def _render(
    frame: CarouselFrame,
    assets: Sequence[AssetManifestItem],
    variant: ResolvedVariant,
    semantic_kind: str,
    footer: str | None,
) -> str:
    body = render_composed_body(
        frame,
        assets,
        mode=_MODE_BY_VARIANT[variant.composition_variant],
        marker_style="number",
        semantic_kind=semantic_kind,
    )
    return f"<style>{FAMILY_CSS}</style>{render_card_shell(FAMILY, frame, variant, body, footer=footer)}"


def _focus(frame, assets, variant, footer):
    return _render(frame, assets, variant, "focus", footer)


def _narrative(frame, assets, variant, footer):
    return _render(frame, assets, variant, "narrative", footer)


def _structured(frame, assets, variant, footer):
    return _render(frame, assets, variant, "structured", footer)


_ARCHETYPE_KIND = archetype_renderer_map(_focus, _narrative, _structured)

_EMPTY_HEADER = '<header class="template-header"></header>'


def render_frame(
    frame: CarouselFrame,
    assets: Sequence[AssetManifestItem],
    variant: ResolvedVariant,
) -> str:
    archetype = frame.page_archetype
    footer = _persona_atom(frame) or None
    if archetype == "cover" and not frame.content_blocks:
        body = _cover_body(frame, assets)
        return f"<style>{FAMILY_CSS}</style>{render_card_shell(FAMILY, frame, variant, body, header=_EMPTY_HEADER, footer=footer)}"
    if archetype in _BESPOKE_ARCHETYPES:
        body = _bespoke_body(frame, assets, archetype)
        return f"<style>{FAMILY_CSS}</style>{render_card_shell(FAMILY, frame, variant, body, header=_EMPTY_HEADER, footer=footer)}"
    return _ARCHETYPE_KIND[archetype](frame, assets, variant, footer)
