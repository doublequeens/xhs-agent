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


FAMILY: TemplateFamily = "coral_impact"

# Archetypes that get the bespoke coral_impact composition (珊瑚宣传: bold coral
# field, oversized Heavy headlines, A/B/C story beats, translucent step cells,
# big boundary closer). Cover handled separately. All visible copy flows through
# copy_atom / render_blocks / render_assets so every content_blocks field,
# emphasis chip and asset slot is emitted with the probe's expected roles and
# order; only structure/CSS are bespoke. Archetypes outside this set fall
# through to generic (still with the persona footer rendered).
# save is rendered bespoke too (centered closer), but only for sparse content
# (see render_frame) — so it's NOT in this general gate; a content-rich save
# falls through to the generic grid instead of overflowing the centered layout.
_BESPOKE_ARCHETYPES = frozenset({"story_beat", "steps", "boundary"})

_SECTION_CLASS = {
    "story_beat": "ci-story",
    "steps": "ci-steps",
    "boundary": "ci-boundary",
    "save": "ci-save",
}

# Decorative emoji icons (aria-hidden — not copy) matching the set4 mockup.
_CHAT_HTML = '<span class="ci-chat" aria-hidden="true">💬</span>'

FAMILY_CSS = """
/* coral_impact card: coral field, no inner border frame. Compound selector
   beats the base .template-card rule. */
.template-card.template-coral-impact{background:#F45A5A;color:#fff;padding:90px 88px;gap:0}
.template-card.template-coral-impact::before{display:none}
.template-coral-impact .template-footer{border-top:none;padding-top:0}
.template-coral-impact .page-number{display:none}
/* bespoke body section becomes the layout root (flex column, overflow:visible) */
.template-coral-impact .template-body.composition-ci-cover,
.template-coral-impact .template-body.composition-ci-boundary,
.template-coral-impact .template-body.composition-ci-save{
  display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;min-height:0;overflow:visible}
.template-coral-impact .template-body.composition-ci-story,
.template-coral-impact .template-body.composition-ci-steps{
  display:flex;flex-direction:column;justify-content:flex-start;min-height:0;overflow:visible}
/* persona handle: bottom-center, one copy atom, body family for the probe */
.template-coral-impact .ci-handle{
  position:absolute;bottom:54px;left:50%;transform:translateX(-50%);font-size:26px;line-height:1.3;
  color:rgba(255,255,255,.9);letter-spacing:.04em;font-weight:700;white-space:nowrap}
/* headline atom — Alibaba PuHuiTi Heavy (display family); 2-line via <br> */
.template-coral-impact .ci-q{
  font-family:var(--template-display);font-weight:700;color:#fff;
  letter-spacing:-.02em;overflow-wrap:anywhere}
.template-coral-impact .ci-tag{
  font-size:30px;line-height:1.3;color:#FFE3E3;letter-spacing:.12em;font-weight:700}
.template-coral-impact .ci-sub{
  font-size:48px;line-height:1.55;color:#FFE3E3;overflow-wrap:anywhere}
.template-coral-impact .ci-keys{display:flex;flex-wrap:wrap;gap:12px;justify-content:center;margin-top:24px}
.template-coral-impact .ci-chip{
  font-size:26px;line-height:1.3;color:#fff;background:rgba(255,255,255,.18);font-weight:700;
  padding:10px 22px;border-radius:999px}
.template-coral-impact .ci-chat{font-size:44px;line-height:1}
.template-coral-impact .ci-row{
  display:flex;align-items:center;justify-content:center;gap:16px;margin-top:36px;font-size:36px;
  line-height:1.3;color:#fff;font-weight:700}
/* generic-fallback (non-bespoke archetypes) scaled up so sparse pages don't look empty */
.template-coral-impact .composition-grid,.template-coral-impact .composition-stack,.template-coral-impact .composition-focus{align-content:flex-start}
.template-coral-impact .block-heading{font-size:40px;line-height:1.3;color:#fff}
.template-coral-impact .block-body{font-size:32px;line-height:1.5;color:rgba(255,255,255,.95)}
.template-coral-impact .item-copy{font-size:30px;line-height:1.5;color:rgba(255,255,255,.95)}
.template-coral-impact .item-marker{font-size:30px;line-height:1;color:#FFE3E3}
.template-coral-impact .emphasis-chip{font-size:28px;line-height:1.3;padding:12px 26px;background:rgba(255,255,255,.18);color:#fff}
/* ===== COVER (oversized title + chat row + deco circle) ===== */
.template-coral-impact .composition-ci-cover .ci-tag{font-size:32px;letter-spacing:.22em}
.template-coral-impact .composition-ci-cover .ci-q{font-size:128px;line-height:1.15;margin-top:24px}
.template-coral-impact .composition-ci-cover .ci-sub{font-size:48px;line-height:1.55;margin-top:20px}
.template-coral-impact .composition-ci-cover .ci-deco{
  position:absolute;left:-90px;bottom:-80px;width:380px;height:380px;border-radius:50%;
  background:#7B1730;opacity:.28;pointer-events:none}
/* ===== STORY_BEAT (A/B/C marks, thick dividers) ===== */
.template-coral-impact .composition-ci-story .ci-q{font-size:72px;line-height:1.14;margin-top:8px}
.template-coral-impact .ci-beats{flex:1;display:flex;flex-direction:column;justify-content:flex-start;gap:0;margin-top:20px}
.template-coral-impact .ci-beat{display:flex;gap:24px;align-items:flex-start;padding:22px 0;border-bottom:5px solid rgba(255,255,255,.72)}
.template-coral-impact .ci-beat:last-child{border-bottom:none}
.template-coral-impact .ci-mark{
  font-family:var(--template-display);font-weight:700;font-size:64px;line-height:1;
  color:rgba(255,255,255,.5);min-width:90px;flex:0 0 auto}
.template-coral-impact .ci-beat-copy{min-width:0;font-size:32px;line-height:1.5;color:rgba(255,255,255,.95)}
.template-coral-impact .ci-beat-name{font-family:var(--template-display);font-weight:700;font-size:46px;line-height:1.18;color:#fff;display:block}
.template-coral-impact .ci-beat-desc{display:block;font-size:32px;line-height:1.5;color:rgba(255,255,255,.95);margin-top:6px}
.template-coral-impact .ci-sep{display:none}
/* ===== STEPS (translucent 2-col cells) ===== */
.template-coral-impact .composition-ci-steps .ci-q{font-size:68px;line-height:1.14;margin-top:8px}
.template-coral-impact .ci-grid{flex:1;display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:24px;align-content:start}
.template-coral-impact .ci-cell{
  background:rgba(255,255,255,.18);border-radius:22px;padding:26px;display:flex;flex-direction:column;gap:10px}
.template-coral-impact .ci-cell-num{font-family:var(--template-display);font-weight:700;font-size:54px;line-height:1;color:#FFE3E3}
.template-coral-impact .ci-cell-copy{display:flex;flex-direction:column;gap:6px;min-width:0;font-size:28px;line-height:1.45}
.template-coral-impact .ci-cell-h{font-family:var(--template-display);font-weight:700;font-size:38px;line-height:1.2;color:#fff}
.template-coral-impact .ci-cell-p{font-size:28px;line-height:1.45;color:rgba(255,255,255,.94)}
/* ===== BOUNDARY (centered closer + icon) ===== */
.template-coral-impact .composition-ci-boundary .ci-icon{font-size:150px;line-height:1}
.template-coral-impact .composition-ci-boundary .ci-q{font-size:112px;line-height:1.18;margin-top:20px}
.template-coral-impact .composition-ci-boundary .ci-sub{font-size:44px;line-height:1.55;margin-top:22px}
/* ===== SAVE (centered — sparse content centered, ends with the chat CTA) ===== */
.template-coral-impact .composition-ci-save .ci-icon{font-size:140px;line-height:1}
.template-coral-impact .composition-ci-save .ci-q{font-size:96px;line-height:1.16;margin-top:22px}
.template-coral-impact .composition-ci-save .ci-sub{font-size:38px;line-height:1.55;margin-top:22px}
"""

