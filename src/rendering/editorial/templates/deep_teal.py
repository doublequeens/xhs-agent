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


FAMILY: TemplateFamily = "deep_teal"

# Archetypes that get the bespoke deep_teal composition (深青极简: teal field,
# numbered concept rows, bordered checklist grid, Q/A stack). Cover handled
# separately. All visible copy flows through copy_atom / render_blocks /
# render_assets so every content_blocks field, emphasis chip and asset slot is
# emitted with the probe's expected roles and order; only structure/CSS are
# bespoke. Archetypes outside this set fall through to generic (still with the
# persona footer rendered).
_BESPOKE_ARCHETYPES = frozenset({"explanation", "checklist", "qa", "scene"})

_SECTION_CLASS = {
    "explanation": "dt-explain",
    "checklist": "dt-checklist",
    "qa": "dt-qa",
    "scene": "dt-scene",
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

# Decorative brand label top-left of the cover (aria-hidden — not copy).
_BRAND = "MISTIPS"

FAMILY_CSS = """
/* deep_teal card: teal field, no inner border frame. Compound selector beats
   the base .template-card rule (BASE <style> is emitted after FAMILY_CSS). */
.template-card.template-deep-teal{padding:90px 88px;gap:0}
.template-card.template-deep-teal::before{display:none}
.template-deep-teal .template-footer{border-top:none;padding-top:0}
.template-deep-teal .page-number{display:none}
/* bespoke body section becomes the layout root (flex column, overflow:visible so
   a top-flush headline's ascender isn't clipped — the card clips at its bounds). */
.template-deep-teal .template-body.composition-dt-cover{
  display:flex;flex-direction:column;justify-content:space-between;min-height:0;overflow:visible}
.template-deep-teal .template-body.composition-dt-explain,
.template-deep-teal .template-body.composition-dt-checklist,
.template-deep-teal .template-body.composition-dt-qa,
.template-deep-teal .template-body.composition-dt-scene{
  display:flex;flex-direction:column;justify-content:flex-start;min-height:0;overflow:visible}
/* persona handle: bottom-left, one copy atom, body family for the probe */
.template-deep-teal .dt-handle{
  position:absolute;left:88px;bottom:54px;font-size:26px;line-height:1.3;
  color:rgba(255,255,255,.6);letter-spacing:.04em;font-weight:700;white-space:nowrap}
/* headline atom — HarmonyOS Sans Medium (display family); 2-line via <br> */
.template-deep-teal .dt-q{
  font-family:var(--template-display);font-weight:700;color:#fff;
  letter-spacing:.05em;overflow-wrap:anywhere}
.template-deep-teal .dt-tag{
  font-size:30px;line-height:1.3;color:#7FD6D6;letter-spacing:.12em;font-weight:700}
.template-deep-teal .dt-block-h{
  font-size:34px;line-height:1.4;color:#fff;font-weight:700;margin:0 0 12px}
.template-deep-teal .dt-sub{
  font-size:36px;line-height:1.55;color:rgba(255,255,255,.82);overflow-wrap:anywhere}
.template-deep-teal .dt-keys{
  display:flex;flex-wrap:wrap;gap:12px;justify-content:flex-end;margin-top:18px}
.template-deep-teal .dt-chip{
  font-size:26px;line-height:1.3;color:#fff;background:rgba(127,214,214,.18);
  border:1px solid rgba(127,214,214,.4);font-weight:700;padding:10px 22px;border-radius:999px}
/* generic-fallback (non-bespoke archetypes) scaled up so sparse pages don't look empty.
   Top-align the composition so content sits right under the headline, matching
   the bespoke content pages (checklist/explanation/qa). */
.template-deep-teal .composition-grid{align-content:flex-start}
.template-deep-teal .composition-stack{align-content:flex-start}
.template-deep-teal .composition-focus{align-content:flex-start}
.template-deep-teal .block-heading{font-size:40px;line-height:1.3;color:#fff}
.template-deep-teal .block-body{font-size:32px;line-height:1.5;color:rgba(255,255,255,.9)}
.template-deep-teal .item-copy{font-size:30px;line-height:1.5;color:rgba(255,255,255,.9)}
.template-deep-teal .item-marker{font-size:30px;line-height:1;color:#7FD6D6}
.template-deep-teal .emphasis-chip{font-size:28px;line-height:1.3;padding:12px 26px;background:rgba(127,214,214,.18);color:#fff;border:1px solid rgba(127,214,214,.4)}
/* ===== COVER ===== */
.template-deep-teal .composition-dt-cover .dt-topbar{
  display:flex;justify-content:space-between;font-size:24px;line-height:1.3;
  font-weight:700;letter-spacing:.2em;color:rgba(255,255,255,.72);text-transform:uppercase}
.template-deep-teal .composition-dt-cover .dt-toprule{height:2px;background:rgba(255,255,255,.3);margin-top:8px}
.template-deep-teal .composition-dt-cover .dt-hero{
  flex:1;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;gap:14px}
.template-deep-teal .composition-dt-cover .dt-q{font-size:80px;line-height:1.15}
.template-deep-teal .composition-dt-cover .dt-sub{font-size:36px;line-height:1.4;margin-top:8px}
/* ===== EXPLANATION (numbered concept rows) ===== */
.template-deep-teal .composition-dt-explain .dt-q{font-size:66px;line-height:1.2;margin-top:8px}
.template-deep-teal .dt-rows{flex:1;display:flex;flex-direction:column;justify-content:flex-start;gap:0;margin-top:20px}
.template-deep-teal .dt-row{display:flex;gap:28px;align-items:flex-start;padding:22px 0;border-top:2px solid rgba(255,255,255,.28)}
.template-deep-teal .dt-row:first-child{border-top:none}
.template-deep-teal .dt-num{
  font-family:var(--template-display);font-weight:700;font-size:78px;line-height:1;
  color:#7FD6D6;min-width:110px;flex:0 0 auto}
.template-deep-teal .dt-row-copy{min-width:0;font-size:32px;line-height:1.55;color:rgba(255,255,255,.9)}
.template-deep-teal .dt-row-name{font-family:var(--template-display);font-weight:700;font-size:42px;line-height:1.2;color:#fff;display:block}
.template-deep-teal .dt-row-desc{display:block;font-size:32px;line-height:1.55;color:rgba(255,255,255,.9);margin-top:6px}
.template-deep-teal .dt-sep{display:none}
/* ===== CHECKLIST (bordered grid) ===== */
.template-deep-teal .composition-dt-checklist .dt-q{font-size:62px;line-height:1.2;margin-top:8px}
.template-deep-teal .dt-grid{flex:1;display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:24px;align-content:start}
.template-deep-teal .dt-cell{
  padding:24px;border:2px solid rgba(255,255,255,.4);border-radius:18px;display:flex;flex-direction:column;gap:8px}
.template-deep-teal .dt-cell-mark{font-size:30px;line-height:1.3;color:#7FD6D6;font-weight:700}
.template-deep-teal .dt-cell-copy{display:flex;flex-direction:column;gap:6px;min-width:0;font-size:26px;line-height:1.4}
.template-deep-teal .dt-cell-h{font-family:var(--template-display);font-weight:700;font-size:32px;line-height:1.2;color:#fff}
.template-deep-teal .dt-cell-p{font-size:26px;line-height:1.45;color:rgba(255,255,255,.82)}
/* ===== QA (Q/A stack) ===== */
.template-deep-teal .composition-dt-qa .dt-q{font-size:64px;line-height:1.2;margin-top:8px}
.template-deep-teal .dt-qa-list{flex:1;display:flex;flex-direction:column;justify-content:flex-start;gap:30px;margin-top:20px}
.template-deep-teal .dt-qa-item{display:flex;flex-direction:column;gap:10px}
.template-deep-teal .dt-qa-item-copy{display:flex;flex-direction:column;gap:10px;min-width:0;font-size:32px;line-height:1.55}
.template-deep-teal .dt-qa-q{font-family:var(--template-display);font-weight:700;font-size:38px;line-height:1.3;color:#7FD6D6}
.template-deep-teal .dt-qa-a{font-size:32px;line-height:1.55;color:rgba(255,255,255,.92)}
/* ===== SCENE (bordered bento cards filling the page, content centered) ===== */
.template-deep-teal .composition-dt-scene .dt-q{font-size:60px;line-height:1.2;margin-top:8px}
.template-deep-teal .dt-scene-cards{
  flex:1;display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:24px;align-content:stretch;min-height:0}
.template-deep-teal .dt-scene-cards .dt-scene-card:only-child{grid-column:1/-1}
.template-deep-teal .dt-scene-cards .dt-scene-card:last-child:nth-child(odd){grid-column:1/-1}
.template-deep-teal .dt-scene-card{
  border:2px solid rgba(255,255,255,.4);border-radius:18px;padding:36px;
  display:flex;flex-direction:column;justify-content:center;gap:16px;min-width:0;overflow:hidden}
.template-deep-teal .dt-scene-eyebrow{
  font-size:22px;line-height:1.3;color:#7FD6D6;letter-spacing:.2em;font-weight:700;text-transform:uppercase}
.template-deep-teal .dt-scene-h{margin:0;font-size:38px;line-height:1.2;color:#fff;font-weight:700}
.template-deep-teal .dt-scene-b{margin:0;font-size:28px;line-height:1.55;color:rgba(255,255,255,.85)}
.template-deep-teal .dt-scene-items{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:12px}
.template-deep-teal .dt-scene-item{display:flex;gap:14px;align-items:center}
.template-deep-teal .dt-scene-dot{width:10px;height:10px;border-radius:50%;background:#7FD6D6;opacity:.7;flex:0 0 auto}
.template-deep-teal .dt-scene-item-copy{font-size:28px;line-height:1.5;color:rgba(255,255,255,.88)}
"""

_MODE_BY_VARIANT = {
    "centered-minimal": "focus",
    "numbered-column": "stack",
    "rule-grid": "grid",
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
    return copy_atom(frame.persona, role="persona", class_name="dt-handle", tag="div")


def _headline_atom(frame: CarouselFrame, *, cls: str = "dt-q") -> str:
    return _two_line_atom(frame.headline, role="headline", class_name=cls, tag="div")


def _tag_atom(frame: CarouselFrame) -> str:
    """kicker rendered as the section tag (light-teal label)."""
    if not frame.kicker:
        return ""
    return copy_atom(frame.kicker, role="kicker", class_name="dt-tag", tag="div")


def _emphasis_atoms(frame: CarouselFrame) -> str:
    if not frame.emphasis:
        return ""
    return "".join(
        copy_atom(value, role=f"emphasis[{i}]", class_name="dt-chip", tag="span")
        for i, value in enumerate(frame.emphasis)
    )


def _extra_blocks(frame: CarouselFrame, start: int) -> str:
    if len(frame.content_blocks) <= start:
        return ""
    return "".join(
        _render_block(b, i, "number")
        for i, b in enumerate(frame.content_blocks[start:], start=start)
    )


def _explain_rows(frame: CarouselFrame) -> str:
    """block 0 items → numbered concept rows (decorative 01/02/03 + name/desc).
    Each item split on ｜ into name + desc; one copy atom per item. Block 0
    heading/body rendered first; remaining blocks via fallback."""
    block = frame.content_blocks[0] if frame.content_blocks else None
    if not block:
        return ""
    heading = (
        copy_atom(block.heading, role="content_blocks[0].heading", class_name="dt-block-h", tag="div")
        if block.heading else ""
    )
    body = (
        copy_atom(block.body, role="content_blocks[0].body", class_name="dt-row-desc", tag="div")
        if block.body else ""
    )
    rows = ""
    for i, item in enumerate(block.items or []):
        segs = item.split("｜")
        if len(segs) == 1:
            inner = f'<span class="dt-row-desc">{_render_copy_value(segs[0])}</span>'
        else:
            inner = (
                f'<span class="dt-row-name">{_render_copy_value(segs[0])}</span>'
                f'<span class="dt-sep">｜</span>'
                f'<span class="dt-row-desc">{_render_copy_value(segs[1])}</span>'
            )
        rows += (
            f'<div class="dt-row"><div class="dt-num" aria-hidden="true">{i + 1:02d}</div>'
            f'<span class="dt-row-copy" data-card-copy data-copy-role="content_blocks[0].items[{i}]">{inner}</span></div>'
        )
    extra = _extra_blocks(frame, 1)
    return f"{heading}{body}<div class=\"dt-rows\">{rows}</div>{extra}"


def _checklist_grid(frame: CarouselFrame) -> str:
    """block 0 items → bordered cells (decorative ✓ mark + ch/cp). One atom each."""
    block = frame.content_blocks[0] if frame.content_blocks else None
    if not block:
        return ""
    heading = (
        copy_atom(block.heading, role="content_blocks[0].heading", class_name="dt-block-h", tag="div")
        if block.heading else ""
    )
    body = (
        copy_atom(block.body, role="content_blocks[0].body", class_name="dt-cell-p", tag="div")
        if block.body else ""
    )
    cells = ""
    for i, item in enumerate(block.items or []):
        segs = item.split("｜")
        if len(segs) == 1:
            inner = f'<span class="dt-cell-h">{_render_copy_value(segs[0])}</span>'
        else:
            inner = (
                f'<span class="dt-cell-h">{_render_copy_value(segs[0])}</span>'
                f'<span class="dt-sep">｜</span>'
                f'<span class="dt-cell-p">{_render_copy_value(segs[1])}</span>'
            )
        cells += (
            f'<div class="dt-cell"><div class="dt-cell-mark" aria-hidden="true">✓</div>'
            f'<span class="dt-cell-copy" data-card-copy data-copy-role="content_blocks[0].items[{i}]">{inner}</span></div>'
        )
    grid = f'<div class="dt-grid">{cells}</div>' if cells else ""
    extra = _extra_blocks(frame, 1)
    return f"{heading}{body}{grid}{extra}"


def _qa_list(frame: CarouselFrame) -> str:
    """block 0 items → Q/A items (split on ｜ into question + answer). One atom each."""
    block = frame.content_blocks[0] if frame.content_blocks else None
    if not block:
        return ""
    heading = (
        copy_atom(block.heading, role="content_blocks[0].heading", class_name="dt-block-h", tag="div")
        if block.heading else ""
    )
    body = (
        copy_atom(block.body, role="content_blocks[0].body", class_name="dt-row-desc", tag="div")
        if block.body else ""
    )
    items = ""
    for i, item in enumerate(block.items or []):
        segs = item.split("｜", 1)
        q = _render_copy_value(segs[0])
        a = _render_copy_value(segs[1]) if len(segs) > 1 else ""
        inner = (
            f'<span class="dt-qa-q">{q}</span>'
            + (f'<span class="dt-sep">｜</span><span class="dt-qa-a">{a}</span>' if a else "")
        )
        items += (
            f'<div class="dt-qa-item"><span class="dt-qa-item-copy" data-card-copy '
            f'data-copy-role="content_blocks[0].items[{i}]">{inner}</span></div>'
        )
    list_html = f'<div class="dt-qa-list">{items}</div>' if items else ""
    extra = _extra_blocks(frame, 1)
    return f"{heading}{body}{list_html}{extra}"


def _scene_card(idx_blocks: list, card_num: int) -> str:
    """One bordered bento card. ``idx_blocks`` is a list of (block_index, block)
    — usually one block; the tail blocks merge into the 4th card when content
    exceeds 4 blocks so the grid never exceeds 2×2 while every block's
    heading/body/items still carry their contract roles in order."""
    label = _PANEL_LABEL.get(getattr(idx_blocks[0][1], "block_type", "") or "", "要点")
    eyebrow = f'<div class="dt-scene-eyebrow" aria-hidden="true">{card_num:02d} · {label}</div>'
    inner = ""
    for i, block in idx_blocks:
        heading = (
            copy_atom(block.heading, role=f"content_blocks[{i}].heading", class_name="dt-scene-h", tag="div")
            if block.heading else ""
        )
        body = (
            copy_atom(block.body, role=f"content_blocks[{i}].body", class_name="dt-scene-b", tag="div")
            if block.body else ""
        )
        items = ""
        if block.items:
            lis = "".join(
                f'<li class="dt-scene-item"><span class="dt-scene-dot" aria-hidden="true"></span>'
                f'{copy_atom(item, role=f"content_blocks[{i}].items[{j}]", class_name="dt-scene-item-copy", tag="span")}'
                "</li>"
                for j, item in enumerate(block.items)
            )
            items = f'<ul class="dt-scene-items">{lis}</ul>'
        inner += heading + body + items
    return f'<div class="dt-scene-card">{eyebrow}{inner}</div>'


def _scene_panels(frame: CarouselFrame) -> str:
    """Scene page = a 2-column grid of bordered cards (1–4 cards) that fill the
    page height with content centered in each card (balanced, not crowded at
    top). Each content block is one card; >4 blocks merge into the 4th card."""
    blocks = list(enumerate(frame.content_blocks))
    if not blocks:
        return ""
    if len(blocks) <= 4:
        groups = [[blocks[k]] for k in range(len(blocks))]
    else:
        groups = [[blocks[k]] for k in range(3)] + [blocks[3:]]
    cards = "".join(_scene_card(g, n + 1) for n, g in enumerate(groups))
    return f'<div class="dt-scene-cards">{cards}</div>'


def _cover_body(frame: CarouselFrame, assets: Sequence[AssetManifestItem]) -> str:
    kicker = _tag_atom(frame)
    topbar = (
        f'<div class="dt-topbar"><span aria-hidden="true">{_render_copy_value(_BRAND)}</span>{kicker}</div>'
        if kicker else f'<div class="dt-topbar"><span aria-hidden="true">{_render_copy_value(_BRAND)}</span></div>'
    )
    toprule = '<div class="dt-toprule" aria-hidden="true"></div>'
    headline = _headline_atom(frame, cls="dt-q")
    extra = _extra_blocks(frame, 0)
    sub = "".join(
        copy_atom(value, role=f"emphasis[{i}]", class_name="dt-sub", tag="div")
        for i, value in enumerate(frame.emphasis)
    )
    assets_html = render_assets(assets)
    hero = f'<div class="dt-hero">{headline}{extra}{sub}</div>{assets_html}'
    inner = f"{topbar}{toprule}{hero}"
    return f'<section class="template-body composition-dt-cover">{inner}</section>'


def _bespoke_body(
    frame: CarouselFrame, assets: Sequence[AssetManifestItem], archetype: str
) -> str:
    section_cls = _SECTION_CLASS[archetype]
    tag = _tag_atom(frame)
    headline = _headline_atom(frame)
    assets_html = render_assets(assets)

    if archetype == "explanation":
        rows = _explain_rows(frame)
        emph = _emphasis_atoms(frame)
        emph_html = f'<div class="dt-keys">{emph}</div>' if emph else ""
        inner = f"{tag}{headline}{rows}{emph_html}{assets_html}"
    elif archetype == "checklist":
        grid = _checklist_grid(frame)
        emph = _emphasis_atoms(frame)
        emph_html = f'<div class="dt-keys">{emph}</div>' if emph else ""
        inner = f"{tag}{headline}{grid}{emph_html}{assets_html}"
    elif archetype == "qa":
        qa = _qa_list(frame)
        emph = _emphasis_atoms(frame)
        emph_html = f'<div class="dt-keys">{emph}</div>' if emph else ""
        inner = f"{tag}{headline}{qa}{emph_html}{assets_html}"
    else:  # scene
        cards = _scene_panels(frame)
        emph = _emphasis_atoms(frame)
        emph_html = f'<div class="dt-keys">{emph}</div>' if emph else ""
        inner = f"{tag}{headline}{cards}{emph_html}{assets_html}"
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
