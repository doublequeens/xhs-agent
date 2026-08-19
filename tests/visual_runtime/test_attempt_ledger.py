from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import src.visual_runtime.attempt_ledger as ledger_module
from src.schemas.v4.runtime import (
    AttemptFinished,
    AttemptProjection,
    AttemptReconciled,
    AttemptStarted,
    canonical_json,
)
from src.run_registry import RunRegistry
from src.visual_runtime.attempt_ledger import AttemptLedger, AttemptLedgerError


UTC = timezone.utc


def make_attempt(
    *,
    candidate_id: str = "candidate-1",
    attempt_number: int = 1,
    request_fingerprint: str = "f" * 64,
) -> AttemptStarted:
    # Keep the fixture in the past relative to either local or UTC wall-clock
    # time; the ledger enforces terminal-event causality against this instant.
    started_at = datetime(2020, 8, 20, 1, 2, 3, 456789, tzinfo=UTC)
    return AttemptStarted(
        run_id="run-1",
        workflow_version="llm_scene_v4",
        run_mode="production",
        candidate_id=candidate_id,
        revision_id="revision-1",
        parent_revision_id=None,
        node="visual_director",
        page_ids=("page-1", "page-2"),
        operation_kind="structured_request",
        attempt_number=attempt_number,
        request_fingerprint=request_fingerprint,
        started_at=started_at,
        deadline_at=started_at + timedelta(seconds=90),
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def test_attempt_events_are_append_only(tmp_path: Path):
    ledger = AttemptLedger(tmp_path / "agent_runs.sqlite")
    try:
        started = ledger.start(make_attempt())
        finished = ledger.finish(started.attempt_id, status="SUCCESS")

        assert [type(event).__name__ for event in ledger.events(started.attempt_id)] == [
            "AttemptStarted",
            "AttemptFinished",
        ]
        assert finished.status == "SUCCESS"
        assert started.sequence is not None
        assert finished.sequence is not None
        assert started.sequence < finished.sequence
    finally:
        ledger.close()


def test_start_generates_unique_collision_resistant_ids_and_keeps_identity(tmp_path: Path):
    ledger = AttemptLedger(tmp_path / "agent_runs.sqlite")
    try:
        first = ledger.start(make_attempt())
        second = ledger.start(make_attempt(attempt_number=2))

        assert first.attempt_id
        assert first.attempt_id != second.attempt_id
        assert first.run_id == "run-1"
        assert first.page_ids == ("page-1", "page-2")
        assert first.workflow_version == "llm_scene_v4"
    finally:
        ledger.close()


def test_open_attempt_is_reconciled_and_consumes_budget_once(tmp_path: Path):
    ledger = AttemptLedger(tmp_path / "agent_runs.sqlite")
    try:
        started = ledger.start(make_attempt())

        first = ledger.reconcile_open_attempts(run_id="run-1")
        second = ledger.reconcile_open_attempts(run_id="run-1")

        assert [event.status for event in first] == ["UNKNOWN_AFTER_CRASH"]
        assert second == []
        assert ledger.projection(started.attempt_id).status == "UNKNOWN_AFTER_CRASH"
        assert ledger.consumed_attempts("run-1", "candidate-1") == 1
        assert len(ledger.events(started.attempt_id)) == 2
    finally:
        ledger.close()


def test_reconcile_is_safe_when_finish_races_it(tmp_path: Path):
    database = tmp_path / "agent_runs.sqlite"
    creator = AttemptLedger(database)
    started = creator.start(make_attempt())
    creator.close()

    def finish() -> object:
        ledger = AttemptLedger(database)
        try:
            return ledger.finish(started.attempt_id, status="SUCCESS")
        except AttemptLedgerError:
            return None
        finally:
            ledger.close()

    def reconcile() -> list[object]:
        ledger = AttemptLedger(database)
        try:
            return ledger.reconcile_open_attempts(run_id="run-1")
        finally:
            ledger.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        finish_result, reconcile_result = list(
            executor.map(lambda operation: operation(), (finish, reconcile))
        )

    ledger = AttemptLedger(database)
    try:
        terminal_events = ledger.events(started.attempt_id)[1:]
        assert len(terminal_events) == 1
        assert terminal_events[0].status in {"SUCCESS", "UNKNOWN_AFTER_CRASH"}
        assert (finish_result is None) == bool(reconcile_result)
    finally:
        ledger.close()


def test_direct_update_and_delete_are_rejected_by_database_triggers(tmp_path: Path):
    database = tmp_path / "agent_runs.sqlite"
    ledger = AttemptLedger(database)
    started = ledger.start(make_attempt())
    connection = ledger._connection
    try:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE visual_attempt_events SET payload_json = ? WHERE attempt_id = ?",
                ("{}", started.attempt_id),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM visual_attempt_events WHERE attempt_id = ?",
                (started.attempt_id,),
            )
        assert len(ledger.events(started.attempt_id)) == 1
    finally:
        ledger.close()


