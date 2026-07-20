from __future__ import annotations

import re
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


FAMILY: TemplateFamily = "pink_red"

# Archetypes that get the bespoke pink_red composition (粉红粗体 motivational).
# Cover is handled separately. All visible copy flows through copy_atom /
# render_blocks / render_assets so every content_blocks field, emphasis chip and
# asset slot is emitted with the probe's expected roles and order; only the
# structure and CSS are bespoke. Archetypes outside this set fall through to
# generic (still with the persona footer rendered).
_BESPOKE_ARCHETYPES = frozenset({"steps", "comparison", "save", "scene"})

_SECTION_CLASS = {
    "steps": "pr-steps",
    "comparison": "pr-compare",
    "save": "pr-save",
    "scene": "pr-scene",
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
}

# Decorative brand label top-left of the cover (aria-hidden — not copy).
_BRAND = "MISTIPS"

# The defining trait of pink_red: pink and red backgrounds STRICTLY ALTERNATE
# across the carousel (pink, red, pink, red, …), never two of the same in a row.
# The page index is encoded in frame_id as ``frame-NN-archetype`` (set by the
# storyboards generator). Odd positions (1,3,…) are pink; even (2,4,…) are red.
_FRAME_NUM_RE = re.compile(r"(\d+)")


def _is_red_page(frame: CarouselFrame) -> bool:
    match = _FRAME_NUM_RE.search(frame.frame_id or "")
    if not match:
        # No parseable page number (e.g. test fixtures): default to pink so the
        # red-text-on-pink scheme stays legible.
        return False
    return int(match.group(1)) % 2 == 0


