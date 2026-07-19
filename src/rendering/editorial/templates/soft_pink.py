from __future__ import annotations

import re
from collections.abc import Sequence
from html import escape

from src.schemas.assets import AssetManifestItem
from src.schemas.editorial_templates import ResolvedVariant, TemplateFamily
from src.schemas.storyboard import CarouselFrame

from ..primitives import (
    _render_block,
    _render_copy_value,
    archetype_renderer_map,
    copy_atom,
    render_assets,
    render_blocks,
    render_card_shell,
    render_composed_body,
)


FAMILY: TemplateFamily = "soft_pink"

# Archetypes that get the bespoke soft_pink editorial composition (floating card
# centered in the pink field, dashed dividers, pill emphasis, persona footer,
# cover hero numeral). All visible copy still flows through the shared
# render_blocks/render_assets primitives (so every content_blocks field, every
# emphasis chip and every asset slot is emitted with the probe's expected
# data-card-copy / data-asset-slot roles and order); only the surrounding
# structure and CSS are bespoke. Archetypes outside this set are unaffected.
# Non-cover archetypes that get the bespoke floating-card composition. Cover is
# handled separately (bespoke hero only when the headline has an N步 numeral,
# else it falls back to the generic composition path).
_BESPOKE_ARCHETYPES = frozenset(
    {"scene", "story_beat", "explanation", "save", "steps", "boundary"}
)

# marker style passed to render_blocks per archetype. "" yields numeric markers
# (01, 02, …) which CSS enlarges into the numbered spine for concept/step pages.
_MARKER_BY_ARCHETYPE = {
    "scene": "dot",
    "story_beat": "dot",
    "explanation": "",
    "save": "check",
    "steps": "",
    "boundary": "dot",
}
_SECTION_CLASS = {
    "scene": "sp-scene",
    "story_beat": "sp-story",
    "explanation": "sp-explain",
    "save": "sp-save",
    "steps": "sp-steps",
    "boundary": "sp-boundary",
}

# Matches the "N步" inside a cover headline so the digit can be rendered as the
# hero numeral. The digit stays part of the headline copy atom (textContent is
# preserved exactly), so no duplicate numeral and no new locked field.
_HERO_DIGIT_RE = re.compile(r"(\d+)\s*步")

