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


FAMILY: TemplateFamily = "white_quote"

# Archetypes that get the bespoke white_quote composition (霞鹜文楷 quote
# aesthetic: thin top rule, centered quote pages, calm centered explanation
# columns, bordered checklist grid). Cover is handled separately. All visible
# copy still flows through copy_atom / render_blocks / render_assets so every
# content_blocks field, every emphasis chip and every asset slot is emitted with
# the probe's expected data-card-copy / data-asset-slot roles and order; only the
# surrounding structure and CSS are bespoke. Archetypes outside this set fall
# through to the generic composition path (still with the persona footer).
_BESPOKE_ARCHETYPES = frozenset({"quote", "explanation", "checklist", "boundary"})

_SECTION_CLASS = {
    "quote": "wq-quote",
    "explanation": "wq-explain",
    "checklist": "wq-checklist",
    "boundary": "wq-boundary",
}

# Decorative top-right page label per archetype (aria-hidden — pure visual
# flavor, not part of the copy contract). Mirrors the mockup's 壹 / 贰 / 叁 / 结语.
_PG_LABEL = {
    "cover": "护肤 · 语录",
    "quote": "壹",
    "explanation": "贰",
    "checklist": "叁",
    "boundary": "结语",
}

# Decorative oversized opening quote mark (aria-hidden) for quote / boundary
# pages, matching the mockup's `mark` element.
_MARK_HTML = '<div class="wq-mark" aria-hidden="true">"</div>'

# Checklist cell decorative time-of-day marker cycles (aria-hidden). Mirrors the
# mockup's —晨 / —晚 / —周 labels.
_CHK_MARKS = ("— 晨", "— 晚", "— 周")

