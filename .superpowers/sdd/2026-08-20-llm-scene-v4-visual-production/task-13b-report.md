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
  parameters. The full suite's two unrelated browser smoke/probe failures
  remain the sandbox's intermittent Chromium launch permission error; the
  controller should rerun the Task13B module externally once more before
  committing.
- No network, model, provider or live asset path was used by the integration
  builders.
