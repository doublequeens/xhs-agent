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

## Independent-review corrections

The first Task 10 review rejected five Important and two Minor details. The
follow-up closes each item without changing production prompts or introducing
fixture content outside tests.

### Canonical safety-review contract

The previous Render QA helper duplicated only part of the lifecycle rules and
accepted a truthy but invalid or timezone-naive review timestamp. The lifecycle
module now exposes one canonical `SAFETY_CHECK_KEYS` set and one strict
`ApprovedSafetyReview` model. `PendingAuditRecord` and Render QA both validate
through that model. It requires an exact decision/check key match, rejects unknown
or duplicate checks and non-boolean values, parses ISO-8601, requires an aware
timezone, binds approved status to `approved_for_publishing`, requires
`allowed_for_publishing == true`, and requires every hazard decision to be false.

Focused RED evidence was `3 failed, 7 passed`: the shared contract did not exist,
and malformed/naive timestamps passed Render QA. The expanded table also covers
unknown and missing keys, duplicate checks, string booleans, missing timestamp,
status mismatch, and disposition mismatch. The positive approved case remains
green. The first aggregate run then found one existing item-local audit regression:
a duplicate local manifest item carrying stray safety evidence was skipped. The
existing regression failed (`1 failed, 247 passed`), the gate was corrected so
external items or any item carrying safety evidence use the canonical model, and
the exact regression plus strict table passed (`10 passed`).

### Real main resume and run registry

The interrupted-run E2Es no longer create or update registry rows themselves.
They invoke `main.main()` twice through real CLI parsing: first with `--new`, using
a real graph wrapper that simulates process death only after the selected committed
checkpoint, then with `--resume <same-thread>`. Production `select_run`,
`load_run_state`, `stream_graph_until_stop`, error handling, registry status
transitions, interrupt response routing, and completed export all execute.

Both download-resume and render-resume pass together (`2 passed`). The final
registry has exactly one completed row with the original run ID and thread ID.
After the completed external run, Pexels and Unsplash each have exactly one search,
there is exactly one download and one render, and the active/source/render hashes
match. Render resume compares the pre-resume checkpoint paths and hashes to the
terminal manifest, retains one render, one output/version, and artifact generation
1.

### Persistent row and fixture isolation

The structured write-back assertions now enumerate the real temporary SQLite row
IDs and reload the sole row with `XHSMemoryManager.get_content_by_id`. For all four
fixtures, the ordered `image_paths` exactly equal `RenderManifest.pages`, and the
row is also checked for topic/angle IDs and copy, title, cover, content, hashtags,
card count, storyboard payload, compliance status, and content contract.

Fixture names and envelope validation now come from one test-only loader. Isolation
uses `git ls-files` and scans every UTF-8-readable tracked production surface while
excluding tests, docs/test plans, worktrees, and outputs. It covers root entrypoints,
config, prompts/source, memory, topic-seed code, assets, and publish-candidate code.
For every fixture it rejects the fixture ID, synthetic title, topic ID/topic,
focus keyword, cover copy, and every headline. All production composer tasks are
checked separately. Before fixture injection, each runtime harness also proves its
temporary SQLite file does not exist, its embedding/Chroma sidecar is empty,
`topic_signals` is empty, and its publish directory does not exist.

### Reserved grid geometry and resource cleanup

The temporary absolute/z-index galleries were removed. Morning/evening flow and
left/right comparison now reserve an explicit second grid row for the asset gallery;
the dual copy panels remain in the first row. A real Chromium test renders and
screenshots all 11 layouts with two content blocks, persists the normal font/layout
probe, compares every visible content-block rectangle with every asset rectangle,
and verifies zero intersections. Flow and comparison additionally require one
non-empty block on each side and a non-absolute gallery. RED was exactly the two
absolute layouts (`2 failed, 9 passed`); GREEN is all 11 layouts.

SQLite checkpointer connections, run-registry handles, structured-memory managers,
and browsers now close through `finally` blocks or a pytest `ExitStack` cleanup
fixture, including failed assertions.

### Final review verification

```text
# E2E + all production prompts + real Chromium layouts
61 passed, 1 warning in 36.50s

# Task 10 selected command
78 passed, 1 warning in 31.04s

# Full repository suite
1343 passed, 2 skipped, 3 warnings in 82.29s
```

The two skips remain the explicitly opt-in live provider tests. The warnings remain
the known LangGraph serializer deprecation and two intentional legacy fallback
warnings. `git diff --check` remains clean.