FAMILY_CSS = """
.template-soft-pink{background:#F8DADA;color:#3a2020}
.template-soft-pink::before{display:none}
.template-soft-pink .template-kicker{
  align-self:flex-start;display:inline-block;background:#EE5C5C;color:#fff;
  font-weight:500;font-size:26px;line-height:1.3;letter-spacing:.08em;padding:12px 30px;border-radius:999px}
.template-soft-pink .template-headline{color:#D8444C;font-weight:500;letter-spacing:-.02em}
.template-soft-pink .template-body{display:flex;flex-direction:column;gap:24px}
.template-soft-pink .template-footer{border-color:rgba(216,68,76,.25)}
.template-soft-pink .footer-copy{color:#a86570}
.template-soft-pink .page-number{display:none}
.template-soft-pink .template-footer{border-top:none;padding-top:0}
.template-soft-pink .sp-wrap{flex:1;display:flex;flex-direction:column;justify-content:center;min-height:0}
.template-soft-pink .sp-card{
  background:#fff;border-radius:40px;padding:56px 52px;
  box-shadow:0 22px 56px rgba(216,68,76,.16)}
.template-soft-pink .sp-card .copy-grid{gap:16px}
.template-soft-pink .sp-card .content-block{gap:10px}
.template-soft-pink .sp-card .block-heading{color:#D8444C}
.template-soft-pink .sp-card .block-body{color:#5a3a3a}
.template-soft-pink .sp-card .item-copy{color:#3a2020}
.template-soft-pink .sp-persona{
  position:absolute;left:88px;bottom:54px;font-size:24px;line-height:1.4;color:#a86a72;letter-spacing:.04em}
.template-soft-pink .sp-emphasis{display:flex;flex-wrap:wrap;gap:14px;margin-top:4px}
.template-soft-pink .emphasis-chip{
  background:#FDEAEC;color:#D8444C;font-weight:500;font-size:28px;line-height:1.3;
  padding:12px 26px;border-radius:999px}
/* cover: prototype replica — a centered row: big numeral (left) + title block
   (title + subtitle, right). num/title/sub are separate copy atoms (each a
   single font size), matching the approved mockup exactly. */
.template-soft-pink .composition-sp-cover .sp-wrap{align-items:center;justify-content:center}
.template-soft-pink .sp-row{display:flex;align-items:center;justify-content:center;gap:42px}
.template-soft-pink .sp-num{
  font-family:var(--template-display);font-weight:500;font-size:300px;line-height:1.05;
  color:#EE5C5C;letter-spacing:-.05em}
.template-soft-pink .sp-ttl-block{display:flex;flex-direction:column;align-items:flex-start}
.template-soft-pink .sp-ttl{
  font-family:var(--template-display);font-weight:500;font-size:78px;line-height:1.12;color:#D8444C}
.template-soft-pink .sp-ttl-pre{color:#7a444c}
.template-soft-pink .sp-ttl-suf{color:#EE5C5C}
.template-soft-pink .sp-sub{font-size:36px;line-height:1.4;color:#7a444c;margin-top:22px}
/* ===== shared page elements ===== */
.template-soft-pink .sp-h{font-family:var(--template-display);font-weight:500;color:#3a2020;line-height:1.15}
.template-soft-pink .sp-sh{font-size:30px;line-height:1.4;color:#7a444c;margin-top:10px}
.template-soft-pink .sp-tags{display:flex;flex-wrap:wrap;gap:14px;margin-top:24px}
.template-soft-pink .sp-tag{background:#FDEAEC;color:#D8444C;font-size:28px;line-height:1.3;padding:12px 26px;border-radius:999px}
.template-soft-pink .sp-item-copy{display:block;min-width:0;font-size:30px;line-height:1.45}
.template-soft-pink .sp-sep{display:none}
/* 02 SCENE — diagnostic table */
.template-soft-pink .sp-scene-card{padding:56px 50px}
.template-soft-pink .composition-sp-scene .sp-h{font-size:56px}
.template-soft-pink .sp-scene-rows{margin-top:14px}
.template-soft-pink .sp-scene-row{padding:28px 0;border-top:1px dashed #e6c0c6}
.template-soft-pink .sp-scene-row:first-child{border-top:none}
.template-soft-pink .sp-scene-copy{display:flex;justify-content:space-between;align-items:center;width:100%;font-size:34px;line-height:1.45}
.template-soft-pink .sp-scene-subj{font-size:34px;line-height:1.3;color:#6a4444}
.template-soft-pink .sp-scene-stat{font-family:var(--template-display);font-weight:500;font-size:36px;line-height:1.3;color:#D8444C}
/* 03 STORY_BEAT — minimal tension */
.template-soft-pink .sp-story-card{padding:88px 60px;text-align:center}
.template-soft-pink .composition-sp-story .sp-big{font-family:var(--template-display);font-weight:500;font-size:74px;line-height:1.2;color:#3a2020}
.template-soft-pink .sp-p{font-size:32px;line-height:1.5;color:#7a444c;margin-top:30px}
.template-soft-pink .composition-sp-story .sp-tags{justify-content:center;margin-top:34px}
.template-soft-pink .composition-sp-story .sp-tag{background:#EE5C5C;color:#fff}
/* 04 EXPLANATION — numbered concept spine */
.template-soft-pink .composition-sp-explain .sp-h{font-size:60px}
.template-soft-pink .sp-lead{font-size:30px;line-height:1.4;color:#7a444c;margin-top:14px}
.template-soft-pink .sp-explain-card{margin-top:26px;padding:44px 50px}
.template-soft-pink .sp-erow{display:flex;align-items:center;gap:30px;padding:26px 0}
.template-soft-pink .sp-erow + .sp-erow{border-top:1px dashed #e6c0c6}
.template-soft-pink .sp-enum{width:104px;height:104px;border-radius:50%;background:#EE5C5C;color:#fff;font-family:var(--template-display);font-weight:500;font-size:56px;display:flex;align-items:center;justify-content:center;flex:0 0 auto}
.template-soft-pink .sp-ename{font-family:var(--template-display);font-weight:500;font-size:50px;line-height:1.1;color:#D8444C}
.template-soft-pink .sp-edesc{display:block;font-size:30px;line-height:1.4;color:#7a444c;margin-top:6px}
/* 05 SAVE — checklist card */
.template-soft-pink .sp-save-card{padding:56px 52px}
.template-soft-pink .composition-sp-save .sp-h{font-size:56px}
.template-soft-pink .sp-sub{font-size:30px;line-height:1.5;color:#7a444c;margin-top:16px}
.template-soft-pink .sp-save-list{margin-top:14px}
.template-soft-pink .sp-save-item{display:flex;align-items:center;gap:22px;padding:26px 0;border-top:1px dashed #e6c0c6}
.template-soft-pink .sp-save-item:first-child{border-top:none}
.template-soft-pink .sp-save-copy{font-size:36px;line-height:1.45;color:#3a2020}
.template-soft-pink .sp-chk{width:48px;height:48px;border-radius:50%;background:#EE5C5C;color:#fff;font-family:var(--template-display);font-weight:500;font-size:26px;display:flex;align-items:center;justify-content:center;flex:0 0 auto}
/* 06 STEPS — numbered spine */
.template-soft-pink .sp-steps-card{padding:52px 50px 56px}
.template-soft-pink .composition-sp-steps .sp-h{font-size:58px}
.template-soft-pink .sp-rows{margin-top:28px}
.template-soft-pink .sp-step{padding:28px 0;border-top:1px dashed #e6c0c6}
.template-soft-pink .sp-step:first-child{border-top:none;padding-top:8px}
.template-soft-pink .sp-name{font-family:var(--template-display);font-weight:500;font-size:40px;line-height:1.1;color:#D8444C}
.template-soft-pink .sp-what{display:block;font-size:29px;line-height:1.4;color:#5a3a3a;margin-top:8px}
.template-soft-pink .sp-how{display:block;font-size:25px;line-height:1.4;color:#9a6a6a;margin-top:6px}
.template-soft-pink .composition-sp-steps .sp-tags{justify-content:center;margin-top:30px}
/* 07 BOUNDARY — advisory card */
.template-soft-pink .composition-sp-boundary .sp-pill{background:#3a2020;color:#FFE3E3}
.template-soft-pink .sp-boundary-card{position:relative;padding:60px 52px 60px 68px;box-shadow:0 22px 56px rgba(58,32,32,.18);overflow:hidden}
.template-soft-pink .sp-boundary-card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:14px;background:#EE5C5C}
.template-soft-pink .composition-sp-boundary .sp-h{font-size:56px;line-height:1.18;margin-top:18px}
.template-soft-pink .sp-note{font-size:32px;line-height:1.5;color:#5a3a3a;margin-top:30px}
.template-soft-pink .composition-sp-boundary .sp-tag{background:#3a2020;color:#FFE3E3}
"""

