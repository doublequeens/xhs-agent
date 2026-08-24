# Task 13A report: adapt v4 scene plans and publish immutable revisions

## Scope and provenance

Implemented only the bounded Task 13A slice: the hash-bound v4 rendering
contracts, the v4 adapter over the existing generic compiler/Chromium renderer,
the v4 render node, owned adapter/node tests, and the minimum generic compiler
and probe seams needed to carry v4 typography and browser evidence.

At the required initial status check, four untracked test files were already
present:

```text
?? tests/integration/test_v4_three_grammar_render.py
?? tests/nodes/v4/test_render.py
?? tests/rendering/scene/test_v4_adapter.py
?? tests/visual_design/v4/test_render_qa.py
```

The parent agent identified these as delayed writes from the interrupted
attempt. `tests/nodes/v4/test_render.py` and
`tests/rendering/scene/test_v4_adapter.py` were inspected and adapted as the
owned tests. The delayed Task 13B stubs
`tests/visual_design/v4/test_render_qa.py` and
`tests/integration/test_v4_three_grammar_render.py` were preserved unchanged
and are not included in this commit.

## TDD evidence

Before production code was written, the owned test command was run:

```text
pytest -q tests/rendering/scene/test_v4_adapter.py tests/nodes/v4/test_render.py
```

It failed during collection with the expected RED boundary:

```text
ModuleNotFoundError: No module named 'src.rendering.scene.v4_adapter'
ModuleNotFoundError: No module named 'src.nodes.v4.render'
```

After implementation, the same owned command passed with 9 tests.

## Implementation

### Durable v4 contracts

`src/schemas/v4/rendering.py` adds frozen, strict, `extra=forbid`,
canonical-hash-bound contracts for:

| Contract | Evidence carried |
| --- | --- |
| `RenderManifestV4` | v4 workflow and run/candidate/revision identity, exact plan and aggregate hashes, all transitive source hashes, ordered page records, PNG/contact byte hashes, and measured font evidence |
| `RenderPageEvidenceV4` | revision-relative page path, fixed 1080x1440 dimensions, byte hash, and complete element evidence |
| `RenderElementEvidenceV4` | expected/actual boxes, actual DOM text/hash, scroll/client geometry, overflow/clipping, computed font, glyph evidence, and opaque asset/crop evidence |
| `RenderFontEvidenceV4` / `RenderGlyphEvidenceV4` | computed family/weight/size/line-height, checked-in font digest, `document.fonts` status, load and glyph visibility observations |
| `RenderAssetEvidenceV4` | opaque asset ref, byte hash, fit/orientation, intrinsic/rendered dimensions, load and crop facts |
| `RenderIssueV4` / `RenderQAResultV4` | closed issue codes, sanitized structural evidence, constrained revision targets, and derived pass state |

Durable paths are restricted to `render/...`; public asset refs are restricted
to `v4-asset-<sha256>`. Provider, license, source path, prompt and provenance
fields are not represented in these contracts.

### Adapter and node

`src/rendering/scene/v4_adapter.py`:

- Revalidates the exact v4 design plan, fresh passed aggregate Q0-Q2 result,
  atom set, ContentLock, semantic model, page briefs, direction plan, asset
  manifest, family tokens and Task 9 artifact identity before rendering.
- Projects only private v3-compatible fragments/assets/style inputs into the
  existing single generic compiler. Asset directives are checked against page,
  run, security status, pending human decision, source containment/no-follow
  and source byte hash before private opaque mapping.
- Reconstructs only the approved source line breaks and explicit newline
  semantics, applies content insets, and emits local `@font-face` declarations
  backed by the exact checked-in v4 font bytes.
- Requires one measured probe per planned element, preserves actual raw DOM
  text (including an explicitly measured empty string), computed font and
  image data, and marks text/glyph/geometry/font/asset failures in the typed
  result.
- Produces all page PNGs and a contact sheet in private staging, then publishes
  pages, contact sheet and canonical manifest with Task 9 descriptor-relative,
  no-follow, atomic, non-overwrite binding. Final bytes are rehashed and the
  artifact hierarchy is revalidated; staging cleanup cannot mask a primary
  render error.

`src/nodes/v4/render.py` normalizes v4 state aliases, invokes the adapter and
returns the manifest, typed render result, artifact paths and either the
`render_qa` or `design_reviser` route.

`src/rendering/scene/compiler.py` gained only optional backwards-compatible
font-face and text-layout options. `src/rendering/scene/probes.py` gained
optional raw browser fields for actual text, font readiness/weight, glyph
visibility and asset load state; the v3 probe model and API remain unchanged.

