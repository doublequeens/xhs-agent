from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, cast

RunStatus = Literal["running", "interrupted", "awaiting_review", "completed"]
RUN_STATUSES = ("running", "interrupted", "awaiting_review", "completed")
RESUMABLE_STATUSES = ("running", "interrupted", "awaiting_review")
WorkflowVersion = Literal["llm_scene_v3", "llm_scene_v4"]
RunMode = Literal["production", "shadow"]
WorkflowMode = RunMode
ExecutionState = Literal[
    "RUNNING",
    "WAITING_HUMAN",
    "INTERRUPTED_RETRYABLE",
    "INTERRUPTED_EXHAUSTED",
    "FAILED_FATAL",
    "COMPLETED",
]
WORKFLOW_VERSIONS = ("llm_scene_v3", "llm_scene_v4")
RUN_MODES = ("production", "shadow")
WORKFLOW_MODES = RUN_MODES
EXECUTION_STATES = (
    "RUNNING",
    "WAITING_HUMAN",
    "INTERRUPTED_RETRYABLE",
    "INTERRUPTED_EXHAUSTED",
    "FAILED_FATAL",
    "COMPLETED",
)
EXECUTION_TO_LEGACY_STATUS = {
    "RUNNING": "running",
    "WAITING_HUMAN": "awaiting_review",
    "INTERRUPTED_RETRYABLE": "interrupted",
    "INTERRUPTED_EXHAUSTED": "interrupted",
    "FAILED_FATAL": "interrupted",
    "COMPLETED": "completed",
}
LEGACY_STATUS_TO_EXECUTION = {
    "running": "RUNNING",
    "awaiting_review": "WAITING_HUMAN",
    "interrupted": "INTERRUPTED_RETRYABLE",
    "completed": "COMPLETED",
}
EXECUTION_STATE_TO_LEGACY_STATUS = EXECUTION_TO_LEGACY_STATUS
LEGACY_STATUS_TO_EXECUTION_STATE = LEGACY_STATUS_TO_EXECUTION
V4_RESUMABLE_EXECUTION_STATES = (
    "RUNNING",
    "WAITING_HUMAN",
    "INTERRUPTED_RETRYABLE",
)
_UNSET = object()


class RunRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentRun:
    run_id: int
    thread_id: str
    status: RunStatus
    workflow_version: WorkflowVersion
    run_mode: RunMode
    execution_state: ExecutionState
    focus_keyword: str | None
    domain: str | None
    subdomain: str | None
    topic_summary: str | None
    title: str | None
    last_node: str | None
    error_summary: str | None
    created_at: str
    updated_at: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def exception_summary(error: BaseException) -> str:
    return f"{type(error).__name__}: {str(error)[:240]}"


def format_run(run: AgentRun, *, verbose: bool = False) -> str:
    labels = {
        "running": "运行中",
        "interrupted": "已中断",
        "awaiting_review": "等待审核",
        "completed": "已完成",
    }
    subject = run.title or run.topic_summary or run.focus_keyword or "（尚无选题摘要）"
    short_id = run.thread_id if len(run.thread_id) <= 33 else run.thread_id[:30] + "..."
    lines = [
        f"[{run.run_id}] {run.updated_at.replace('T', ' ').replace('Z', ' UTC')} ｜"
        f"{labels[run.status]}｜断在：{run.last_node or '未知'}",
        f"     当前选题：{subject}",
    ]
    if run.focus_keyword:
        lines.insert(1, f"     主题词：{run.focus_keyword}")
    if run.error_summary:
        lines.append(f"     原因：{run.error_summary}")
    lines.append(f"     ID：{run.thread_id if verbose else short_id}")
    return "\n".join(lines)


