# Task 3 report: select graph before checkpoint loading

## Outcome

- Added the frozen `WorkflowContext` and version-aware selection/factory helpers in
  `src/editorial_carousel/workflow_selection.py`.
- Updated `main.py` to resolve registry identity and build exactly one graph before
  the first checkpoint operation. The v4 factory imports `src.graph_v4` only at the
  selected v4 boundary; v3 continues to call the unchanged `src.graph.create_graph`.
- Added `load_versioned_run`: v3 delegates to the existing legacy-aware loader;
  v4 reads `get_state` directly, never hydrates legacy state, and preserves the
  empty-state/initial-input contract.
- Updated lifecycle writes so v4 uses authoritative `execution_state`, rejects
  fatal/exhausted/completed explicit resumes, and keeps `WAITING_HUMAN` bound to
  review. v3 status transitions and QA-counter reset behavior remain unchanged.
- Added ordering, mismatch, lazy-import, v4 bypass, v3-default/backfill, and v4
  resume regression coverage.
- Review follow-up classifies v4 failures by lifecycle phase: a missing selected
  graph is `FAILED_FATAL`, graph/checkpoint/bootstrap failures are
  `INTERRUPTED_RETRYABLE`, and only an active review-input failure preserves
  `WAITING_HUMAN` while recording the error.
- Integration coverage now drives `main.main` with persisted v4 metadata and
  connected factory/checkpoint call traces, including wrong-graph exclusion and
  mismatch rejection before either factory or checkpoint access.

## TDD evidence

The focused red run was executed after adding the tests and before implementation:

```text
pytest -q tests/test_main.py tests/integration/test_legacy_editorial_resume.py
5 failed, 67 passed
```

The failures were the expected missing v4 resume transitions and missing
`load_versioned_run`; the new workflow-selection module was also absent during the
initial collection run.

The review-follow-up red run was:

```text
pytest -q tests/test_main.py -k 'v4_waiting_resume' tests/integration/test_workflow_version_selection.py
3 failed
```

The failures were the expected unclassified `WAITING_HUMAN` outcomes. The
dedicated orchestration regressions were then run without the `-k` filter and
passed against the corrected `main.main` path.

## Verification

- `pytest -q tests/test_main.py tests/integration/test_workflow_version_selection.py tests/integration/test_legacy_editorial_resume.py` — 78 passed.
- `pytest -q tests/test_main.py tests/test_graph.py tests/test_run_registry.py tests/integration/test_legacy_editorial_resume.py tests/integration/test_workflow_version_selection.py` — 116 passed.
- Review follow-up focused suites — 120 passed.
- `pytest -q` — 1,323 passed, 2 expected live-AI tests skipped.
- `python main.py --help` — succeeded without importing the absent `src.graph_v4`.
- `python -m compileall -q src main.py` — passed.
- `git diff --check` — passed.