def test_external_explicit_sequence_cannot_replace_or_insert_history(tmp_path: Path):
    database = tmp_path / "agent_runs.sqlite"
    ledger = AttemptLedger(database)
    try:
        started = ledger.start(make_attempt())
        payload_json = json.dumps(
            started.model_dump(mode="json", exclude={"sequence"}),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for sequence in (started.sequence, 999):
            with pytest.raises(sqlite3.IntegrityError, match="database-assigned"):
                ledger.connection.execute(
                    "INSERT OR REPLACE INTO visual_attempt_events "
                    "(sequence, attempt_id, event_kind, payload_json) VALUES (?, ?, ?, ?)",
                    (sequence, started.attempt_id, "AttemptStarted", payload_json),
                )
        assert ledger.events(started.attempt_id) == [started]
    finally:
        ledger.close()


def test_ledger_uses_full_synchronous_durability(tmp_path: Path):
    ledger = AttemptLedger(tmp_path / "agent_runs.sqlite")
    try:
        assert ledger.connection.execute("PRAGMA synchronous").fetchone()[0] == 2
    finally:
        ledger.close()


def test_persisted_payload_is_canonical_json_and_sequence_is_global(tmp_path: Path):
    database = tmp_path / "agent_runs.sqlite"
    ledger = AttemptLedger(database)
    try:
        started = ledger.start(
            make_attempt(candidate_id="候选-一", request_fingerprint="a" * 64)
        )
        finished = ledger.finish(started.attempt_id, status="SUCCESS")
        rows = ledger._connection.execute(
            "SELECT sequence, event_kind, payload_json FROM visual_attempt_events "
            "ORDER BY sequence"
        ).fetchall()

        assert [row[0] for row in rows] == [started.sequence, finished.sequence]
        for row, event in zip(rows, ledger.events(started.attempt_id), strict=True):
            payload = json.loads(row[2])
            expected = json.dumps(
                event.model_dump(mode="json", exclude={"sequence"}),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            assert row[2] == expected
            assert row[2] == json.dumps(
                json.loads(row[2]),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if isinstance(event, AttemptStarted):
                assert payload["run_id"] == "run-1"
    finally:
        ledger.close()


def test_projection_replays_terminal_event_without_mutating_start(tmp_path: Path):
    ledger = AttemptLedger(tmp_path / "agent_runs.sqlite")
    try:
        started = ledger.start(make_attempt())
        finished = ledger.finish(
            started.attempt_id,
            status="SCHEMA_INVALID",
            error_class="SchemaValidationError",
            latency_ms=42,
            token_usage={"input_tokens": 10, "output_tokens": 3},
        )

        projection = ledger.projection(started.attempt_id)
        assert isinstance(projection, AttemptProjection)
        assert projection.status == "SCHEMA_INVALID"
        assert projection.attempt_number == 1
        assert projection.request_fingerprint == "f" * 64
        assert projection.error_class == "SchemaValidationError"
        assert projection.latency_ms == 42
        assert projection.token_usage == {"input_tokens": 10, "output_tokens": 3}
        assert projection.completed_at == finished.completed_at
        assert ledger.events(started.attempt_id)[0] == started
    finally:
        ledger.close()


def test_duplicate_terminal_and_unknown_attempt_fail_without_appending(tmp_path: Path):
    ledger = AttemptLedger(tmp_path / "agent_runs.sqlite")
    try:
        started = ledger.start(make_attempt())
        ledger.finish(started.attempt_id, status="SUCCESS")
        before = len(ledger.events(started.attempt_id))

        with pytest.raises(AttemptLedgerError, match="terminal"):
            ledger.finish(started.attempt_id, status="TRANSPORT_FATAL")
        with pytest.raises(AttemptLedgerError, match="terminal"):
            ledger.reconcile_attempt(started.attempt_id)
        with pytest.raises(AttemptLedgerError, match="unknown"):
            ledger.finish("missing-attempt", status="SUCCESS")
        with pytest.raises(AttemptLedgerError, match="unknown"):
            ledger.reconcile_attempt("missing-attempt")

        assert len(ledger.events(started.attempt_id)) == before
    finally:
        ledger.close()


def test_hash_only_or_reference_only_result_is_rejected_without_append(tmp_path: Path):
    result_root = tmp_path / "results"
    result_root.mkdir()
    result_file = result_root / "result.json"
    result_file.write_text("result", encoding="utf-8")
    result_hash = sha256_bytes(result_file.read_bytes())
    ledger = AttemptLedger(tmp_path / "agent_runs.sqlite", result_root=result_root)
    try:
        for kwargs in (
            {"sanitized_result_sha256": result_hash},
            {"sanitized_result_ref": "result.json"},
        ):
            started = ledger.start(make_attempt(attempt_number=len(ledger.events()) + 1))
            with pytest.raises(AttemptLedgerError, match="paired"):
                ledger.finish(started.attempt_id, status="SUCCESS", **kwargs)
            assert ledger.events(started.attempt_id) == [started]
    finally:
        ledger.close()


def test_runtime_models_are_frozen_strict_and_reject_invalid_terminal_shapes():
    started = make_attempt()
    with pytest.raises((TypeError, ValueError)):
        started.run_id = "other"  # type: ignore[misc]
    with pytest.raises(ValueError):
        AttemptStarted.model_validate(
            {**started.model_dump(), "unexpected": "field"}
        )
    with pytest.raises(ValueError):
        AttemptFinished(
            attempt_id="attempt-1",
            status="UNKNOWN_AFTER_CRASH",
            completed_at=datetime.now(UTC),
        )
    with pytest.raises(ValueError):
        AttemptReconciled(
            attempt_id="attempt",
            reconciled_at=datetime.now(UTC).replace(tzinfo=None),
            evidence="crash",
        )


def test_result_success_requires_contained_file_and_hash_verified_reuse(tmp_path: Path):
    result_root = tmp_path / "results"
    result_root.mkdir()
    result_file = result_root / "nested" / "result.json"
    result_file.parent.mkdir()
    result_file.write_bytes("结果\n".encode("utf-8"))
    result_hash = sha256_bytes(result_file.read_bytes())
    ledger = AttemptLedger(tmp_path / "agent_runs.sqlite", result_root=result_root)
    try:
        started = ledger.start(make_attempt())
        ledger.finish(
            started.attempt_id,
            status="SUCCESS",
            sanitized_result_ref="nested/result.json",
            sanitized_result_sha256=result_hash,
        )

        reusable = ledger.reusable_result("f" * 64)
        assert reusable is not None
        assert reusable.attempt_id == started.attempt_id
        assert reusable.result_ref == "nested/result.json"
        assert reusable.result_sha256 == result_hash
        assert reusable.content == result_file.read_bytes()
        assert not hasattr(reusable, "path")
    finally:
        ledger.close()


def test_final_path_swap_to_symlink_fails_closed_before_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    result_root = tmp_path / "results"
    result_root.mkdir()
    result_file = result_root / "result.json"
    result_file.write_bytes(b"safe")
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"outside")
    ledger = AttemptLedger(tmp_path / "agent_runs.sqlite", result_root=result_root)
    real_open = os.open
    swapped = False

    def swap_before_final_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if not swapped and kwargs.get("dir_fd") is not None and os.fspath(path) == "result.json":
            result_file.unlink()
            result_file.symlink_to(outside)
            swapped = True
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(ledger_module.os, "open", swap_before_final_open)
    try:
        started = ledger.start(make_attempt())
        with pytest.raises(AttemptLedgerError):
            ledger.finish(
                started.attempt_id,
                status="SUCCESS",
                sanitized_result_ref="result.json",
                sanitized_result_sha256=sha256_bytes(b"safe"),
            )
        assert ledger.events(started.attempt_id) == [started]
    finally:
        ledger.close()


def test_ancestor_swap_after_open_keeps_read_on_original_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    result_root = tmp_path / "results"
    result_root.mkdir()
    nested = result_root / "nested"
    nested.mkdir()
    result_file = nested / "result.json"
    result_file.write_bytes(b"safe")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "result.json").write_bytes(b"outside")
    ledger = AttemptLedger(tmp_path / "agent_runs.sqlite", result_root=result_root)
    real_open = os.open
    swapped = False
    swap_enabled = False

    def swap_after_nested_open(path, flags, *args, **kwargs):
        nonlocal swapped
        fd = real_open(path, flags, *args, **kwargs)
        if (
            swap_enabled
            and not swapped
            and kwargs.get("dir_fd") is not None
            and os.fspath(path) == "nested"
        ):
            nested.rename(result_root / "nested-original")
            nested.symlink_to(outside, target_is_directory=True)
            swapped = True
        return fd

    monkeypatch.setattr(ledger_module.os, "open", swap_after_nested_open)
    try:
        started = ledger.start(make_attempt())
        ledger.finish(
            started.attempt_id,
            status="SUCCESS",
            sanitized_result_ref="nested/result.json",
            sanitized_result_sha256=sha256_bytes(b"safe"),
        )
        swap_enabled = True
        reusable = ledger.reusable_result("f" * 64)
        assert reusable is not None
        assert reusable.content == b"safe"
    finally:
        ledger.close()


@pytest.mark.parametrize(
    "reference",
    [
        "/tmp/result.json",
        "../result.json",
        "nested/../../result.json",
        "nested\\result.json",
        "",
    ],
)
def test_result_reference_rejects_absolute_dotdot_and_non_posix_paths(
    tmp_path: Path, reference: str
):
    result_root = tmp_path / "results"
    result_root.mkdir()
    ledger = AttemptLedger(tmp_path / "agent_runs.sqlite", result_root=result_root)
    try:
        started = ledger.start(make_attempt())
        with pytest.raises(AttemptLedgerError):
            ledger.finish(
                started.attempt_id,
                status="SUCCESS",
                sanitized_result_ref=reference,
                sanitized_result_sha256="a" * 64,
            )
        assert ledger.events(started.attempt_id) == [started]
    finally:
        ledger.close()


def test_result_reference_rejects_symlink_non_file_and_missing_root(tmp_path: Path):
    result_root = tmp_path / "results"
    result_root.mkdir()
    target = tmp_path / "outside.json"
    target.write_text("outside", encoding="utf-8")
    (result_root / "link.json").symlink_to(target)
    (result_root / "directory").mkdir()
    ledger = AttemptLedger(tmp_path / "agent_runs.sqlite", result_root=result_root)
    try:
        for reference in ("link.json", "directory", "missing.json"):
            started = ledger.start(make_attempt(attempt_number=len(ledger.events()) + 1))
            with pytest.raises(AttemptLedgerError):
                ledger.finish(
                    started.attempt_id,
                    status="SUCCESS",
                    sanitized_result_ref=reference,
                    sanitized_result_sha256="a" * 64,
                )
    finally:
        ledger.close()

    no_root = AttemptLedger(tmp_path / "no-root.sqlite")
    try:
        started = no_root.start(make_attempt())
        with pytest.raises(AttemptLedgerError, match="result_root"):
            no_root.finish(
                started.attempt_id,
                status="SUCCESS",
                sanitized_result_ref="result.json",
                sanitized_result_sha256="a" * 64,
            )
    finally:
        no_root.close()


def test_tampered_or_missing_result_is_not_reusable(tmp_path: Path):
    result_root = tmp_path / "results"
    result_root.mkdir()
    result_file = result_root / "result.json"
    result_file.write_text("original", encoding="utf-8")
    result_hash = sha256_bytes(result_file.read_bytes())
    ledger = AttemptLedger(tmp_path / "agent_runs.sqlite", result_root=result_root)
    try:
        started = ledger.start(make_attempt())
        ledger.finish(
            started.attempt_id,
            status="SUCCESS",
            sanitized_result_ref="result.json",
            sanitized_result_sha256=result_hash,
        )
        assert ledger.reusable_result("f" * 64) is not None
        result_file.write_text("tampered", encoding="utf-8")
        assert ledger.reusable_result("f" * 64) is None
        result_file.unlink()
        assert ledger.reusable_result("f" * 64) is None
    finally:
        ledger.close()


def test_failure_result_is_never_reused(tmp_path: Path):
    result_root = tmp_path / "results"
    result_root.mkdir()
    result_file = result_root / "failed.json"
    result_file.write_text("failure artifact", encoding="utf-8")
    result_hash = sha256_bytes(result_file.read_bytes())
    ledger = AttemptLedger(tmp_path / "agent_runs.sqlite", result_root=result_root)
    try:
        started = ledger.start(make_attempt())
        ledger.finish(
            started.attempt_id,
            status="TRANSPORT_FATAL",
            sanitized_result_ref="failed.json",
            sanitized_result_sha256=result_hash,
        )
        assert ledger.reusable_result("f" * 64) is None
    finally:
        ledger.close()


def test_scoped_queries_ignore_unrelated_malformed_history(tmp_path: Path):
    database = tmp_path / "agent_runs.sqlite"
    result_root = tmp_path / "results"
    result_root.mkdir()
    result_file = result_root / "result.json"
    result_file.write_bytes(b"safe")
    result_hash = sha256_bytes(b"safe")
    ledger = AttemptLedger(database, result_root=result_root)
    try:
        target = ledger.start(make_attempt())
        ledger.finish(
            target.attempt_id,
            status="SUCCESS",
            sanitized_result_ref="result.json",
            sanitized_result_sha256=result_hash,
        )
        other = make_attempt(
            candidate_id="other-candidate", request_fingerprint="e" * 64
        ).model_copy(update={"run_id": "other-run"})
        ledger.connection.execute(
            "INSERT INTO visual_attempt_events "
            "(attempt_id, event_kind, payload_json, run_id, candidate_id, request_fingerprint) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "malformed-other",
                "AttemptStarted",
                "{not-json",
                other.run_id,
                other.candidate_id,
                other.request_fingerprint,
            ),
        )
        ledger.connection.commit()

        assert ledger.consumed_attempts("run-1", "candidate-1") == 1
        assert ledger.reusable_result("f" * 64) is not None
        reconciled = ledger.reconcile_open_attempts(run_id="run-1")
        assert [event.attempt_id for event in reconciled] == []
    finally:
        ledger.close()


