# Task 6 implementation report

## Outcome

Implemented the project-local beauty editorial renderer with all eleven explicit
layout functions, one immutable dispatch table, local font enforcement, browser
probes, ordered page output, a Chromium-rendered contact sheet, and transactional
output-set publication.

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
  detect hidden/clipped/overflowing copy using DOM Range bounds against real clipping
  ancestors, enforce the two-line headline and 1.4–1.5 body line-height rules, and
  verify local image decode before each page screenshot.
- Output names are deterministic: `01-cover.png`, followed by
  `NN-<sanitized-frame-role>.png`. `RenderManifest` records exact page dimensions,
  source hashes keyed by asset slot, the font report, and the contact-sheet path.
- The contact sheet is a local HTML grid captured by Chromium. Pillow is not used by
  the renderer or the tests to build a contact sheet.
- Every PNG and temporary HTML file is first created in an invocation-scoped sibling
  staging directory. Only after screenshots, probes, contact sheet, browser close,
  HTML cleanup, and manifest validation succeed is the complete directory published.
  Any pre-existing complete output set is preserved on pre-commit failure;
  publication errors restore it rather than leaving a mixed set. Non-renderer-owned
  files and directories are copied into the new set before its atomic commit. Once
  the new set is committed, failure while retiring the old set leaves recognizable
  quarantine residue and emits a warning without rolling back damaged old bytes.
- Every storyboard `VisualSlot` binds to exactly one manifest item with the same slot
  ID and frame layout. The renderer verifies current local bytes against sha256 and
  records only assets actually passed to a layout. It deliberately does not compare
  the semantic storyboard role to the adapted concrete catalog role; that domain seam
  belongs to Task 7 Carousel QA.
- The renderer rejects frame-order/layout drift, duplicate plan or storyboard frame
  IDs, and duplicate visual-slot IDs within a frame before launching Chromium. This
  protects frame-to-assets lookup and the slot-keyed source-hash provenance map from
  identity overwrite.

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

## Review-correction RED/GREEN evidence

The first review rejected four Important behaviors. Each correction used its own
RED/GREEN cycle.

### Atomic output-set publication

RED:

```text
python -m pytest tests/rendering/editorial/test_renderer.py -q \
  -k "existing_complete or failed_screenshot"

4 failed
```

The failures proved that after-write and before-write screenshot errors deleted old
page files, browser-close failure removed the complete old set, and temporary-HTML
cleanup failure left newly overwritten finals. After moving the entire render into a
sibling staging directory and publishing/restoring at directory granularity:

```text
4 passed, 7 deselected
```

### Strict actual-asset consumption

The accepted RED cases were wrong frame layout, missing declared slot, changed source
bytes, and an unused manifest item incorrectly included in the rendered hash map:

```text
python -m pytest tests/rendering/editorial/test_renderer.py -q \
  -k "declared_frame_slot or missing_declared or tampered_bytes or unused_manifest"

5 failed (4 accepted contract failures; 1 role-equality case later discarded)
```

The fifth role-equality case was discarded after checking the domain contracts:
Storyboard roles are semantic (`beauty_subject`) while AssetManifest roles are adapted
catalog roles (`background_token`). Renderer binding therefore uses unique slot ID,
frame layout, local path, and current sha256; Task 7 owns semantic-role QA.

GREEN:

```text
4 passed, 11 deselected
```

### Vertical glyph/range clipping

The deterministic real-browser RED showed that a text Range extending beyond an
intermediate `overflow:hidden` ancestor produced no issue, while the Source Han
characterization case demonstrated legitimate `scrollHeight > clientHeight` overhang.
After comparing every Range rect with each actual clipping ancestor's client box:

```text
python -m pytest tests/rendering/editorial/test_probes.py -q \
  -k "clipped or overhang"

2 passed
```

The clipped case now emits `ink_clip`; normal Source Han overhang does not.

### Typography hard rules

RED:

```text
python -m pytest tests/rendering/editorial/test_probes.py -q \
  -k "line_height or headline"

3 failed
```