# Colour scheme lives in CSS variables so any bespoke layout renders correctly
# on EITHER a pink page or a red page (the bg alternates by index, not by
# archetype). Defaults below are the PINK scheme; the red scheme overrides the
# same vars via _RED_SCHEME_CSS (emitted per-frame on red pages).
FAMILY_CSS = """
/* pink_red card: pink field by default, no inner border frame. Compound selector
   beats the base .template-card rule (BASE <style> is emitted after FAMILY_CSS). */
.template-card.template-pink-red{
  --pr-ink:#DC2333; --pr-sub:#B01828;
  --pr-cell-bg:#fff; --pr-cell-ink:#DC2333; --pr-cell-no:#8a3a44; --pr-cell-sub:#5a3a40;
  --pr-marker:rgba(220,35,51,.32);
  --pr-panel-bg:rgba(255,255,255,.55); --pr-panel-ring:rgba(220,35,51,.16);
  --pr-btn-bg:#DC2333; --pr-btn-ink:#fff;
  padding:90px 88px;gap:0}
.template-card.template-pink-red::before{display:none}
/* footer chrome stripped (persona renders via absolute pr-handle; footer-copy
   atom, when present e.g. in smoke tests, must stay visible — no display:none) */
.template-pink-red .template-footer{border-top:none;padding-top:0}
.template-pink-red .page-number{display:none}
/* bespoke body section becomes the layout root (flex column). overflow:visible
   so a headline flush at the top isn't clipped by the section box — the card's
   own overflow:hidden still clips at the card bounds (padding gives room). */
.template-pink-red .template-body.composition-pr-cover{
  display:flex;flex-direction:column;justify-content:space-between;min-height:0;overflow:visible}
.template-pink-red .template-body.composition-pr-steps{
  display:flex;flex-direction:column;justify-content:flex-start;min-height:0;overflow:visible}
.template-pink-red .template-body.composition-pr-compare{
  display:flex;flex-direction:column;justify-content:flex-start;min-height:0;overflow:visible}
.template-pink-red .template-body.composition-pr-save{
  display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;min-height:0;overflow:visible}
.template-pink-red .template-body.composition-pr-scene{
  display:flex;flex-direction:column;justify-content:flex-start;min-height:0;overflow:visible;gap:22px}
/* persona handle: bottom-left, one copy atom, body family for the probe */
.template-pink-red .pr-handle{
  position:absolute;left:88px;bottom:54px;font-size:26px;line-height:1.3;
  color:var(--pr-sub);letter-spacing:.04em;font-weight:700;white-space:nowrap}
/* headline atom — Heavy (display family); 2-line via <br> at first comma/mid */
.template-pink-red .pr-q{
  font-family:var(--template-display);font-weight:700;color:var(--pr-ink);
  letter-spacing:-.01em;overflow-wrap:anywhere}
.template-pink-red .pr-kicker{
  font-size:32px;line-height:1.3;color:var(--pr-sub);letter-spacing:.12em;font-weight:700}
.template-pink-red .pr-lead{font-size:30px;line-height:1.4;font-weight:700;color:var(--pr-ink)}
.template-pink-red .pr-keys{
  display:flex;flex-wrap:wrap;gap:12px;justify-content:flex-end;margin-top:18px}
.template-pink-red .pr-chip{
  font-size:26px;line-height:1.3;color:var(--pr-cell-ink);background:var(--pr-cell-bg);font-weight:700;
  padding:10px 22px;border-radius:999px}
/* generic-fallback (non-bespoke archetypes e.g. scene) scaled up to match the
   bold pink_red aesthetic so sparse pages don't look empty. Bespoke pages use
   pr-* classes, so these only affect the generic path. */
.template-pink-red .block-heading{font-size:40px;line-height:1.3;color:var(--pr-ink)}
.template-pink-red .block-body{font-size:32px;line-height:1.55}
.template-pink-red .item-copy{font-size:30px;line-height:1.5}
.template-pink-red .item-marker{font-size:30px;line-height:1;color:var(--pr-sub)}
.template-pink-red .emphasis-chip{font-size:28px;line-height:1.3;padding:12px 26px;background:var(--pr-cell-bg);color:var(--pr-cell-ink)}
/* ===== COVER ===== */
.template-pink-red .composition-pr-cover .pr-topbar{
  display:flex;justify-content:space-between;font-size:24px;line-height:1.3;
  font-weight:700;letter-spacing:.22em;color:var(--pr-sub);text-transform:uppercase}
.template-pink-red .composition-pr-cover .pr-hero{
  flex:1;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;gap:22px}
.template-pink-red .composition-pr-cover .pr-q{font-size:96px;line-height:1.08}
.template-pink-red .composition-pr-cover .pr-sub{
  font-size:38px;line-height:1.3;color:var(--pr-sub);font-weight:700}
.template-pink-red .composition-pr-cover .pr-btn{
  margin-top:12px;font-size:38px;line-height:1.3;color:var(--pr-btn-ink);background:var(--pr-btn-bg);
  font-weight:700;padding:22px 50px;border-radius:999px}
/* ===== STEPS (numbered) ===== */
.template-pink-red .composition-pr-steps .pr-q{font-size:74px;line-height:1.16;color:var(--pr-ink);margin-top:10px}
.template-pink-red .pr-steps-list{flex:1;display:flex;flex-direction:column;justify-content:center;gap:30px;margin-top:20px}
.template-pink-red .pr-step{display:flex;gap:28px;align-items:flex-start}
.template-pink-red .pr-marker{
  font-family:var(--template-display);font-weight:700;font-size:96px;line-height:1;
  color:var(--pr-marker);min-width:120px;flex:0 0 auto}
.template-pink-red .pr-step-copy{min-width:0;font-size:32px;line-height:1.55;color:var(--pr-ink)}
.template-pink-red .pr-step-name{font-family:var(--template-display);font-weight:700;font-size:46px;line-height:1.2;color:var(--pr-ink);display:block}
.template-pink-red .pr-step-desc{display:block;font-size:32px;line-height:1.55;color:var(--pr-sub);margin-top:8px}
.template-pink-red .pr-sep{display:none}
/* ===== COMPARISON (do/don't grid) ===== */
.template-pink-red .composition-pr-compare .pr-q{font-size:60px;line-height:1.16;color:var(--pr-ink)}
.template-pink-red .pr-grid{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:24px;align-content:start}
.template-pink-red .pr-cell{
  background:var(--pr-cell-bg);border-radius:24px;padding:36px 32px;display:flex;flex-direction:column;gap:14px;
  box-shadow:0 12px 36px rgba(176,24,40,.14)}
.template-pink-red .pr-cell-mark{font-size:28px;line-height:1.3;color:var(--pr-cell-ink);font-weight:700}
.template-pink-red .pr-cell.no .pr-cell-mark{color:var(--pr-cell-no)}
.template-pink-red .pr-cell-copy{display:flex;flex-direction:column;gap:6px;min-width:0;font-size:28px;line-height:1.45}
.template-pink-red .pr-cell-h{font-family:var(--template-display);font-weight:700;font-size:34px;line-height:1.2;color:var(--pr-cell-ink)}
.template-pink-red .pr-cell.no .pr-cell-h{color:var(--pr-cell-no)}
.template-pink-red .pr-cell-p{font-size:28px;line-height:1.45;color:var(--pr-cell-sub)}
/* ===== SAVE (centered) ===== */
.template-pink-red .composition-pr-save .pr-q{font-size:96px;line-height:1.14;color:var(--pr-ink)}
.template-pink-red .composition-pr-save .pr-sub{
  font-size:36px;line-height:1.55;color:var(--pr-sub);font-weight:700;margin-top:20px;max-width:760px}
/* ===== SCENE (content panels — Double-Bezel cards, editorial) ===== */
.template-pink-red .composition-pr-scene .pr-q{font-size:64px;line-height:1.15;color:var(--pr-ink)}
.template-pink-red .composition-pr-scene .pr-kicker{font-size:26px;letter-spacing:.18em}
.template-pink-red .pr-panels{
  display:grid;grid-template-columns:1fr 1fr;gap:18px;align-content:start;margin-top:6px}
/* odd card count (1 or 3): the last card spans full width for visual balance */
.template-pink-red .pr-panels .pr-panel:last-child:nth-child(odd){grid-column:1/-1}
.template-pink-red .pr-panel{
  background:var(--pr-panel-bg);border:1px solid var(--pr-panel-ring);border-radius:28px;
  padding:30px 38px;box-shadow:inset 0 1px 1px rgba(255,255,255,.18)}
.template-pink-red .pr-eyebrow{
  display:inline-block;font-size:22px;line-height:1.3;font-weight:700;letter-spacing:.2em;
  color:var(--pr-sub);text-transform:uppercase;margin-bottom:12px}
.template-pink-red .pr-panel-h{
  margin:0;font-size:38px;line-height:1.2;color:var(--pr-ink)}
.template-pink-red .pr-panel-h-txt{font-family:var(--template-display);font-weight:700}
.template-pink-red .pr-panel-b{margin:10px 0 0;font-size:28px;line-height:1.55;color:var(--pr-sub)}
.template-pink-red .pr-panel-items{list-style:none;margin:16px 0 0;padding:0;display:flex;flex-direction:column;gap:14px}
.template-pink-red .pr-panel-item{display:flex;gap:16px;align-items:center}
.template-pink-red .pr-panel-dot{
  width:12px;height:12px;border-radius:50%;background:var(--pr-ink);opacity:.45;flex:0 0 auto}
.template-pink-red .pr-panel-item-copy{font-size:28px;line-height:1.5;color:var(--pr-cell-sub)}
"""