def test_scoped_query_indexes_cover_run_candidate_and_fingerprint(tmp_path: Path):
    ledger = AttemptLedger(tmp_path / "agent_runs.sqlite")
    try:
        indexes = {
            row[1]
            for row in ledger.connection.execute(
                "PRAGMA index_list(visual_attempt_events)"
            )
        }
        assert "idx_visual_attempt_events_run_candidate" in indexes
        assert "idx_visual_attempt_events_fingerprint" in indexes
        run_plan = ledger.connection.execute(
            "EXPLAIN QUERY PLAN SELECT attempt_id FROM visual_attempt_events "
            "WHERE event_kind = 'AttemptStarted' AND run_id = ? AND candidate_id = ?",
            ("run-1", "candidate-1"),
        ).fetchall()
        fingerprint_plan = ledger.connection.execute(
            "EXPLAIN QUERY PLAN SELECT attempt_id FROM visual_attempt_events "
            "WHERE event_kind = 'AttemptStarted' AND request_fingerprint = ?",
            ("f" * 64,),
        ).fetchall()
        assert any("idx_visual_attempt_events_run_candidate" in row[3] for row in run_plan)
        assert any("idx_visual_attempt_events_fingerprint" in row[3] for row in fingerprint_plan)
    finally:
        ledger.close()