## Verification

Passing fresh checks:

```text
pytest -q tests/rendering/scene/test_v4_adapter.py tests/nodes/v4/test_render.py
9 passed

pytest -q tests/rendering/scene/test_compiler.py tests/rendering/scene/test_renderer.py tests/rendering/scene/test_probes.py tests/nodes/test_generic_scene_renderer.py
83 passed

pytest -q tests/rendering/scene/test_v4_adapter.py tests/nodes/v4/test_render.py tests/nodes/v4/test_design_qa.py tests/schemas/v4 tests/visual_design/v4/test_compiler.py
124 passed

python -m compileall -q src main.py
git diff --check
```

The required broader generic-scene command was run once:

```text
pytest -q tests/rendering/scene tests/nodes/v4/test_render.py
105 passed, 1 failed
```

The sole failure is the existing real-Chromium smoke test. Chromium launches
then exits in this restricted macOS environment with the exact fatal log:

```text
FATAL:base/apple/mach_port_rendezvous_mac.cc:159] Check failed: kr == KERN_SUCCESS. bootstrap_check_in org.chromium.Chromium.MachPortRendezvousServer.<pid>: Permission denied (1100)
```

The required full offline suite was also run once. Collection stops before
tests because the preserved delayed Task 13B file has the same basename as an
existing test:

```text
pytest -q
ERROR collecting tests/visual_design/v4/test_render_qa.py
import file mismatch: imported module 'test_render_qa' has this __file__ attribute:
.../tests/nodes/test_render_qa.py
which is not the same as the test file we want to collect
```

The delayed file was not renamed or modified in this slice.

## Immutable publication proof

The owned adapter tests verify that:

- pages are published below `run-a/candidate-a/revision-1/render/` with only
  revision-relative paths in the manifest;
- manifest JSON contains no provider or machine-local `/Users/` path;
- a second attempt at the same revision fails with
  `ArtifactBindingError` and leaves the first page bytes unchanged;
- artifact identity drift is rejected before the renderer is called;
- the frozen manifest rejects mutation;
- measured DOM text deletion produces `RENDER_DOM_TEXT` and a failed result;
- compiled v4 pages carry private checked-in font faces and preformatted
  layout options.

## Self-review and concerns

- The Q3 evaluator module and the three-grammar real-Chromium integration test
  are intentionally deferred to Task 13B; their delayed stubs remain
  uncommitted.
- Real Chromium/font/image geometry could not be exercised in this sandbox;
  the controller should rerun the broader/browser commands with the necessary
  execution rights.
- Q3's full blank/alpha, exact font-family, crop, and final-file independent
  evaluation remains the next slice's responsibility. The adapter preserves
  the raw evidence and immutable byte bindings needed for that evaluator.
- No graph wiring, publisher, ContentLock, database, output package or retired
  visual path was changed.

## Fix round 1: harden v4 render evidence publication

The independent review rejected the initial implementation on browser-evidence
fallbacks, path-based asset reads, per-file publication, durable path identity,
provisional Q3 routing, and page-global text options. This fix round addresses
each finding while preserving the two delayed Task 13B stubs unchanged.

### Fix-round TDD evidence

The first fix-round run of the owned command was RED: 5 failed and 4 passed.
The failures were the expected stale owned seams after the contract change:
the adapter still called `_private_assets` with its old signature, and the
owned renderer fixture did not provide the newly required measured
`actual_text`/glyph fields. The exact command was:

```text
pytest -q tests/rendering/scene/test_v4_adapter.py tests/nodes/v4/test_render.py
5 failed, 4 passed
```

After each vertical fix and fixture adaptation, the covering owned/artifact
command is GREEN:

```text
pytest -q tests/rendering/scene/test_v4_adapter.py tests/nodes/v4/test_render.py tests/visual_runtime/test_artifact_identity.py
43 passed
```

### Review finding resolutions

- Browser evidence now rejects absent/null v4 probe fields instead of using
  planned geometry, expected text/font values, or successful defaults. The
  browser script awaits `document.fonts.ready`, checks the exact declared face
  and weight, records per-grapheme Range coverage, and uses text Range line
  boxes. The adapter preserves only those raw measured values. It no longer
  computes `RenderQAResultV4`, attestations, issues, or issue-derived routing;
  the node returns the immutable manifest and routes unconditionally to
  `render_qa` after publication. Q3 remains Task 13B's sole policy factory.