class RunRegistry:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(self.path)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA busy_timeout=5000")
            with self._connection:
                self._connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_runs (
                        run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        thread_id TEXT NOT NULL UNIQUE,
                        status TEXT NOT NULL CHECK (status IN ('running', 'interrupted', 'awaiting_review', 'completed')),
                        focus_keyword TEXT,
                        domain TEXT,
                        subdomain TEXT,
                        topic_summary TEXT,
                        title TEXT,
                        last_node TEXT,
                        error_summary TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                self._connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_agent_runs_thread_id ON agent_runs(thread_id)"
                )
                self._connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_agent_runs_status_updated_at
                    ON agent_runs(status, updated_at DESC)
                    """
                )
                self._migrate_additive_columns()
            self._validate_all_rows()
        except RunRegistryError:
            if hasattr(self, "_connection"):
                self._connection.close()
            raise
        except (OSError, sqlite3.Error) as exc:
            if hasattr(self, "_connection"):
                self._connection.close()
            raise RunRegistryError(f"local registry {self.path}: {exc}") from exc

    def close(self) -> None:
        try:
            self._connection.close()
        except sqlite3.Error as exc:
            raise RunRegistryError(str(exc)) from exc

    def _migrate_additive_columns(self) -> None:
        columns = {
            row[1] for row in self._connection.execute("PRAGMA table_info(agent_runs)")
        }
        for column in ("workflow_version", "run_mode", "execution_state"):
            if column not in columns:
                self._connection.execute(f"ALTER TABLE agent_runs ADD COLUMN {column} TEXT")

        self._connection.execute(
            "UPDATE agent_runs SET workflow_version = ? WHERE workflow_version IS NULL",
            ("llm_scene_v3",),
        )
        self._connection.execute(
            "UPDATE agent_runs SET run_mode = ? WHERE run_mode IS NULL",
            ("production",),
        )
        self._connection.execute(
            """
            UPDATE agent_runs
            SET execution_state = CASE status
                WHEN 'running' THEN 'RUNNING'
                WHEN 'awaiting_review' THEN 'WAITING_HUMAN'
                WHEN 'interrupted' THEN 'INTERRUPTED_RETRYABLE'
                WHEN 'completed' THEN 'COMPLETED'
            END
            WHERE execution_state IS NULL
            """
        )

    def create_run(
        self,
        thread_id: str,
        focus_keyword: str | None = None,
        *,
        status: RunStatus | object = _UNSET,
        workflow_version: WorkflowVersion = "llm_scene_v3",
        run_mode: RunMode = "production",
        execution_state: ExecutionState | object = _UNSET,
        domain: str | None = None,
        subdomain: str | None = None,
        topic_summary: str | None = None,
        title: str | None = None,
        last_node: str | None = None,
        error_summary: str | None = None,
    ) -> AgentRun:
        self._validate_workflow_version(workflow_version)
        self._validate_run_mode(run_mode)
        status_value, execution_state_value = self._resolve_state_projection(
            status=status,
            execution_state=execution_state,
        )
        now = utc_now()
        try:
            with self._connection:
                cursor = self._connection.execute(
                    """
                    INSERT INTO agent_runs (
                        thread_id, status, focus_keyword, domain, subdomain,
                        topic_summary, title, last_node, error_summary, created_at, updated_at,
                        workflow_version, run_mode, execution_state
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        thread_id,
                        status_value,
                        focus_keyword,
                        domain,
                        subdomain,
                        topic_summary,
                        title,
                        last_node,
                        error_summary,
                        now,
                        now,
                        workflow_version,
                        run_mode,
                        execution_state_value,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise RunRegistryError(f"run for thread_id {thread_id!r} already exists") from exc
        except sqlite3.Error as exc:
            raise RunRegistryError(str(exc)) from exc
        run = self.get_by_run_id(cursor.lastrowid)
        if run is None:
            raise RunRegistryError(f"unknown run ID: {cursor.lastrowid}")
        return run

    def get_by_run_id(self, run_id: int) -> AgentRun | None:
        return self._get_one("SELECT * FROM agent_runs WHERE run_id = ?", (run_id,))

    def get_by_thread_id(self, thread_id: str) -> AgentRun | None:
        return self._get_one("SELECT * FROM agent_runs WHERE thread_id = ?", (thread_id,))

    def list_resumable(self, limit: int | None = None) -> list[AgentRun]:
        return self._list_runs(
            """
            SELECT * FROM agent_runs
            WHERE (
                workflow_version = ? AND status IN (?, ?, ?)
            ) OR (
                workflow_version = ? AND execution_state IN (?, ?, ?)
            )
            ORDER BY updated_at DESC, run_id DESC
            """,
            (
                "llm_scene_v3",
                *RESUMABLE_STATUSES,
                "llm_scene_v4",
                *V4_RESUMABLE_EXECUTION_STATES,
            ),
            limit,
        )

    def list_recent(self, limit: int | None = None) -> list[AgentRun]:
        return self._list_runs(
            "SELECT * FROM agent_runs ORDER BY updated_at DESC, run_id DESC",
            (),
            limit,
        )

    def delete_run(self, thread_id: str) -> bool:
        """Delete a single run by thread_id. Returns True if a row was removed."""
        try:
            with self._connection:
                cursor = self._connection.execute(
                    "DELETE FROM agent_runs WHERE thread_id = ?",
                    (thread_id,),
                )
        except sqlite3.Error as exc:
            raise RunRegistryError(str(exc)) from exc
        return cursor.rowcount > 0

    def delete_all(self, statuses: tuple[str, ...] | None = None) -> int:
        """Delete runs from the registry.

        With ``statuses`` only runs in those statuses are removed; otherwise every
        run is removed. Returns the number of rows deleted.
        """
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            query = f"DELETE FROM agent_runs WHERE status IN ({placeholders})"
            params: tuple[object, ...] = tuple(statuses)
        else:
            query = "DELETE FROM agent_runs"
            params = ()
        try:
            with self._connection:
                cursor = self._connection.execute(query, params)
        except sqlite3.Error as exc:
            raise RunRegistryError(str(exc)) from exc
        return cursor.rowcount


    def update_run(
        self,
        thread_id: str,
        *,
        status: RunStatus | object = _UNSET,
        workflow_version: WorkflowVersion | object = _UNSET,
        run_mode: RunMode | object = _UNSET,
        execution_state: ExecutionState | object = _UNSET,
        focus_keyword: str | None | object = _UNSET,
        domain: str | None | object = _UNSET,
        subdomain: str | None | object = _UNSET,
        topic_summary: str | None | object = _UNSET,
        title: str | None | object = _UNSET,
        last_node: str | None | object = _UNSET,
        error_summary: str | None | object = _UNSET,
    ) -> AgentRun:
        existing = self.get_by_thread_id(thread_id)
        if existing is None:
            raise RunRegistryError(f"unknown thread ID: {thread_id}")

        self._validate_immutable_identity(
            existing,
            workflow_version=workflow_version,
            run_mode=run_mode,
        )
        status_value, execution_state_value, update_projection = self._resolve_update_projection(
            existing,
            status=status,
            execution_state=execution_state,
        )

        fields = {
            "status": status_value if update_projection else _UNSET,
            "execution_state": execution_state_value if update_projection else _UNSET,
            "focus_keyword": focus_keyword,
            "domain": domain,
            "subdomain": subdomain,
            "topic_summary": topic_summary,
            "title": title,
            "last_node": last_node,
            "error_summary": error_summary,
        }
        assignments = [f"{name} = ?" for name, value in fields.items() if value is not _UNSET]
        values = [value for value in fields.values() if value is not _UNSET]
        assignments.append("updated_at = ?")
        values.extend((utc_now(), thread_id))
        try:
            with self._connection:
                cursor = self._connection.execute(
                    f"UPDATE agent_runs SET {', '.join(assignments)} WHERE thread_id = ?", values
                )
        except sqlite3.Error as exc:
            raise RunRegistryError(str(exc)) from exc
        if cursor.rowcount != 1:
            raise RunRegistryError(f"unknown thread ID: {thread_id}")
        run = self.get_by_thread_id(thread_id)
        if run is None:
            raise RunRegistryError(f"unknown thread ID: {thread_id}")
        return run

    def upsert_run(
        self,
        thread_id: str,
        *,
        status: RunStatus | object = _UNSET,
        workflow_version: WorkflowVersion | object = _UNSET,
        run_mode: RunMode | object = _UNSET,
        execution_state: ExecutionState | object = _UNSET,
        focus_keyword: str | None | object = _UNSET,
        domain: str | None | object = _UNSET,
        subdomain: str | None | object = _UNSET,
        topic_summary: str | None | object = _UNSET,
        title: str | None | object = _UNSET,
        last_node: str | None | object = _UNSET,
        error_summary: str | None | object = _UNSET,
    ) -> AgentRun:
        existing = self.get_by_thread_id(thread_id)
        if existing is None:
            return self.create_run(
                thread_id,
                None if focus_keyword is _UNSET else cast(str | None, focus_keyword),
                status=status,
                workflow_version=(
                    "llm_scene_v3"
                    if workflow_version is _UNSET
                    else cast(WorkflowVersion, workflow_version)
                ),
                run_mode=("production" if run_mode is _UNSET else cast(RunMode, run_mode)),
                execution_state=execution_state,
                domain=None if domain is _UNSET else cast(str | None, domain),
                subdomain=None if subdomain is _UNSET else cast(str | None, subdomain),
                topic_summary=None if topic_summary is _UNSET else cast(str | None, topic_summary),
                title=None if title is _UNSET else cast(str | None, title),
                last_node=None if last_node is _UNSET else cast(str | None, last_node),
                error_summary=None if error_summary is _UNSET else cast(str | None, error_summary),
            )

        return self.update_run(
            thread_id,
            status=status,
            workflow_version=workflow_version,
            run_mode=run_mode,
            execution_state=execution_state,
            domain=domain,
            subdomain=subdomain,
            topic_summary=topic_summary,
            title=title,
            last_node=last_node,
            error_summary=error_summary,
        )

    def _get_one(self, query: str, parameters: tuple[object, ...]) -> AgentRun | None:
        try:
            row = self._connection.execute(query, parameters).fetchone()
        except sqlite3.Error as exc:
            raise RunRegistryError(str(exc)) from exc
        return self._row_to_run(row) if row is not None else None

    def _list_runs(
        self, query: str, parameters: tuple[object, ...], limit: int | None
    ) -> list[AgentRun]:
        self._validate_all_rows()
        if limit is not None:
            query += " LIMIT ?"
            parameters += (limit,)
        try:
            rows = self._connection.execute(query, parameters).fetchall()
        except sqlite3.Error as exc:
            raise RunRegistryError(str(exc)) from exc
        return [self._row_to_run(row) for row in rows]

    def _validate_all_rows(self) -> None:
        try:
            rows = self._connection.execute("SELECT * FROM agent_runs").fetchall()
        except sqlite3.Error as exc:
            raise RunRegistryError(str(exc)) from exc
        for row in rows:
            self._validate_persisted_row(row)

    @classmethod
    def _row_to_run(cls, row: sqlite3.Row) -> AgentRun:
        cls._validate_persisted_row(row)
        return AgentRun(**dict(row))

    @classmethod
    def _validate_persisted_row(cls, row: sqlite3.Row) -> None:
        cls._validate_status(row["status"])
        cls._validate_workflow_version(row["workflow_version"])
        cls._validate_run_mode(row["run_mode"])
        cls._validate_execution_state(row["execution_state"])
        projected_status = EXECUTION_TO_LEGACY_STATUS[row["execution_state"]]
        if row["status"] != projected_status:
            raise RunRegistryError(
                "inconsistent persisted status/execution_state projection: "
                f"{row['status']!r} != {projected_status!r}"
            )

    @staticmethod
    def _validate_status(status: object) -> None:
        if status not in RUN_STATUSES:
            raise RunRegistryError(f"invalid run status: {status!r}")

    @staticmethod
    def _validate_workflow_version(workflow_version: object) -> None:
        if workflow_version not in WORKFLOW_VERSIONS:
            raise RunRegistryError(f"invalid workflow version: {workflow_version!r}")

    @staticmethod
    def _validate_run_mode(run_mode: object) -> None:
        if run_mode not in RUN_MODES:
            raise RunRegistryError(f"invalid run mode: {run_mode!r}")

    @staticmethod
    def _validate_execution_state(execution_state: object) -> None:
        if execution_state not in EXECUTION_STATES:
            raise RunRegistryError(f"invalid execution_state: {execution_state!r}")

    @classmethod
    def _resolve_state_projection(
        cls,
        *,
        status: RunStatus | object,
        execution_state: ExecutionState | object,
    ) -> tuple[RunStatus, ExecutionState]:
        status_supplied = status is not _UNSET
        execution_supplied = execution_state is not _UNSET
        if status_supplied:
            cls._validate_status(status)
        if execution_supplied:
            cls._validate_execution_state(execution_state)

        if status_supplied and execution_supplied:
            projected_status = EXECUTION_TO_LEGACY_STATUS[execution_state]
            if status != projected_status:
                raise RunRegistryError(
                    "conflicting status/execution_state projection: "
                    f"{status!r} != {projected_status!r}"
                )
            return cast(RunStatus, status), cast(ExecutionState, execution_state)
        if execution_supplied:
            return (
                cast(RunStatus, EXECUTION_TO_LEGACY_STATUS[execution_state]),
                cast(ExecutionState, execution_state),
            )
        if status_supplied:
            return (
                cast(RunStatus, status),
                cast(ExecutionState, LEGACY_STATUS_TO_EXECUTION[status]),
            )
        return "running", "RUNNING"

    @classmethod
    def _resolve_update_projection(
        cls,
        existing: AgentRun,
        *,
        status: RunStatus | object,
        execution_state: ExecutionState | object,
    ) -> tuple[RunStatus, ExecutionState, bool]:
        status_supplied = status is not _UNSET
        execution_supplied = execution_state is not _UNSET
        if status_supplied:
            cls._validate_status(status)
        if execution_supplied:
            cls._validate_execution_state(execution_state)

        if execution_supplied:
            projected_status = EXECUTION_TO_LEGACY_STATUS[execution_state]
            if status_supplied and status != projected_status:
                raise RunRegistryError(
                    "conflicting status/execution_state projection: "
                    f"{status!r} != {projected_status!r}"
                )
            return (
                cast(RunStatus, projected_status),
                cast(ExecutionState, execution_state),
                True,
            )
        if status_supplied:
            status_value = cast(RunStatus, status)
            # A v4 fatal/exhausted state shares the legacy ``interrupted``
            # projection. A status-only compatibility update must not erase
            # that authoritative state unless the projection actually changes.
            if (
                existing.workflow_version == "llm_scene_v4"
                and status_value == existing.status
            ):
                return status_value, existing.execution_state, True
            return status_value, cast(ExecutionState, LEGACY_STATUS_TO_EXECUTION[status]), True
        return existing.status, existing.execution_state, False

    @classmethod
    def _validate_immutable_identity(
        cls,
        existing: AgentRun,
        *,
        workflow_version: WorkflowVersion | object,
        run_mode: RunMode | object,
    ) -> None:
        if workflow_version is not _UNSET:
            cls._validate_workflow_version(workflow_version)
            if workflow_version != existing.workflow_version:
                raise RunRegistryError(
                    "workflow_version is immutable for an existing thread"
                )
        if run_mode is not _UNSET:
            cls._validate_run_mode(run_mode)
            if run_mode != existing.run_mode:
                raise RunRegistryError("run_mode is immutable for an existing thread")