# RED page scheme: flips the card to a red field with white type. Emitted as a
# per-frame <style> AFTER FAMILY_CSS so the var overrides win (same specificity,
# later in source). Each rendered page is its own document, so this only affects
# the one red page.
_RED_SCHEME_CSS = """
.template-card.template-pink-red{
  background:#DC2333;color:#fff;
  --pr-ink:#fff; --pr-sub:#FFE3E3;
  --pr-cell-bg:rgba(255,255,255,.12); --pr-cell-ink:#fff; --pr-cell-no:rgba(255,255,255,.72); --pr-cell-sub:rgba(255,255,255,.9);
  --pr-marker:rgba(255,255,255,.32);
  --pr-panel-bg:rgba(255,255,255,.10); --pr-panel-ring:rgba(255,255,255,.18);
  --pr-btn-bg:#fff; --pr-btn-ink:#DC2333;
}
/* generic-fallback type on red pages must flip to white too */
.template-pink-red .block-heading,.template-pink-red .block-body,.template-pink-red .item-copy{color:#fff}
.template-pink-red .item-marker{color:rgba(255,255,255,.6)}
"""

# Generic-fallback composition modes keyed by the family's registered variants.
_MODE_BY_VARIANT = {
    "centered-number": "focus",
    "red-panel": "stack",
    "white-card": "stack",
    "split-card": "split",
}


