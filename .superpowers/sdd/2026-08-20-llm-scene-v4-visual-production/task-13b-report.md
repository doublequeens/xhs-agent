# Task 13B report: independently evaluate Q3 and render the first three Grammars

## Scope

Implemented the independent v4 Q3 evaluator and narrow Q3 node. The Task 13A
adapter remains manifest-only: it publishes measured browser evidence and the
Q3 node alone derives `RenderQAResultV4` and its hard-gate route. The delayed
Q3 test stub was renamed to `test_v4_render_qa.py`; the old colliding
`tests/visual_design/v4/test_render_qa.py` file is absent. The integration
marker was replaced with a three-Grammar local-Chromium vertical slice.

Changed files:

- `src/visual_design/v4/render_qa.py`: deterministic source-bound Q3
  evaluator, descriptor-relative final-file revalidation, closed issues and
  sanitized structural failures.
- `src/rendering/scene/v4_adapter.py`: supplies the complete page raw-probe
  set to the legacy base-probe mapper before selecting each element's evidence.
- `src/nodes/v4/render.py`: independent `render_qa_node` and hard-gate route.
- `src/schemas/v4/rendering.py`: source-hash bindings on `RenderQAResultV4`
  and signed geometry issue values that may represent off-canvas coordinates.
- `src/visual_design/v4/__init__.py`: public Q3 evaluator exports.
- `tests/visual_design/v4/test_v4_render_qa.py`: focused Q3 tests.
- `tests/rendering/scene/test_v4_adapter.py`: multi-element page probe
  regression.
- `tests/nodes/v4/test_render.py`: Q3 node routing tests.
- `tests/integration/test_v4_three_grammar_render.py`: real adapter/Chromium
  tests for `editorial_hero`, `comparison_grid` and `step_flow`.

No Q0-Q2 producer, ContentLock/visible-copy contract, graph wiring, publisher,
database, output, or retired visual path was changed.

## TDD evidence

Before the production evaluator and Q3 node existed, the focused test command
failed during collection:

```text
pytest -q tests/visual_design/v4/test_v4_render_qa.py tests/nodes/v4/test_render.py
ModuleNotFoundError: No module named 'src.visual_design.v4.render_qa'
ImportError: cannot import name 'render_qa_node' from 'src.nodes.v4.render'
```

After implementation, the same focused boundary is green:

```text
12 passed in 8.16s
```

The focused suite covers deterministic repeated evaluation, frozen results,
inclusive 2 px box tolerance, actionable `RENDER_BOX_DRIFT`, canonical path
and page-order rejection, manifest byte binding, scroll overflow, and exact
pass/fail routing.

## Q3 evidence and contracts

| Area | Independent proof |
| --- | --- |
| Source integrity | Revalidates `ContentAtomSetV4`, `ContentLock`, semantic model, page briefs, direction, asset manifest, canonical family tokens, design plan and passed Q0-Q2 aggregate; recomputes hashes and fresh Q0-Q2 aggregate and rejects stale, mixed, tampered or self-inconsistent inputs. |
| Artifact identity | Revalidates `ArtifactPaths` and pinned base/revision hierarchy; requires exact run/candidate/revision identity and canonical `render/pages/NN-page-id.png` paths. |
| Final bytes | Reads every page, contact sheet and canonical manifest through existing descriptor-relative no-follow reads with containment and byte/inode revalidation; checks PNG signature, decoding, dimensions, hashes, order and blank/transparent output. |
| DOM/layout | Compares exact semantic text after only approved line-break reconstruction, element kind/ref/order, expected and actual boxes with inclusive 2 px tolerance, client/scroll/range geometry, clipping and canvas bounds. |
| Typography/glyphs | Recomputes canonical family role, checked-in font digest, weight, size, line height and `document.fonts`; requires exact-face, fallback and tofu raster witnesses for every non-whitespace grapheme and rejects painted whitespace. |
| Assets | Recomputes opaque asset refs, directive/page/revision/hash binding, descriptor-relative source bytes, intrinsic/rendered dimensions, fit/orientation, box ratio and crop factor without exposing provider/path/provenance data. |
| Result/routing | Derives ordered sanitized `RenderIssueV4` values, attestations and `passed` from observations; frozen `RenderQAResultV4` binds manifest, plan, Q0-Q2 aggregate, identity and all source hashes. Q3 routes pass only to `visual_critic`, failure only to `design_reviser`; structural contradictions raise a fixed sanitized exception. |

