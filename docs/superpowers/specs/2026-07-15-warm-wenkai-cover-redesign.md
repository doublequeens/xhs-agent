# Warm 文楷 Cover & Carousel Redesign — Design Spec

**Date:** 2026-07-15
**Branch:** `feature/warm-wenkai-cover-redesign`
**Status:** Approved (validated via 4 mockup iterations in `examples/text-cover-samples/`)

## 1. Problem

The production editorial renderer (`src/rendering/editorial/`) emits flat, PPT-like
carousel images (verified on package
`20260715-beauty-skincare-妆前护肤等多久…`). Root causes:

1. Cards are ~85% flat `--ivory` (`#F7F2EA`) with only a faint mauve circle and a
   hairline border — no real visual subject. The "imagery" is flat SVG vector
   insets (textures/containers) since real photos are disallowed by account
   strategy.
2. Content clusters at the top with a large empty bottom (头重脚轻) because the
   layout stacks with fixed margins and nothing fills the 1440px height.
3. `思源宋/黑` reads as geometric/cold; lacks warmth.
4. `left_right_comparison` splits by `content_block` count, but storyboards emit
   one `comparison` block with N items → the right column renders empty.

This contradicts the agreed account strategy (memory `xhs-account-strategy`):
pure-text covers, typography-as-design, benchmark 大杨 (cream + bold + whitespace),
credibility via persona not photos.

## 2. Goal

Replace the illustrated-carousel visual layer with a **warm, pure-text,
typography-led** design that fills the canvas and matches the account strategy.
All output uses 霞鹜文楷 (LXGW WenKai). No raster imagery.

## 3. Design Tokens (replace `BEAUTY_EDITORIAL_V1` palette; fonts)

- **Background:** `--cream #F4ECE0` (warm), paper `--paper #FBF6EE`.
- **Ink:** `--ink #2B2622`, `--soft #6B625A`.
- **Accents:** `--coral #D45D4C` (problem / emphasis), `--sage #78805E` (solution / go),
  `--mauve #9A707B` (neutral label), `--line rgba(43,38,34,.16)`.
- **Fonts:** 霞鹜文楷 — `LXGWWenKai-Medium.otf` (display/heading, weight 500) +
  `LXGWWenKai-Regular.otf` (body, weight 400). `BodoniModa` retained **only** for
  the corner page-number marker (`01 / 05`); all Chinese content and all numerals
  inside content use WenKai.
- Canvas unchanged: 1080×1440.

Font files (Medium + Regular) are added under `assets/fonts/beauty-editorial-v1/`
(user owns licensing vetting; both WenKai weights are SIL OFL).

## 4. Layout Principle: Three-Section Fill (fixes 头重脚轻)

Every card is a vertical flex column with three sections:

```
.page = flex column
  .head   (flex 0)   kicker + title + lede
  .body   (flex 1, min-height 0)   main content — DISTRIBUTED to fill full height
  .foot   (flex 0)   persona (left) + page number (right)
```

`.body` consumes all vertical slack, so even sparse content (3–4 items) fills the
canvas instead of clustering at top. Inner containers use `flex:1` +
`justify-content:space-between` (timeline) or `grid-template-rows:1fr 1fr` /
`align-items:stretch` (decision, comparison) so children stretch edge-to-edge.

This is the core fix — content volume is unchanged; distribution does the work.

## 5. Page Layouts (map to existing storyboard `layout` values)

| Page | `layout` | Structure |
|---|---|---|
| Cover | `editorial_cover` | Dark pill badge (coral dot + kicker) · big WenKai headline with one coral phrase + hand-drawn SVG underline · sub · two rounded chips |
| Timeline | `step_timeline` | Vertical rail (coral→mauve→sage gradient); WenKai ordinals (壹贰叁肆) left; each step = name + wait-time pill (ink/sage/coral) + hint; steps `space-between` top→bottom |
| Decision | `decision_tree` | 2×2 cards (paper bg, mauve left-border); each = when-label + check + green ✓ go / coral → wait |
| Comparison | `left_right_comparison` | **Two equal panels** (bad=coral border ✕ / good=sage border ✓), each item prefixed ✕/✓; centered conclusion line below |
| Save | `saveable_reference` | Framed "SAVE" tear card; horizontal ①→④ flow with wait-times; dashed divider; total time |

### 5.1 Comparison fix (the bug)

`left_right_comparison` currently splits by `content_block` count. It must instead
split the **items of the single `comparison` content_block** across two columns:
left = first half (problem), right = second half (solution). Panels stretch to fill
height. Both columns are always populated when ≥2 items exist.

## 6. Implementation Targets

1. `design_system.py` — add WenKai Medium/Regular to `font_paths`; update `colors`
   to the warm palette (background `#F4ECE0`, etc.).
2. `renderer.py` — `_font_css()` emits WenKai `@font-face`; `_CARD_CSS` replaced
   with the warm three-section design system (tokens, `.head/.body/.foot`).
3. `layouts.py` — rewrite each layout renderer to the three-section fill structure
   + the per-page designs above; fix `render_left_right_comparison` to split items.
4. Asset/visual-slot handling: pure-text design uses no raster assets. Layouts no
   longer render `.asset-figure`/`.asset-placeholder`; `visual_slots` remain in the
   storyboard contract but are not composited into text cards. (Asset manifest
   validation in the guard/renderer stays intact; we just stop drawing insets.)

## 7. Verification

- Regenerate the `别让防晒毁在赶时间上` package on this branch; visually confirm all 5
  pages match the approved mockups (`examples/text-cover-samples/full-*.png`).
- Vision-check: no empty bottom (head/body/foot fill), comparison has two populated
  columns, WenKai throughout, no overflow/clipping.
- `pytest -q` green (renderer/probe tests will need updating to the new design
  tokens/CSS class names).

## 8. Out of Scope

- Changing the storyboard generator's content or the 5-page frame plan.
- Reintroducing raster imagery / photos.
- Other domains' design systems (this is `beauty_editorial_v1`).
