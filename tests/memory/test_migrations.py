from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from memory.migrations import (
    migrate_contents_domain_fields,
    migrate_metrics_collection_schema,
)
from memory.memory_manager import XHSMemoryManager


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "memory" / "schema.sql"


def _table_columns(
    connection: sqlite3.Connection, table_name: str = "contents"
) -> list[str]:
    return [row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")]


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        is not None
    )


def _primary_key_columns(
    connection: sqlite3.Connection, table_name: str
) -> list[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})")
    return [
        row[1]
        for row in sorted((row for row in rows if row[5]), key=lambda row: row[5])
    ]


def _column_details(
    connection: sqlite3.Connection, table_name: str
) -> dict[str, tuple[str, bool, str | None]]:
    return {
        row[1]: (row[2], bool(row[3]), row[4])
        for row in connection.execute(f"PRAGMA table_info({table_name})")
    }


def _foreign_keys(
    connection: sqlite3.Connection, table_name: str
) -> set[tuple[str, str, str, str]]:
    return {
        (row[2], row[3], row[4], row[6])
        for row in connection.execute(f"PRAGMA foreign_key_list({table_name})")
    }


def _index_names(
    connection: sqlite3.Connection, table_name: str = "contents"
) -> set[str]:
    return {
        row[1] for row in connection.execute(f"PRAGMA index_list({table_name})")
    }


def _index_columns(connection: sqlite3.Connection, index_name: str) -> list[str]:
    return [row[2] for row in connection.execute(f"PRAGMA index_info({index_name})")]


def test_migrate_contents_domain_fields_is_idempotent_and_backfills_legacy_rows(tmp_path):
    db_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE contents (content_id TEXT PRIMARY KEY, topic TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO contents(content_id, topic, created_at) VALUES (?, ?, ?)",
        ("c1", "防晒", "2026-07-03T10:00:00+08:00"),
    )
    connection.commit()

    migrate_contents_domain_fields(connection)
    migrate_contents_domain_fields(connection)

    row = connection.execute(
        """
        SELECT domain, subdomain, content_intent, profile_version, risk_level
        FROM contents
        WHERE content_id = ?
        """,
        ("c1",),
    ).fetchone()

    assert tuple(row) == ("beauty", "skincare", None, "legacy-v1", "low")
    assert "idx_contents_domain_subdomain" in _index_names(connection)
    assert "idx_contents_domain_subdomain_created_at" in _index_names(connection)


def test_migrate_contents_domain_fields_preserves_existing_values(tmp_path):
    db_path = tmp_path / "prefilled.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE contents (
            content_id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            domain TEXT,
            subdomain TEXT,
            content_intent TEXT,
            profile_version TEXT,
            risk_level TEXT
        )
        """
    )
    connection.execute(
        """
        INSERT INTO contents(
            content_id, topic, domain, subdomain, content_intent, profile_version, risk_level
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("c2", "睡眠", "wellness", "sleep", "how_to", "wellness-v1", "medium"),
    )
    connection.commit()

    migrate_contents_domain_fields(connection)

    row = connection.execute(
        """
        SELECT domain, subdomain, content_intent, profile_version, risk_level
        FROM contents
        WHERE content_id = ?
        """,
        ("c2",),
    ).fetchone()

    assert row == ("wellness", "sleep", "how_to", "wellness-v1", "medium")


def test_migrate_contents_domain_fields_rolls_back_on_failure(tmp_path):
    db_path = tmp_path / "rollback.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE contents (content_id TEXT PRIMARY KEY, topic TEXT NOT NULL)")
    connection.commit()

    class FailingConnection:
        def __init__(self, inner: sqlite3.Connection):
            self.inner = inner
            self.alter_calls = 0

        def __enter__(self):
            self.inner.__enter__()
            return self

        def __exit__(self, exc_type, exc, tb):
            return self.inner.__exit__(exc_type, exc, tb)

        def execute(self, sql, params=()):
            if sql.lstrip().upper().startswith("ALTER TABLE CONTENTS ADD COLUMN"):
                self.alter_calls += 1
                if self.alter_calls == 2:
                    raise RuntimeError("boom")
            return self.inner.execute(sql, params)

        def __getattr__(self, name):
            return getattr(self.inner, name)

    wrapper = FailingConnection(connection)

    with pytest.raises(RuntimeError, match="boom"):
        migrate_contents_domain_fields(wrapper)

    assert _table_columns(connection) == ["content_id", "topic"]