FAMILY_CSS = """
/* white_quote card: calm white field, no inner border frame, generous margin.
   Compound selector beats the base .template-card rule (BASE <style> is emitted
   after FAMILY_CSS, so a single-class override would lose the cascade). */
.template-card.template-white-quote{padding:120px 104px;gap:0}
.template-card.template-white-quote::before{display:none}
/* The default footer row is unused in production (curation clears frame.footer
   and the persona renders via the absolute wq-handle atom), so strip its chrome.
   page-number is aria-hidden and safe to hide; the footer element itself stays
   (an empty, borderless box) so any footer-copy atom, when present, stays visible
   for the probe. */
.template-white-quote .template-footer{border-top:none;padding-top:0}
.template-white-quote .page-number{display:none}
/* bespoke body section becomes the layout root: a flex column that either centers
   its content (cover/quote/boundary) or stacks it from the top (explain/checklist).
   The base .template-body is display:grid; these compound rules override it. */
.template-white-quote .template-body.composition-wq-cover,
.template-white-quote .template-body.composition-wq-quote,
.template-white-quote .template-body.composition-wq-boundary{
  display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;min-height:0}
.template-white-quote .template-body.composition-wq-explain,
.template-white-quote .template-body.composition-wq-checklist{
  display:flex;flex-direction:column;justify-content:flex-start;min-height:0}
/* page chrome: top-right label only (decorative, aria-hidden) */
.template-white-quote .wq-pg{position:absolute;top:80px;right:96px;font-size:26px;line-height:1.3;color:#9FB0CC;letter-spacing:.1em;font-weight:700}
/* persona handle: bottom-center, one copy atom, body family for the probe */
.template-white-quote .wq-handle{
  position:absolute;bottom:80px;left:50%;transform:translateX(-50%);
  font-size:26px;line-height:1.3;color:#8AA0C8;letter-spacing:.04em;font-weight:700;
  white-space:nowrap}
/* headline atom — 霞鹜文楷 Medium (display family); size scoped per composition.
   Rendered two lines via a <br> at the first comma (mockup convention); <br> adds
   no textContent so the probe's headline contract is unchanged. */
.template-white-quote .wq-q{
  font-family:var(--template-display);font-weight:700;color:#2A4A8C;
  letter-spacing:-.01em;overflow-wrap:anywhere}
.template-white-quote .wq-kicker{
  font-size:28px;line-height:1.3;color:#4A66A0;letter-spacing:.14em;font-weight:700}
.template-white-quote .wq-sm{
  font-size:36px;line-height:1.9;color:#4A66A0;overflow-wrap:anywhere}
/* emphasis rendered as a quiet pill row (used on explanation/checklist) */
.template-white-quote .wq-keys{display:flex;flex-wrap:wrap;gap:14px;justify-content:center;margin-top:8px}
.template-white-quote .wq-key{
  font-size:26px;line-height:1.4;color:#2A4A8C;background:#EEF2F8;
  padding:10px 22px;border-radius:999px;font-weight:700}
/* decorative oversized opening quote mark (quote / boundary pages) */
.template-white-quote .wq-mark{
  font-family:var(--template-display);font-weight:700;font-size:120px;line-height:1;
  color:#D7DFEE}
/* ===== COVER ===== */
.template-white-quote .composition-wq-cover .wq-q{font-size:104px;line-height:1.5}
.template-white-quote .composition-wq-cover .wq-sm{font-size:36px;line-height:1.9;margin-top:40px}
/* ===== QUOTE ===== */
.template-white-quote .composition-wq-quote .wq-q{font-size:96px;line-height:1.55;margin-top:0}
.template-white-quote .composition-wq-quote .wq-sm{font-size:32px;line-height:1.85;margin-top:30px}
/* ===== EXPLANATION ===== */
.template-white-quote .composition-wq-explain .wq-q{font-size:72px;line-height:1.4;margin-top:18px;text-align:left}
.template-white-quote .composition-wq-explain .wq-kicker{margin-bottom:0}
.template-white-quote .wq-cols{margin-top:48px;display:flex;flex-direction:column;gap:30px;align-items:flex-start;width:100%}
.template-white-quote .wq-col{max-width:820px;display:flex;flex-direction:column;gap:10px;width:100%}
.template-white-quote .wq-col-h{margin:0;font-size:38px;line-height:1.3;color:#2A4A8C;font-weight:700}
.template-white-quote .wq-col-p{margin:0;font-size:32px;line-height:1.55;color:#4A66A0;overflow-wrap:anywhere}
.template-white-quote .wq-col-items{list-style:none;margin:6px 0 0;padding:0;display:flex;flex-direction:column;gap:6px}
.template-white-quote .wq-col-item{font-size:28px;line-height:1.5;color:#4A66A0}
/* ===== CHECKLIST ===== */
.template-white-quote .composition-wq-checklist .wq-q{font-size:68px;line-height:1.4;margin-top:18px;text-align:left}
.template-white-quote .wq-grid{margin-top:42px;display:grid;grid-template-columns:1fr 1fr;gap:24px;align-content:start;width:100%}
.template-white-quote .wq-cell{padding:28px;border:1px solid #D7DFEE;border-radius:18px;display:flex;flex-direction:column;gap:10px}
.template-white-quote .wq-cell-mark{font-size:28px;line-height:1.3;color:#9FB0CC;font-weight:700}
.template-white-quote .wq-cell-copy{display:flex;flex-direction:column;gap:6px;min-width:0;font-size:28px;line-height:1.5}
.template-white-quote .wq-cell-h{font-size:32px;line-height:1.3;color:#2A4A8C;font-weight:700}
.template-white-quote .wq-cell-p{font-size:28px;line-height:1.5;color:#4A66A0}
.template-white-quote .wq-sep{display:none}
/* ===== BOUNDARY ===== */
.template-white-quote .composition-wq-boundary .wq-q{font-size:104px;line-height:1.5;margin-top:0}
.template-white-quote .composition-wq-boundary .wq-sm{font-size:34px;line-height:1.55;margin-top:28px}
"""

# Generic-fallback composition modes keyed by the family's registered variants.
_MODE_BY_VARIANT = {
    "centered-focus": "focus",
    "editorial-column": "stack",
    "quiet-grid": "grid",
}


def _two_line_value(text: str) -> str:
    """Render ``text`` as two lines by inserting a ``<br>`` after the first
    comma (the mockup's editorial convention), or near the midpoint when there is
    no comma. ``<br>`` contributes no textContent, so the probe's copy contract
    (actual == expected) is unaffected."""
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
    return copy_atom(frame.persona, role="persona", class_name="wq-handle", tag="div")


def _chrome(archetype: str) -> str:
    """Decorative top-right page label (aria-hidden, not part of the copy
    contract). The mockup's top-center rule is intentionally omitted per the
    account's preference for a cleaner field."""
    label = _PG_LABEL.get(archetype, "")
    return f'<div class="wq-pg" aria-hidden="true">{_render_copy_value(label)}</div>'


