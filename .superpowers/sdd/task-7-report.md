# Task 7 implementation report

## Outcome

Replaced the primary Carousel QA and Render QA contracts with deterministic
editorial invariants while preserving the existing deterministic-failure to R1
routing shape. The new path accepts 5–7 semantic editorial frames, validates the
VisualPlan/semantic-slot adapter seam, audits rendered manifests and source files,
and records explicitly labelled deterministic proxy metrics for Human Review.

## Delivered behavior

### Carousel QA

- Validates each raw storyboard frame as a strict `CarouselFrame` without allowing
  the aggregate Pydantic validator to hide actionable composition failures.
- Emits stable, atomic issues for frame count, exact cover promise, missing saveable
  frame, fewer than three layouts, adjacent layout repetition, undeclared layout
  family, plan identity/layout drift, changed or missing frame task, schema failure,
  missing semantic slot, and asset requirement drift.
- Keeps semantic storyboard roles separate from concrete catalog roles. For every
  slot, QA checks the semantic role against `FramePlanItem.asset_roles`, then applies
  `ASSET_ADAPTER[(layout, semantic_role)]`, and finally checks the same-slot
  `AssetRequirement` concrete role and layout. It never compares semantic role
  directly with the catalog role.
- Rule IDs are schema-constrained to stable lowercase snake case. Issues include the
  narrowest available `frame_id` and `location_hint`.
- The public `validate_carousel(package, contract, visual_plan)` interface contains
  no fixed-six assumptions and performs no LLM repair.

### Render QA

- Adds `validate_render(package, asset_manifest, render_manifest)` and atomically
  audits ordered page identity, PNG signature and measured `1080 x 1440` dimensions,
  exact local font families, explicit overflow/token diagnostics, exact visible-text
  audit values when present, asset provenance, current source hash, rendered source
  hash, intrinsic dimensions, semantic-slot to concrete-role adaptation, contact
  sheet, render errors, and partial output.
- `RenderQAIssue` now carries `frame_id`; repeated failures generate one R1 task per
  issue using the existing `render_qa` source and high severity.
- Asset stretching is detected from intrinsic source dimensions versus the manifest
  geometry. Source hashes are checked both against current bytes and the slot-keyed
  `RenderManifest.source_asset_sha256` record.
- Task 6's renderer constructs visible copy only from the storyboard and returns a
  manifest only after its DOM/font/layout probes pass. Render QA additionally checks
  optional persisted `rendered_visible_text` and `render_diagnostics` facts when the
  graph supplies them.

### Deterministic quality proxies

`RenderQAResult` exposes all six requested 0–100 metrics:

- `editorial_quality`
- `beauty_category_fit`
- `visual_hierarchy`
- `saveability`
- `cross_page_consistency`
- `template_stiffness`

They are computed only from measurable frame/layout diversity, adapter-bound asset
roles, exact source hashes, actual page-file dimensions, page identity/order, local
font status, and saveable-layout presence. `template_stiffness` explicitly documents
that a higher score means more adjacent repetition. The result serializes
`metric_kind="deterministic_proxy"` and this Human Review-facing note:

```text
Deterministic proxy metrics derived from measured layout, token, and asset facts;
they do not replace human aesthetic review.
```

Task 8's Human Review payload is specified to expose the serialized
`render_qa_result`, so the metrics cannot be presented there without the proxy label
and non-replacement notice.

### Migration isolation

The current graph has not yet been rewired by Task 8. To keep every intermediate
commit deployable, node adapters use a narrow checkpoint bridge only when
`visual_plan` or the two manifests are absent. The bridge retains the pre-Task-8
fixed-card graph behavior in private legacy functions. New editorial public
validators never call that code. No graph, renderer, export, or footer code changed.

## TDD evidence

Pre-change named suite baseline:

```text
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest \
  tests/nodes/test_carousel_qa.py tests/nodes/test_render_qa.py -q

6 passed in 0.10s
```

Valid editorial invariant RED after replacing the fixed-six tests:

```text
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest \
  tests/nodes/test_carousel_qa.py tests/nodes/test_render_qa.py -q

24 failed, 1 passed in 0.25s
```

The failures were behavioral: the old Carousel QA parsed semantic frames as
`TextCardPayload`, retained fixed-six rules, and Render QA lacked `validate_render`,
manifest consumption, frame IDs, and proxy fields. There were no collection or
fixture-construction errors.

Stable rule-ID schema RED:

```text
2 failed in 0.09s
Failed: DID NOT RAISE ValidationError
```

Measured-quality RED:

```text
1 failed in 0.11s
assert degraded.visual_hierarchy < baseline.visual_hierarchy
assert 100 < 100
```

This proved the first proxy implementation read declared dimensions but not the
actual PNG IHDR. The dimension fact was shared with Render QA and now reads the file.

Final focused GREEN:

```text
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest \
  tests/nodes/test_carousel_qa.py tests/nodes/test_render_qa.py -q

28 passed in 0.13s
```

Related schema, strategy, resolver, renderer, legacy-renderer, and graph regression:

```text
215 passed, 2 skipped, 1 warning in 14.14s
```

The two skips are opt-in live stock-provider tests.

Human-review/final-guard/domain integration regression:

```text
67 passed, 3 warnings in 8.49s
```

Fresh full repository verification:

```text
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest -q --disable-warnings

992 passed, 2 skipped, 3 warnings in 29.11s
```

The two skips are the opt-in Pexels/Unsplash live-provider tests. The three counted
warnings are existing LangGraph/legacy-checkpoint warnings. Pytest also printed a
non-failing macOS temporary-directory cleanup warning after completion.

## Self-review

- Re-read the Task 7 brief, Global Constraints, QA design section, and Task 1–6
  schema/renderer/resolver contracts against the final diff.
- Confirmed the validator entrypoints only compose focused helpers in a fixed order;
  repeated frame/asset failures preserve input order and therefore stable task IDs.
- Confirmed every actionable per-frame/page/asset failure carries a frame ID and
  narrow location; global count/composition failures intentionally use `frame_id=None`.
- Confirmed semantic and concrete roles meet only through the existing adapter and
  same-slot requirement contract.
- Confirmed quality fields are integer results of explicit facts, not an LLM, image
  model, topic keyword, aesthetic claim, randomness, wall-clock value, or I/O order.
- Confirmed no QA function imports or calls a model or attempts repair.
- Confirmed successful and failed node paths retain `CarouselQAResult`/
  `RenderQAResult`, `DecisionOutput(next_node="R1_REFLECTOR")`, and one mandatory R1
  task per issue.
- Confirmed graph, rendering, export, and Task 6 footer code are untouched.

## Concerns

- `RenderManifest` intentionally contains only pages, font report, contact sheet,
  and source hashes. Task 6 already blocks DOM overflow/copy failures before creating
  that manifest. Render QA consumes explicit `render_diagnostics` and
  `rendered_visible_text` if Task 8 persists them, but absence of those optional audit
  copies is not treated as failure because the current strict renderer cannot emit
  them without an out-of-scope renderer/schema change.
- The private legacy branches should be deleted when Task 8 removes the old graph
  path. They exist only to keep this intermediate Task 7 commit green and do not
  weaken the new editorial validators.
