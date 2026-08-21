# Task 11 report: deterministic v4 Layout Compiler

## RED / GREEN

The required first run was executed before any Task 11 production module
existed:

```text
$ pytest -q tests/visual_design/v4/test_typography.py tests/visual_design/v4/test_compiler.py tests/nodes/v4/test_layout.py
ERROR collecting ...
ModuleNotFoundError: No module named 'src.visual_design.v4.typography'
ModuleNotFoundError: No module named 'src.visual_design.v4.compiler'
ModuleNotFoundError: No module named 'src.nodes.v4.layout'
3 errors during collection
```

After implementation, the same focused command passed:

```text
20 passed in 1.11s
```

## Changed files

- Added checked-in-font Pillow/FreeType measurement with exact Unicode and
  grapheme-safe wrapping in `src/visual_design/v4/typography.py`.
- Added the hash-bound compiler input boundary, six structured failure codes,
  deterministic geometry context and one compiler dispatch in
  `src/visual_design/v4/compiler.py`.
- Added independent family-neutral solvers for `editorial_hero`,
  `comparison_grid` and `step_flow` under
  `src/visual_design/v4/grammar_compilers/`.
- Added `CompilerProvenanceV4`, `CompiledPageV4` and
  `CarouselDesignPlanV4` durable contracts to `src/schemas/v4/layout.py`.
- Added pure ordered page compilation/aggregation in
  `src/nodes/v4/layout.py`.
- Added focused typography, compiler, and node tests.

No renderer, Chromium, graph, v3 contract, publish code, state, asset
transaction, output, or progress-ledger files were changed.

## Verification

Fresh offline verification completed:

```text
pytest -q tests/visual_design/v4/test_typography.py tests/visual_design/v4/test_compiler.py tests/nodes/v4/test_layout.py
51 passed, 7 warnings

pytest -q tests/visual_design/v4/test_typography.py tests/visual_design/v4/test_compiler.py tests/nodes/v4/test_layout.py tests/schemas/test_scene_graph.py tests/rendering/scene/test_compiler.py
118 passed, 9 warnings

pytest -q tests/schemas/v4/test_layout.py tests/visual_design/v4/test_grammars.py tests/nodes/v4/test_composition.py
54 passed

pytest -q
1690 passed, 3 skipped, 11 warnings

python -m compileall -q src main.py
git diff --check
```

The skipped tests are the repository's explicitly disabled live provider and
live Gemini smoke tests. The full suite warnings are existing pytest cleanup
and Pydantic tampered-fixture warnings; no test failed.

## Self-review / concerns

- The v4 compiler deliberately returns only flat scene primitives and embeds
  no asset provider, local path, or internal provenance payload; only the
  compiler's checked-in font byte hashes are durable.
- The current task implements the first three approved grammar solvers only;
  Q2 metrics and the Chromium adapter remain Task 12/13 work.
- The compiler uses a canonical 80px safe margin and 1080x1440 canvas, and
  fails closed on stale `model_copy` contracts, cross-page assets, unsafe
  typography, and density overflow.

## Fix round 1

Review attack tests were written before the fixes and run RED.  The focused
compiler run first reported `12 passed, 20 failed`; failures demonstrated
that recomputed outer hashes could authorize `x=0` geometry and fake font
hashes, candidate/revision identity was absent, legal region choices were
ignored, palette foregrounds failed WCAG contrast, typography evidence and
nominal weights were absent, portrait assets could be forced into an extreme
cover crop, four structured failure paths were unreachable, and contract
errors retained Pydantic input details.

The fix round now provides:

- strict compiler provenance for canonical compiler/canvas/safe-margin/font/
  minimum-size/wrap/contrast policies, exact upstream hashes, candidate /
  revision / run identity, grapheme-safe measurement evidence and sanitized
  asset binding evidence;
- compiled-page scene revalidation for identity, exact-once refs, font floors
  and nominal weights, safe finite geometry, line endpoints, evidence-bound
  assets and unintended overlaps;
- a required hash-bound `VisualDirectionPlanV4` at node aggregation, durable
  PageBriefSet source-hash checks, global fragment/page/program/asset
  ownership, candidate/revision consistency and fresh scene+provenance
  recompilation at consumption;
- grammar registry validation and region-aware editorial, comparison and step
  solvers; deterministic semantic WCAG colors for all six families; checked-in
  Pillow ink extents; versioned Task 13 wrap evidence; and aspect/crop guards;
- positive tests for all six structured failure codes and sanitized error
  strings/cause chains, plus non-vacuous compiled-page/design-plan JSON
  leakage checks.

Fix-round focused and adjacent verification was rerun offline after the final
changes.  Focused compiler/node/typography tests passed 51; the adjacent
scene/compiler regression set passed 118; Task 10 grammar/composition tests
passed 54; and the full offline suite passed 1690 with 3 explicitly skipped
live tests.  The 11 warnings are limited to deliberate Pydantic tampered
fixtures and pytest temporary-directory cleanup.