def test_terminal_timestamps_must_not_precede_start(tmp_path: Path):
    ledger = AttemptLedger(tmp_path / "agent_runs.sqlite")
    try:
        started = ledger.start(make_attempt())
        before = started.started_at - timedelta(microseconds=1)
        with pytest.raises(AttemptLedgerError, match="completed_at"):
            ledger.finish(started.attempt_id, status="SUCCESS", completed_at=before)
        with pytest.raises(AttemptLedgerError, match="reconciled_at"):
            ledger.reconcile_attempt(started.attempt_id, reconciled_at=before)
        assert ledger.events(started.attempt_id) == [started]
    finally:
        ledger.close()


def test_replay_rejects_terminal_timestamp_before_start(tmp_path: Path):
    database = tmp_path / "agent_runs.sqlite"
    ledger = AttemptLedger(database)
    started = ledger.start(make_attempt())
    finished = AttemptFinished(
        attempt_id=started.attempt_id,
        completed_at=started.started_at - timedelta(seconds=1),
        status="SUCCESS",
    )
    payload_json = json.dumps(
        finished.model_dump(mode="json", exclude={"sequence"}),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    ledger.connection.execute(
        "INSERT INTO visual_attempt_events "
        "(attempt_id, event_kind, payload_json, run_id, candidate_id, request_fingerprint) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            started.attempt_id,
            "AttemptFinished",
            payload_json,
            started.run_id,
            started.candidate_id,
            started.request_fingerprint,
        ),
    )
    ledger.connection.commit()
    try:
        with pytest.raises(AttemptLedgerError, match="completed_at"):
            ledger.projection(started.attempt_id)
    finally:
        ledger.close()