## Real three-Grammar Chromium result

`command -v npx` was checked before browser work (`npx available`). The
integration test invokes the Task 13A adapter with no injected renderer for all
three parameters and reaches the real Playwright Chromium launch. In this
restricted macOS sandbox, all three attempts were blocked at browser launch
and were recorded as skips for the controller's external rerun:

```text
3 skipped
FATAL:base/apple/mach_port_rendezvous_mac.cc:159] Check failed: kr == KERN_SUCCESS. bootstrap_check_in org.chromium.Chromium.MachPortRendezvousServer.60503: Permission denied (1100)
```

The integration code does not fall back to a fake renderer; after a successful
external launch it will require the published 1080x1440 pages/contact sheet,
relative immutable paths, measured text/font/geometry evidence and an
independent passing Q3 result.

## External overflow diagnosis and follow-up fix

The controller reran the real browser vertical slice:

```text
pytest -q tests/integration/test_v4_three_grammar_render.py
3 failed, 2 passed in 7.30s
```

The failures were all `RENDER_OVERFLOW` issues with evidence
`measured text line box exceeds reserved bounds`; no scroll/client overflow was
present. Immutable manifests showed the same repeated geometry:

- Editorial hero: every page had actual `(80,100,920,520)`, one Range line
  `(80,90,401.375,120)`, and `scroll == client == (920,520)`.
- Comparison heading: actual `(80,100,920,180)`, Range line
  `(80,90,348.484375,120)`, and equal scroll/client dimensions; both body
  elements had their line top at `341` inside actual top `340`.
- Step heading: actual `(80,80,920,180)`, Range line
  `(80,70,401.375,120)`, and equal scroll/client dimensions.

The published PNGs retained intact glyph ink. The 10 px top extension was
typographic leading from Chromium's Range rectangle (the font metric extent was
taller than the declared CSS line-height), not clipped painted ink. The
test-only diagnostic was changed to one newline-delimited numeric line per
element, including actual box, offending line extrema, deltas, scroll/client
dimensions and tolerance, so external failures are not hidden by pytest's
nested-dict abbreviation.

TDD evidence for the corrected semantics:

```text
# Before the production change: heading-leading acceptance RED,
# genuine beyond-leading rejection already green
1 failed, 1 passed

pytest -q tests/visual_design/v4/test_v4_render_qa.py
10 passed

pytest -q tests/integration/test_v4_three_grammar_render.py -k diagnostic \
  tests/rendering/scene/test_v4_adapter.py::test_v4_adapter_builds_base_probes_for_all_page_elements
3 passed, 4 deselected
```

Q3 now derives a vertical leading allowance only when strict glyph/font
witnesses are valid and canonical painted bounds remain inside the reserved
box. The allowance is the measured half-difference between font ascent plus
descent and computed CSS line-height. Horizontal bounds, scroll/client
overflow, canvas bounds, and line boxes beyond that derived allowance remain
hard failures. A regression accepts the observed heading Range leading and
rejects a line box beyond the measured allowance. An isolated real-browser
rerun of the complete integration module passed all six collected tests:

```text
pytest -vv tests/integration/test_v4_three_grammar_render.py
6 passed in 7.16s
```

A final controller-side Chromium rerun is still required because the full
offline suite remains subject to the sandbox's intermittent Chromium launch
permission failure.

## Verification

```text
pytest -q tests/visual_design/v4/test_v4_render_qa.py tests/nodes/v4/test_render.py
12 passed

pytest -q tests/schemas/v4 tests/visual_design/v4/test_v4_render_qa.py tests/nodes/v4/test_render.py tests/visual_design/v4/test_compiler.py
116 passed

pytest -q tests/rendering/scene tests/visual_design/v4 tests/nodes/v4
404 passed, 2 failed
```