## Fix round 2

The second review attack suite was written and run before the fixes. After
correcting one test fixture to use the existing `paragraph` role, the focused
RED run reported 11 expected behavior failures: policy constants were only
format-checked, nested evidence could still be mutated, grammar axes and
relationships were not executed, newline/bearing evidence was incomplete,
portrait assets were forced through an incompatible cover box, whitespace
classification was reversed, and dynamic step-flow layouts could not handle
both three- and five-fragment programs.

The fix closes those seams by:

- enforcing canonical compiler, contrast, accessibility-ink, and wrap-policy
  constants, and deep-freezing typography, asset, font, and region evidence
  with deterministic thawing only during serialization;
- recording hash-bound named-region geometry and executing the canonical
  editorial, comparison, and step-flow axes, order, focus, pair, and sequence
  constraints, with unknown constraint kinds rejected as invariants;
- preserving Unicode-codepoint offsets for explicit LF/CRLF breaks versus
  inserted grapheme breaks, recording Pillow ink bearings/ascent/descent, and
  translating glyph boxes into the safe margin;
- selecting deterministic `contain` boxes for compatible portrait, square,
  and landscape assets while retaining a real intrinsic-orientation mismatch
  failure path and binding fit/ratio/crop evidence;
- classifying whitespace from actual occupied geometry, keeping solver box
  overlap as an internal invariant, and dynamically allocating non-overlapping
  step-flow heading/sequence/support slots with an explicit fragment-to-icon
  mapping;
- making the public compiler and aggregate APIs require a complete
  hash-bound `VisualDirectionPlanV4`, candidate, revision, and run identity,
  and extending the non-vacuous leakage test to real compiled page and design
  plan JSON containing provider/path/provenance secrets.

Fresh fix-round verification was run offline:

```text
$ pytest -q tests/visual_design/v4/test_typography.py tests/visual_design/v4/test_compiler.py tests/nodes/v4/test_layout.py
66 passed in 8.27s

$ pytest -q tests/visual_design/v4/test_typography.py tests/visual_design/v4/test_compiler.py tests/nodes/v4/test_layout.py tests/schemas/test_scene_graph.py tests/rendering/scene/test_compiler.py
133 passed, 2 warnings in 8.54s

$ pytest -q tests/schemas/v4/test_layout.py tests/visual_design/v4/test_grammars.py tests/nodes/v4/test_composition.py
54 passed in 0.15s

$ pytest -q
1705 passed, 3 skipped, 4 warnings in 40.82s

$ python -m compileall -q src main.py
$ git diff --check
```

The three skipped tests are explicitly disabled live provider/Gemini smoke
tests. The four full-suite warnings are two deliberate Pydantic tampered
fixture serializer warnings and two pytest temporary-directory cleanup
warnings; no test failed. No renderer or Chromium was invoked, and the v3
renderer/schema behavior remains unchanged. Task 13 still owns actual CSS
application/render verification: this round only emits the versioned,
hash-bound wrap and measurement evidence needed to enforce that seam.

## Fix round 3

The third review attack tests were added first and run RED:

```text
$ pytest -q tests/visual_design/v4/test_compiler.py -k 'vacuous_pair or negative_bearing_uses_inset or opaque_ref_not_manifest or deep_bound_to_regions'
4 failed
```

The failures showed that a comparison page containing only a heading could
pass with empty paired regions, negative bearings were still represented by
moving the reserved text box, resolver production asset IDs crossed into the
scene/evidence, and scene elements had no durable element-to-region binding.

The round 3 fix now provides:

- non-vacuous comparison pairing: both left and right regions must contain
  balanced content, with canonical paired geometry and executable editorial
  focus / step ordering checks preserved;
- versioned content-origin inset and painted bounds/offset evidence for
  typography, with the complete requested text box retained and validator
  checks for box, inset-adjusted ink, region containment, safe margin, and
  painted-bound overlap safety;
- provider-neutral `v4-asset-<sha256>` references derived from candidate,
  revision, page, directive, and asset-byte digest. Durable asset evidence
  stores only the opaque ref, directive/page/region, byte digest, fit,
  orientation, and ratios. Direct page validation, aggregation, and fresh
  recompilation all rederive and verify the opaque ref;
- deep-frozen element-to-region evidence created at solver placement time.
  Every scene box, painted text bound, image, icon, shape, or line endpoint is
  checked against its canonical region and safe margin, and asset directive
  regions must match their bound image region. The editorial, comparison, and
  step asset lanes now contain their actual image boxes.

Additional regressions cover `j`, `Åg`, combining marks, all three normal
asset+text grammar paths, provider/path/provenance leakage, deep-freeze and
serialization, rehashed region contradictions, rehashed asset digest
contradictions, and opaque asset references.

Fresh offline verification for this round:

