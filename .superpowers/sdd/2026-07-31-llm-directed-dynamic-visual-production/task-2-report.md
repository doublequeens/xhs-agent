# Task 2 Report: Dynamic Visual Scene Contracts

## Status

Implemented the Task 2 contract slice only. No nodes, providers, graph edges,
renderers, or obsolete slot/storyboard consumers were changed.

## Files

Created:

- `src/schemas/visual_style.py`
- `src/schemas/scene_graph.py`
- `src/schemas/design_qa.py`
- `src/schemas/visual_critique.py`
- `tests/schemas/test_visual_direction.py`
- `tests/schemas/test_scene_graph.py`
- `tests/schemas/test_visual_qa.py`

Replaced:

- `src/schemas/visual_director.py`
- `src/schemas/assets.py`
- `src/schemas/render_manifest.py`
- `src/schemas/render_qa.py`

Modified:

- `src/schemas/__init__.py`

## RED

Command:

```text
pytest -q tests/schemas/test_visual_direction.py tests/schemas/test_scene_graph.py tests/schemas/test_visual_qa.py
```

Observed before production implementation:

```text
ERROR tests/schemas/test_visual_direction.py
ImportError: cannot import name 'PageDirection' from 'src.schemas.visual_director'

ERROR tests/schemas/test_scene_graph.py
ModuleNotFoundError: No module named 'src.schemas.scene_graph'

ERROR tests/schemas/test_visual_qa.py
ModuleNotFoundError: No module named 'src.schemas.design_qa'

3 errors in 0.14s
```

This was the expected missing-contract RED (exit code 2).

## GREEN

Focused contract command:

```text
pytest -q tests/schemas/test_visual_direction.py tests/schemas/test_scene_graph.py tests/schemas/test_visual_qa.py
```

Final output:

```text
.................                                                        [100%]
17 passed in 0.04s
```

Task 1 atom primitive regression:

```text
pytest -q tests/schemas/test_content_atoms.py
```

Final output:

```text
.......                                                                  [100%]
7 passed in 0.03s
```

## Compile and Diff Checks

Commands:

```text
python -m compileall -q src main.py
git diff --check 63e3cdd..HEAD
```

Final result: both exited 0 with no output.

## Contract Notes

- `TemplateFamily` contains exactly `pink_red`, `deep_teal`, `soft_pink`,
  `coral_impact`, `green_catalog`, and `white_quote`.
- `VisualDirectionPlan.validate_against(...)` calls
  `ContentAtomSet.validate_complete_fragments(...)` directly for immutable,
  character-exact fragment validation. It does not reconstruct atoms itself.
- Direction plans enforce 5–18 pages, contiguous unique pages, complete
  one-page ownership of every fragment, non-blank unique visual jobs, and
  page-bound asset directives.
- Family palette and motif subsets are checked at the producer boundary against
  the selected `FamilyStyleProfile`.
- Scene elements are a discriminated union of only text, image, shape, line,
  and approved icon primitives. Strict extra-field rejection prevents HTML,
  CSS, scripts, URLs, and embedded visible text.
- Design plans bind direction, atom-set, and asset-manifest hashes.
- Asset manifests use the Task 7 directive-resolution fields and retain
  security status separately from the final human decision.
- Design/Render QA issues carry rule, message, repair instruction, and a
  page/element/atom location.
- Render probes carry measured bounds, computed font values, overflow/clipping
  flags, contrast, content/asset references, rasterized text hashes, and
  optional image crop/focal-point attestation.
- Text-only visual critiques require `image_relevance="not_applicable"`.

## Self-Review

- Scope: only the eleven Task 2 files plus this report were touched.
- Mutation check: removing page-count bounds, fragment delegation, scene
  extra-field rejection, image asset binding, any one source hash, actionable
  QA instructions, render-probe text attestation, or text-only image relevance
  makes at least one focused test fail.
- The source-hash checks compare canonical model serialization and the
  atom-set-owned canonical hash rather than duplicating hash logic.
- New contracts use strict, frozen Pydantic models; ContentAtom and
  ContentFragment remain unchanged and immutable.

## Concerns

- Replacing the old slot-based `assets.py` contract intentionally leaves the
  obsolete `visual_plan`, asset resolver, renderer, `AgentState`, and `main`
  import path broken until their scheduled Task 7/Task 14 migration or
  deletion. A broader upstream check reached 23 passing tests before one
  `main` import failed on the removed `AssetRequirement`; no old consumer was
  patched in this task.