@pytest.mark.parametrize(
    "token_usage",
    [
        {},
        {"": 1},
        {"input_tokens": -1},
        {"input_tokens": 1.5},
        {"input_tokens": math.nan},
        {"input_tokens": math.inf},
        {"input_tokens": True},
    ],
)
def test_token_usage_is_nonempty_finite_nonnegative_integer_counts(token_usage):
    with pytest.raises(ValueError):
        AttemptFinished(
            attempt_id="attempt-1",
            completed_at=datetime.now(UTC),
            status="SUCCESS",
            token_usage=token_usage,
        )


def test_canonical_json_rejects_nonfinite_numbers():
    with pytest.raises(ValueError):
        canonical_json({"value": math.nan})


def test_non_json_reconciliation_evidence_fails_without_append(tmp_path: Path):
    ledger = AttemptLedger(tmp_path / "agent_runs.sqlite")
    try:
        started = ledger.start(make_attempt())
        with pytest.raises(AttemptLedgerError, match="serialize"):
            ledger.reconcile_attempt(started.attempt_id, evidence={"path": Path("x")})
        assert ledger.events(started.attempt_id) == [started]
    finally:
        ledger.close()


def test_result_root_resolution_errors_are_translated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    original_resolve = Path.resolve

    def fail_resolve(path, *args, **kwargs):
        if path.name == "results":
            raise OSError("resolve failed")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", fail_resolve)
    with pytest.raises(AttemptLedgerError, match="result_root"):
        AttemptLedger(tmp_path / "agent_runs.sqlite", result_root=tmp_path / "results")


