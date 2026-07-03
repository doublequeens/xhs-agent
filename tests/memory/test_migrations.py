from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from memory.migrations import migrate_contents_domain_fields
from memory.memory_manager import XHSMemoryManager


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "memory" / "schema.sql"


def _table_columns(connection: sqlite3.Connection) -> list[str]:
    return [row[1] for row in connection.execute("PRAGMA table_info(contents)")]


def _index_names(connection: sqlite3.Connection) -> set[str]:
    return {row[1] for row in connection.execute("PRAGMA index_list(contents)")}


def test_migrate_contents_domain_fields_is_idempotent_and_backfills_legacy_rows(tmp_path):
    db_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE contents (content_id TEXT PRIMARY KEY, topic TEXT NOT NULL)")
    connection.execute("INSERT INTO contents(content_id, topic) VALUES (?, ?)", ("c1", "防晒"))
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


def test_init_db_runs_schema_then_migration_on_legacy_database(tmp_path):
    db_path = tmp_path / "manager.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE contents (content_id TEXT PRIMARY KEY, topic TEXT NOT NULL)")
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