def _css_for(frame: CarouselFrame) -> str:
    return FAMILY_CSS + (_RED_SCHEME_CSS if _is_red_page(frame) else "")


def _two_line_value(text: str) -> str:
    """Two-line render via a <br> after the first comma (mockup convention), else
    near the midpoint. <br> adds no textContent, so the probe contract holds."""
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
    return copy_atom(frame.persona, role="persona", class_name="pr-handle", tag="div")


def _headline_atom(frame: CarouselFrame, *, cls: str = "pr-q") -> str:
    return _two_line_atom(frame.headline, role="headline", class_name=cls, tag="div")


def _kicker_atom(frame: CarouselFrame, *, cls: str = "pr-kicker") -> str:
    if not frame.kicker:
        return ""
    return copy_atom(frame.kicker, role="kicker", class_name=cls, tag="div")


def _emphasis_atoms(frame: CarouselFrame, cls: str = "pr-sub") -> str:
    if not frame.emphasis:
        return ""
    return "".join(
        copy_atom(value, role=f"emphasis[{i}]", class_name=cls, tag="div")
        for i, value in enumerate(frame.emphasis)
    )


def _extra_blocks(frame: CarouselFrame, start: int) -> str:
    if len(frame.content_blocks) <= start:
        return ""
    return "".join(
        _render_block(b, i, "number")
        for i, b in enumerate(frame.content_blocks[start:], start=start)
    )


def _steps_list(frame: CarouselFrame) -> str:
    """block 0 items → numbered steps (decorative 01/02/03 marker + name/desc).
    Each item split on ｜ into name + desc; one copy atom per item. Block 0
    heading/body rendered first (contract); remaining blocks via fallback."""
    block = frame.content_blocks[0] if frame.content_blocks else None
    if not block:
        return ""
    heading = (
        copy_atom(block.heading, role="content_blocks[0].heading", class_name="pr-lead", tag="div")
        if block.heading else ""
    )
    body = (
        copy_atom(block.body, role="content_blocks[0].body", class_name="pr-step-desc", tag="div")
        if block.body else ""
    )
    rows = ""
    for i, item in enumerate(block.items or []):
        segs = item.split("｜")
        if len(segs) == 1:
            inner = f'<span class="pr-step-desc">{_render_copy_value(segs[0])}</span>'
        else:
            inner = (
                f'<span class="pr-step-name">{_render_copy_value(segs[0])}</span>'
                f'<span class="pr-sep">｜</span>'
                f'<span class="pr-step-desc">{_render_copy_value(segs[1])}</span>'
            )
        rows += (
            f'<div class="pr-step"><div class="pr-marker" aria-hidden="true">{i + 1:02d}</div>'
            f'<span class="pr-step-copy" data-card-copy data-copy-role="content_blocks[0].items[{i}]">{inner}</span></div>'
        )
    extra = _extra_blocks(frame, 1)
    return f"{heading}{body}<div class=\"pr-steps-list\">{rows}</div>{extra}"