def test_concurrent_wal_writers_have_strict_global_sequences_and_no_loss(tmp_path: Path):
    database = tmp_path / "agent_runs.sqlite"
    total = 24

    def write(index: int) -> tuple[int, int]:
        ledger = AttemptLedger(database)
        try:
            started = ledger.start(
                make_attempt(
                    candidate_id=f"candidate-{index}",
                    attempt_number=1,
                    request_fingerprint=f"{index:064x}",
                )
            )
            finished = ledger.finish(started.attempt_id, status="SUCCESS")
            return started.sequence or 0, finished.sequence or 0
        finally:
            ledger.close()

    with ThreadPoolExecutor(max_workers=8) as executor:
        sequences = list(executor.map(write, range(total)))

    ledger = AttemptLedger(database)
    try:
        rows = ledger._connection.execute(
            "SELECT sequence FROM visual_attempt_events ORDER BY sequence"
        ).fetchall()
        all_sequences = [row[0] for row in rows]
        assert len(all_sequences) == total * 2
        assert all_sequences == list(range(1, total * 2 + 1))
        assert len({sequence for pair in sequences for sequence in pair}) == total * 2
        assert sum(len(ledger.events(f"does-not-exist-{i}")) for i in range(2)) == 0
        assert sum(
            ledger.consumed_attempts("run-1", f"candidate-{i}") for i in range(total)
        ) == total
    finally:
        ledger.close()


