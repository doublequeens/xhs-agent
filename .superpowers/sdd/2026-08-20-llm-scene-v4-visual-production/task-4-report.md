# Task 4 report: record append-only visual attempts

## Outcome

- Added frozen, `extra="forbid"` v4 runtime contracts for `AttemptStarted`,
  `AttemptFinished`, `AttemptReconciled`, and the replay `AttemptProjection`.
- Added `AttemptLedger`, backed by the caller-provided SQLite database through an
  additive `visual_attempt_events` table. It uses WAL, bounded busy timeout,
  database-assigned monotonic sequences, canonical JSON, and database triggers
  rejecting direct updates and deletes.
- Added atomic start/terminal append operations, duplicate/unknown-attempt guards,
  crash reconciliation, replay validation, consumed-budget projection, and a
  latest projection helper. Reconciliation uses a write transaction so a racing
  finish can produce at most one terminal event.
- Added fail-closed result reuse: normalized relative POSIX references are checked
  for containment, symlinks, regular-file identity, and exact bytes SHA-256 on
  append and every successful-fingerprint lookup. Failure events are never reused.
- Added regression coverage for append-only enforcement, canonical payloads,
  malformed replay, result tampering/missing files, path traversal, WAL writers,
  crash accounting, and additive coexistence with `agent_runs`.

## TDD evidence

Tests were written before the v4 runtime implementation. The required red command
was:

```text
pytest -q tests/visual_runtime/test_attempt_ledger.py
```

It failed during collection with the expected missing-production-boundary error:
`ModuleNotFoundError: No module named 'src.schemas.v4'`.

After implementing the schema and ledger, the focused green command was:

```text
pytest -q tests/visual_runtime/test_attempt_ledger.py
```

Result: `23 passed, 2 warnings`.

## Verification

- `pytest -q tests/visual_runtime/test_attempt_ledger.py tests/test_run_registry.py`
  — `54 passed, 2 warnings`.
- Repeated focused concurrent-WAL runs (5 executions) — each passed.
- `pytest -q` — `1349 passed, 2 skipped, 2 warnings`. The skips are the documented
  opt-in Gemini live tests.
- `python -m compileall -q src main.py` — passed.
- `git diff --check` — passed.

## Commit

Implementation commit message: `feat: record append only visual attempts`.
The final commit SHA is reported in the agent handoff.

## Remaining risks

The illustrative plan snippet passes a hash-only `result_sha256` without a result
reference. The implementation follows the controller ruling that sanitized result
reference and hash fields must be paired and that recorded results require a
configured result root; hash-only terminal events are therefore rejected.
