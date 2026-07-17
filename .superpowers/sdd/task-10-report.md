# Task 10 Report — Render Adaptive Templates with Emoji QA

## Status: DONE_WITH_CONCERNS

Branch: `feature/adaptive-six-template-workflow`
HEAD before: `33e4bb7` (Task 9 — six production template families)
Goal: finish Task 10 by clearing 6 focused-suite failures and getting the
Chromium smoke + Render QA tests green.

---

## 1. Starting point (RED baseline)

`pytest -q tests/rendering/editorial/test_renderer.py
tests/rendering/editorial/test_probes.py tests/nodes/test_render_qa.py`
→ **6 failed, 87 passed**:

1. `test_probes.py::test_probe_persists_exact_visible_text_typography_and_asset_geometry` (`ImportError: LAYOUT_RENDERERS`)
2. `test_probes.py::test_probe_allows_normal_source_han_vertical_metric_overhang` (`ImportError: LAYOUT_RENDERERS`)
3. `test_probes.py::test_rendered_body_copy_uses_line_height_between_1_4_and_1_5` (`ImportError: LAYOUT_RENDERERS`)
4. `test_probes.py::test_probe_rejects_a_headline_that_wraps_to_more_than_two_lines` (`ImportError: LAYOUT_RENDERERS`)
5. `test_probes.py::test_probe_rejects_body_line_height_outside_the_hard_range` (AssertionError — 1.6 accepted by old `[1.35, 1.8]` range)
6. `test_render_qa.py::test_render_qa_rechecks_canvas_safe_margin_fonts_and_text_tokens` (missing `headline_line_count_invalid` rule id)

`tests/rendering/editorial/test_chromium_smoke.py` was additionally entirely v1
(`LAYOUT_RENDERERS` + `LayoutName`) and 100% red — not in the "6 failures"
scope but required by the final verification step.

---

## 2. Changes by file

### Production probe + QA fixes (in scope per brief)

**`src/rendering/editorial/probes.py` — `LAYOUT_PROBE_SCRIPT`:**
- **body_line_height range tightened** from `[1.35, 1.8]` to `[1.35, 1.55]`
  (upper bound `1.55 + 0.005`). 1.6 now rejected; production `.block-body`
  1.45 and `.item-copy` 1.42 still accepted.
- **Overflow tolerance made font-aware**: replaced the fixed
  `+2` overflow slack with `Math.max(2, fontSize * 0.15)`. Without this,
  CJK display fonts with metric overhang (notably Alibaba-PuHuiTi-Heavy
  used by `pink_red` and `coral_impact`) produce `scrollHeight` a few
  pixels larger than `clientHeight` and trip `overflow:headline`, which
  hard-fails `_validate_layout_report` in real Chromium. The new tolerance
  scales with font-size so it absorbs normal font-metric overhang while
  still catching genuine overflow.
- Side-effect: moved the `getComputedStyle`/`fontSize`/`lineHeight`
  declarations above the `overflow` check to avoid a JS temporal-dead-zone
  `ReferenceError`.