_MODE_BY_VARIANT = {
    "impact-cover": "focus",
    "stacked-impact": "stack",
    "contrast-impact": "grid",
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
    return copy_atom(frame.persona, role="persona", class_name="ci-handle", tag="div")


def _headline_atom(frame: CarouselFrame, *, cls: str = "ci-q") -> str:
    return _two_line_atom(frame.headline, role="headline", class_name=cls, tag="div")


def _tag_atom(frame: CarouselFrame) -> str:
    if not frame.kicker:
        return ""
    return copy_atom(frame.kicker, role="kicker", class_name="ci-tag", tag="div")


def _sub_atoms(frame: CarouselFrame) -> str:
    """emphasis rendered as coral-light subtitle lines."""
    if not frame.emphasis:
        return ""
    return "".join(
        copy_atom(value, role=f"emphasis[{i}]", class_name="ci-sub", tag="div")
        for i, value in enumerate(frame.emphasis)
    )


def _emphasis_atoms(frame: CarouselFrame) -> str:
    if not frame.emphasis:
        return ""
    return "".join(
        copy_atom(value, role=f"emphasis[{i}]", class_name="ci-chip", tag="span")
        for i, value in enumerate(frame.emphasis)
    )


def _extra_blocks(frame: CarouselFrame, start: int) -> str:
    if len(frame.content_blocks) <= start:
        return ""
    return "".join(
        _render_block(b, i, "number")
        for i, b in enumerate(frame.content_blocks[start:], start=start)
    )


def _story_beats(frame: CarouselFrame) -> str:
    """block 0 items → A/B/C beats (decorative mark + name/desc, thick dividers).
    Each item split on ｜ into name + desc; one copy atom per item."""
    block = frame.content_blocks[0] if frame.content_blocks else None
    if not block:
        return ""
    heading = (
        copy_atom(block.heading, role="content_blocks[0].heading", class_name="ci-beat-desc", tag="div")
        if block.heading else ""
    )
    body = (
        copy_atom(block.body, role="content_blocks[0].body", class_name="ci-beat-desc", tag="div")
        if block.body else ""
    )
    beats = ""
    for i, item in enumerate(block.items or []):
        mark = chr(ord("A") + i) if i < 26 else str(i + 1)
        segs = item.split("｜")
        if len(segs) == 1:
            inner = f'<span class="ci-beat-desc">{_render_copy_value(segs[0])}</span>'
        else:
            inner = (
                f'<span class="ci-beat-name">{_render_copy_value(segs[0])}</span>'
                f'<span class="ci-sep">｜</span>'
                f'<span class="ci-beat-desc">{_render_copy_value(segs[1])}</span>'
            )
        beats += (
            f'<div class="ci-beat"><div class="ci-mark" aria-hidden="true">{_render_copy_value(mark)}</div>'
            f'<span class="ci-beat-copy" data-card-copy data-copy-role="content_blocks[0].items[{i}]">{inner}</span></div>'
        )
    extra = _extra_blocks(frame, 1)
    return f"{heading}{body}<div class=\"ci-beats\">{beats}</div>{extra}"


def _steps_grid(frame: CarouselFrame) -> str:
    """block 0 items → translucent cells (decorative num + name/desc). One atom each."""
    block = frame.content_blocks[0] if frame.content_blocks else None
    if not block:
        return ""
    heading = (
        copy_atom(block.heading, role="content_blocks[0].heading", class_name="ci-cell-p", tag="div")
        if block.heading else ""
    )
    body = (
        copy_atom(block.body, role="content_blocks[0].body", class_name="ci-cell-p", tag="div")
        if block.body else ""
    )
    cells = ""
    for i, item in enumerate(block.items or []):
        segs = item.split("｜")
        if len(segs) == 1:
            inner = f'<span class="ci-cell-h">{_render_copy_value(segs[0])}</span>'
        else:
            inner = (
                f'<span class="ci-cell-h">{_render_copy_value(segs[0])}</span>'
                f'<span class="ci-sep">｜</span>'
                f'<span class="ci-cell-p">{_render_copy_value(segs[1])}</span>'
            )
        cells += (
            f'<div class="ci-cell"><div class="ci-cell-num" aria-hidden="true">{i + 1:02d}</div>'
            f'<span class="ci-cell-copy" data-card-copy data-copy-role="content_blocks[0].items[{i}]">{inner}</span></div>'
        )
    grid = f'<div class="ci-grid">{cells}</div>' if cells else ""
    extra = _extra_blocks(frame, 1)
    return f"{heading}{body}{grid}{extra}"


def _cover_body(frame: CarouselFrame, assets: Sequence[AssetManifestItem]) -> str:
    tag = _tag_atom(frame)
    headline = _headline_atom(frame, cls="ci-q")
    extra = _extra_blocks(frame, 0)
    sub = _sub_atoms(frame)
    deco = '<div class="ci-deco" aria-hidden="true"></div>'
    assets_html = render_assets(assets)
    inner = f"{tag}{headline}{extra}{sub}{deco}{assets_html}"
    return f'<section class="template-body composition-ci-cover">{inner}</section>'


def _bespoke_body(
    frame: CarouselFrame, assets: Sequence[AssetManifestItem], archetype: str
) -> str:
    section_cls = _SECTION_CLASS[archetype]
    tag = _tag_atom(frame)
    headline = _headline_atom(frame)
    assets_html = render_assets(assets)

    if archetype == "story_beat":
        beats = _story_beats(frame)
        emph = _emphasis_atoms(frame)
        emph_html = f'<div class="ci-keys">{emph}</div>' if emph else ""
        inner = f"{tag}{headline}{beats}{emph_html}{assets_html}"
    elif archetype == "steps":
        grid = _steps_grid(frame)
        emph = _emphasis_atoms(frame)
        emph_html = f'<div class="ci-keys">{emph}</div>' if emph else ""
        inner = f"{tag}{headline}{grid}{emph_html}{assets_html}"
    elif archetype == "save":
        # centered closer — sparse content centered, ends with the chat CTA
        # moved off the cover so the opening page stays clean.
        icon = '<div class="ci-icon" aria-hidden="true">🔖</div>'
        extra = _extra_blocks(frame, 0)
        sub = _sub_atoms(frame)
        row = f'<div class="ci-row">{_CHAT_HTML}<span>评论区告诉我你的痛点</span></div>'
        inner = f"{tag}{icon}{headline}{extra}{sub}{row}{assets_html}"
    else:  # boundary
        icon = '<div class="ci-icon" aria-hidden="true">🧴</div>'
        extra = _extra_blocks(frame, 0)
        sub = _sub_atoms(frame)
        row = f'<div class="ci-row">{_CHAT_HTML}<span>下一步想解决什么？</span></div>'
        inner = f"{tag}{icon}{headline}{extra}{sub}{row}{assets_html}"
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
    if archetype == "save" and len(frame.content_blocks) <= 1:
        # centered save only for sparse content (production closing page); a
        # content-rich save (raw frames) falls through to the generic grid.
        body = _bespoke_body(frame, assets, archetype)
        return f"<style>{FAMILY_CSS}</style>{render_card_shell(FAMILY, frame, variant, body, header=_EMPTY_HEADER, footer=footer)}"
    if archetype in _BESPOKE_ARCHETYPES:
        body = _bespoke_body(frame, assets, archetype)
        return f"<style>{FAMILY_CSS}</style>{render_card_shell(FAMILY, frame, variant, body, header=_EMPTY_HEADER, footer=footer)}"
    return _ARCHETYPE_KIND[archetype](frame, assets, variant, footer)