The two broader-suite failures are the existing real-Chromium generic smoke
and strict v4 probe, both failing with the same
`MachPortRendezvousServer ... Permission denied (1100)` sandbox fatal. The
repository-wide offline run completed collection and reported:

```text
pytest -q
1844 passed, 2 failed, 6 skipped
```

The six skips are the repository's existing opt-in live-provider/live-Gemini
skips plus the three sandbox-blocked Grammar parameters. The required static
checks also passed:

```text
python -m compileall -q src main.py
git diff --check
```

## Self-review and concerns

- Reviewed the complete changed surface; no adapter policy, graph, v3
  contract, visible copy, persistence, publisher or retired path was moved.
- The isolated Task13B integration run passed all three real Chromium grammar
  parameters (six collected tests), and the controller supplied fresh
  external green evidence for the three-Grammar slice, v3 smoke, strict v4
  probe and filtered full suite. The full local suite's two unrelated browser
  smoke/probe failures remain the sandbox's Chromium launch permission error.
- No network, model, provider or live asset path was used by the integration
  builders.

## Fix Round 1 — independent review hardening

Base for this round: `333ceb2`. The review identified two boundary defects and
an incomplete independent Q3 negative matrix. The public evaluator previously
accepted a caller-supplied geometry tolerance, and the route helper accepted a
duck-typed object with a boolean `passed` field. Both were corrected without
moving policy into the Task 13A adapter.

### TDD RED and implementation

The first review regressions were run before their production fixes:

```text
pytest -q tests/visual_design/v4/test_v4_render_qa.py::test_q3_rejects_caller_tolerance_override \
  tests/nodes/v4/test_render.py::test_v4_q3_route_rejects_duck_typed_spoofed_result
FF
FAILED ...test_q3_rejects_caller_tolerance_override - DID NOT RAISE
FAILED ...test_v4_q3_route_rejects_duck_typed_spoofed_result - DID NOT RAISE
```

The evaluator no longer exposes `tolerance_px`; an attempted keyword or
fixture override is rejected with the fixed sanitized Q3 invariant error, and
all geometry checks continue to use `RENDER_BOX_TOLERANCE_PX_V4 == 2.0`. The
route helper now accepts only an exact `RenderQAResultV4`, revalidates its
canonical integrity, checks its artifact identity, and compares every result
binding with the canonical render manifest, design/Q0-Q2 evidence, content
contracts, direction, page briefs, asset manifest and family tokens still in
state. It does not re-evaluate Q3 or route partial state. Exact pass and fail
results still route to `visual_critic` and `design_reviser` respectively;
spoofed, tampered and stale results fail closed.

The added behavior-oriented Q3 matrix independently exercises:

- DOM text mutation while retaining a spoofed expected source hash;
- compiler-approved inserted line breaks versus dropped or changed copy;
- absent/false font-face witnesses, computed-family, size, weight and
  line-height mismatches;
- false glyph coverage and fallback/tofu raster ambiguity;
- page, contact-sheet and manifest byte mutation;
- malformed PNG signature and dimensions, plus page-order rejection;
- blank/fully transparent page and contact output;
- missing and symlink-substituted render files;
- asset hash/ref/load mismatch and crop/orientation mismatch, including a
  Q3 byte-substitution check. Existing Task 13A adapter tests continue to
  cover source transaction and symlink identity before Q3.

The focused boundary is green after implementation:

```text
pytest -q tests/visual_design/v4/test_v4_render_qa.py
36 passed in 28.93s

pytest -q tests/nodes/v4/test_render.py
10 passed in 6.57s

pytest -q tests/schemas/v4 tests/rendering/scene/test_v4_adapter.py
71 passed in 12.62s

pytest -q tests/integration/test_v4_three_grammar_render.py
6 passed in 6.98s

pytest -q tests/visual_design/v4/test_v4_render_qa.py tests/nodes/v4/test_render.py \
  tests/schemas/v4 tests/rendering/scene/test_v4_adapter.py
117 passed in 47.65s
```