def _compare_grid(frame: CarouselFrame) -> str:
    """block 0 items → do/don't cells (alternating ✓/✗ decorative marker + ch/cp).
    Each item split on ｜ into ch + cp; one copy atom per item."""
    block = frame.content_blocks[0] if frame.content_blocks else None
    if not block:
        return ""
    heading = (
        copy_atom(block.heading, role="content_blocks[0].heading", class_name="pr-lead", tag="div")
        if block.heading else ""
    )
    body = (
        copy_atom(block.body, role="content_blocks[0].body", class_name="pr-cell-p", tag="div")
        if block.body else ""
    )
    cells = ""
    for i, item in enumerate(block.items or []):
        segs = item.split("｜")
        no = (i % 2 == 1)
        mark = "✗" if no else "✓"
        if len(segs) == 1:
            inner = f'<span class="pr-cell-h">{_render_copy_value(segs[0])}</span>'
        else:
            inner = (
                f'<span class="pr-cell-h">{_render_copy_value(segs[0])}</span>'
                f'<span class="pr-sep">｜</span>'
                f'<span class="pr-cell-p">{_render_copy_value(segs[1])}</span>'
            )
        cells += (
            f'<div class="pr-cell{" no" if no else ""}"><div class="pr-cell-mark" aria-hidden="true">{mark}</div>'
            f'<span class="pr-cell-copy" data-card-copy data-copy-role="content_blocks[0].items[{i}]">{inner}</span></div>'
        )
    grid = f'<div class="pr-grid">{cells}</div>' if cells else ""
    extra = _extra_blocks(frame, 1)
    return f"{heading}{body}{grid}{extra}"


def _scene_card(idx_blocks: list, card_num: int) -> str:
    """One Double-Bezel panel card. ``idx_blocks`` is a list of (block_index,
    block) — usually one block, but when content exceeds 4 blocks the tail
    blocks merge into the 4th card so the layout never exceeds 2×2 while every
    block's heading/body/items still carry their contract roles in order."""
    label = _PANEL_LABEL.get(getattr(idx_blocks[0][1], "block_type", "") or "", "要点")
    eyebrow = f'<div class="pr-eyebrow" aria-hidden="true">{card_num:02d} · {label}</div>'
    inner = ""
    for i, block in idx_blocks:
        heading = (
            f'<div class="pr-panel-h" data-card-copy data-copy-role="content_blocks[{i}].heading">'
            f'<span class="pr-panel-h-txt">{_render_copy_value(block.heading)}</span></div>'
            if block.heading else ""
        )
        body = (
            copy_atom(block.body, role=f"content_blocks[{i}].body", class_name="pr-panel-b", tag="div")
            if block.body else ""
        )
        items = ""
        if block.items:
            lis = "".join(
                f'<li class="pr-panel-item"><span class="pr-panel-dot" aria-hidden="true"></span>'
                f'{copy_atom(item, role=f"content_blocks[{i}].items[{j}]", class_name="pr-panel-item-copy", tag="span")}'
                "</li>"
                for j, item in enumerate(block.items)
            )
            items = f'<ul class="pr-panel-items">{lis}</ul>'
        inner += heading + body + items
    return f'<div class="pr-panel">{eyebrow}{inner}</div>'


def _scene_panels(frame: CarouselFrame) -> str:
    """Scene page = a 2-column grid of white cards (1–4 cards). Each content
    block is one card; if there are more than 4 blocks the tail merges into the
    4th card so the grid never exceeds 2×2 (every block still renders)."""
    blocks = list(enumerate(frame.content_blocks))
    if not blocks:
        return ""
    if len(blocks) <= 4:
        groups = [[blocks[k]] for k in range(len(blocks))]
    else:
        groups = [[blocks[k]] for k in range(3)] + [blocks[3:]]
    cards = "".join(_scene_card(g, n + 1) for n, g in enumerate(groups))
    return f'<div class="pr-panels">{cards}</div>'