The probe did not reject a 1.6 body line height, production body copy computed to
1.55, and an 80-character-schema-valid headline could exceed two lines. Production
body copy now uses 1.45, the probe checks computed ratios, and unique Range line tops
enforce the two-line limit.

GREEN:

```text
3 passed, 2 deselected
```

Integrated focused GREEN after all corrections:

```text
python -m pytest tests/rendering/editorial/test_layouts.py \
  tests/rendering/editorial/test_renderer.py \
  tests/rendering/editorial/test_probes.py -q

43 passed in 2.62s
```

Final review-correction verification:

```text
python -m pytest tests/rendering/editorial -q
44 passed in 5.08s

python -m pytest tests/schemas/test_editorial_carousel.py \
  tests/rendering/test_text_cards.py \
  tests/editorial_carousel/test_strategy.py -q
54 passed in 1.24s
```

The first command includes the real Chromium smoke and deterministic probe tests.
`compileall` and `git diff --check` also exited successfully after the corrections.

## Second review-correction RED/GREEN evidence

### Transactional publication commit point

Fault-injection tests were added for both directory replacements, retirement of a
partially deleted old set, and preservation of unrelated output entries. The valid
RED distinguished two missing behaviors from two passing characterizations:

```text
python -m pytest tests/rendering/editorial/test_renderer.py -q \
  -k "publication or backup_retirement"

2 failed, 2 passed
```

The renderer now copies non-owned entries into staging without overwriting new
outputs, treats successful `staging -> output` replacement as the commit point, and
only retires the old directory after commit. Retirement failure warns and leaves
quarantine residue; it never restores partially deleted old bytes over committed
new output.

```text
4 passed, 15 deselected
```

### Strict render identities

Schema-valid duplicate IDs showed that one-sided frame duplicates produced a generic
order error, matching duplicates launched Chromium and overwrote frame asset lookup,
and duplicate slots within a frame launched Chromium:

```text
python -m pytest tests/rendering/editorial/test_renderer.py -q \
  -k "duplicate_frame_ids or duplicate_visual_slot"

4 failed
```

Unique plan frame IDs, storyboard frame IDs, and per-frame visual-slot IDs are now
validated before plan matching, asset resolution, staging, or browser launch:

```text
4 passed, 19 deselected
```

Fresh verification after both second-review corrections:

```text
python -m pytest tests/rendering/editorial/test_layouts.py \
  tests/rendering/editorial/test_renderer.py \
  tests/rendering/editorial/test_probes.py -q
51 passed in 3.05s

python -m pytest tests/rendering/editorial -q
52 passed in 5.12s

python -m pytest tests/schemas/test_editorial_carousel.py \
  tests/rendering/test_text_cards.py \
  tests/editorial_carousel/test_strategy.py -q
54 passed in 1.28s
```

The full editorial suite includes the real-Chromium smoke and deterministic browser
probe tests. `compileall` and `git diff --check` also exited successfully.

## Self-review

- Scope is limited to `src/rendering/editorial`, `tests/rendering/editorial`, and
  this report. Graph, QA, export, plan, and schema contracts were not modified.
- The renderer imports no network client and never reads provider URLs. Asset
  selection remains upstream; the renderer only consumes resolved manifest paths.
- The eleven renderer functions share escaped primitives without collapsing back to
  one fixed visual template: each layout has a distinct semantic structure and CSS
  composition while the shell owns tokens, dimensions, and typography.
- Failure cleanup removes the isolated staging tree and does not mutate the existing
  output directory before publication. Existing complete-set tests cover failures
  before and after bytes are written, during browser close, during temporary-HTML
  cleanup, and at both pre-commit directory replacements. Post-commit retirement
  failure leaves quarantine residue rather than rolling damaged old bytes back.
- The browser session is reused for all pages and the contact sheet, and fonts are
  re-probed after every local document navigation.

## Concerns

- The environment does not have `ruff` or `black` installed, so those optional
  format/lint commands could not run. Compilation, `git diff --check`, focused tests,
  real Chromium tests, and related regression tests are green.
- Pytest intermittently prints the repository's existing macOS temporary-directory
  cleanup warning after successful runs; it does not change the zero exit status or
  leave renderer output in the tested directory.
