"""Append-only SQLite Attempt Ledger for visual-production v4.

The ledger is intentionally independent from LangGraph checkpoints.  It owns a
single additive table in the caller-provided database and reconstructs attempt
state by replaying immutable events.  A provider gateway can therefore commit a
start before doing work and append exactly one terminal event afterwards.
"""

from __future__ import annotations

import errno
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
_STALE_RESULT_ERRNOS = frozenset(
    {errno.ENOENT, errno.ELOOP, errno.ENOTDIR, errno.EISDIR}
)


class AttemptLedgerError(RuntimeError):
    """Contextual error raised for invalid ledger state or durable I/O."""


class _StaleResultVerificationError(AttemptLedgerError):
    """Result-file failure that makes a candidate ineligible for reuse."""


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

    # Reuse is intentionally bounded. A corrupt or repeatedly failing history
    # must not turn a fingerprint lookup into an unbounded replay/IO operation.
    MAX_REUSABLE_RESULT_CANDIDATES = 32

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
        except AttemptLedgerError as primary:
            cleanup_error = self._close_connection_quietly()
            if cleanup_error is not None:
                primary.add_note(f"constructor cleanup failed: {cleanup_error}")
            raise
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            cleanup_error = self._close_connection_quietly()
            error = AttemptLedgerError(f"could not initialize ledger {self.path}: {exc}")
            if cleanup_error is not None:
                error.add_note(f"constructor cleanup failed: {cleanup_error}")
            raise error from exc

    def __enter__(self) -> "AttemptLedger":
        return self

    def __exit__(self, _exc_type, exc, _traceback) -> bool:
        cleanup_error = self._close_connection_quietly()
        if cleanup_error is None:
            return False
        if exc is not None:
            exc.add_note(f"ledger cleanup failed: {cleanup_error}")
            return False
        raise AttemptLedgerError(
            f"could not close ledger {self.path}: {cleanup_error}"
        ) from cleanup_error

    def _close_connection_quietly(self) -> BaseException | None:
        connection = self._connection
        self._connection = None
        if connection is None:
            return None
        try:
            connection.close()
        except BaseException as exc:
            return exc

    @staticmethod
    def _rollback_quietly(connection: sqlite3.Connection) -> BaseException | None:
        try:
            connection.rollback()
        except BaseException as exc:
            return exc
        return None

    def close(self) -> None:
        cleanup_error = self._close_connection_quietly()
        if cleanup_error is not None:
            raise AttemptLedgerError(
                f"could not close ledger {self.path}: {cleanup_error}"
            ) from cleanup_error

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the connection for diagnostics and read-only audits."""

        return self._require_connection()

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise AttemptLedgerError(f"ledger {self.path} is closed")
        return self._connection

    @staticmethod
    def _table_info(connection: sqlite3.Connection) -> dict[str, sqlite3.Row]:
        return {
            row[1]: row
            for row in connection.execute("PRAGMA table_info(visual_attempt_events)")
        }

    @staticmethod
    def _schema_is_hardened(
        connection: sqlite3.Connection, table_info: dict[str, sqlite3.Row]
    ) -> bool:
        expected_columns = {
            "sequence",
            "attempt_id",
            "event_kind",
            "payload_json",
            "run_id",
            "candidate_id",
            "request_fingerprint",
        }
        if set(table_info) != expected_columns:
            return False
        if table_info["sequence"][5] != 1:
            return False
        if any(table_info[column][3] != 1 for column in expected_columns - {"sequence"}):
            return False
        schema_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            "AND name = 'visual_attempt_events'"
        ).fetchone()
        schema_sql = str(schema_row[0]).lower() if schema_row is not None else ""
        return bool(
            re.search(r"check\s*\(\s*sequence\s*>\s*0\s*\)", schema_sql)
            and "event_kind" in schema_sql
            and "attemptstarted" in schema_sql
        )

    def _validate_legacy_rows(
        self,
        rows: list[sqlite3.Row],
        *,
        has_identity_columns: bool,
    ) -> list[tuple[int, str, str, str, str, str, str]]:
        replayed: list[Event] = []
        metadata: list[tuple[str | None, str | None, str | None]] = []
        previous_sequence = 0
        for row in rows:
            raw_sequence = row[0]
            if isinstance(raw_sequence, bool) or not isinstance(raw_sequence, int):
                raise AttemptLedgerError(
                    f"invalid legacy event sequence {raw_sequence!r}: sequence must be positive integer"
                )
            sequence = raw_sequence
            if sequence <= 0 or sequence <= previous_sequence:
                raise AttemptLedgerError(
                    f"invalid legacy event sequence {sequence}: sequence must be positive and increasing"
                )
            previous_sequence = sequence
            row_attempt_id = str(row[1])
            event_kind = str(row[2])
            event = self._decode_event(sequence, row_attempt_id, event_kind, row[3])
            replayed.append(event)
            if has_identity_columns:
                metadata.append((row[4], row[5], row[6]))
            else:
                metadata.append((None, None, None))

        starts_by_attempt = {
            event.attempt_id: event
            for event in replayed
            if isinstance(event, AttemptStarted)
        }
        grouped: dict[str, list[Event]] = {}
        for event in replayed:
            grouped.setdefault(event.attempt_id, []).append(event)
        for attempt_id, events in grouped.items():
            self._project_events(attempt_id, events)

        validated_rows: list[tuple[int, str, str, str, str, str, str]] = []
        for row, event, existing_identity in zip(
            rows, replayed, metadata, strict=True
        ):
            start = starts_by_attempt.get(event.attempt_id)
            if start is None:
                raise AttemptLedgerError(
                    f"invalid legacy replay for attempt {event.attempt_id}: "
                    "terminal event has no start identity"
                )
            expected_identity = (
                start.run_id,
                start.candidate_id,
                start.request_fingerprint,
            )
            if any(
                value is not None and value != expected
                for value, expected in zip(existing_identity, expected_identity, strict=True)
            ):
                raise AttemptLedgerError(
                    f"invalid legacy replay for attempt {event.attempt_id}: "
                    "denormalized identity does not match start payload"
                )
            validated_rows.append(
                (
                    int(row[0]),
                    str(row[1]),
                    str(row[2]),
                    str(row[3]),
                    *expected_identity,
                )
            )
        return validated_rows

    def _migrate_legacy_table(
        self,
        connection: sqlite3.Connection,
        table_info: dict[str, sqlite3.Row],
    ) -> None:
        base_columns = {"sequence", "attempt_id", "event_kind", "payload_json"}
        identity_columns = {"run_id", "candidate_id", "request_fingerprint"}
        names = set(table_info)
        if names not in (base_columns, base_columns | identity_columns):
            raise AttemptLedgerError(
                "unsupported visual_attempt_events schema; refusing migration"
            )
        has_identity_columns = names == base_columns | identity_columns
        select_columns = (
            "sequence, attempt_id, event_kind, payload_json, run_id, candidate_id, "
            "request_fingerprint"
            if has_identity_columns
            else "sequence, attempt_id, event_kind, payload_json"
        )
        rows = connection.execute(
            f"SELECT {select_columns} FROM visual_attempt_events ORDER BY sequence"
        ).fetchall()
        validated_rows = self._validate_legacy_rows(
            rows,
            has_identity_columns=has_identity_columns,
        )
        maximum_sequence = validated_rows[-1][0] if validated_rows else 0
        sequence_row = connection.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = ?",
            ("visual_attempt_events",),
        ).fetchone()
        if sequence_row is None:
            legacy_high_water = 0
        else:
            raw_high_water = sequence_row[0]
            if (
                isinstance(raw_high_water, bool)
                or not isinstance(raw_high_water, int)
                or raw_high_water < 0
            ):
                raise AttemptLedgerError(
                    "invalid sqlite_sequence high-water for visual_attempt_events"
                )
            legacy_high_water = raw_high_water
        if legacy_high_water < maximum_sequence:
            raise AttemptLedgerError(
                "sqlite_sequence high-water is below the maximum event sequence"
            )

        temporary_table = f"visual_attempt_events__migrating_{uuid4().hex}"
        collision = connection.execute(
            "SELECT type FROM sqlite_master WHERE name = ?",
            (temporary_table,),
        ).fetchone()
        if collision is not None:
            raise AttemptLedgerError(
                f"migration temporary table name is already in use: {temporary_table}"
            )
        connection.execute(
            f"""
            CREATE TABLE {temporary_table} (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT CHECK (sequence > 0),
                attempt_id TEXT NOT NULL,
                event_kind TEXT NOT NULL CHECK (
                    event_kind IN ('AttemptStarted', 'AttemptFinished', 'AttemptReconciled')
                ),
                payload_json TEXT NOT NULL,
                run_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                request_fingerprint TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            f"INSERT INTO {temporary_table} "
            "(sequence, attempt_id, event_kind, payload_json, run_id, candidate_id, "
            "request_fingerprint) VALUES (?, ?, ?, ?, ?, ?, ?)",
            validated_rows,
        )
        connection.execute("DROP TABLE visual_attempt_events")
        connection.execute(
            f"ALTER TABLE {temporary_table} RENAME TO visual_attempt_events"
        )
        target_high_water = max(legacy_high_water, maximum_sequence)
        if target_high_water:
            sequence_row = connection.execute(
                "SELECT seq FROM sqlite_sequence WHERE name = ?",
                ("visual_attempt_events",),
            ).fetchone()
            if sequence_row is None:
                connection.execute(
                    "INSERT INTO sqlite_sequence(name, seq) VALUES (?, ?)",
                    ("visual_attempt_events", target_high_water),
                )
            else:
                connection.execute(
                    "UPDATE sqlite_sequence SET seq = ? WHERE name = ?",
                    (target_high_water, "visual_attempt_events"),
                )

    def _create_schema(self) -> None:
        connection = self._require_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            table_info = self._table_info(connection)
            if not table_info:
                connection.execute(
                    """
                    CREATE TABLE visual_attempt_events (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT CHECK (sequence > 0),
                        attempt_id TEXT NOT NULL,
                        event_kind TEXT NOT NULL CHECK (
                            event_kind IN ('AttemptStarted', 'AttemptFinished', 'AttemptReconciled')
                        ),
                        payload_json TEXT NOT NULL,
                        run_id TEXT NOT NULL,
                        candidate_id TEXT NOT NULL,
                        request_fingerprint TEXT NOT NULL
                    )
                    """
                )
            elif not self._schema_is_hardened(connection, table_info):
                self._migrate_legacy_table(connection, table_info)

            schema_statements = (
                """
                CREATE INDEX IF NOT EXISTS idx_visual_attempt_events_attempt
                    ON visual_attempt_events(attempt_id, sequence)
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_visual_attempt_events_kind_attempt
                    ON visual_attempt_events(event_kind, attempt_id, sequence)
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_visual_attempt_events_run_candidate
                    ON visual_attempt_events(event_kind, run_id, candidate_id, sequence, attempt_id)
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_visual_attempt_events_fingerprint
                    ON visual_attempt_events(event_kind, request_fingerprint, sequence, attempt_id)
                """,
                """
                CREATE TRIGGER IF NOT EXISTS visual_attempt_events_no_update
                BEFORE UPDATE ON visual_attempt_events
                BEGIN
                    SELECT RAISE(ABORT, 'visual attempt events are append-only');
                END
                """,
                """
                CREATE TRIGGER IF NOT EXISTS visual_attempt_events_no_delete
                BEFORE DELETE ON visual_attempt_events
                BEGIN
                    SELECT RAISE(ABORT, 'visual attempt events are append-only');
                END
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
                END
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
                END
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
                END
                """,
                """
                CREATE TRIGGER IF NOT EXISTS visual_attempt_events_start_identity
                BEFORE INSERT ON visual_attempt_events
                WHEN NEW.event_kind = 'AttemptStarted'
                    AND NOT (
                        NEW.attempt_id IS json_extract(NEW.payload_json, '$.attempt_id')
                        AND NEW.run_id IS json_extract(NEW.payload_json, '$.run_id')
                        AND NEW.candidate_id IS json_extract(NEW.payload_json, '$.candidate_id')
                        AND NEW.request_fingerprint IS json_extract(NEW.payload_json, '$.request_fingerprint')
                    )
                BEGIN
                    SELECT RAISE(ABORT, 'AttemptStarted identity does not match payload');
                END
                """,
                """
                CREATE TRIGGER IF NOT EXISTS visual_attempt_events_terminal_identity
                BEFORE INSERT ON visual_attempt_events
                WHEN NEW.event_kind IN ('AttemptFinished', 'AttemptReconciled')
                    AND EXISTS (
                        SELECT 1 FROM visual_attempt_events
                        WHERE attempt_id = NEW.attempt_id
                          AND event_kind = 'AttemptStarted'
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM visual_attempt_events
                        WHERE attempt_id = NEW.attempt_id
                          AND event_kind = 'AttemptStarted'
                          AND run_id = NEW.run_id
                          AND candidate_id = NEW.candidate_id
                          AND request_fingerprint = NEW.request_fingerprint
                    )
                BEGIN
                    SELECT RAISE(ABORT, 'terminal identity does not match start');
                END
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
        except AttemptLedgerError as exc:
            cleanup_error = self._rollback_quietly(connection)
            if cleanup_error is not None:
                exc.add_note(f"schema rollback failed: {cleanup_error}")
            raise
        except sqlite3.Error as exc:
            cleanup_error = self._rollback_quietly(connection)
            error = AttemptLedgerError(
                f"could not create ledger schema {self.path}: {exc}"
            )
            if cleanup_error is not None:
                error.add_note(f"schema rollback failed: {cleanup_error}")
            raise error from exc

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

    @staticmethod
    def _decode_event(
        sequence: int,
        row_attempt_id: str,
        event_kind: str,
        raw_payload: Any,
    ) -> Event:
        model_type = _EVENT_KINDS.get(event_kind)
        if model_type is None:
            raise AttemptLedgerError(
                f"invalid event sequence {sequence} ({event_kind}) for "
                f"attempt {row_attempt_id}: unknown event kind"
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
        return event  # type: ignore[return-value]

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
            raw_sequence = row[0]
            if isinstance(raw_sequence, bool) or not isinstance(raw_sequence, int):
                raise AttemptLedgerError(
                    f"invalid event sequence {raw_sequence!r}: sequence must be positive integer"
                )
            sequence = raw_sequence
            row_attempt_id = str(row[1])
            event_kind = str(row[2])
            raw_payload = row[3]
            if len(row) < 7:
                raise AttemptLedgerError(
                    f"invalid event sequence {sequence} ({event_kind}) for "
                    f"attempt {row_attempt_id}: missing query identity columns"
                )
            query_identity = (row[4], row[5], row[6])
            if sequence <= 0 or sequence <= previous_sequence:
                raise AttemptLedgerError(
                    f"invalid event sequence {sequence}: sequence must be positive and increasing"
                )
            previous_sequence = sequence
            event = self._decode_event(sequence, row_attempt_id, event_kind, raw_payload)
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

    @staticmethod
    def _close_descriptor(
        fd: int,
        label: str,
        open_fds: dict[int, str],
        cleanup_errors: list[str],
    ) -> None:
        if fd not in open_fds:
            return
        open_fds.pop(fd, None)
        try:
            os.close(fd)
        except BaseException as exc:
            cleanup_errors.append(f"{label} fd {fd}: {exc}")

    @staticmethod
    def _open_result_component(
        component: str,
        flags: int,
        *,
        dir_fd: int,
        label: str,
    ) -> int:
        try:
            return os.open(component, flags, dir_fd=dir_fd)
        except OSError as exc:
            if exc.errno in _STALE_RESULT_ERRNOS:
                raise _StaleResultVerificationError(
                    f"{label} is stale or missing: {exc}"
                ) from exc
            raise

    def _read_verified_result(self, reference: str, expected_sha256: str) -> tuple[str, bytes]:
        normalized = self._normalize_result_ref(reference)
        if self.result_root is None:
            raise AttemptLedgerError("result_root is required for result references")
        root = self.result_root
        directory_flag = getattr(os, "O_DIRECTORY", 0)
        no_follow_flag = getattr(os, "O_NOFOLLOW", 0)
        close_on_exec_flag = getattr(os, "O_CLOEXEC", 0)
        open_fds: dict[int, str] = {}
        cleanup_errors: list[str] = []
        primary_error: BaseException | None = None
        verified_result: tuple[str, bytes] | None = None
        try:
            root_fd = os.open(
                root,
                os.O_RDONLY | directory_flag | no_follow_flag | close_on_exec_flag,
            )
            open_fds[root_fd] = "result_root"
            current_fd = root_fd
            if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
                raise AttemptLedgerError(f"result_root is not an existing directory: {root}")

            parts = PurePosixPath(normalized).parts
            for part in parts[:-1]:
                next_fd = self._open_result_component(
                    part,
                    os.O_RDONLY | directory_flag | no_follow_flag | close_on_exec_flag,
                    dir_fd=current_fd,
                    label=f"result path component {part}",
                )
                open_fds[next_fd] = f"ancestor {part}"
                if current_fd != root_fd:
                    self._close_descriptor(
                        current_fd,
                        "ancestor",
                        open_fds,
                        cleanup_errors,
                    )
                current_fd = next_fd

            result_fd = self._open_result_component(
                parts[-1],
                os.O_RDONLY | no_follow_flag | close_on_exec_flag,
                dir_fd=current_fd,
                label=f"result target {parts[-1]}",
            )
            open_fds[result_fd] = "result"
            if not stat.S_ISREG(os.fstat(result_fd).st_mode):
                raise _StaleResultVerificationError(
                    "result reference must identify a regular file"
                )

            chunks: list[bytes] = []
            while True:
                chunk = os.read(result_fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            content = b"".join(chunks)
            actual_sha256 = hashlib.sha256(content).hexdigest()
            if not _SHA256_RE.fullmatch(expected_sha256) or actual_sha256 != expected_sha256:
                raise _StaleResultVerificationError(
                    "result reference sha256 does not match bytes"
                )
            verified_result = normalized, content
        except BaseException as exc:
            primary_error = exc
        finally:
            for fd, label in reversed(list(open_fds.items())):
                self._close_descriptor(fd, label, open_fds, cleanup_errors)

        if primary_error is not None:
            if cleanup_errors:
                combined_error = AttemptLedgerError(
                    f"could not verify result reference {reference}: {primary_error}; "
                    "descriptor cleanup also failed: "
                    + "; ".join(cleanup_errors)
                )
                combined_error.add_note(
                    f"primary verification error: {primary_error}"
                )
                combined_error.add_note(
                    "result descriptor cleanup errors: " + "; ".join(cleanup_errors)
                )
                raise combined_error from primary_error
            raise primary_error
        if cleanup_errors:
            raise AttemptLedgerError(
                f"could not close result descriptors for {reference}: "
                + "; ".join(cleanup_errors)
            )
        if verified_result is None:
            raise AttemptLedgerError(f"could not verify result reference {reference}")
        return verified_result

    def _verify_result_file(self, reference: str, expected_sha256: str) -> tuple[str, bytes]:
        try:
            return self._read_verified_result(reference, expected_sha256)
        except AttemptLedgerError:
            raise
        except OSError as exc:
            raise AttemptLedgerError(
                f"could not verify result reference {reference}: {exc}"
            ) from exc
        except ValueError as exc:
            raise AttemptLedgerError(
                f"could not verify result reference {reference}: {exc}"
            ) from exc

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
                LIMIT ?
                """,
                (request_fingerprint, self.MAX_REUSABLE_RESULT_CANDIDATES),
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
            except _StaleResultVerificationError:
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
