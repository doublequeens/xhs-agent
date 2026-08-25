# Task 14 report: bounded v4 visual revisions

## RED/GREEN evidence

- RED: `pytest -q tests/visual_design/v4/test_revisions.py tests/nodes/v4/test_revision.py tests/integration/test_v4_revision_state_machine.py` initially stopped at collection with `ModuleNotFoundError` for the three new Task 14 modules. This proves the new tests did not pass against an absent implementation.
- GREEN focused: the same command completed as `9 passed in 0.16s` after implementation.
- Resume/ledger regression: `pytest -q tests/visual_runtime/test_attempt_ledger.py tests/integration/test_visual_loop_regression.py` completed as `76 passed in 3.95s`.
- Adjacent contracts/nodes: `pytest -q tests/schemas/v4 tests/nodes/v4` completed as `147 passed, 1 warning in 11.35s`. The warning is pre-existing Pydantic serializer coverage for deliberately tampered semantic test input.
- Adjacent visual modules excluding the long Chromium Q3 module: `pytest -q tests/visual_design/v4 --ignore=tests/visual_design/v4/test_v4_render_qa.py` completed as `168 passed, 1 warning in 3.47s`; its warning is the corresponding deliberately tampered semantic fixture.
- Static checks: `python -m compileall -q src main.py` and `git diff --check` both completed with no output.

## Schema/API surface

| API | Purpose |
| --- | --- |
| `FailureFingerprintV4` | Frozen canonical identity derived from node, page, closed code, sorted fragment IDs and optional geometry region. |
| `NormalizedFailureV4` | Hash-bound, non-copy-bearing router input. |
| `RevisionInvalidationV4` | Exact partial/whole-page invalidation and named downstream contracts; rejects ContentLock/atom mutation. |
| `RevisionRequestV4` | Strict constrained layer/operations request with ordered fingerprints and canonical hash. |
| `RevisionEventV4` | Frozen append-only consumed repair event, hash-bound to its fingerprint and operation. |
| `VisualExecutionInterrupted` | Sanitized terminal signal with `execution_state=INTERRUPTED_EXHAUSTED`. |
| `route_revision` / `append_revision_event` | Pure deterministic routing and event append functions. |
| `serialize_revision_state` / `deserialize_revision_state` | Canonical byte-stable history round trip used by resume. |
| `revision_node` | Exact Q0–Q3 node boundary; derives request, event and constrained route; rejects duck-typed result/request/history input. |

## Closed issue mapping

| Issue family | Layer |
| --- | --- |
| Q0 semantic/character/relationship/hash failures and forbidden visible copy | `SEMANTIC` |
| Q1 page responsibility, density, page-count/order and repagination failures; Q2 density/block-ratio; Q3 page order | `AUTHORING` |
| Q1 asset-directive ownership/binding; Q3 asset/crop/path | `ASSET` |
| Q1 family/composition; Q2 image/text composition | `COMPOSITION` |
| Q2 safe-area, overlap, type, spacing, alignment, hierarchy and line/orphan failures; Q3 box drift/overflow | `LAYOUT` |
| Q3 input/identity/page/bytes/dimension/blank/DOM/font/glyph failures | `RENDER` |
| Closed critic-only aesthetic failure | `AESTHETIC` |

`HASH_BINDING_MISMATCH` is disambiguated by its exact source node: Q0 maps to `SEMANTIC`, Q1 to `AUTHORING`. Unknown codes fail closed.

## Determinism, ladder and invalidation

- Fingerprints hash exactly `(node, page_id, failure_code, sorted unique affected_fragment_ids, geometry_region)` with `None` retained for absence. Caller digests are revalidated rather than trusted; tampered model copies fail.
- For a layout fingerprint: occurrence 1 permits only `REFLOW`; occurrence 2 permits only `CHANGE_GRAMMAR` and forbids `REFLOW`; occurrence 3 raises `VisualExecutionInterrupted` with `INTERRUPTED_EXHAUSTED` and `START_NEW_CANDIDATE`. Counts are candidate + fingerprint scoped, so another page/fingerprint starts at `REFLOW`.
- History validates append lineage, candidate identity, layer mapping and the operation ladder before it can consume budget.
- `FAMILY_MISMATCH`, page-count changes and page-order changes invalidate the whole set and authoring/downstream contracts. Other failures carry only their exact affected pages and invalidate only design-plan/render/critic downstream contracts. ContentLock and atoms are structurally prohibited from invalidation.
- Resume is canonical JSON bytes over strict events; `serialize -> deserialize -> serialize` is byte-identical and preserves the first repair event, so ordinary resume selects the second operation rather than resetting history.

## Architecture constraints retained

The implementation adds no graph edge, no run-registry mutation, no Attempt Ledger mutation, no ContentLock mutation, and no old v3-path dependency. It consumes only public run execution-state vocabulary (`INTERRUPTED_EXHAUSTED`) and does not inspect checkpoint SQLite internals. It uses neither clocks nor random UUIDs for route, revision identity, fingerprint or serialization.

## Self-review / concerns

- Reviewed failure-forgery, unknown-code, duck-typed, stale-hash, history-lineage, budget-isolation, invalidation and ordinary-resume paths. The event operation is re-derived from the full prior history so a syntactically valid but ladder-inconsistent event cannot spend budget.
- Scope intentionally stops at this typed node boundary: later Task graph integration must connect the emitted constrained route names and consume `revision_invalidation_v4`; this task does not modify graph, Q0–Q3 producers or existing persistence APIs.
- The complete visual-design directory was separately verified except the existing Chromium-heavy `test_v4_render_qa.py`; its Q3 node/schema neighbours are covered by the focused and node suites, while the requested ledger/resume regression passed.