### Verification and fresh external evidence

Controller-provided fresh external evidence after the preceding Chromium
overflow correction is recorded here verbatim: three-Grammar integration
`6 passed`, v3 smoke `1 passed`, strict v4 probe `1 passed`, and filtered full
suite `1841 passed, 3 live skips`. The three-Grammar run remained a real
Chromium path with no injected renderer.

The required full offline run completed with the two unrelated legacy/browser
smoke failures and the exact sandbox error recorded above:

```text
pytest -q
1876 passed, 2 failed, 6 skipped, 2 warnings in 89.13s
```

The three-Grammar module itself passed all six collected tests in this local
run; only the generic legacy smoke and strict v4 probe hit Chromium's
`MachPortRendezvousServer ... Permission denied (1100)` launch restriction.

## Fix Round 2 — public Q3 attack coverage

Base for this round: `b9b997b`. The independent review found that the newline,
glyph-witness and asset regressions did not all exercise the public
`evaluate_v4_render` boundary. No production code was widened in this round.

### TDD RED

The new public-boundary tests were first run before their real fixture builders
were added:

```text
pytest -q tests/visual_design/v4/test_v4_render_qa.py \
  -k 'public_preserves_explicit or public_accepts_only_compiler_inserted'
4 failed - NameError: name '_world_with_text' is not defined

pytest -q tests/visual_design/v4/test_v4_render_qa.py \
  -k 'public_evaluator_accepts_a_valid_asset_world or public_evaluator_rejects_asset_binding_mutations or public_evaluator_rejects_substituted_asset_bytes'
7 failed - NameError: name '_asset_evaluator_world' is not defined
```

### Corrections and GREEN

The test-only builders now rebuild source atoms, semantic fragments, direction,
page briefs, compiler measurements, Q0-Q2 and immutable render evidence before
calling the public evaluator. Explicit LF, CRLF and CR source cases assert the
source hash and exact newline span, accept Chromium's LF normalization, reject
dropped/changed copy, and reject an unwrapped source when the compiler recorded
inserted layout breaks. Independent public-Q3 mutations now cover
`face_loaded=False`, `font_check=False` and a tofu-raster collision, each with
rehashed valid evidence and `RENDER_GLYPH` classification. A complete
image-bearing comparison world uses real `ImageElement`, approved manifest
bytes, compiler asset bindings and adapter publication; public evaluation
accepts the baseline and rejects asset ref/hash/load/crop/orientation changes,
as well as substituted source bytes fail-closed.

```text
pytest -q tests/visual_design/v4/test_v4_render_qa.py \
  -k 'public_preserves_explicit or public_accepts_only_compiler_inserted'
4 passed, 36 deselected in 19.11s

pytest -q tests/visual_design/v4/test_v4_render_qa.py \
  -k 'font_face_metric_and_glyph_witness'
10 passed, 33 deselected in 12.96s

pytest -q tests/visual_design/v4/test_v4_render_qa.py \
  -k 'public_evaluator_accepts_a_valid_asset_world or public_evaluator_rejects_asset_binding_mutations or public_evaluator_rejects_substituted_asset_bytes'
7 passed, 43 deselected in 14.46s

pytest -q tests/visual_design/v4/test_v4_render_qa.py
50 passed in 66.55s

pytest -q tests/rendering/scene/test_v4_adapter.py tests/visual_design/v4/test_compiler.py tests/nodes/v4/test_assets.py
110 passed in 15.70s

python -m compileall -q tests/visual_design/v4/test_v4_render_qa.py
git diff --check
passed
```

### Round 2 concerns

The added coverage is offline and uses deterministic fixture bytes; it does
not replace the required real-Chromium controller rerun. The earlier external
three-Grammar, v3 smoke, strict-probe and filtered-suite evidence remains the
authoritative live-browser evidence, while this round leaves the production
evaluator and Task13A adapter unchanged.
