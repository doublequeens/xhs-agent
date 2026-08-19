# Task 2 report: immutable workflow identity and execution state

## Outcome

Implemented a strictly additive `agent_runs` migration and public run-registry API for
`workflow_version`, `run_mode`, and six-state `execution_state` metadata.

- Existing databases are migrated with `PRAGMA table_info` plus nullable
  `ALTER TABLE ... ADD COLUMN` statements; no table rebuild is used.
- Existing rows backfill to `llm_scene_v3` / `production`, with execution state derived
  from the legacy four-state `status`.
- v4 execution state projects atomically to the legacy status field, while v3 status
  updates retain their original resumability behavior.
- Workflow version and run mode are immutable for an existing thread; conflicting
  updates fail before the write.
- Unknown/corrupt persisted enums and inconsistent state/status projections raise
  `RunRegistryError` at the registry boundary.
- The legacy SQLite `status` CHECK remains unchanged, and a deterministic pre-v4 SQL
  fixture covers migration/resume compatibility.
- v4 status-only updates are accepted only when the supplied status equals the current
  legacy projection; all v4 state transitions require an explicit `execution_state`.
- Resumable queries validate returned rows at the public boundary, while initialization
  performs the one-time full-row validation. A composite
  `workflow_version/execution_state/updated_at` index is added after migration without
  replacing the legacy indexes.
- The public surface keeps only `RunMode` and the canonical projection map names.

## TDD evidence

1. Added migration, resumability, projection, immutability, corruption, CHECK, and
   legacy-fixture tests before changing production code.
2. Red run: `pytest -q tests/test_run_registry.py` reported 12 existing passes and
   11 expected failures for the missing v4 API/migration.
3. Green focused run: `pytest -q tests/test_run_registry.py` — 23 passed.

## Verification

- `pytest -q tests/test_run_registry.py tests/memory/test_migrations.py` — 46 passed.
- Review regression cycle: the new tests first produced 48 passed / 6 failed, then the
  focused suite passed with 54 tests.
- `pytest -q` — 1308 passed, 2 skipped (live Gemini tests opt-in).
- `python -m compileall -q src main.py` — passed.
- `git diff --check` — passed.

## Changed files

- `src/run_registry.py`
- `tests/test_run_registry.py`
- `tests/fixtures/run_registry/legacy-v3-schema.sql`
- `.superpowers/sdd/2026-08-20-llm-scene-v4-visual-production/task-2-report.md`