def test_fresh_schema_includes_domain_columns_and_composite_index(tmp_path):
    db_path = tmp_path / "fresh.db"
    connection = sqlite3.connect(db_path)
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    columns = set(_table_columns(connection))
    assert {"domain", "subdomain", "content_intent", "profile_version", "risk_level"} <= columns
    assert "idx_contents_domain_subdomain" in _index_names(connection)
    assert "idx_contents_domain_subdomain_created_at" in _index_names(connection)
    assert _index_columns(connection, "idx_contents_domain_subdomain_created_at") == [
        "domain",
        "subdomain",
        "created_at",
    ]

    connection.executemany(
        """
        INSERT INTO contents(content_id, topic, created_at, domain, subdomain)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("c1", "a", "2026-07-03T10:00:00+08:00", "wellness", "sleep"),
            ("c2", "b", "2026-07-03T11:00:00+08:00", "wellness", "sleep"),
            ("c3", "c", "2026-07-03T12:00:00+08:00", "beauty", "skincare"),
        ],
    )
    plan_rows = connection.execute(
        """
        EXPLAIN QUERY PLAN
        SELECT content_id
        FROM contents
        WHERE domain = ? AND subdomain = ?
        ORDER BY created_at DESC
        LIMIT 10
        """,
        ("wellness", "sleep"),
    ).fetchall()
    plan_details = [row[3] for row in plan_rows]
    assert any("idx_contents_domain_subdomain_created_at" in detail for detail in plan_details)
    assert all("TEMP B-TREE" not in detail for detail in plan_details)


def test_migrate_metrics_collection_schema_is_idempotent_for_legacy_metrics(tmp_path):
    db_path = tmp_path / "legacy-metrics.db"
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("CREATE TABLE contents (content_id TEXT PRIMARY KEY)")
    connection.execute(
        """
        CREATE TABLE metrics (
            content_id TEXT PRIMARY KEY,
            views INTEGER DEFAULT 0,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (content_id) REFERENCES contents(content_id)
                ON DELETE CASCADE
        )
        """
    )
    connection.commit()

    migrate_metrics_collection_schema(connection)
    migrate_metrics_collection_schema(connection)

    assert {
        "impressions",
        "cover_click_rate",
        "avg_watch_time_seconds",
        "danmaku_count",
    } <= set(_table_columns(connection, "metrics"))
    assert _table_exists(connection, "metrics_history")
    assert _table_exists(connection, "metrics_collection_runs")
    assert (
        "idx_metrics_collection_runs_execution_date"
        in _index_names(connection, "metrics_collection_runs")
    )
    assert _index_columns(
        connection,
        "idx_metrics_collection_runs_execution_date",
    ) == ["execution_date"]

    connection.execute(
        """
        INSERT INTO metrics_collection_runs(
            scheduled_date,
            execution_date,
            status,
            started_at
        )
        VALUES ('2026-07-05', '2026-07-06', 'failed', '2026-07-06T09:00:00+08:00')
        """
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO metrics_collection_runs(
                scheduled_date,
                execution_date,
                status,
                started_at
            )
            VALUES ('2026-07-06', '2026-07-06', 'running', '2026-07-06T22:00:00+08:00')
            """
        )