- Per the approved task boundary, full-suite GREEN is not claimed at this
  intermediate migration point. The new Task 2 contract gate and Task 1 atom
  primitive regression are GREEN.

## Review Round 1

### RED

Tests were added before production changes for:

- exact design/direction page bindings;
- unknown and cross-page text fragment references;
- atom-set revalidation at the design producer boundary;
- unknown, unsafe, cross-page, and wrong-directive image asset references;
- strict scalar validation;
- direct mutation and stable JSON serialization of every Task 2 mapping;
- required and malformed VisualCritique input hashes;
- branch-specific HTML, CSS, and unknown-icon rejection details.

Command:

```text
pytest -q tests/schemas/test_visual_direction.py tests/schemas/test_scene_graph.py tests/schemas/test_visual_qa.py
```

Observed:

```text
18 failed, 16 passed in 0.09s
```

The failures were the expected missing enforcement: coercion did not raise,
mapping mutation did not raise, reference-binding calls did not raise, and the
four VisualCritique hashes were rejected as extra fields.

### GREEN

The same focused command after the minimal contract changes produced:

```text
34 passed in 0.04s
```

Implementation notes:

- `StrictModel` now uses `strict=True`.
- Hash-covered mappings are recursively frozen with `MappingProxyType` after
  validation and have explicit serializers that restore ordinary JSON
  mappings for canonical hashing.
- `CarouselDesignPlan.validate_bindings(...)` revalidates fragments through
  `ContentAtomSet.validate_complete_fragments(...)`, requires the exact
  direction page identity/sequence, and validates page-local text and approved
  asset/directive references.
- `VisualCritique` now requires atom-set, direction-plan, design-plan, and
  render-manifest SHA-256 bindings.
- HTML, CSS, and unknown icons now have independent tests asserting exact
  Pydantic error location, type, and relevant message/context.
- EOF blank lines reported against the Task 2 range were removed.

### Final Verification

Commands:

```text
pytest -q tests/schemas/test_visual_direction.py tests/schemas/test_scene_graph.py tests/schemas/test_visual_qa.py
pytest -q tests/schemas/test_content_atoms.py
python -m compileall -q src main.py
git diff --check 63e3cdd..HEAD
```

Final results are recorded after the separate review-fix commit so the
range-aware diff command includes both Task 2 commits.

Fresh pre-commit evidence:

```text
Task 2 schemas: 34 passed in 0.03s
Task 1 content atoms: 7 passed in 0.02s
compileall: exit 0, no output
git diff --check 63e3cdd: exit 0, no output
```

The pre-commit diff command compares the complete Task 2 working tree against
the Task 1 base. After commit, the equivalent committed-range command is
`git diff --check 63e3cdd..HEAD`.

## Fix round 1 finalization

### Files and fixes

- `src/schemas/scene_graph.py`: validate exact direction/design page identity
  and sequence, revalidate immutable atom fragments, and require page-local
  text fragments plus approved, page-owned directive-bound image assets.
- `src/schemas/visual_style.py`, `visual_director.py`, `assets.py`, and
  `render_manifest.py`: make hash-covered mappings strict and recursively
  immutable while preserving canonical JSON serialization.
- `src/schemas/visual_critique.py`: require the atom, direction, design, and
  render input hashes.
- `tests/schemas/test_scene_graph.py`, `test_visual_direction.py`, and
  `test_visual_qa.py`: add focused regression coverage for these bindings and
  independent HTML, CSS, and unknown-icon rejection behavior.

### Fresh verification before commit

```text
pytest -q tests/schemas/test_visual_direction.py tests/schemas/test_scene_graph.py tests/schemas/test_visual_qa.py
34 passed in 0.03s

pytest -q tests/schemas/test_content_atoms.py
7 passed in 0.02s

python -m compileall -q src main.py
exit 0, no output

git diff --check
exit 0, no output
```

### Self-review

The fix remains limited to Task 2 contracts, their focused tests, and this
report. No graph, node, renderer, provider, or legacy-consumer migration was
included. Post-commit `git diff --check 63e3cdd..HEAD` exited 0 with no output,
and `git status --short` was empty.
