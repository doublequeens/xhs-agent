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

## Fix Round 1/5: review findings

### TDD RED/GREEN

- RED: after adding layer-ladder, invalidation, normalized/multi-failure, cross-layer and stale-prior regressions, `pytest -q tests/visual_design/v4/test_revisions.py tests/nodes/v4/test_revision.py tests/integration/test_v4_revision_state_machine.py` produced `16 failed, 9 passed`. Failures demonstrated repeated non-layout operations, one generic invalidation set, stale prior acceptance and normalized/multi-failure rejection.
- GREEN: the same focused command completed as `26 passed in 0.64s` after the routing/state-machine changes.
- Grammar approval proof: `pytest -q tests/visual_design/v4/test_revisions.py::test_second_layout_uses_only_hash_bound_page_brief_alternative` completed as `1 passed in 0.62s`. The test recompiled a source-bound plan whose affected Page Brief permits `comparison_grid`; the second request binds that exact alternative and the PageBrief/plan hashes. A no-context/no-alternative second layout case terminates fail-closed.

### Changes and evidence

- **No repeated second operation:** only layout has an authorized second operation. Its first event is `REFLOW`, its second is source-bound `CHANGE_GRAMMAR`; every other layer exhausts on the second identical fingerprint because no independent safe action is authorized. The third identical layout fingerprint remains `INTERRUPTED_EXHAUSTED`.
- **Layer-aware invalidation:** `SEMANTIC` starts at semantic model/Q0; `AUTHORING` starts at page briefs/direction/Q1; `ASSET` starts at asset manifest; `COMPOSITION` and `LAYOUT` start at layout/design-plan Q2; `RENDER` starts at render manifest/Q3; `AESTHETIC` starts at critique/review. Each list includes its exact downstream contracts through final attestation. Content atoms and ContentLock occur in none. Family/page-count/page-order codes are the only whole-set cases; all other routes retain exact affected pages.
- **Strict aggregation:** the node accepts only a non-empty tuple of exact, revalidated `NormalizedFailureV4` values or one exact Q0–Q3 result. It canonical-sorts/de-duplicates failures, selects the earliest layer (`SEMANTIC → AUTHORING → ASSET → COMPOSITION → LAYOUT → RENDER → AESTHETIC`), and drops downstream symptoms because the selected repair invalidates them. Same-layer requests/events carry every page, code and fingerprint; the event is bound to all request fingerprints. A mixed or tampered identity fails closed.
- **Budget and resume:** history validates candidate, lineage, exact source-derived layer and operation before it contributes to any fingerprint count. The public router derives `prior_revision_id` from the durable tail and rejects stale caller values. Per-fingerprint counts use every fingerprint in batch events; any exhausted fingerprint exhausts the candidate. Canonical serialize/deserialize retains those events and therefore retains the budget.
- **Approved grammar source context:** a second layout route requires exact `PageBriefSetV4` and `CarouselDesignPlanV4`, revalidates both and their page-brief binding, then emits only each affected page's first already-listed implemented composition that differs from the plan's current grammar. `RevisionRequestV4` hashes both inputs and has frozen `ApprovedGrammarAlternativeV4` witnesses. No approved alternative terminates; it never chooses arbitrary grammar.

### Fix-round verification

- Focused revision/node/state suite: `26 passed in 0.64s`.
- `pytest -q tests/integration/test_v4_revision_state_machine.py tests/visual_runtime/test_attempt_ledger.py tests/integration/test_visual_loop_regression.py`: `79 passed in 6.03s`.
- `pytest -q tests/schemas/v4 tests/nodes/v4`: `149 passed, 1 warning in 16.96s`; warning is the existing deliberately-tampered semantic draft serializer fixture.
- `python -m compileall -q src main.py` and `git diff --check`: completed with no output.

## Fix Round 2/5: durable grammar witnesses and closed attribution

### TDD RED/GREEN

- RED: before the round-2 fixes, `pytest -q tests/visual_design/v4/test_revisions.py tests/nodes/v4/test_revision.py tests/integration/test_v4_revision_state_machine.py` reported `16 failed, 23 passed`. The failures exposed duplicate normalized failures being rejected, unauditable grammar event context, Composition grammar requests rejected by the layout-only guard, and the event canonical digest omitting default optional fields.
- GREEN focused: after the fixes and regressions, the same command completed as `41 passed in 3.32s`.
- Resume/ledger: `pytest -q tests/integration/test_v4_revision_state_machine.py tests/visual_runtime/test_attempt_ledger.py tests/integration/test_visual_loop_regression.py` completed as `79 passed in 6.20s`.
- Adjacent v4 contracts/nodes: `pytest -q tests/schemas/v4 tests/nodes/v4` completed as `151 passed, 1 warning in 16.96s`; the warning is the existing deliberately tampered semantic serializer fixture.
- Static: `python -m compileall -q src main.py` and `git diff --check` completed with no output.

### Contract changes and review closures

| Finding | Closed behavior |
| --- | --- |
| Exact duplicate normalized issue | Router and node compare revalidated canonical payloads, de-duplicate same digest deterministically, then sort by digest. A same digest with differing payload fails closed; one event has one fingerprint and consumes one budget slot. |
| Closed node/code mismatch | `FailureFingerprintV4` has a closed node-to-code matrix: Q0 semantic, Q1 authoring, Q2 quality, Q3 rendering and critic-only aesthetic. Shared `HASH_BINDING_MISMATCH` is permitted only where its source schema declares it. Construction and revalidation reject every wrong pair. |
| Grammar authorization durability | `RevisionEventV4` stores the PageBriefSet hash, plan hash and page-unique sorted approved alternatives. These fields participate in its canonical hash and canonical resume bytes. |
| Caller-forged/stale grammar request | `append_revision_event` requires the current exact PageBriefSet and plan for every `CHANGE_GRAMMAR`, revalidates their binding, re-derives page-local allowed alternatives, and requires exact equality with the request witness/hashes. Missing, forged or stale context fails closed. |
| Composition first operation | Composition's only authorized first operation is also `CHANGE_GRAMMAR`; it is therefore governed by the same Page Brief `preferred_compositions` witness, must differ from the current grammar, and exhausts if none exists. |

The event additionally binds affected pages exactly to its fingerprints, and grammar alternatives are sorted and unique by page. Optional event fields are made explicit before canonical hashing, which preserves byte-identical ordinary (non-grammar) events as well as witness-bearing events.

### Resume and architecture evidence

- The grammar request → append event → serialize → deserialize regression proves both source hashes and witness objects survive byte-identically; a model-copied event with a removed witness is rejected during serialization.
- The node passes the current `PageBriefSetV4` and `CarouselDesignPlanV4` into both route and append boundaries. No graph, Attempt Ledger, registry, ContentLock, producer, v3-path or persistence implementation changed.
- The added node/code matrix narrows attribution at the Task 14 boundary only; it does not modify any Q0–Q3 producer issue vocabulary. Existing mapping/invalidation tests were updated to use legal source node/code pairs.

### Self-review / concerns

- Rechecked deterministic ordering, duplicate payload attacks, direct stale prior rejection, no-alternative termination, Composition authorization, and event/request fingerprint binding. Routing, hashing and serialization use no clock or random value.
- Focused, resume/ledger and adjacent schema/node verification passed. No broader Chromium/live-provider suite was run because this change is isolated to pure contracts/routing and the existing requested regression coverage covers the v4 state boundary.
