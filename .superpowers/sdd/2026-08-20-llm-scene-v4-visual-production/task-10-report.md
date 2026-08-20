# Task 10 report: v4 composition grammars

Status: implemented and verified.

## Scope

Implemented the frozen structural-intent contracts, six-family token projection,
the first three family-neutral Composition Grammars, and deterministic page
composition planning. No v3 schema/node/renderer, graph wiring, publish
contract, state, asset, output, or database files were changed.

## RED/GREEN proof

Initial command (before implementation):

```text
pytest -q tests/schemas/v4/test_layout.py tests/visual_design/v4/test_grammars.py tests/nodes/v4/test_composition.py
```

It failed during collection with three expected missing-module errors:
`ModuleNotFoundError: No module named 'src.schemas.v4.layout'` and the
corresponding missing `src.nodes.v4.composition` module.

After implementation, the focused suite passed: `15 passed`.

## Changed files

- `src/schemas/v4/layout.py`: frozen extra-forbid grammar, token, placement,
  and `LayoutProgramV4` contracts with canonical hash/integrity checks.
- `src/visual_design/v4/tokens.py`: immutable six-family token registry derived
  from `load_style_registry()`.
- `src/visual_design/v4/grammars.py`: immutable `editorial_hero`,
  `comparison_grid`, and `step_flow` definitions with reference validation.
- `src/nodes/v4/composition.py`: strict PageBrief/hash/grammar checks and
  deterministic fragment/asset placement construction without provider or
  renderer calls.
- `tests/schemas/v4/test_layout.py`
- `tests/visual_design/v4/test_grammars.py`
- `tests/nodes/v4/test_composition.py`

## Verification

- Focused Task 10 plus style registry: `17 passed`.
- Adjacent v4 direction/authoring/QA regressions: `30 passed`.
- Full offline suite: `1600 passed, 3 skipped` (live provider/Gemini tests
  skipped by their existing environment gates).
- `python -m compileall -q src main.py`: passed.
- `git diff --check`: passed.

The full suite emitted four existing warnings: two Pydantic serializer
warnings in tampered semantic-model tests and two pytest temporary-directory
cleanup warnings. No warning originated from the Task 10 modules.

## Self-review and remaining concerns

- Layout programs contain only IDs, named regions, relationships, abstract
  density/alignment/response rules, and hashes; nested models reject geometry,
  markup, paths, provider metadata, and unknown fields.
- Fragment and asset references are page-local and unique; stale PageBrief or
  LayoutProgram hashes fail closed, and an allowed-but-unimplemented grammar
  has no fallback.
- The compiler/typography measurement layer remains intentionally unimplemented
  for Task 11; this task only supplies its structural input boundary.
