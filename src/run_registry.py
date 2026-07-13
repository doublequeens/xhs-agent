from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, cast

RunStatus = Literal["running", "interrupted", "awaiting_review", "completed"]
RUN_STATUSES = ("running", "interrupted", "awaiting_review", "completed")
RESUMABLE_STATUSES = ("running", "interrupted", "awaiting_review")
_UNSET = object()


class RunRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentRun:
    run_id: int
    thread_id: str
    status: RunStatus
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
    short_id = run.thread_id if len(run.thread_id) <= 31 else run.thread_id[:30] + "..."
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
        except sqlite3.Error as exc:
            if hasattr(self, "_connection"):
                self._connection.close()
            raise RunRegistryError(str(exc)) from exc

    def close(self) -> None:
        try:
            self._connection.close()
        except sqlite3.Error as exc:
            raise RunRegistryError(str(exc)) from exc

    def create_run(
        self,
        thread_id: str,
        focus_keyword: str | None = None,
        *,
        status: RunStatus = "running",
        domain: str | None = None,
        subdomain: str | None = None,
        topic_summary: str | None = None,
        title: str | None = None,
        last_node: str | None = None,
        error_summary: str | None = None,
    ) -> AgentRun:
        self._validate_status(status)
        now = utc_now()
        try:
            with self._connection:
                cursor = self._connection.execute(
                    """
                    INSERT INTO agent_runs (
                        thread_id, status, focus_keyword, domain, subdomain,
                        topic_summary, title, last_node, error_summary, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        thread_id,
                        status,
                        focus_keyword,
                        domain,
                        subdomain,
                        topic_summary,
                        title,
                        last_node,
                        error_summary,
                        now,
                        now,
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
            WHERE status IN (?, ?, ?)
            ORDER BY updated_at DESC, run_id DESC
            """,
            RESUMABLE_STATUSES,
            limit,
        )

    def list_recent(self, limit: int | None = None) -> list[AgentRun]:
        return self._list_runs(
            "SELECT * FROM agent_runs ORDER BY updated_at DESC, run_id DESC",
            (),
            limit,
        )

    def update_run(
        self,
        thread_id: str,
        *,
        status: RunStatus | object = _UNSET,
        focus_keyword: str | None | object = _UNSET,
        domain: str | None | object = _UNSET,
        subdomain: str | None | object = _UNSET,
        topic_summary: str | None | object = _UNSET,
        title: str | None | object = _UNSET,
        last_node: str | None | object = _UNSET,
        error_summary: str | None | object = _UNSET,
    ) -> AgentRun:
        if status is not _UNSET:
            self._validate_status(status)

        fields = {
            "status": status,
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
                status="running" if status is _UNSET else cast(RunStatus, status),
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
        if limit is not None:
            query += " LIMIT ?"
            parameters += (limit,)
        try:
            rows = self._connection.execute(query, parameters).fetchall()
        except sqlite3.Error as exc:
            raise RunRegistryError(str(exc)) from exc
        return [self._row_to_run(row) for row in rows]

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> AgentRun:
        return AgentRun(**dict(row))

    @staticmethod
    def _validate_status(status: object) -> None:
        if status not in RUN_STATUSES:
            raise RunRegistryError(f"invalid run status: {status!r}")