_MODE_BY_VARIANT = {
    "offset-cover": "focus",
    "floating-card": "stack",
    "soft-grid": "grid",
}


def _persona_atom(frame: CarouselFrame) -> str:
    if not frame.persona:
        return ""
    return copy_atom(frame.persona, role="persona", class_name="sp-persona", tag="div")


def _cover_header(frame: CarouselFrame) -> str:
    """Cover header with only the kicker; the headline is rendered inside the
    body (beside the hero numeral) so the two share a row, matching the approved
    mockup. render_card_shell accepts this via its ``header`` override."""
    kicker = (
        copy_atom(frame.kicker, role="kicker", class_name="template-kicker", tag="span")
        if frame.kicker
        else ""
    )
    return f'<header class="template-header">{kicker}</header>'


def _cover_num_atom(frame: CarouselFrame) -> str:
    if not frame.hero_numeral:
        return ""
    return copy_atom(
        frame.hero_numeral, role="hero_numeral", class_name="sp-num", tag="div"
    )


def _cover_title_atom(frame: CarouselFrame) -> str:
    """The cover title as one headline atom: pre<br>suf, with the hero-numeral
    digit and any colon removed. textContent == cover_title_text(headline) (the
    <br> contributes no text), so the probe's actual==expected copy contract
    holds and the numeral is not duplicated in the title."""
    headline = frame.headline
    digit = frame.hero_numeral
    idx = headline.find(digit) if digit else -1
    if digit and idx >= 0:
        pre = headline[:idx].replace("：", "").replace(":", "")
        suf = headline[idx + len(digit):]
        # pre (scenario) muted, suf ("步清爽补妆") matches the numeral's coral
        # so the eye groups "3" + "步清爽补妆" as "3步清爽补妆". textContent is
        # still pre + suf (spans/<br> add no text) == cover_title_text.
        return (
            f'<div class="sp-ttl" data-card-copy data-copy-role="headline">'
            f'<span class="sp-ttl-pre">{_render_copy_value(pre)}</span>'
            f'<br><span class="sp-ttl-suf">{_render_copy_value(suf)}</span></div>'
        )
    return copy_atom(
        headline.replace("：", "").replace(":", ""),
        role="headline",
        class_name="sp-ttl",
        tag="div",
    )


