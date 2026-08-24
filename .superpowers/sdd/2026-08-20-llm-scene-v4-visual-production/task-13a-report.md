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
