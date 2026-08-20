# Task 7 report — Semantic Content Model + Q0 hard gate

## Status

`DONE_WITH_CONCERNS`

The Task 7 semantic contracts, Gateway-backed node, deterministic Q0 hard gate,
prompt, tests, and route boundary are implemented. Graph integration was not
changed, as required by the brief (Task 18 owns that boundary).

## Changes and requirement mapping

- `src/schemas/v4/semantic.py`: frozen/`extra="forbid"` semantic fragments,
  groups, `SemanticContentModelV4`, strict provider draft without `exact_text`,
  sanitized stable issue codes, and hash-bound `SemanticQAResultV4`.
- `src/nodes/v4/semantic.py`: fail-closed persisted atom/lock/projection and
  run identity loading; `InvocationRequest` uses `page_ids=("content",)` and
  `node=operation_kind="semantic_modeling"`; injected gateway only; local
  Unicode-codepoint slicing; fixed Q0 routes (`visual_authoring` on pass,
  `semantic_modeling` on fail).
- `src/visual_design/v4/semantic_qa.py`: deterministic fragment source/bounds/
  text/coverage/sequence checks, parent-cycle and group checks, projection
  hash/ContentLock binding, table header/row/cell relation protection, stable
  sanitized evidence, and no force-pass path.
- `src/visual_design/v4/__init__.py`: v4 QA exports only.
- `src/prompts/base/v4_semantic_modeling.txt`: explicitly forbids visible-text
  output/rewrite, pagination, and visual decisions; requires atom coverage and
  table relation preservation.
- Tests cover exact local reconstruction, rewrite rejection, complete rebuild,
  gap/overlap/duplicate, unknown atom/parent/group, parent cycles, sequence and
  group order, table relation loss/reordering, hash/lock binding, gateway
  identity, no node retry, and hard-gate routing.

No `tests/**/v4/__init__.py` marker was needed; pytest collected all new tests.

## TDD evidence

RED command:

```text
pytest -q tests/schemas/v4/test_semantic.py tests/nodes/v4/test_semantic.py tests/visual_design/v4/test_semantic_qa.py
3 collection errors: ModuleNotFoundError: No module named 'src.schemas.v4.semantic'
```

GREEN focused command after implementation:

```text
16 passed in 0.55s
```

## Verification

1. `pytest -q tests/schemas/v4/test_semantic.py tests/nodes/v4/test_semantic.py tests/visual_design/v4/test_semantic_qa.py`
   → `16 passed in 0.55s`.
2. `pytest -q tests/schemas/v4/test_semantic.py tests/nodes/v4/test_semantic.py tests/visual_design/v4/test_semantic_qa.py tests/visual_ai/test_gateway.py`
   → `56 passed, 2 warnings in 1.09s`.
3. `pytest -q`
   → `1496 passed, 2 skipped, 2 warnings in 36.03s`; the skips are live Gemini
   tests disabled by default.
4. `python -m compileall -q src main.py`
   → exit code 0, no output.
5. `git diff --cached --check`
   → exit code 0, no output.
6. Task 6 regression check
   `pytest -q tests/schemas/v4/test_content.py tests/nodes/v4/test_content.py`
   → `22 passed in 0.13s`.

## Self-review

- Q0 issue ordering is deterministic: persisted hash checks, fragment-local
  source/bounds/text checks (with `VISIBLE_TEXT_MUTATED` emitted before later
  coverage findings), sequence/coverage, parent graph, groups, table relation,
  and final bindings.
- `SemanticQAResultV4.passed` is validator-bound to `issues == ()`; the route
  rehydrates/revalidates persisted QA results before authoring, so a stale or
  `model_copy`-mutated result cannot force passage.
- The node never calls a provider, retries, sets a timeout, or fabricates a
  result. Gateway exceptions propagate. The draft schema has no visible-text
  field, and the model's `exact_text` is always rebuilt from the persisted atom
  slice.
- Q0 uses only deterministic IDs, indexes, hashes, and structural evidence;
  prompt/provider raw responses are not copied into issues.

## Concerns

- The full suite and focused gateway suite each emitted two existing pytest
  temporary-directory cleanup warnings. They did not fail tests and are
  unrelated to Task 7 behavior.
- Graph wiring and downstream authoring remain intentionally deferred to later
  tasks; this commit exposes the route boundary without modifying `src/graph.py`.
