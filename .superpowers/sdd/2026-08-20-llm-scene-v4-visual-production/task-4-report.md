# Task 4 report: record append-only visual attempts

## Outcome

- Added strict, frozen, `extra="forbid"` v4 runtime contracts for
  `AttemptStarted`, `AttemptFinished`, `AttemptReconciled`, and the replay
  `AttemptProjection`; token usage is limited to non-empty, finite,
  non-negative integer counts.
- Added `AttemptLedger`, backed by the caller-provided SQLite database through an
  additive `visual_attempt_events` table. It uses WAL, bounded busy timeout,
  `synchronous=FULL`, database-assigned monotonic sequences, canonical JSON,
  and database triggers rejecting direct updates, deletes, and all explicit
  sequence values (including `INSERT OR REPLACE`).
- Added atomic start/terminal append operations, duplicate/unknown-attempt guards,
  crash reconciliation, replay validation, consumed-budget projection, and a
  latest projection helper. Reconciliation uses a write transaction so a racing
  finish can produce at most one terminal event; replay enforces terminal
  sequence and timestamp causality.
- Added denormalized identity columns and indexes for scoped run/candidate and
  fingerprint queries. Replay validates those columns against the start payload,
  while budget, reconciliation, and reuse queries avoid lifetime ledger scans.
- Added transactional migration for both the original four-column ledger and the
  nullable-identity intermediate ledger. Migration validates every canonical
  payload, sequence, identity, and terminal causality before rebuilding the table;
  corrupt history rolls back without changing the original schema or rows.
- Hardened identity columns to `NOT NULL`, added database insert invariants binding
  start identities to JSON and terminal identities to their start, and made
  reconciliation replay every requested-run start before deciding whether it is
  open. Reuse scans are capped at a documented fixed candidate limit.
- Added fail-closed result reuse: normalized relative POSIX references are
  traversed beneath the configured root with no-follow file descriptors, hashed
  and read from the same opened regular-file descriptor, and returned as
  immutable verified bytes plus metadata. Failure events are never reused.
- Added regression coverage for append-only enforcement, canonical payloads,
  malformed replay, timestamp causality, strict token usage, result
  tampering/missing files, final-path and ancestor swaps, path traversal, WAL
  writers, crash accounting, bounded scoped queries, legacy migration,
  identity-trigger tampering, nonpositive sequence rejection, descriptor cleanup,
  and additive coexistence with `agent_runs`.

## TDD evidence

Tests were written before the v4 runtime implementation. The initial required red
command was:

```text
pytest -q tests/visual_runtime/test_attempt_ledger.py
```

It failed during collection with the expected missing-production-boundary error:
`ModuleNotFoundError: No module named 'src.schemas.v4'`.

During the review hardening pass, the new regression tests were run before the
corresponding fixes:

```text
pytest -q tests/visual_runtime/test_attempt_ledger.py
```

Result: `19 failed, 22 passed, 2 warnings`.

The migration/invariant/cleanup review pass added further regressions and was
run red before implementation:

```text
pytest -q tests/visual_runtime/test_attempt_ledger.py
```

Result: `12 failed, 41 passed, 2 warnings`.

After implementing the schema and ledger, the focused green command was rerun:

```text
pytest -q tests/visual_runtime/test_attempt_ledger.py
```

Result: `54 passed, 2 warnings`.

## Verification

- `pytest -q tests/visual_runtime/test_attempt_ledger.py tests/test_run_registry.py`
  — `85 passed, 2 warnings`.
- `pytest -q tests/visual_runtime/test_attempt_ledger.py -k concurrent_wal`
  — `1 passed, 53 deselected`.
- `pytest -q` — `1380 passed, 2 skipped, 2 warnings`. The skips are the documented
  opt-in Gemini live tests.
- `python -m compileall -q src main.py` — passed.
- `git diff --check` — passed.

## Commit

Initial implementation commit message: `feat: record append only visual attempts`.
Review-hardening commits and the final migration/invariant commit SHAs are
reported in the agent handoff.

## Remaining risks

The illustrative plan snippet passes a hash-only `result_sha256` without a result
reference. The implementation follows the controller ruling that sanitized result
reference and hash fields must be paired and that recorded results require a
configured result root; hash-only terminal events are therefore rejected.