def _headline_atom(frame: CarouselFrame) -> str:
    return _two_line_atom(frame.headline, role="headline", class_name="wq-q", tag="div")


def _kicker_atom(frame: CarouselFrame) -> str:
    if not frame.kicker:
        return ""
    return copy_atom(frame.kicker, role="kicker", class_name="wq-kicker", tag="div")


def _emphasis_atoms(frame: CarouselFrame, cls: str = "wq-key") -> str:
    if not frame.emphasis:
        return ""
    return "".join(
        copy_atom(value, role=f"emphasis[{i}]", class_name=cls, tag="span")
        for i, value in enumerate(frame.emphasis)
    )


def _extra_blocks(frame: CarouselFrame, start: int) -> str:
    """Render content_blocks[start:] with the standard fallback so the probe's
    expected copy still matches (production frames have a single block; the
    multi-block test fixture exercises this path)."""
    if len(frame.content_blocks) <= start:
        return ""
    return "".join(
        _render_block(b, i, "dash")
        for i, b in enumerate(frame.content_blocks[start:], start=start)
    )


def _items_atoms(block, idx: int, cls: str) -> str:
    """Render a block's items as one copy atom each (role content_blocks[idx].items[i])."""
    if not block or not block.items:
        return ""
    lis = "".join(
        copy_atom(item, role=f"content_blocks[{idx}].items[{i}]", class_name=cls, tag="div")
        for i, item in enumerate(block.items)
    )
    return f'<div class="wq-col-items">{lis}</div>'


def _explanation_cols(frame: CarouselFrame) -> str:
    # Render EVERY block as a centered col (heading + body + items), so all column
    # headings share the wq-col-h style (consistent, matching the mockup).
    cols = ""
    for i, block in enumerate(frame.content_blocks):
        heading = (
            copy_atom(block.heading, role=f"content_blocks[{i}].heading", class_name="wq-col-h", tag="h3")
            if block.heading else ""
        )
        body = (
            copy_atom(block.body, role=f"content_blocks[{i}].body", class_name="wq-col-p", tag="p")
            if block.body else ""
        )
        items = _items_atoms(block, i, "wq-col-item")
        cols += f'<div class="wq-col">{heading}{body}{items}</div>'
    return f'<div class="wq-cols">{cols}</div>'


def _checklist_grid(frame: CarouselFrame) -> str:
    block = frame.content_blocks[0] if frame.content_blocks else None
    if not block:
        return ""
    heading = (
        copy_atom(block.heading, role="content_blocks[0].heading", class_name="wq-col-h", tag="h3")
        if block.heading else ""
    )
    body = (
        copy_atom(block.body, role="content_blocks[0].body", class_name="wq-col-p", tag="p")
        if block.body else ""
    )
    grid = ""
    if block.items:
        cells = ""
        for i, item in enumerate(block.items):
            segs = item.split("｜")
            mark = _CHK_MARKS[i % len(_CHK_MARKS)]
            if len(segs) == 1:
                inner = f'<span class="wq-cell-h">{_render_copy_value(segs[0])}</span>'
            else:
                inner = (
                    f'<span class="wq-cell-h">{_render_copy_value(segs[0])}</span>'
                    f'<span class="wq-sep">｜</span>'
                    f'<span class="wq-cell-p">{_render_copy_value(segs[1])}</span>'
                )
            cells += (
                f'<div class="wq-cell"><div class="wq-cell-mark" aria-hidden="true">'
                f'{_render_copy_value(mark)}</div>'
                f'<span class="wq-cell-copy" data-card-copy '
                f'data-copy-role="content_blocks[0].items[{i}]">{inner}</span></div>'
            )
        grid = f'<div class="wq-grid">{cells}</div>'
    extra = _extra_blocks(frame, 1)
    return f"{heading}{body}{grid}{extra}"


