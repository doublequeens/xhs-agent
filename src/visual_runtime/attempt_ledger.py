"""Append-only SQLite Attempt Ledger for visual-production v4.

The ledger is intentionally independent from LangGraph checkpoints.  It owns a
single additive table in the caller-provided database and reconstructs attempt
state by replaying immutable events.  A provider gateway can therefore commit a
start before doing work and append exactly one terminal event afterwards.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, TypeAlias
from uuid import uuid4

from pydantic import ValidationError

from src.schemas.v4.runtime import (
    AttemptFinished,
    AttemptProjection,
    AttemptReconciled,
    AttemptStarted,
    canonical_json,
)


Event: TypeAlias = AttemptStarted | AttemptFinished | AttemptReconciled
_EVENT_KINDS = {
    "AttemptStarted": AttemptStarted,
    "AttemptFinished": AttemptFinished,
    "AttemptReconciled": AttemptReconciled,
}
_TERMINAL_EVENT_KINDS = ("AttemptFinished", "AttemptReconciled")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AttemptLedgerError(RuntimeError):
    """Contextual error raised for invalid ledger state or durable I/O."""


@dataclass(frozen=True)
class ReusableResult:
    """A successful result whose path and bytes were verified at lookup time."""

    attempt_id: str
    request_fingerprint: str
    result_ref: str
    result_sha256: str
    content: bytes
    validated_contract_sha256: str | None = None

    @property
    def sanitized_result_ref(self) -> str:
        return self.result_ref

    @property
    def sanitized_result_sha256(self) -> str:
        return self.result_sha256

    @property
    def data(self) -> bytes:
        """Alias for consumers that call the verified bytes ``data``."""

        return self.content


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AttemptLedger:
    """Persist and replay append-only v4 visual attempt events."""

    def __init__(
        self,
        path: str | Path,
        *,
        result_root: str | Path | None = None,
        busy_timeout_ms: int = 5000,
    ) -> None:
        if busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be positive")
        self.path = Path(path)
        self.result_root: Path | None = None
        self.busy_timeout_ms = busy_timeout_ms
        self._connection: sqlite3.Connection | None = None
        try:
            if result_root is not None:
                self.result_root = Path(result_root).resolve()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(
                self.path,
                timeout=busy_timeout_ms / 1000,
                check_same_thread=False,
                isolation_level=None,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
            for attempt_number in range(8):
                try:
                    self._connection.execute("PRAGMA journal_mode=WAL")
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower() or attempt_number == 7:
                        raise
                    time.sleep(0.01 * (attempt_number + 1))
            self._connection.execute("PRAGMA synchronous=FULL")
            self._create_schema()
        except AttemptLedgerError:
            self.close()
            raise
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            self.close()
            raise AttemptLedgerError(f"could not initialize ledger {self.path}: {exc}") from exc

    def __enter__(self) -> "AttemptLedger":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def close(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is None:
            return
        try:
            connection.close()
        except sqlite3.Error as exc:
            raise AttemptLedgerError(f"could not close ledger {self.path}: {exc}") from exc

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the connection for diagnostics and read-only audits."""

        return self._require_connection()

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise AttemptLedgerError(f"ledger {self.path} is closed")
        return self._connection

    def _create_schema(self) -> None:
        connection = self._require_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS visual_attempt_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT CHECK (sequence > 0),
                    attempt_id TEXT NOT NULL,
                    event_kind TEXT NOT NULL CHECK (
                        event_kind IN ('AttemptStarted', 'AttemptFinished', 'AttemptReconciled')
                    ),
                    payload_json TEXT NOT NULL,
                    run_id TEXT,
                    candidate_id TEXT,
                    request_fingerprint TEXT
                )
                """
            )
            existing_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(visual_attempt_events)")
            }
            for column in ("run_id", "candidate_id", "request_fingerprint"):
                if column not in existing_columns:
                    connection.execute(
                        f"ALTER TABLE visual_attempt_events ADD COLUMN {column} TEXT"
                    )
            schema_statements = (
                """
                CREATE INDEX IF NOT EXISTS idx_visual_attempt_events_attempt
                    ON visual_attempt_events(attempt_id, sequence);
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_visual_attempt_events_kind_attempt
                    ON visual_attempt_events(event_kind, attempt_id, sequence);
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_visual_attempt_events_run_candidate
                    ON visual_attempt_events(event_kind, run_id, candidate_id, sequence, attempt_id);
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_visual_attempt_events_fingerprint
                    ON visual_attempt_events(event_kind, request_fingerprint, sequence, attempt_id);
                """,
                """
                CREATE TRIGGER IF NOT EXISTS visual_attempt_events_no_update
                BEFORE UPDATE ON visual_attempt_events
                BEGIN
                    SELECT RAISE(ABORT, 'visual attempt events are append-only');
                END;
                """,
                """
                CREATE TRIGGER IF NOT EXISTS visual_attempt_events_no_delete
                BEFORE DELETE ON visual_attempt_events
                BEGIN
                    SELECT RAISE(ABORT, 'visual attempt events are append-only');
                END;
                """,
                """
                CREATE TRIGGER IF NOT EXISTS visual_attempt_events_one_start
                BEFORE INSERT ON visual_attempt_events
                WHEN NEW.event_kind = 'AttemptStarted'
                    AND EXISTS (
                        SELECT 1 FROM visual_attempt_events
                        WHERE attempt_id = NEW.attempt_id
                          AND event_kind = 'AttemptStarted'
                    )
                BEGIN
                    SELECT RAISE(ABORT, 'attempt already has a start event');
                END;
                """,
                """
                CREATE TRIGGER IF NOT EXISTS visual_attempt_events_requires_start
                BEFORE INSERT ON visual_attempt_events
                WHEN NEW.event_kind IN ('AttemptFinished', 'AttemptReconciled')
                    AND NOT EXISTS (
                        SELECT 1 FROM visual_attempt_events
                        WHERE attempt_id = NEW.attempt_id
                          AND event_kind = 'AttemptStarted'
                    )
                BEGIN
                    SELECT RAISE(ABORT, 'terminal event requires a start event');
                END;
                """,
                """
                CREATE TRIGGER IF NOT EXISTS visual_attempt_events_one_terminal
                BEFORE INSERT ON visual_attempt_events
                WHEN NEW.event_kind IN ('AttemptFinished', 'AttemptReconciled')
                    AND EXISTS (
                        SELECT 1 FROM visual_attempt_events
                        WHERE attempt_id = NEW.attempt_id
                          AND event_kind IN ('AttemptFinished', 'AttemptReconciled')
                    )
                BEGIN
                    SELECT RAISE(ABORT, 'attempt already has a terminal event');
                END;
                """,
            )
            for statement in schema_statements:
                connection.execute(statement)
            # SQLite evaluates same-timing triggers in reverse creation order.
            # Install this guard last so an explicit sequence is rejected before
            # any event-kind trigger can report a misleading domain error.
            connection.execute(
                "DROP TRIGGER IF EXISTS visual_attempt_events_no_explicit_sequence"
            )
            connection.execute(
                """
                CREATE TRIGGER visual_attempt_events_no_explicit_sequence
                BEFORE INSERT ON visual_attempt_events
                WHEN NEW.sequence >= 0
                BEGIN
                    SELECT RAISE(ABORT, 'sequence is database-assigned');
                END
                """
            )
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            raise AttemptLedgerError(f"could not create ledger schema {self.path}: {exc}") from exc

    @contextmanager
    def _write_transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._require_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            try:
                connection.rollback()
            except sqlite3.Error:
                pass
            raise

    @staticmethod
    def _payload_for(event: Event) -> str:
        return canonical_json(event.model_dump(mode="python", exclude={"sequence"}))

    def _query_identity_for_event(self, event: Event) -> tuple[str, str, str]:
        if isinstance(event, AttemptStarted):
            return event.run_id, event.candidate_id, event.request_fingerprint
        try:
            row = self._require_connection().execute(
                "SELECT run_id, candidate_id, request_fingerprint "
                "FROM visual_attempt_events "
                "WHERE attempt_id = ? AND event_kind = 'AttemptStarted'",
                (event.attempt_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise AttemptLedgerError(
                f"could not read start identity for attempt {event.attempt_id}: {exc}"
            ) from exc
        if row is None:
            raise AttemptLedgerError(
                f"unknown attempt while appending {type(event).__name__}: {event.attempt_id}"
            )
        return str(row[0]), str(row[1]), str(row[2])

    @staticmethod
    def _event_with_sequence(event: Event, sequence: int) -> Event:
        return event.model_copy(update={"sequence": sequence})

    def _insert_event(self, event: Event) -> Event:
        connection = self._require_connection()
        try:
            payload_json = self._payload_for(event)
            run_id, candidate_id, request_fingerprint = self._query_identity_for_event(event)
        except AttemptLedgerError:
            raise
        except (TypeError, ValueError, OverflowError) as exc:
            raise AttemptLedgerError(
                f"could not serialize {type(event).__name__} for attempt "
                f"{event.attempt_id}: {exc}"
            ) from exc
        try:
            cursor = connection.execute(
                "INSERT INTO visual_attempt_events "
                "(attempt_id, event_kind, payload_json, run_id, candidate_id, request_fingerprint) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    event.attempt_id,
                    type(event).__name__,
                    payload_json,
                    run_id,
                    candidate_id,
                    request_fingerprint,
                ),
            )
            sequence = int(cursor.lastrowid)
        except sqlite3.Error as exc:
            raise AttemptLedgerError(
                f"could not append {type(event).__name__} for attempt "
                f"{event.attempt_id}: {exc}"
            ) from exc
        return self._event_with_sequence(event, sequence)

    def start(self, attempt: AttemptStarted | dict[str, Any]) -> AttemptStarted:
        if not isinstance(attempt, AttemptStarted):
            try:
                attempt = AttemptStarted.model_validate(attempt)
            except (TypeError, ValueError, ValidationError) as exc:
                raise AttemptLedgerError(f"start expects an AttemptStarted event: {exc}") from exc
        # The caller supplies identity, but the durable ledger owns attempt IDs.
        for _ in range(4):
            candidate = attempt.model_copy(update={"attempt_id": uuid4().hex, "sequence": None})
            try:
                with self._write_transaction():
                    persisted = self._insert_event(candidate)
                return persisted  # type: ignore[return-value]
            except AttemptLedgerError as exc:
                if "already has a start event" not in str(exc):
                    raise
            except sqlite3.Error as exc:
                raise AttemptLedgerError(
                    f"could not append AttemptStarted for attempt {candidate.attempt_id}: {exc}"
                ) from exc
        raise AttemptLedgerError("could not allocate a unique attempt_id")

    @staticmethod
    def _resolve_result_aliases(
        *,
        sanitized_result_ref: str | None,
        sanitized_result_sha256: str | None,
        result_ref: str | None,
        result_sha256: str | None,
    ) -> tuple[str | None, str | None]:
        if sanitized_result_ref is not None and result_ref is not None:
            raise AttemptLedgerError("result reference supplied twice")
        if sanitized_result_sha256 is not None and result_sha256 is not None:
            raise AttemptLedgerError("result sha256 supplied twice")
        return (
            sanitized_result_ref if sanitized_result_ref is not None else result_ref,
            sanitized_result_sha256
            if sanitized_result_sha256 is not None
            else result_sha256,
        )

    def finish(
        self,
        attempt_id: str,
        *,
        status: str,
        completed_at: datetime | None = None,
        error_class: str | None = None,
        provider_request_id: str | None = None,
        latency_ms: float | None = None,
        token_usage: dict[str, int | float] | None = None,
        sanitized_result_ref: str | None = None,
        sanitized_result_sha256: str | None = None,
        validated_contract_sha256: str | None = None,
        result_ref: str | None = None,
        result_sha256: str | None = None,
    ) -> AttemptFinished:
        sanitized_result_ref, sanitized_result_sha256 = self._resolve_result_aliases(
            sanitized_result_ref=sanitized_result_ref,
            sanitized_result_sha256=sanitized_result_sha256,
            result_ref=result_ref,
            result_sha256=result_sha256,
        )
        try:
            event = AttemptFinished(
                attempt_id=attempt_id,
                completed_at=completed_at or _utc_now(),
                status=status,
                error_class=error_class,
                provider_request_id=provider_request_id,
                latency_ms=latency_ms,
                token_usage=token_usage,
                sanitized_result_ref=sanitized_result_ref,
                sanitized_result_sha256=sanitized_result_sha256,
                validated_contract_sha256=validated_contract_sha256,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise AttemptLedgerError(f"invalid AttemptFinished for {attempt_id}: {exc}") from exc

        if event.sanitized_result_ref is not None:
            self._verify_result_file(
                event.sanitized_result_ref,
                event.sanitized_result_sha256 or "",
            )

        try:
            with self._write_transaction():
                projection = self._require_open_attempt(attempt_id)
                if event.completed_at < projection.started_at:
                    raise AttemptLedgerError(
                        f"completed_at must not precede started_at for attempt {attempt_id}"
                    )
                persisted = self._insert_event(event)
        except AttemptLedgerError:
            raise
        except sqlite3.Error as exc:
            raise AttemptLedgerError(
                f"could not append AttemptFinished for attempt {attempt_id}: {exc}"
            ) from exc
        return persisted  # type: ignore[return-value]

    def reconcile_attempt(
        self,
        attempt_id: str,
        *,
        evidence: str | dict[str, Any] = "open attempt during recovery",
        reconciled_at: datetime | None = None,
    ) -> AttemptReconciled:
        try:
            event = AttemptReconciled(
                attempt_id=attempt_id,
                reconciled_at=reconciled_at or _utc_now(),
                evidence=evidence,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise AttemptLedgerError(
                f"invalid AttemptReconciled for {attempt_id}: {exc}"
            ) from exc
        try:
            with self._write_transaction():
                projection = self._require_open_attempt(attempt_id)
                if event.reconciled_at < projection.started_at:
                    raise AttemptLedgerError(
                        f"reconciled_at must not precede started_at for attempt {attempt_id}"
                    )
                persisted = self._insert_event(event)
        except AttemptLedgerError:
            raise
        except sqlite3.Error as exc:
            raise AttemptLedgerError(
                f"could not append AttemptReconciled for attempt {attempt_id}: {exc}"
            ) from exc
        return persisted  # type: ignore[return-value]

    def reconcile_open_attempts(
        self,
        run_id: str,
        *,
        evidence: str | dict[str, Any] = "open attempt during recovery",
    ) -> list[AttemptReconciled]:
        if not run_id:
            raise AttemptLedgerError("run_id is required for reconciliation")
        persisted: list[AttemptReconciled] = []
        try:
            with self._write_transaction():
                rows = self._require_connection().execute(
                    """
                    SELECT start.sequence, start.attempt_id, start.event_kind,
                           start.payload_json, start.run_id, start.candidate_id,
                           start.request_fingerprint
                    FROM visual_attempt_events AS start
                    WHERE start.event_kind = 'AttemptStarted'
                      AND start.run_id = ?
                      AND NOT EXISTS (
                          SELECT 1
                          FROM visual_attempt_events AS terminal
                          WHERE terminal.attempt_id = start.attempt_id
                            AND terminal.event_kind IN ('AttemptFinished', 'AttemptReconciled')
                      )
                    ORDER BY start.sequence
                    """,
                    (run_id,),
                ).fetchall()
                for row in rows:
                    attempt_id = str(row[1])
                    projection = self._project_events(
                        attempt_id,
                        self._events_for_attempt(attempt_id),
                    )
                    if projection.status != "RUNNING":
                        continue
                    event = AttemptReconciled(
                        attempt_id=attempt_id,
                        reconciled_at=_utc_now(),
                        evidence=evidence,
                    )
                    if event.reconciled_at < projection.started_at:
                        raise AttemptLedgerError(
                            f"reconciled_at must not precede started_at for attempt {attempt_id}"
                        )
                    persisted.append(self._insert_event(event))  # type: ignore[arg-type]
        except AttemptLedgerError:
            raise
        except (sqlite3.Error, TypeError, ValueError, ValidationError) as exc:
            raise AttemptLedgerError(
                f"could not reconcile open attempts for run {run_id}: {exc}"
            ) from exc
        return [event for event in persisted if isinstance(event, AttemptReconciled)]

    def _require_open_attempt(self, attempt_id: str) -> AttemptProjection:
        events = self._events_for_attempt(attempt_id)
        if not events:
            raise AttemptLedgerError(f"unknown attempt: {attempt_id}")
        projection = self._project_events(attempt_id, events)
        if projection.status != "RUNNING":
            raise AttemptLedgerError(
                f"attempt {attempt_id} already has terminal status {projection.status}"
            )
        return projection

    def _events_for_attempt(self, attempt_id: str) -> list[Event]:
        try:
            connection = self._require_connection()
            rows = connection.execute(
                "SELECT sequence, attempt_id, event_kind, payload_json, "
                "run_id, candidate_id, request_fingerprint "
                "FROM visual_attempt_events WHERE attempt_id = ? ORDER BY sequence",
                (attempt_id,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise AttemptLedgerError(
                f"could not read events for attempt {attempt_id}: {exc}"
            ) from exc
        return self._replay_rows(rows)

    def events(self, attempt_id: str | None = None) -> list[Event]:
        try:
            connection = self._require_connection()
            if attempt_id is None:
                rows = connection.execute(
                    "SELECT sequence, attempt_id, event_kind, payload_json, "
                    "run_id, candidate_id, request_fingerprint "
                    "FROM visual_attempt_events ORDER BY sequence"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT sequence, attempt_id, event_kind, payload_json, "
                    "run_id, candidate_id, request_fingerprint "
                    "FROM visual_attempt_events WHERE attempt_id = ? ORDER BY sequence",
                    (attempt_id,),
                ).fetchall()
        except sqlite3.Error as exc:
            subject = "all attempts" if attempt_id is None else f"attempt {attempt_id}"
            raise AttemptLedgerError(f"could not read events for {subject}: {exc}") from exc
        return self._replay_rows(rows)

    def _replay_rows(self, rows: list[sqlite3.Row] | list[tuple[Any, ...]]) -> list[Event]:
        replayed: list[Event] = []
        row_metadata: list[tuple[str, str, str]] = []
        previous_sequence = 0
        for row in rows:
            sequence = int(row[0])
            row_attempt_id = str(row[1])
            event_kind = str(row[2])
            raw_payload = row[3]
            if len(row) < 7:
                raise AttemptLedgerError(
                    f"invalid event sequence {sequence} ({event_kind}) for "
                    f"attempt {row_attempt_id}: missing query identity columns"
                )
            query_identity = (row[4], row[5], row[6])
            if sequence <= previous_sequence:
                raise AttemptLedgerError(
                    f"invalid event sequence {sequence}: sequence is not increasing"
                )
            previous_sequence = sequence
            model_type = _EVENT_KINDS.get(event_kind)
            if model_type is None:
                raise AttemptLedgerError(
                    f"invalid event sequence {sequence} ({event_kind}): unknown event kind"
                )
            try:
                if not isinstance(raw_payload, str):
                    raise ValueError("payload_json must be text")
                payload = json.loads(raw_payload)
                if not isinstance(payload, dict):
                    raise ValueError("payload must be a JSON object")
                expected_json = canonical_json(payload)
                if raw_payload != expected_json:
                    raise ValueError("payload is not canonical JSON")
                event = model_type.model_validate_json(
                    canonical_json({**payload, "sequence": sequence})
                )
                if event.attempt_id != row_attempt_id:
                    raise ValueError("row attempt_id does not match payload attempt_id")
            except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
                raise AttemptLedgerError(
                    f"invalid event sequence {sequence} ({event_kind}) for "
                    f"attempt {row_attempt_id}: {exc}"
                ) from exc
            replayed.append(event)  # type: ignore[arg-type]
            row_metadata.append(query_identity)

        starts_by_attempt = {
            event.attempt_id: event
            for event in replayed
            if isinstance(event, AttemptStarted)
        }
        for event, query_identity in zip(replayed, row_metadata, strict=True):
            start = starts_by_attempt.get(event.attempt_id)
            if start is None:
                raise AttemptLedgerError(
                    f"invalid replay for attempt {event.attempt_id}: "
                    "terminal event has no start identity"
                )
            expected_identity = (
                start.run_id,
                start.candidate_id,
                start.request_fingerprint,
            )
            if query_identity != expected_identity:
                raise AttemptLedgerError(
                    f"invalid replay for attempt {event.attempt_id}: "
                    "query identity does not match start payload"
                )
        return replayed

    @staticmethod
    def _project_events(attempt_id: str, events: list[Event]) -> AttemptProjection:
        if not events:
            raise AttemptLedgerError(f"unknown attempt: {attempt_id}")
        starts = [event for event in events if isinstance(event, AttemptStarted)]
        terminals = [
            event
            for event in events
            if isinstance(event, (AttemptFinished, AttemptReconciled))
        ]
        if len(starts) != 1:
            raise AttemptLedgerError(
                f"invalid replay for attempt {attempt_id}: expected one start, got {len(starts)}"
            )
        start = starts[0]
        if start.attempt_id != attempt_id:
            raise AttemptLedgerError(f"invalid replay for attempt {attempt_id}: ID mismatch")
        if len(terminals) > 1:
            raise AttemptLedgerError(
                f"invalid replay for attempt {attempt_id}: multiple terminal events"
            )
        terminal = terminals[0] if terminals else None
        if terminal is not None:
            if start.sequence is None or terminal.sequence is None:
                raise AttemptLedgerError(
                    f"invalid replay for attempt {attempt_id}: missing event sequence"
                )
            if terminal.sequence <= start.sequence:
                raise AttemptLedgerError(
                    f"invalid replay for attempt {attempt_id}: terminal sequence "
                    "must follow start sequence"
                )
            if isinstance(terminal, AttemptFinished):
                if terminal.completed_at < start.started_at:
                    raise AttemptLedgerError(
                        f"invalid replay for attempt {attempt_id}: completed_at "
                        "must not precede started_at"
                    )
            elif terminal.reconciled_at < start.started_at:
                raise AttemptLedgerError(
                    f"invalid replay for attempt {attempt_id}: reconciled_at "
                    "must not precede started_at"
                )
        values: dict[str, Any] = {
            **start.model_dump(mode="python", exclude={"sequence"}),
            "status": "RUNNING",
            "start_sequence": start.sequence,
            "terminal_sequence": None,
        }
        if isinstance(terminal, AttemptFinished):
            values.update(
                {
                    **terminal.model_dump(mode="python", exclude={"attempt_id", "sequence"}),
                    "status": terminal.status,
                    "terminal_sequence": terminal.sequence,
                }
            )
        elif isinstance(terminal, AttemptReconciled):
            values.update(
                {
                    "status": terminal.status,
                    "reconciled_at": terminal.reconciled_at,
                    "evidence": terminal.evidence,
                    "terminal_sequence": terminal.sequence,
                }
            )
        values.pop("sequence", None)
        try:
            return AttemptProjection.model_validate(values)
        except (TypeError, ValueError, ValidationError) as exc:
            raise AttemptLedgerError(
                f"invalid replay projection for attempt {attempt_id}: {exc}"
            ) from exc

    def projection(self, attempt_id: str) -> AttemptProjection:
        return self._project_events(attempt_id, self._events_for_attempt(attempt_id))

    def consumed_attempts(self, run_id: str, candidate_id: str) -> int:
        if not run_id or not candidate_id:
            raise AttemptLedgerError("run_id and candidate_id are required")
        try:
            rows = self._require_connection().execute(
                """
                SELECT sequence, attempt_id, event_kind, payload_json,
                       run_id, candidate_id, request_fingerprint
                FROM visual_attempt_events
                WHERE event_kind = 'AttemptStarted'
                  AND run_id = ?
                  AND candidate_id = ?
                ORDER BY sequence
                """,
                (run_id, candidate_id),
            ).fetchall()
        except sqlite3.Error as exc:
            raise AttemptLedgerError(
                f"could not count attempts for run {run_id}, candidate {candidate_id}: {exc}"
            ) from exc
        return sum(isinstance(event, AttemptStarted) for event in self._replay_rows(rows))

    @staticmethod
    def _normalize_result_ref(reference: str) -> str:
        if not reference or "\\" in reference:
            raise AttemptLedgerError("result reference must be a non-empty POSIX path")
        path = PurePosixPath(reference)
        if path.is_absolute() or ".." in path.parts:
            raise AttemptLedgerError("result reference escapes result_root")
        parts = [part for part in path.parts if part not in {"", "."}]
        if not parts:
            raise AttemptLedgerError("result reference must name a file")
        return PurePosixPath(*parts).as_posix()

    def _read_verified_result(self, reference: str, expected_sha256: str) -> tuple[str, bytes]:
        normalized = self._normalize_result_ref(reference)
        if self.result_root is None:
            raise AttemptLedgerError("result_root is required for result references")
        root = self.result_root
        directory_flag = getattr(os, "O_DIRECTORY", 0)
        no_follow_flag = getattr(os, "O_NOFOLLOW", 0)
        close_on_exec_flag = getattr(os, "O_CLOEXEC", 0)
        root_fd = -1
        current_fd = -1
        result_fd = -1
        try:
            root_fd = os.open(
                root,
                os.O_RDONLY | directory_flag | no_follow_flag | close_on_exec_flag,
            )
            current_fd = root_fd
            if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
                raise AttemptLedgerError(f"result_root is not an existing directory: {root}")

            parts = PurePosixPath(normalized).parts
            for part in parts[:-1]:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | directory_flag | no_follow_flag | close_on_exec_flag,
                    dir_fd=current_fd,
                )
                if current_fd != root_fd:
                    os.close(current_fd)
                current_fd = next_fd

            result_fd = os.open(
                parts[-1],
                os.O_RDONLY | no_follow_flag | close_on_exec_flag,
                dir_fd=current_fd,
            )
            if not stat.S_ISREG(os.fstat(result_fd).st_mode):
                raise AttemptLedgerError("result reference must identify a regular file")

            chunks: list[bytes] = []
            while True:
                chunk = os.read(result_fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            content = b"".join(chunks)
            actual_sha256 = hashlib.sha256(content).hexdigest()
            if not _SHA256_RE.fullmatch(expected_sha256) or actual_sha256 != expected_sha256:
                raise AttemptLedgerError("result reference sha256 does not match bytes")
            return normalized, content
        finally:
            if result_fd >= 0:
                os.close(result_fd)
            if current_fd >= 0 and current_fd != root_fd:
                os.close(current_fd)
            if root_fd >= 0:
                os.close(root_fd)

    def _verify_result_file(self, reference: str, expected_sha256: str) -> tuple[str, bytes]:
        try:
            return self._read_verified_result(reference, expected_sha256)
        except AttemptLedgerError:
            raise
        except (OSError, ValueError) as exc:
            raise AttemptLedgerError(f"could not verify result reference {reference}: {exc}") from exc

    def reusable_result(self, request_fingerprint: str) -> ReusableResult | None:
        if not _SHA256_RE.fullmatch(request_fingerprint):
            return None
        try:
            rows = self._require_connection().execute(
                """
                SELECT sequence, attempt_id, event_kind, payload_json,
                       run_id, candidate_id, request_fingerprint
                FROM visual_attempt_events
                WHERE event_kind = 'AttemptStarted'
                  AND request_fingerprint = ?
                ORDER BY sequence DESC
                """,
                (request_fingerprint,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise AttemptLedgerError(
                f"could not find reusable result for fingerprint {request_fingerprint}: {exc}"
            ) from exc
        for row in rows:
            attempt_id = str(row[1])
            projection = self._project_events(
                attempt_id,
                self._events_for_attempt(attempt_id),
            )
            if projection.status != "SUCCESS":
                continue
            if (
                projection.sanitized_result_ref is None
                or projection.sanitized_result_sha256 is None
            ):
                continue
            try:
                normalized, content = self._verify_result_file(
                    projection.sanitized_result_ref,
                    projection.sanitized_result_sha256,
                )
            except AttemptLedgerError:
                # A stale or tampered artifact is never trusted. A previous
                # valid success with the same fingerprint may still be used.
                continue
            return ReusableResult(
                attempt_id=projection.attempt_id,
                request_fingerprint=projection.request_fingerprint,
                result_ref=normalized,
                result_sha256=projection.sanitized_result_sha256,
                content=content,
                validated_contract_sha256=projection.validated_contract_sha256,
            )
        return None

    def find_reusable_result(self, request_fingerprint: str) -> ReusableResult | None:
        """Alias for callers that use a query-oriented method name."""

        return self.reusable_result(request_fingerprint)

    def all_events(self) -> list[Event]:
        return self.events()

    def latest(self, attempt_id: str | None = None) -> AttemptProjection | None:
        """Return the latest replay projection, or ``None`` when empty.

        This is a convenience for gateway diagnostics; callers that need the
        immutable event stream should use :meth:`events` instead.
        """

        replayed = self.events(attempt_id)
        if not replayed:
            return None
        if attempt_id is not None:
            return self._project_events(attempt_id, replayed)
        grouped: dict[str, list[Event]] = {}
        for event in replayed:
            grouped.setdefault(event.attempt_id, []).append(event)
        latest_attempt_id = max(
            grouped,
            key=lambda candidate: max(
                event.sequence or 0 for event in grouped[candidate]
            ),
        )
        return self._project_events(latest_attempt_id, grouped[latest_attempt_id])


__all__ = ["AttemptLedger", "AttemptLedgerError", "ReusableResult"]