def test_migrate_metrics_collection_schema_deduplicates_execution_dates(tmp_path):
    db_path = tmp_path / "legacy-duplicate-runs.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE contents (content_id TEXT PRIMARY KEY)")
    connection.execute(
        "CREATE TABLE metrics (content_id TEXT PRIMARY KEY, updated_at TEXT NOT NULL)"
    )
    connection.execute(
        """
        CREATE TABLE metrics_collection_runs (
            scheduled_date TEXT PRIMARY KEY,
            execution_date TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            exported_rows INTEGER NOT NULL DEFAULT 0,
            updated_rows INTEGER NOT NULL DEFAULT 0,
            skipped_rows INTEGER NOT NULL DEFAULT 0,
            ambiguous_rows INTEGER NOT NULL DEFAULT 0,
            matched_post_ids INTEGER NOT NULL DEFAULT 0,
            error_summary TEXT
        )
        """
    )
    connection.execute(
        """
        INSERT INTO metrics_collection_runs
            (scheduled_date, execution_date, status, started_at, completed_at)
        VALUES
            (
                '2026-07-05',
                '2026-07-06',
                'failed',
                '2026-07-06T09:00:00+08:00',
                '2026-07-06T09:05:00+08:00'
            ),
            (
                '2026-07-06',
                '2026-07-06',
                'success',
                '2026-07-06T22:00:00+08:00',
                '2026-07-06T22:05:00+08:00'
            )
        """
    )
    connection.commit()

    migrate_metrics_collection_schema(connection)

    rows = connection.execute(
        """
        SELECT scheduled_date, execution_date, status
        FROM metrics_collection_runs
        ORDER BY scheduled_date
        """
    ).fetchall()
    assert rows == [("2026-07-06", "2026-07-06", "success")]
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO metrics_collection_runs(
                scheduled_date,
                execution_date,
                status,
                started_at
            )
            VALUES ('2026-07-07', '2026-07-06', 'running', '2026-07-07T09:00:00+08:00')
            """
        )


def test_init_db_adds_missing_legacy_run_ledger_columns(tmp_path):
    db_path = tmp_path / "legacy-run-columns.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE contents (content_id TEXT PRIMARY KEY)")
    connection.execute(
        "CREATE TABLE metrics (content_id TEXT PRIMARY KEY, updated_at TEXT NOT NULL)"
    )
    connection.execute(
        """
        CREATE TABLE metrics_collection_runs (
            scheduled_date TEXT PRIMARY KEY,
            execution_date TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    connection.close()

    manager = XHSMemoryManager(db_path)
    manager.init_db(SCHEMA_PATH)

    assert _table_columns(manager.connect(), "metrics_collection_runs") == [
        "scheduled_date",
        "execution_date",
        "status",
        "started_at",
        "completed_at",
        "exported_rows",
        "updated_rows",
        "skipped_rows",
        "ambiguous_rows",
        "matched_post_ids",
        "error_summary",
    ]
    manager.start_collection_run("2026-07-05", "2026-07-06")
    manager.finish_collection_run(
        {
            "scheduled_date": "2026-07-05",
            "execution_date": "2026-07-06",
            "status": "failed",
            "exported_rows": 1,
            "updated_rows": 0,
            "skipped_rows": 1,
            "ambiguous_rows": 0,
            "matched_post_ids": 0,
            "error_summary": "safe",
        }
    )
    row = manager.connect().execute(
        """
        SELECT status, completed_at, exported_rows, error_summary
        FROM metrics_collection_runs
        WHERE scheduled_date = '2026-07-05'
        """
    ).fetchone()
    assert row[0] == "failed"
    assert row[1] is not None
    assert row[2:] == (1, "safe")


def test_fresh_schema_includes_metrics_collection_tables(tmp_path):
    db_path = tmp_path / "fresh-metrics.db"
    connection = sqlite3.connect(db_path)
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert {
        "impressions",
        "cover_click_rate",
        "avg_watch_time_seconds",
        "danmaku_count",
    } <= set(_table_columns(connection, "metrics"))
    assert _table_exists(connection, "metrics_history")
    assert set(_table_columns(connection, "metrics_history")) == {
        "content_id",
        "collected_date",
        "source",
        "impressions",
        "views",
        "cover_click_rate",
        "likes",
        "saves",
        "comments",
        "shares",
        "followers_gained",
        "avg_watch_time_seconds",
        "danmaku_count",
        "like_rate",
        "save_rate",
        "comment_rate",
        "share_rate",
        "engagement_rate",
        "performance_level",
        "collected_at",
    }
    assert _primary_key_columns(connection, "metrics_history") == [
        "content_id",
        "collected_date",
    ]
    history_details = _column_details(connection, "metrics_history")
    assert history_details["content_id"] == ("TEXT", True, None)
    assert history_details["collected_date"] == ("TEXT", True, None)
    assert history_details["source"] == ("TEXT", True, None)
    assert history_details["collected_at"] == ("TEXT", True, None)
    assert (
        "contents",
        "content_id",
        "content_id",
        "CASCADE",
    ) in _foreign_keys(connection, "metrics_history")
    assert _table_exists(connection, "metrics_collection_runs")
    assert _table_columns(connection, "metrics_collection_runs") == [
        "scheduled_date",
        "execution_date",
        "status",
        "started_at",
        "completed_at",
        "exported_rows",
        "updated_rows",
        "skipped_rows",
        "ambiguous_rows",
        "matched_post_ids",
        "error_summary",
    ]
    assert _primary_key_columns(connection, "metrics_collection_runs") == [
        "scheduled_date"
    ]
    assert (
        "idx_metrics_collection_runs_execution_date"
        in _index_names(connection, "metrics_collection_runs")
    )
    assert _index_columns(
        connection,
        "idx_metrics_collection_runs_execution_date",
    ) == ["execution_date"]
    run_details = _column_details(connection, "metrics_collection_runs")
    for required_column in ("execution_date", "status", "started_at"):
        assert run_details[required_column][1] is True
    for counter_column in (
        "exported_rows",
        "updated_rows",
        "skipped_rows",
        "ambiguous_rows",
        "matched_post_ids",
    ):
        assert run_details[counter_column] == ("INTEGER", True, "0")


def test_migrate_metrics_collection_schema_rolls_back_on_failure(tmp_path):
    db_path = tmp_path / "metrics-rollback.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE contents (content_id TEXT PRIMARY KEY)")
    connection.execute(
        "CREATE TABLE metrics (content_id TEXT PRIMARY KEY, updated_at TEXT NOT NULL)"
    )
    connection.commit()

    class FailingConnection:
        def __init__(self, inner: sqlite3.Connection):
            self.inner = inner

        def execute(self, sql, params=()):
            normalized_sql = " ".join(sql.split()).upper()
            if normalized_sql.startswith(
                "CREATE TABLE IF NOT EXISTS METRICS_COLLECTION_RUNS"
            ):
                raise RuntimeError("boom")
            return self.inner.execute(sql, params)

        def __getattr__(self, name):
            return getattr(self.inner, name)

    with pytest.raises(RuntimeError, match="boom"):
        migrate_metrics_collection_schema(FailingConnection(connection))

    assert _table_columns(connection, "metrics") == ["content_id", "updated_at"]
    assert not _table_exists(connection, "metrics_history")
    assert not _table_exists(connection, "metrics_collection_runs")


