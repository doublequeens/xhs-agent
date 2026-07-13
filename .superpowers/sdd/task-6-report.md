# Task 6 implementation report

## Outcome

Implemented the project-local beauty editorial renderer with all eleven explicit
layout functions, one immutable dispatch table, local font enforcement, browser
probes, ordered page output, a Chromium-rendered contact sheet, and all-or-nothing
failure cleanup.

## Delivered behavior

- `LAYOUT_RENDERERS` maps exactly the eleven strict `LayoutName` values. Dispatch is
  based only on `CarouselFrame.layout`; no topic/title keyword routing exists.
- Every layout emits semantic `data-layout`, `data-frame-role`, `data-frame-id`, and
  `data-card-copy` attributes, escapes all storyboard strings, and accepts only
  resolved local asset files rendered through `file://` URLs.
- The shared document shell fixes the canvas at `1080 × 1440`, uses an 84px safe
  margin, exposes the required ivory/ink/mauve/coral/sage palette, and declares only
  the repository-local Source Han Serif SC, Source Han Sans SC, and Bodoni Moda
  fonts. There is no system-font fallback or remote resource URL.
- Browser probes explicitly load all three font families, await
  `document.fonts.ready`, verify exact computed families, check canvas semantics,
  detect hidden/clipped/overflowing copy, and verify local image decode before each
  page screenshot.
- Output names are deterministic: `01-cover.png`, followed by
  `NN-<sanitized-frame-role>.png`. `RenderManifest` records exact page dimensions,
  source hashes keyed by asset slot, the font report, and the contact-sheet path.
- The contact sheet is a local HTML grid captured by Chromium. Pillow is not used by
  the renderer or the tests to build a contact sheet.
- Every PNG and invocation-owned temporary HTML file is removed if font loading,
  layout probing, card capture, contact-sheet capture, browser lifecycle, or final
  temporary-file cleanup fails. Unrelated files in the output directory are kept.
- The renderer rejects frame-order/layout drift between `VisualPlan` and
  `CarouselPayload` before launching Chromium.

## TDD evidence

The first attempted RED run found a test-package relative-import error. That test
error was corrected before counting RED. The valid RED run was:

```text
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest \
  tests/rendering/editorial/test_layouts.py \
  tests/rendering/editorial/test_renderer.py -q

30 failed
ModuleNotFoundError: No module named 'src.rendering.editorial.layouts'
ModuleNotFoundError: No module named 'src.rendering.editorial.renderer'
```

Focused fake-browser GREEN:

```text
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest \
  tests/rendering/editorial/test_layouts.py \
  tests/rendering/editorial/test_renderer.py -q

30 passed in 0.07s
```

The first real-Chromium run correctly rejected the cover because the initial probe
treated Source Han glyph overhang beyond the CSS line box as clipping. Browser
metrics showed 1–8px vertical font-metric overhang without actual layout clipping.
The probe was narrowed to hidden text, horizontal overflow, and actual layout-body
boundary violations. The same pass also removed CSS that hid secondary cover blocks,
so every storyboard copy remains visible.

Real Chromium GREEN:

```text
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/rendering/editorial -q

31 passed in 2.66s
```

Related regression GREEN:

```text
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest \
  tests/schemas/test_editorial_carousel.py \
  tests/rendering/test_text_cards.py \
  tests/rendering/editorial -q

62 passed in 3.67s
```

`python -m compileall -q src/rendering/editorial tests/rendering/editorial` and
`git diff --check` also completed successfully. A retained real render was inspected
through its Chromium contact sheet; `file` reported every page as `1080 × 1440` and
the contact sheet as `1320 × 1145`.

## Self-review

- Scope is limited to `src/rendering/editorial`, `tests/rendering/editorial`, and
  this report. Graph, QA, export, plan, and schema contracts were not modified.
- The renderer imports no network client and never reads provider URLs. Asset
  selection remains upstream; the renderer only consumes resolved manifest paths.
- The eleven renderer functions share escaped primitives without collapsing back to
  one fixed visual template: each layout has a distinct semantic structure and CSS
  composition while the shell owns tokens, dimensions, and typography.
- Cleanup tracks only files created or overwritten by the invocation, so unrelated
  output-directory PNGs survive a failed render.
- The browser session is reused for all pages and the contact sheet, and fonts are
  re-probed after every local document navigation.

## Concerns

- The environment does not have `ruff` or `black` installed, so those optional
  format/lint commands could not run. Compilation, `git diff --check`, focused tests,
  real Chromium tests, and related regression tests are green.
- Pytest intermittently prints the repository's existing macOS temporary-directory
  cleanup warning after successful runs; it does not change the zero exit status or
  leave renderer output in the tested directory.