- Asset bindings require exact directive/page binding, plan run, revision
  transaction identity, approved/pending status, and byte hash. Reads now use
  descriptor-relative no-follow traversal with pinned ancestor/file identity,
  containment beneath the revalidated `asset_root`, and byte revalidation.
  Sentinel tests cover valid traversal, substitution, symlink escape, and
  transaction mismatch.
- Pages, contact sheet, and manifest are built in a private staging directory,
  fsynced as a complete tree, and published once by a descriptor-relative
  directory bind with no replacement. Injected page/contact/manifest failures
  leave no canonical `render/` directory; a second revision attempt cannot
  replace the first bytes. Primary failures remain primary during staging
  cleanup.
- Durable render paths reject absolute, backslash, empty, `.`, `..`, and
  non-canonical components. Manifest identity enforces
  `artifact_identity.revision_id == revision_id == f"revision-{revision}"` and
  exact run/candidate bindings.
- Text break/inset options are keyed by `(page_id, fragment_ref)` and reduced
  to a page-local map at the generic compiler boundary, preventing reused
  fragment refs from inheriting another page's measurements.

### Fix-round verification

Fresh covering checks after the final edit:

```text
pytest -q tests/nodes/v4
96 passed, 1 warning

pytest -q tests/rendering/scene/test_compiler.py tests/rendering/scene/test_probes.py tests/rendering/scene/test_renderer.py
79 passed

pytest -q tests/rendering/scene/test_chromium_smoke.py
1 passed

python -m compileall -q src main.py
git diff --check
```

The filtered offline suite (excluding only the two preserved delayed Task 13B
stubs) completed with 1813 passed and 3 skipped; its one real-Chromium smoke
attempt failed only at browser launch in the restricted sandbox with
`mach_port_rendezvous_mac ... Permission denied (1100)`. The standalone smoke
command passed, and the controller also recorded a sandbox-external Chromium
smoke pass. The preserved stubs were not modified, renamed, or deleted.

The fix-round commit is `fix: harden v4 render evidence publication`.

### Commit handoff

Implementation, tests, compileall, diff check, and this report are complete.
The requested commit could not be created because the sandbox denied the Git
worktree index lock:

```text
fatal: Unable to create '/Users/qinqiang/Documents/Workspace/Projects/xhs-agent/.git/worktrees/llm-scene-v4-visual-production/index.lock': Operation not permitted
```

No index lock was removed or bypassed. The intended Task 13A files remain
unstaged in this worktree; the two delayed Task 13B stubs remain untracked and
untouched.

## Fix round 2: close v4 render race windows

This round addresses the scoped re-review findings for browser glyph evidence,
asset byte TOCTOU, focused race tests, exclusive directory publication, and
the v3 probe regression. The two delayed Task 13B stubs remain unchanged and
uncommitted.

### Fix-round RED evidence

Tests were written before the production seams. The first fresh red command
failed during collection because the new explicit v4 probe seam did not yet
exist:

```text
pytest -q tests/rendering/scene/test_probes.py::test_v3_probe_script_remains_the_default_and_v4_is_explicitly_stricter tests/rendering/scene/test_renderer.py::test_chromium_renderer_keeps_v3_probe_default_and_accepts_v4_seam tests/rendering/scene/test_compiler.py::test_verified_asset_bytes_render_as_stable_data_uri_after_source_substitution tests/rendering/scene/test_v4_adapter.py -q tests/visual_runtime/test_artifact_identity.py::test_staged_directory_destination_creation_race_is_exclusive tests/visual_runtime/test_artifact_identity.py::test_staged_directory_source_substitution_race_fails_closed
ERROR collecting tests/rendering/scene/test_probes.py
ImportError: cannot import name 'V4_PROBE_SCRIPT' from 'src.rendering.scene.probes'
ERROR collecting tests/rendering/scene/test_renderer.py
ImportError: cannot import name 'V4_PROBE_SCRIPT' from 'src.rendering.scene.probes'
```

The first implementation attempt then reached the intended runtime race
assertions with `3 failed, 5 passed`: macOS `RENAME_EXCL` used the wrong native
flag, and the destination-race error discarded `EEXIST` detail. Those were
corrected before the final green run.

### Fix-round implementation

- Restored the v3 `PROBE_SCRIPT` body byte-for-byte from its pre-v4 revision.
  `_ChromiumPageRenderer` now defaults to that script and accepts an explicit
  `probe_script`; the v4 adapter selects `V4_PROBE_SCRIPT` only for its owned
  renderer. The strict v4 script awaits `document.fonts.ready`, checks the
  exact declared face and `FontFaceSet.check(font, grapheme)`, obtains Range
  geometry, and records per-grapheme canvas ink count plus SHA-256 raster
  evidence. Missing fields fail closed; false face/font/raster observations
  are retained for Q3 rather than converted to success.
