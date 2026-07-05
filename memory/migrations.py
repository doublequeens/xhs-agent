from __future__ import annotations

import sqlite3


DOMAIN_COLUMNS: dict[str, str] = {
    "domain": "TEXT",
    "subdomain": "TEXT",
    "content_intent": "TEXT",
    "profile_version": "TEXT",
    "risk_level": "TEXT",
}

LEGACY_DOMAIN_DEFAULTS = {
    "domain": "beauty",
    "subdomain": "skincare",
    "profile_version": "legacy-v1",
    "risk_level": "low",
}

METRICS_COLLECTION_COLUMNS: dict[str, str] = {
    "impressions": "INTEGER",
    "cover_click_rate": "REAL",
    "avg_watch_time_seconds": "INTEGER",
    "danmaku_count": "INTEGER",
}


def _existing_columns(
    connection: sqlite3.Connection, table_name: str = "contents"
) -> set[str]:
    return {
        row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")
    }


def migrate_contents_domain_fields(connection: sqlite3.Connection) -> None:
    connection.execute("SAVEPOINT migrate_contents_domain_fields")
    try:
        existing_columns = _existing_columns(connection)

        for column_name, column_type in DOMAIN_COLUMNS.items():
            if column_name not in existing_columns:
                connection.execute(f"ALTER TABLE contents ADD COLUMN {column_name} {column_type}")

        connection.execute(
            """
            UPDATE contents
            SET domain = COALESCE(domain, :domain),
                subdomain = COALESCE(subdomain, :subdomain),
                profile_version = COALESCE(profile_version, :profile_version),
                risk_level = COALESCE(risk_level, :risk_level)
            """,
            LEGACY_DOMAIN_DEFAULTS,
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_contents_domain_subdomain
            ON contents(domain, subdomain)
            """
        )
        if "created_at" in _existing_columns(connection):
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_contents_domain_subdomain_created_at
                ON contents(domain, subdomain, created_at DESC)
                """
            )
    except Exception:
        connection.execute("ROLLBACK TO migrate_contents_domain_fields")
        connection.execute("RELEASE migrate_contents_domain_fields")
        raise
    else:
        connection.execute("RELEASE migrate_contents_domain_fields")


def migrate_metrics_collection_schema(connection: sqlite3.Connection) -> None:
    connection.execute("SAVEPOINT migrate_metrics_collection_schema")
    try:
        existing_columns = _existing_columns(connection, "metrics")

        for column_name, column_type in METRICS_COLLECTION_COLUMNS.items():
            if column_name not in existing_columns:
                connection.execute(
                    f"ALTER TABLE metrics ADD COLUMN {column_name} {column_type}"
                )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS metrics_history (
                content_id TEXT NOT NULL,
                collected_date TEXT NOT NULL,
                source TEXT NOT NULL,
                impressions INTEGER,
                views INTEGER,
                cover_click_rate REAL,
                likes INTEGER,
                saves INTEGER,
                comments INTEGER,
                shares INTEGER,
                followers_gained INTEGER,
                avg_watch_time_seconds INTEGER,
                danmaku_count INTEGER,
                like_rate REAL,
                save_rate REAL,
                comment_rate REAL,
                share_rate REAL,
                engagement_rate REAL,
                performance_level TEXT,
                collected_at TEXT NOT NULL,
                PRIMARY KEY (content_id, collected_date),
                FOREIGN KEY (content_id) REFERENCES contents(content_id)
                    ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS metrics_collection_runs (
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
    except Exception:
        connection.execute("ROLLBACK TO migrate_metrics_collection_schema")
        connection.execute("RELEASE migrate_metrics_collection_schema")
        raise
    else:
        connection.execute("RELEASE migrate_metrics_collection_schema")