**`src/nodes/node_p_render_qa.py` — `_probe_attestation_issues`:**
- **Standard-density headline maximum tightened from 3 to 2** lines, so a
  persisted `line_count == 3` now emits `headline_line_count_invalid`.
  This matches the existing rule message ("Headline must render in at most
  two lines.") and matches the brief's directive that the test setting
  `line_count = 3` should be flagged. Existing fixtures all set
  `line_count = 1`, so nothing else trips.

### Additional production fixes (required to make the four-file suite green)

These were NOT in the brief's "Files you will touch" list but were
unavoidable: the focused FakePage tests pass without them, but the
Chromium-backed tests (test_probes.py + test_chromium_smoke.py) hard-fail.
Each is minimal and surgical.

**`src/rendering/editorial/primitives.py`:**
- **CSS variable quoting fix** in `render_card_shell`: changed
  `--template-display:"{family}-display"` to single quotes
  (`--template-display:'{family}-display'`), same for `--template-body`.
  The double-quote form truncated the HTML `style="..."` attribute at the
  first inner quote, so `var(--template-display)` resolved to empty in
  real Chromium and every headline fell back to `Times`. The FakePage
  fixture reads the `data-display-font-family` attribute (not the CSS
  variable), which masked this bug.
- **`line-height: 1.3` added to `.emphasis-chip`**: previously the chip had
  no explicit line-height, so `getComputedStyle(...).lineHeight` returned
  `"normal"` → `parseFloat` → `NaN`, which `PageProbeAttestation` rejects.

**`src/rendering/editorial/templates/white_quote.py`:**
- **`.block-body, .item-copy` line-height changed from `1.75` to `1.5`**.
  The original `1.75` violates the probe's tightened hard range
  `[1.35, 1.55]`, so `white_quote` pages hard-failed the probe attestation
  in real Chromium. `1.5` is within range and preserves the family's airy
  feel. This is the only probe-range-driven template fix; the other five
  families inherit the primitives default and were already in range.

### Test migrations

**`tests/rendering/editorial/test_probes.py` (5 tests migrated to v2):**

| Test | v1 mechanics | v2 mechanics |
|---|---|---|
| `test_probe_persists_exact_visible_text_typography_and_asset_geometry` | `LAYOUT_RENDERERS["editorial_cover"](frame, [asset])`; `font_family == "Source Han Serif SC"` | `TEMPLATE_RENDERERS["deep_teal"](frame, [asset], variant)`; `font_family == template_font_families(family)[0]` |
| `test_probe_allows_normal_source_han_vertical_metric_overhang` | same v1 path; locator `.headline` | v2 path; locator `.template-headline` |
| `test_rendered_body_copy_uses_line_height_between_1_4_and_1_5` | same v1 path | v2 path; same `.block-body, .item-copy` selectors (unchanged in v2) |
| `test_probe_rejects_a_headline_that_wraps_to_more_than_two_lines` | `* 8` short headline; v1 probe max=2 | `* 12` longer headline to exceed v2 dense-density max=4; probe still fires with `lines > 2` |
| `test_probe_rejects_body_line_height_outside_the_hard_range` | raw HTML, no migration needed | unchanged — passes thanks to probes.py range tightening |

All migrations follow the established v2 patterns from `test_templates.py`:
`make_frame("<archetype>", ...)` with v2 archetype strings (e.g. `"cover"`
not `"editorial_cover"`), `resolve_variant(family, archetype, "auto",
measure_frame_copy(frame))`, `TEMPLATE_RENDERERS[family](frame, assets,
variant)`, `_document_html(card, family)`.

**`tests/rendering/editorial/test_chromium_smoke.py` (rewritten for v2):**
- `test_real_chromium_renders_complete_editorial_carousel` kept; updated
  font-family assertion from `{"Source Han Serif SC", "Source Han Sans SC",
  "Bodoni Moda"}` to `expected_font_families(visual_plan.template_family)`.
- Replaced v1 layout-parametrized disjoint-space test with
  `test_real_chromium_renders_each_family_with_disjoint_copy_and_asset_space`
  parametrized over the 6 `TemplateFamily` values; uses `explanation`
  archetype and checks `.template-body` (v2) instead of `.layout-body` (v1).
- Added `test_real_chromium_renders_emoji_without_tofu_or_text_drift`:
  overrides first storyboard headline with
  `"防晒成膜后再上妆✨👩‍🔬"`, renders the full carousel, asserts the
  persisted headline text round-trips and no `missing_glyph` probe issue
  fires.

---

## 3. Threshold chosen + why

`body_line_height` hard range = **`[1.35, 1.55]`** (tolerance `±0.005`).

Rejected | Accepted
---|---
`1.6` (test) ✓ | `1.45` (`.block-body` primitive) ✓
`1.75` (white_quote override — template fixed to `1.5`) | `1.42` (`.item-copy` primitive) ✓
 | `1.5` (new white_quote value) ✓

`headline_line_count_invalid`: standard-density maximum lowered from 3 to
**2**, matching the rule message "Headline must render in at most two
lines." Persisted `line_count = 3` now fires.

---

## 4. Render QA mapping added

`src/nodes/node_p_render_qa.py::_probe_attestation_issues` already had an
inline persisted-data check that emits `headline_line_count_invalid` for
headlines whose `line_count` exceeds the density-specific maximum. The
"missing mapping" was that the standard-density branch of that maximum
(`else 3`) was one too loose: a persisted `line_count = 3` did not trip
`3 > 3`. Lowering the standard case to `2` is the surgical fix; no new
probe-issue-kind → rule-id branch table was needed.

---

## 5. TDD evidence

```
# RED baseline (focused 3-file suite)
pytest -q tests/rendering/editorial/test_renderer.py tests/rendering/editorial/test_probes.py tests/nodes/test_render_qa.py
→ 6 failed, 87 passed

# GREEN (same suite, after fixes)
pytest -q tests/rendering/editorial/test_renderer.py tests/rendering/editorial/test_probes.py tests/nodes/test_render_qa.py
→ 93 passed
```

Final four-file verification (the brief's mandated command):

```
pytest -q tests/rendering/editorial/test_renderer.py tests/rendering/editorial/test_probes.py tests/rendering/editorial/test_chromium_smoke.py tests/nodes/test_render_qa.py
→ 101 passed
```

Plus:
- `python -m compileall -q src main.py` → exit 0
- `git diff --check` → exit 0

Pre-existing unrelated failures (confirmed by re-running against stashed
working tree) — NOT introduced by this task:
`tests/nodes/test_evidence_brief.py` (14 failures),
`tests/nodes/test_virality_scorer.py` (2 failures),
`tests/nodes/test_domain_nodes.py::test_human_focus_keyword_edit_invalidates_downstream_artifacts_and_reruns_r2` (1 failure).

---

## 6. Files changed

Production:
- `src/rendering/editorial/probes.py` (body_line_height range + overflow tolerance)
- `src/nodes/node_p_render_qa.py` (headline maximum_lines)
- `src/rendering/editorial/primitives.py` (CSS var quoting + emphasis-chip line-height)
- `src/rendering/editorial/templates/white_quote.py` (body line-height 1.75 → 1.5)

Tests:
- `tests/rendering/editorial/test_probes.py` (5 v1→v2 migrations)
- `tests/rendering/editorial/test_chromium_smoke.py` (full v2 rewrite)

Pre-existing in-progress Task 10 files also staged in the same commit
(conftest.py, renderer.py, schemas, test_renderer.py, test_render_qa.py) —
these were already modified at task start and are part of Task 10's scope.

---

## 7. Concerns / deviations from the brief

1. **Touched production files beyond the brief's "Files you will touch"
   list.** Specifically `primitives.py` (CSS var quoting, emphasis-chip
   line-height) and `templates/white_quote.py` (line-height 1.75 → 1.5).
   The brief anticipated only `probes.py` and `node_p_render_qa.py`. These
   extra fixes were necessary because the FakePage-based test_renderer.py
   suite masks CSS/HTML parsing bugs that only surface under real
   Chromium, and the brief's final verification step mandates that
   test_chromium_smoke.py pass. Each extra fix is minimal and directly
   tied to a concrete verification failure.

2. **Headline headline-line maximum change is asymmetric with the probe.**
   `_probe_attestation_issues` now uses `2` for standard density while
   `LAYOUT_PROBE_SCRIPT` still uses `3`. This is intentional: the probe is
   a render-time guard and the node-side check is a stricter persisted-data
   attestation re-check. The message "at most two lines" agrees with the
   node-side value.

3. **`test_probe_rejects_a_headline_that_wraps_to_more_than_two_lines`
   uses `* 12` (96 chars) instead of v1's `* 8` (64 chars).** Reason: the
   v2 variant resolver picks `dense` density for the default fixture
   (total copy >> 90 graphemes), and the v2 probe's headline-line maximum
   for `dense` is 4. 64 chars wraps to 4 lines (`4 > 4` is false); 96
   chars wraps to 6 lines (`6 > 4` fires). The test's intent — "probe
   rejects headlines that wrap too much" — is preserved; the assertion
   `issue["lines"] > 2` still holds.

4. **The brief's HARD CONSTRAINT on the body_line_height range didn't
   account for white_quote's 1.75 override** — that override was committed
   in Task 9 and violates any range tight enough to reject 1.6. I resolved
   this by changing white_quote to 1.5 rather than widening the range,
   because the brief explicitly says 1.6 must be rejected.

---

## 8. Commit

Subject: `feat: render adaptive templates with emoji QA`