def test_init_db_runs_schema_then_migration_on_legacy_database(tmp_path):
    db_path = tmp_path / "manager.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE contents (content_id TEXT PRIMARY KEY, topic TEXT NOT NULL)")
    connection.execute(
        "CREATE TABLE metrics (content_id TEXT PRIMARY KEY, updated_at TEXT NOT NULL)"
    )
    connection.execute("INSERT INTO contents(content_id, topic) VALUES (?, ?)", ("c3", "面膜"))
    connection.commit()
    connection.close()

    manager = XHSMemoryManager(db_path)
    manager.init_db(SCHEMA_PATH)

    row = manager.connect().execute(
        """
        SELECT domain, subdomain, content_intent, profile_version, risk_level
        FROM contents
        WHERE content_id = ?
        """,
        ("c3",),
    ).fetchone()

    assert tuple(row) == ("beauty", "skincare", None, "legacy-v1", "low")
    assert {
        "impressions",
        "cover_click_rate",
        "avg_watch_time_seconds",
        "danmaku_count",
    } <= set(_table_columns(manager.connect(), "metrics"))


def test_init_db_deduplicates_legacy_post_ids_before_unique_index(tmp_path):
    db_path = tmp_path / "duplicate-post-ids.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE contents (
            content_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            published_at TEXT,
            post_id TEXT,
            url TEXT,
            topic TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE TABLE metrics (content_id TEXT PRIMARY KEY, updated_at TEXT NOT NULL)"
    )
    connection.executemany(
        """
        INSERT INTO contents(
            content_id, status, created_at, published_at, post_id, url, topic
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "older-draft",
                "generated",
                "2026-07-01T10:00:00+08:00",
                None,
                "duplicate-post",
                "https://www.xiaohongshu.com/explore/duplicate-post",
                "旧草稿",
            ),
            (
                "published-winner",
                "published",
                "2026-07-02T10:00:00+08:00",
                "2026-07-03T10:00:00+08:00",
                "duplicate-post",
                "https://www.xiaohongshu.com/explore/duplicate-post",
                "已发布",
            ),
            (
                "unique",
                "published",
                "2026-07-04T10:00:00+08:00",
                "2026-07-04T12:00:00+08:00",
                "unique-post",
                "https://www.xiaohongshu.com/explore/unique-post",
                "唯一",
            ),
        ],
    )
    connection.commit()
    connection.close()

    manager = XHSMemoryManager(db_path)
    manager.init_db(SCHEMA_PATH)
    manager.init_db(SCHEMA_PATH)

    rows = {
        row["content_id"]: dict(row)
        for row in manager.connect().execute(
            """
            SELECT content_id, post_id, url
            FROM contents
            ORDER BY content_id
            """
        )
    }
    assert rows["published-winner"]["post_id"] == "duplicate-post"
    assert rows["published-winner"]["url"] == (
        "https://www.xiaohongshu.com/explore/duplicate-post"
    )
    assert rows["older-draft"] == {
        "content_id": "older-draft",
        "post_id": None,
        "url": None,
    }
    assert rows["unique"]["post_id"] == "unique-post"
    assert "idx_contents_unique_post_id" in _index_names(manager.connect())


def test_init_db_rolls_back_all_schema_changes_when_metrics_migration_fails(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "atomic-init.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE contents (content_id TEXT PRIMARY KEY)")
    connection.execute(
        "CREATE TABLE metrics (content_id TEXT PRIMARY KEY, updated_at TEXT NOT NULL)"
    )
    connection.commit()
    connection.close()

    class FailingConnection:
        def __init__(self, inner: sqlite3.Connection):
            self.inner = inner
            self.metric_alter_calls = 0

        def execute(self, sql, params=()):
            normalized_sql = " ".join(sql.split()).upper()
            if normalized_sql.startswith("ALTER TABLE METRICS ADD COLUMN"):
                self.metric_alter_calls += 1
                if self.metric_alter_calls == 2:
                    raise RuntimeError("metric alter failed")
            return self.inner.execute(sql, params)

        def __getattr__(self, name):
            return getattr(self.inner, name)

    def fail_during_metrics_migration(connection):
        migrate_metrics_collection_schema(FailingConnection(connection))

    monkeypatch.setattr(
        "memory.memory_manager.migrate_metrics_collection_schema",
        fail_during_metrics_migration,
    )

    manager = XHSMemoryManager(db_path)
    with pytest.raises(RuntimeError, match="metric alter failed"):
        manager.init_db(SCHEMA_PATH)

    connection = manager.connect()
    assert _table_columns(connection, "contents") == ["content_id"]
    assert _table_columns(connection, "metrics") == ["content_id", "updated_at"]
    assert not _table_exists(connection, "metrics_history")
    assert not _table_exists(connection, "metrics_collection_runs")
