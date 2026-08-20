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

- Q0 issue ordering is deterministic: fragment-local source/bounds/text checks
  (with `VISIBLE_TEXT_MUTATED` emitted before later coverage findings),
  sequence/coverage, parent graph, groups, table relation, and final hash
  bindings.
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

## Fix round 1 — independent review findings

### Status

`DONE_WITH_CONCERNS`

The five controller requirements from fix round 1 are addressed within the
Task 7 file boundary.  The route now revalidates current contracts and compares
the persisted Q0 result with a freshly evaluated result.  Persisted and gateway
instances are rehydrated through `model_validate(model_dump(...))`; diagnostic
canonical repair uses a second `model_validate` and retains hash-drift evidence,
without allowing a `model_construct` instance into Q0 validation.

### Coverage and requirement mapping

- `src/nodes/v4/semantic.py`: revalidates atom/lock/projection before gateway,
  revalidates the gateway draft before model construction, and fail-closes the
  route when current atom/lock/model/projection contracts or fresh Q0 differ
  from persisted state.
- `src/visual_design/v4/semantic_qa.py`: performs safe nested contract
  rehydration, emits local visible-text findings before stale hash findings,
  enforces source-role compatibility, ordered step/checklist groups, paired
  comparison groups, and table header/each-row/overall boundaries.  Structural
  checks are small deterministic helpers over verified fragment/group indexes;
  malformed nested payloads return sanitized hash findings rather than raising.
- `src/schemas/v4/semantic.py`: adds stable relation issue codes for source-role,
  step, checklist, and comparison failures.
- `tests/nodes/v4/test_semantic.py`: covers tampered persisted atom/lock and
  gateway draft boundaries, fresh-route rejection of an old revision, and
  preserves a valid strict role fixture.
- `tests/visual_design/v4/test_semantic_qa.py`: covers stale-hash mutation
  priority, malformed nested model failure, table role and row-boundary loss,
  step/checklist grouping, and comparison pairing.

### TDD evidence

Fix-round RED command (after adding the nine regression tests and before the
production fixes):

```text
pytest -q tests/schemas/v4/test_semantic.py tests/nodes/v4/test_semantic.py tests/visual_design/v4/test_semantic_qa.py
9 failed, 16 passed, 1 warning
```

The failures reproduced all four review areas: gateway received tampered
contracts, malformed draft/nested model raised instead of failing closed, stale
QA routed to authoring, stale-hash mutation reported hash first, and role/table/
step/checklist/comparison relation checks were absent.

GREEN focused command after the fixes:

```text
pytest -q tests/schemas/v4/test_semantic.py tests/nodes/v4/test_semantic.py tests/visual_design/v4/test_semantic_qa.py
25 passed, 2 warnings in 0.58s
```

### Verification commands

1. `pytest -q tests/schemas/v4/test_semantic.py tests/nodes/v4/test_semantic.py tests/visual_design/v4/test_semantic_qa.py`
   → `25 passed, 2 warnings in 0.54s`.
2. `pytest -q tests/schemas/v4/test_semantic.py tests/nodes/v4/test_semantic.py tests/visual_design/v4/test_semantic_qa.py tests/visual_ai/test_gateway.py`
   → `65 passed, 4 warnings in 0.79s`.
3. `pytest -q tests/schemas/v4/test_content.py tests/nodes/v4/test_content.py`
   → `22 passed in 0.13s`.
4. `pytest -q`
   → `1505 passed, 2 skipped, 4 warnings in 35.61s`; the skips are live Gemini
   tests disabled by default.
5. `python -m compileall -q src main.py`
   → exit code 0, no output.
6. `git diff --check`
   → exit code 0, no output.

### Fix-round self-review

- Issue ordering is deterministic: local fragment source/bounds/text and role
  findings, sequence/coverage, parent/group, semantic relations, table
  boundaries, then cross-contract hashes.  `VISIBLE_TEXT_MUTATED` therefore
  remains first when a stale canonical hash accompanies rewritten `exact_text`.
- Step/checklist grouping compares the verified global fragment sequence with
  ordered relation groups.  Comparison groups require each explicit label/value
  pair exactly once and preserve group order; ordinary paragraphs are not
  promoted to comparison semantics.  Table checks match each persisted source
  table's header, every row boundary, and row-major overall group, including
  ordering and multiple tables.
- The route is fail-closed on any missing/invalid contract, binding mismatch,
  stale QA result, or fresh-Q0 failure.  No gateway retry, provider response,
  credential, path, or visible source text is copied into QA evidence.
- No files outside the Task 7 boundary were changed; no package marker was
  required.  The two Pydantic serializer warnings come from intentionally
  malformed-instance regression fixtures and do not affect pass/fail behavior.

### Concerns

- The full and gateway suites still emit two unrelated pytest temporary-directory
  cleanup warnings plus the two intentional malformed-instance serializer
  warnings; all tests pass.
- Graph wiring and downstream authoring remain intentionally deferred to later
  tasks; this fix round keeps the route boundary isolated and does not modify
  `src/graph.py`.