```text
$ pytest -q tests/visual_design/v4/test_typography.py tests/visual_design/v4/test_compiler.py tests/nodes/v4/test_layout.py
76 passed

$ pytest -q tests/schemas/v4/test_layout.py tests/visual_design/v4/test_grammars.py tests/nodes/v4/test_composition.py
54 passed

$ pytest -q tests/schemas/test_scene_graph.py tests/rendering/scene/test_compiler.py
67 passed, 2 warnings

$ pytest -q
1714 passed, 3 skipped, 1 failed

$ pytest -q -k 'not real_chromium_renders_generic_carousel_with_probes_and_manifest'
1714 passed, 3 skipped, 1 deselected, 4 warnings

$ python -m compileall -q src main.py
$ git diff --check
```

No v3 renderer/compiler behavior, graph wiring, publish code, state, assets,
outputs, database, or progress-ledger files were changed. The composition
node change is limited to selecting the canonical supporting region before
comparison/accent fallbacks so Task 11 asset placement evidence and geometry
remain consistent. Task 13 still owns applying the inset in the renderer
adapter; this round does not modify the v3 renderer. The single full-suite
failure is the existing real Chromium smoke test: the local headless browser
was detected but macOS sandbox launch failed with
`mach_port_rendezvous ... Permission denied`. The filtered offline suite is
green; the three skipped tests are the explicitly disabled live provider and
Gemini smoke tests.

## Fix round 3 verification refresh

The required focused command was rerun from the dirty round3 worktree:

```text
$ pytest -q tests/visual_design/v4/test_typography.py tests/visual_design/v4/test_compiler.py tests/nodes/v4/test_layout.py
76 passed in 9.55s
```

The adjacent scene/compiler regression set and Task 10 contracts were also
rerun:

```text
$ pytest -q tests/visual_design/v4/test_typography.py tests/visual_design/v4/test_compiler.py tests/nodes/v4/test_layout.py tests/schemas/test_scene_graph.py tests/rendering/scene/test_compiler.py
143 passed, 2 warnings in 10.09s

$ pytest -q tests/schemas/v4/test_layout.py tests/visual_design/v4/test_grammars.py tests/nodes/v4/test_composition.py
54 passed in 0.18s
```

Fresh full-suite verification remains blocked only by the machine's real
Chromium launch boundary:

```text
$ pytest -q
1714 passed, 3 skipped, 1 failed, 4 warnings in 42.59s
FAILED tests/rendering/scene/test_chromium_smoke.py::test_real_chromium_renders_generic_carousel_with_probes_and_manifest
TargetClosedError: ... mach_port_rendezvous ... Permission denied

$ pytest -q -k 'not real_chromium_renders_generic_carousel_with_probes_and_manifest'
1714 passed, 3 skipped, 1 deselected, 4 warnings in 42.56s

$ python -m compileall -q src main.py
$ git diff --check
```

The 3 skipped tests are the explicitly disabled live asset-provider and
Gemini tests. The warnings are existing Pydantic tampered-fixture and pytest
temporary-directory cleanup warnings. No code change was needed after this
refresh: the focused and adjacent suites reproduced green against the
inherited round3 implementation. The `src/nodes/v4/composition.py` change is
retained because its prior last-region fallback routed editorial asset
directives to `accent`; selecting the canonical `supporting` region is
required for the opaque asset/directive and region-lane contracts.

## Fix round 4

The independent review found one remaining geometry seam: text validation
recorded a complete reserved box and then replaced it with painted glyph
bounds before the overlap pass. A rehashed comparison page could therefore
move the right reserved lane from x=556 to x=500, move and rehash its region,
and pass while the narrow glyph ink remained visually separate.

The regression was added first and reproduced the bypass against the prior
implementation. The fix keeps two immutable geometry sets through validation:

- every scene element's complete reserved box is checked pairwise for
  unintended overlap;
- each text's painted bounds remain checked inside its reserved box, canonical
  region, and safe margin, then participate in painted-to-painted and
  painted-to-other-reserved overlap checks without replacing the reserved box.

Fresh offline verification:

```text
$ pytest -q tests/visual_design/v4/test_compiler.py
57 passed in 6.70s

$ pytest -q tests/visual_design/v4/test_typography.py tests/visual_design/v4/test_compiler.py tests/nodes/v4/test_layout.py
77 passed in 15.47s

$ pytest -q tests/visual_design/v4/test_typography.py tests/visual_design/v4/test_compiler.py tests/nodes/v4/test_layout.py tests/schemas/test_scene_graph.py tests/rendering/scene/test_compiler.py
144 passed, 2 warnings in 15.85s

$ pytest -q tests/schemas/v4/test_layout.py tests/visual_design/v4/test_grammars.py tests/nodes/v4/test_composition.py
54 passed in 0.25s

$ python -m compileall -q src main.py
$ git diff --check
```

The two warnings are pytest temporary-directory cleanup warnings. No v3
renderer, compiler, graph, publish, state, asset, output, database, or
unrelated source file was changed in this round.
