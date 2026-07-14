# Task 10 Report: Editorial Carousel Golden E2E and Resume Compatibility

## Outcome

Task 10 adds four explicitly test-only synthetic golden fixtures and exercises the
Tasks 1–9 editorial carousel path through the real graph, local asset catalog,
Chromium renderer, QA gates, Human Review, structured SQLite write-back, and
publish-artifact export. Provider and model boundaries are deterministic fakes;
the tests make no network or live LLM calls.

The fixtures cover four distinct strategy families/signatures:

- `zone_diagnosis`: `diagnose_and_adjust` / `face_zone_map`
- `ordered_routine`: `follow_steps` / `step_flow`
- `multi_option_decision`: `compare_and_choose` / `comparison_decision`
- `reference_checklist`: `save_and_check` / `saveable_reference`

Every fixture carries `test_only: true` and a synthetic-regression-only intended
use marker. Tests assert fixture identifiers, synthetic titles, topic IDs, topics,
focus copy, cover copy, and frame headlines are absent from production sources,
seed data, and every composed production prompt. All rendered and exported files
are written below pytest temporary directories, so these fixtures cannot become
production prompts, memory seeds, topic signals, or publish candidates.

## TDD Evidence

Baseline before Task 10:

```text
107 passed, 1 warning in 14.13s
```

The first real workflow run was intentionally RED:

```text
pytest tests/integration/test_editorial_carousel_workflow.py -q
6 failed
```

That run found one test-harness serialization error and exposed a production
renderer contract gap: `morning_evening_flow` and `left_right_comparison` hid
their visual slots with `display: none`, so real Chromium reported zero-sized
assets. The minimal production fix makes those two declared visual slots visible
and measurable without changing any production prompt.

The external-approval case then exposed a second production integration gap.
The focused regression test failed before the fix:

```text
tests/nodes/test_render_qa.py::test_approved_external_asset_accepts_fully_resolved_safety_review
1 failed: asset_safety_checks_unresolved
```

Human Review correctly preserves the canonical safety checklist alongside exact
boolean decisions. Render QA had treated any retained checklist as unresolved.
It now accepts only an exact, timestamped, type-safe decision mapping where
`allowed_for_publishing` is true and every hazard check is false. Missing,
duplicate, mismatched, non-boolean, or unsafe decisions still fail closed.

The focused test passed after the minimal fix:

```text
1 passed in 0.20s
```

## E2E and Resume Assertions

For each local golden fixture, the E2E verifies the expected family and complete
frame signature, 5–7 ordered PNGs, at least three layouts, a saveable page,
computed/loaded font families, contact sheet, Carousel QA and Render QA success,
one structured database record with the rendered paths, `publish-copy.txt`, a
content-locked rescue prompt, title audit JSON, and artifact generation 1. Empty
fake Pexels and Unsplash adapters record zero searches and zero downloads.

The external-gap case removes `serum_texture` from a temporary copy of the real
catalog. Fake Pexels returns no result and fake Unsplash returns one in-memory PNG.
Execution is interrupted after the provider download, then resumed with the same
SQLite-checkpoint thread. Human Review receives and approves the exact binding and
safety decisions. The final active-file SHA-256, manifest source SHA-256, and
render source SHA-256 match. The provider is searched once per configured provider,
the asset is downloaded once, Chromium renders once, artifact generation remains
1, and the registry contains one completed row.

The render-resume case interrupts after real Chromium rendering and resumes the
same thread. It verifies identical output paths and hashes, one renderer call, one
output package/version marker, artifact generation 1, and one completed registry
row. The existing beauty integration was relaxed from a fixed six-page assumption
to the supported 5–7-page contract. Main resume coverage asserts that a modern
pending-external checkpoint is loaded unchanged under the exact thread config and
never resolves again; legacy resume coverage remains green.

## Verification

```text
# Golden E2E plus production-prompt isolation
49 passed, 1 warning in 25.81s

# Task 10 selected command
78 passed, 1 warning in 29.82s

# Legacy resume, Render QA, prompt composer, Chromium smoke
87 passed, 1 warning in 10.25s

# Full repository suite
1321 passed, 2 skipped, 3 warnings in 71.10s
```

The two skips are the opt-in live stock-provider tests and therefore preserve the
no-network test contract. Warnings are the known LangGraph serializer deprecation
and two intentional legacy-checkpoint fallback warnings. `git diff --check` is
clean. No production prompt file was changed.

## Self-review

- The golden data is isolated under `tests/fixtures/editorial_carousel/` and
  explicitly marked synthetic/test-only.
- Network and remote LLM lanes fail immediately if accidentally entered.
- The real workflow surfaces are retained where the task requires them: graph,
  resolver/catalog, Chromium, QA, Human Review, SQLite content record, checkpoint,
  registry, and artifact export.
- Production changes are limited to the two integration defects proven by RED
  tests; no creative defaults, fixture copy, prompts, memory, or topic seeds changed.