def _cover_body(frame: CarouselFrame, assets: Sequence[AssetManifestItem]) -> str:
    # Prototype cover: a centered row with the big numeral on the left and a
    # title block (title + subtitle) on the right — num/title/sub are separate
    # copy atoms (each uniform font size, so no probe overflow/line-count issues
    # from mixing sizes in one atom). persona sits in the card footer.
    num = _cover_num_atom(frame)
    title = _cover_title_atom(frame)
    sub = "".join(
        copy_atom(value, role=f"emphasis[{i}]", class_name="sp-sub", tag="div")
        for i, value in enumerate(frame.emphasis)
    )
    assets_html = render_assets(assets)
    row = (
        f'<div class="sp-row">{num}'
        f'<div class="sp-ttl-block">{title}{sub}</div></div>'
    )
    inner = f'<div class="sp-wrap">{row}{assets_html}</div>'
    return f'<section class="template-body composition-sp-cover">{inner}</section>'


def _headline_atom(frame: CarouselFrame, cls: str = "sp-h") -> str:
    return copy_atom(frame.headline, role="headline", class_name=cls, tag="div")


def _block_heading_atom(frame: CarouselFrame) -> str:
    if not frame.content_blocks or not frame.content_blocks[0].heading:
        return ""
    return copy_atom(
        frame.content_blocks[0].heading,
        role="content_blocks[0].heading",
        class_name="sp-sh",
        tag="div",
    )


def _block_body_atom(frame: CarouselFrame, cls: str) -> str:
    if not frame.content_blocks or not frame.content_blocks[0].body:
        return ""
    return copy_atom(
        frame.content_blocks[0].body,
        role="content_blocks[0].body",
        class_name=cls,
        tag="div",
    )


def _tags_atom(frame: CarouselFrame) -> str:
    if not frame.emphasis:
        return ""
    chips = "".join(
        copy_atom(value, role=f"emphasis[{i}]", class_name="sp-tag", tag="span")
        for i, value in enumerate(frame.emphasis)
    )
    return f'<div class="sp-tags">{chips}</div>'


def _items_for(block, idx: int, archetype: str) -> str:
    """Render a block's items in the prototype structure for the archetype.
    One copy atom per item (textContent == item); roles content_blocks[idx].items[i]."""
    if not block or not block.items:
        return ""
    role = f"content_blocks[{idx}].items"
    if archetype == "scene":
        rows = ""
        for i, item in enumerate(block.items):
            subj, stat = item[:2], item[2:]  # first 2 chars = subject, rest = status
            rows += (
                f'<div class="sp-scene-row">'
                f'<span class="sp-scene-copy" data-card-copy data-copy-role="{role}[{i}]">'
                f'<span class="sp-scene-subj">{_render_copy_value(subj)}</span>'
                f'<span class="sp-scene-stat">{_render_copy_value(stat)}</span>'
                f"</span></div>"
            )
        return f'<div class="sp-scene-rows">{rows}</div>'
    if archetype == "save":
        rows = ""
        for i, item in enumerate(block.items):
            rows += (
                f'<div class="sp-save-item"><div class="sp-chk" aria-hidden="true">{i + 1}</div>'
                f'{copy_atom(item, role=f"{role}[{i}]", class_name="sp-save-copy", tag="span")}</div>'
            )
        return f'<div class="sp-save-list">{rows}</div>'
    # explanation (enum + ename/edesc) / steps (name/what/how): split on ｜
    if archetype == "explanation":
        seg_classes, row_cls, enum = ["sp-ename", "sp-edesc"], "sp-erow", True
    else:  # steps
        seg_classes, row_cls, enum = ["sp-name", "sp-what", "sp-how", "sp-how"], "sp-step", False
    rows = ""
    for i, item in enumerate(block.items):
        segs = item.split("｜")
        if len(segs) == 1:
            inner = f'<span class="{seg_classes[0]}">{_render_copy_value(segs[0])}</span>'
        else:
            parts = [
                f'<span class="{seg_classes[min(j, len(seg_classes) - 1)]}">{_render_copy_value(s)}</span>'
                for j, s in enumerate(segs)
            ]
            inner = '<span class="sp-sep">｜</span>'.join(parts)
        enum_html = f'<div class="sp-enum" aria-hidden="true">{i + 1}</div>' if enum else ""
        rows += (
            f'<div class="{row_cls}">{enum_html}'
            f'<span class="sp-item-copy" data-card-copy data-copy-role="{role}[{i}]">{inner}</span></div>'
        )
    return f'<div class="sp-rows">{rows}</div>'