def _cover_body(frame: CarouselFrame, assets: Sequence[AssetManifestItem]) -> str:
    kicker = _kicker_atom(frame)
    # topbar: decorative brand left + kicker right (kicker stays a copy atom)
    if kicker:
        topbar = (
            f'<div class="pr-topbar"><span aria-hidden="true">{_render_copy_value(_BRAND)}</span>'
            f"{kicker}</div>"
        )
    else:
        topbar = f'<div class="pr-topbar"><span aria-hidden="true">{_render_copy_value(_BRAND)}</span></div>'
    headline = _headline_atom(frame, cls="pr-q")
    extra = _extra_blocks(frame, 0)
    sub = "".join(
        copy_atom(value, role=f"emphasis[{i}]", class_name="pr-sub", tag="div")
        for i, value in enumerate(frame.emphasis)
    )
    btn = '<div class="pr-btn" aria-hidden="true">向右滑动 →</div>'
    assets_html = render_assets(assets)
    hero = f'<div class="pr-hero">{headline}{extra}{sub}{btn}</div>'
    inner = f"{topbar}{hero}{assets_html}"
    return f'<section class="template-body composition-pr-cover">{inner}</section>'


def _bespoke_body(
    frame: CarouselFrame, assets: Sequence[AssetManifestItem], archetype: str
) -> str:
    section_cls = _SECTION_CLASS[archetype]
    kicker = _kicker_atom(frame)
    headline = _headline_atom(frame)
    assets_html = render_assets(assets)

    if archetype == "steps":
        steps = _steps_list(frame)
        emph = _emphasis_atoms(frame, cls="pr-chip")
        emph_html = f'<div class="pr-keys">{emph}</div>' if emph else ""
        inner = f"{kicker}{headline}{steps}{emph_html}{assets_html}"
    elif archetype == "comparison":
        grid = _compare_grid(frame)
        emph = _emphasis_atoms(frame, cls="pr-chip")
        emph_html = f'<div class="pr-keys">{emph}</div>' if emph else ""
        inner = f"{kicker}{headline}{grid}{emph_html}{assets_html}"
    elif archetype == "scene":
        panels = _scene_panels(frame)
        emph = _emphasis_atoms(frame, cls="pr-chip")
        emph_html = f'<div class="pr-keys">{emph}</div>' if emph else ""
        inner = f"{kicker}{headline}{panels}{emph_html}{assets_html}"
    else:  # save
        # block 0 rendered in contract order: heading, body, items
        block = frame.content_blocks[0] if frame.content_blocks else None
        block0 = ""
        if block:
            block0 = (
                copy_atom(block.heading, role="content_blocks[0].heading", class_name="pr-sub", tag="div")
                if block.heading else ""
            )
            block0 += (
                copy_atom(block.body, role="content_blocks[0].body", class_name="pr-sub", tag="div")
                if block.body else ""
            )
            for i, item in enumerate(block.items or []):
                block0 += copy_atom(item, role=f"content_blocks[0].items[{i}]", class_name="pr-sub", tag="div")
        extra = _extra_blocks(frame, 1)
        emph = _emphasis_atoms(frame)
        inner = f"{kicker}{headline}{block0}{extra}{emph}{assets_html}"
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
    return f"<style>{_css_for(frame)}</style>{render_card_shell(FAMILY, frame, variant, body, footer=footer)}"


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
    # persona is injected for every pink_red frame; it MUST render on every path.
    footer = _persona_atom(frame) or None
    if archetype == "cover" and not frame.content_blocks:
        body = _cover_body(frame, assets)
        return f"<style>{_css_for(frame)}</style>{render_card_shell(FAMILY, frame, variant, body, header=_EMPTY_HEADER, footer=footer)}"
    if archetype in _BESPOKE_ARCHETYPES:
        body = _bespoke_body(frame, assets, archetype)
        return f"<style>{_css_for(frame)}</style>{render_card_shell(FAMILY, frame, variant, body, header=_EMPTY_HEADER, footer=footer)}"
    return _ARCHETYPE_KIND[archetype](frame, assets, variant, footer)