def _cover_body(frame: CarouselFrame, assets: Sequence[AssetManifestItem]) -> str:
    kicker = _kicker_atom(frame)
    headline = _headline_atom(frame)
    extra = _extra_blocks(frame, 0)
    # cover subtitle = emphasis, each its own two-line atom
    sub = "".join(
        _two_line_atom(value, role=f"emphasis[{i}]", class_name="wq-sm", tag="div")
        for i, value in enumerate(frame.emphasis)
    )
    assets_html = render_assets(assets)
    inner = (
        f'{_chrome("cover")}{kicker}{headline}{extra}{sub}{assets_html}'
    )
    return f'<section class="template-body composition-wq-cover">{inner}</section>'


def _bespoke_body(
    frame: CarouselFrame, assets: Sequence[AssetManifestItem], archetype: str
) -> str:
    section_cls = _SECTION_CLASS[archetype]
    chrome = _chrome(archetype)
    kicker = _kicker_atom(frame)
    headline = _headline_atom(frame)
    assets_html = render_assets(assets)

    if archetype == "quote":
        # content_blocks (if any) render before emphasis to match _expected_copy order
        extra = _extra_blocks(frame, 0)
        sub = "".join(
            _two_line_atom(value, role=f"emphasis[{i}]", class_name="wq-sm", tag="div")
            for i, value in enumerate(frame.emphasis)
        )
        inner = f"{chrome}{kicker}{_MARK_HTML}{headline}{extra}{sub}{assets_html}"
    elif archetype == "explanation":
        cols = _explanation_cols(frame)
        keys = _emphasis_atoms(frame)
        keys_html = f'<div class="wq-keys">{keys}</div>' if keys else ""
        inner = f"{chrome}{kicker}{headline}{cols}{keys_html}{assets_html}"
    elif archetype == "checklist":
        grid = _checklist_grid(frame)
        keys = _emphasis_atoms(frame)
        keys_html = f'<div class="wq-keys">{keys}</div>' if keys else ""
        inner = f"{chrome}{kicker}{headline}{grid}{keys_html}{assets_html}"
    else:  # boundary
        block = frame.content_blocks[0] if frame.content_blocks else None
        heading = (
            copy_atom(block.heading, role="content_blocks[0].heading", class_name="wq-kicker", tag="div")
            if block and block.heading else ""
        )
        note = (
            _two_line_atom(block.body, role="content_blocks[0].body", class_name="wq-sm", tag="div")
            if block and block.body else ""
        )
        items = _items_atoms(block, 0, "wq-col-item") if block else ""
        extra = _extra_blocks(frame, 1)
        keys = _emphasis_atoms(frame)
        keys_html = f'<div class="wq-keys">{keys}</div>' if keys else ""
        inner = f"{chrome}{kicker}{_MARK_HTML}{headline}{heading}{note}{items}{extra}{keys_html}{assets_html}"
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
        marker_style="dash",
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


def render_frame(
    frame: CarouselFrame,
    assets: Sequence[AssetManifestItem],
    variant: ResolvedVariant,
) -> str:
    archetype = frame.page_archetype
    # persona is injected for every white_quote frame (see
    # _curate_frames_for_publish); it MUST render on every path — bespoke AND
    # generic fallback — or the probe's actual!=expected copy contract breaks. So
    # the footer is threaded through both paths.
    footer = _persona_atom(frame) or None
    # bespoke bodies already emit kicker + headline, so suppress the default
    # header (which would duplicate them). Pass an EMPTY header element (not "")
    # so it occupies grid row 1 and the bespoke body section lands in row 2
    # (the 1fr row) — otherwise the section becomes the only in-flow grid item
    # and auto-placement drops it into row 1, breaking vertical centering.
    empty_header = '<header class="template-header"></header>'
    if archetype == "cover" and not frame.content_blocks:
        # Clean centered quote cover (production: curation clears cover
        # content_blocks). A content-rich cover (raw frames without curation)
        # falls through to the generic composition path, which lays the blocks
        # out without overflowing — mirroring soft_pink's conditional bespoke.
        body = _cover_body(frame, assets)
        return f"<style>{FAMILY_CSS}</style>{render_card_shell(FAMILY, frame, variant, body, header=empty_header, footer=footer)}"
    if archetype in _BESPOKE_ARCHETYPES:
        body = _bespoke_body(frame, assets, archetype)
        return f"<style>{FAMILY_CSS}</style>{render_card_shell(FAMILY, frame, variant, body, header=empty_header, footer=footer)}"
    return _ARCHETYPE_KIND[archetype](frame, assets, variant, footer)