def _primary_block(frame: CarouselFrame, archetype: str) -> str:
    if not frame.content_blocks:
        return ""
    block = frame.content_blocks[0]
    heading = (
        copy_atom(block.heading, role="content_blocks[0].heading", class_name="sp-sh", tag="div")
        if block.heading else ""
    )
    body_cls = {"story_beat": "sp-p", "explanation": "sp-lead", "save": "sp-sub", "boundary": "sp-note"}.get(archetype)
    body = (
        copy_atom(block.body, role="content_blocks[0].body", class_name=body_cls, tag="div")
        if block.body and body_cls else ""
    )
    items = _items_for(block, 0, archetype)
    return heading + body + items


def _bespoke_body(
    frame: CarouselFrame, assets: Sequence[AssetManifestItem], archetype: str
) -> str:
    section_cls = _SECTION_CLASS[archetype]
    assets_html = render_assets(assets)
    h = _headline_atom(frame, "sp-big" if archetype == "story_beat" else "sp-h")
    primary = _primary_block(frame, archetype)
    # remaining blocks (multi-block fixtures) rendered standard so the probe's
    # expected copy still matches; production frames have a single block.
    extra = (
        "".join(_render_block(b, i, "dot") for i, b in enumerate(frame.content_blocks[1:], start=1))
        if len(frame.content_blocks) > 1 else ""
    )
    tags = _tags_atom(frame)
    card_inner = h + primary + extra + tags
    inner = (
        f'<div class="sp-wrap"><div class="sp-card {section_cls}-card">'
        f"{card_inner}{assets_html}</div></div>"
    )
    return f'<section class="template-body composition-{section_cls}">{inner}</section>'


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
        marker_style="dot",
        semantic_kind=semantic_kind,
    )
    return f"<style>{FAMILY_CSS}</style>{render_card_shell(FAMILY, frame, variant, body)}"


def _focus(frame, assets, variant):
    return _render(frame, assets, variant, "focus")


def _narrative(frame, assets, variant):
    return _render(frame, assets, variant, "narrative")


def _structured(frame, assets, variant):
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
    archetype = frame.page_archetype
    # persona sits in the card's footer row; when absent, fall back to the
    # default footer (render_footer) so the probe's expected copy still matches.
    footer = _persona_atom(frame) or None
    if archetype == "cover" and _HERO_DIGIT_RE.search(frame.headline):
        # bespoke hero cover only when there's an N步 digit to hero-ify;
        # covers without it fall through to the generic composition path.
        body = _cover_body(frame, assets)
        return (
            f"<style>{FAMILY_CSS}</style>"
            f"{render_card_shell(FAMILY, frame, variant, body, header=_cover_header(frame), footer=footer)}"
        )
    if archetype in _BESPOKE_ARCHETYPES:
        body = _bespoke_body(frame, assets, archetype)
        return f"<style>{FAMILY_CSS}</style>{render_card_shell(FAMILY, frame, variant, body, header=_cover_header(frame), footer=footer)}"
    return ARCHETYPE_RENDERERS[archetype](frame, assets, variant)
