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
20 passed

pytest -q tests/visual_design/v4/test_typography.py tests/visual_design/v4/test_compiler.py tests/nodes/v4/test_layout.py tests/schemas/test_scene_graph.py tests/rendering/scene/test_compiler.py
87 passed

pytest -q tests/schemas/v4/test_layout.py tests/visual_design/v4/test_grammars.py tests/nodes/v4/test_composition.py
54 passed

pytest -q
1659 passed, 3 skipped, 4 warnings

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
