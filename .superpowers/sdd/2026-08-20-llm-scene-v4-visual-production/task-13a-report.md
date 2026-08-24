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