def test_ledger_adds_only_its_table_to_an_existing_run_registry(tmp_path: Path):
    database = tmp_path / "agent_runs.sqlite"
    registry = RunRegistry(database)
    try:
        existing = registry.create_run("existing-thread", "既有任务")
        ledger = AttemptLedger(database)
        try:
            ledger.start(make_attempt())
        finally:
            ledger.close()
        unchanged = registry.get_by_thread_id("existing-thread")
        assert unchanged == existing
        tables = {
            row[0]
            for row in registry._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "agent_runs" in tables
        assert "visual_attempt_events" in tables
    finally:
        registry.close()


def test_replay_rejects_malformed_payload_with_context(tmp_path: Path):
    database = tmp_path / "agent_runs.sqlite"
    ledger = AttemptLedger(database)
    ledger.close()
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO visual_attempt_events(attempt_id, event_kind, payload_json) "
            "VALUES (?, ?, ?)",
            ("corrupt", "AttemptStarted", "{not-json"),
        )
        connection.commit()
    finally:
        connection.close()

    ledger = AttemptLedger(database)
    try:
        with pytest.raises(AttemptLedgerError, match="sequence 1.*AttemptStarted"):
            ledger.events("corrupt")
    finally:
        ledger.close()


def test_replay_rejects_payload_with_unknown_fields(tmp_path: Path):
    database = tmp_path / "agent_runs.sqlite"
    ledger = AttemptLedger(database)
    ledger.close()
    connection = sqlite3.connect(database)
    try:
        payload = make_attempt().model_dump(mode="json", exclude={"sequence"})
        payload["unexpected"] = "tampered"
        connection.execute(
            "INSERT INTO visual_attempt_events(attempt_id, event_kind, payload_json) "
            "VALUES (?, ?, ?)",
            ("corrupt", "AttemptStarted", json.dumps(payload)),
        )
        connection.commit()
    finally:
        connection.close()

    ledger = AttemptLedger(database)
    try:
        with pytest.raises(AttemptLedgerError, match="sequence 1.*AttemptStarted"):
            ledger.projection("corrupt")
    finally:
        ledger.close()