- `RenderElementEvidenceV4` now requires `dom_text_measured=True` and a
  non-null actual DOM text value for text evidence. Glyph coverage requires
  face-loaded, font-check, ink-pixel-count and raster-signature observations;
  visible glyphs cannot be declared from geometry alone. Fallback/tofu-like
  false measurements remain publishable evidence.
- `_private_assets` retains the descriptor-relative, no-follow verified bytes
  and `compile_page_scene` accepts an optional byte map. v4 image sources are
  emitted as hash-checked data URIs, so Chromium never reopens the original
  `local_path` after validation. The compiler regression mutates the source
  after validation and proves the rendered HTML remains the verified bytes.
- `bind_staged_directory` now pins the source directory inode, fsyncs every
  staged file and directory, uses macOS `renameatx_np(..., RENAME_EXCL)` or
  Linux `renameat2(..., RENAME_NOREPLACE)`, fails closed when unavailable,
  checks destination inode identity after rename, fsyncs the parent, and
  preserves the primary error during cleanup. Destination-creation and
  source-substitution race tests prove no replacement and no canonical output.
- The path regression now validates an otherwise-complete page evidence model
  before replacing only its path, so failures are attributable to the exact
  noncanonical path rather than unrelated missing fields. Tests also cover
  missing DOM/glyph observations and measured fallback glyph evidence.

### Fix-round GREEN evidence

The requested covering tests passed:

```text
pytest -q tests/rendering/scene/test_v4_adapter.py tests/nodes/v4/test_render.py tests/visual_runtime/test_artifact_identity.py tests/rendering/scene/test_probes.py tests/rendering/scene/test_renderer.py tests/rendering/scene/test_compiler.py tests/nodes/test_generic_scene_renderer.py
135 passed in 11.55s

pytest -q tests/nodes/v4 tests/nodes/test_generic_scene_renderer.py
100 passed, 1 warning in 4.49s

pytest -q tests/rendering/scene/test_chromium_smoke.py
1 passed in 0.73s

python -m compileall -q src main.py
git diff --check
node (V4 probe JavaScript parse check)
V4 probe JavaScript parses
```

The full offline run, excluding only the two preserved delayed Task 13B
stubs, produced:

```text
pytest -q --ignore=tests/visual_design/v4/test_render_qa.py --ignore=tests/integration/test_v4_three_grammar_render.py
1822 passed, 1 failed, 3 skipped, 2 warnings in 50.79s
```

The single failure is the existing real generic-Chromium smoke at browser
launch. Chromium exits in this restricted macOS sandbox with
`mach_port_rendezvous_mac ... bootstrap_check_in ... Permission denied
(1100)`; the standalone smoke command above passed, and the controller has
already recorded a sandbox-external Chromium smoke pass. No test failure is
from the v4 adapter or evidence contracts.

### Fix-round concerns

- Real v4 Chromium glyph/font/image observations remain controller-owned in a
  sandbox-external run; this environment cannot provide an independent strict
  v4 browser smoke.
- Q3 policy construction remains deferred to Task 13B. Task 13A publishes only
  the immutable `RenderManifestV4` and routes unconditionally to `render_qa`.
- The two delayed Task 13B stubs were not modified, renamed, deleted, staged,
  or committed.

The fix-round commit attempt was blocked by the same worktree index permission
boundary as the prior round. Exact fresh command/error:

```text
git add .superpowers/sdd/2026-08-20-llm-scene-v4-visual-production/task-13a-report.md src/rendering/scene/compiler.py src/rendering/scene/probes.py src/rendering/scene/renderer.py src/rendering/scene/v4_adapter.py src/schemas/v4/rendering.py src/visual_runtime/artifact_identity.py tests/rendering/scene/test_compiler.py tests/rendering/scene/test_probes.py tests/rendering/scene/test_renderer.py tests/rendering/scene/test_v4_adapter.py tests/visual_runtime/test_artifact_identity.py
fatal: Unable to create '/Users/qinqiang/Documents/Workspace/Projects/xhs-agent/.git/worktrees/llm-scene-v4-visual-production/index.lock': Operation not permitted
```

No index lock was removed or bypassed. All fix-round files remain unstaged;
the two delayed Task 13B stubs remain untracked and untouched.
