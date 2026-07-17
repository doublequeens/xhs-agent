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

VISUAL_SIGNATURE_COLUMNS: dict[str, str] = {
    "narrative_form": "TEXT",
    "narrative_signature": "TEXT",
    "template_family": "TEXT",
    "frame_plan_signature": "TEXT",
    "density_profile": "TEXT",
}

METRICS_COLLECTION_COLUMNS: dict[str, str] = {
    "impressions": "INTEGER",
    "cover_click_rate": "REAL",
    "avg_watch_time_seconds": "INTEGER",
    "danmaku_count": "INTEGER",
}

METRICS_COLLECTION_RUN_COLUMNS: dict[str, str] = {
    "completed_at": "TEXT",
    "exported_rows": "INTEGER NOT NULL DEFAULT 0",
    "updated_rows": "INTEGER NOT NULL DEFAULT 0",
    "skipped_rows": "INTEGER NOT NULL DEFAULT 0",
    "ambiguous_rows": "INTEGER NOT NULL DEFAULT 0",
    "matched_post_ids": "INTEGER NOT NULL DEFAULT 0",
    "error_summary": "TEXT",
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


def migrate_contents_visual_signature_fields(connection: sqlite3.Connection) -> None:
    """Add the v2 visual-signature columns to legacy ``contents`` tables.

    Mirrors ``migrate_contents_domain_fields``: idempotent, single SAVEPOINT,
    no destructive actions. Five columns store the persisted v2 plan identity
    (``narrative_form``/``template_family``) plus the JSON-encoded signatures
    (``narrative_signature``/``frame_plan_signature``/``density_profile``).
    """

    connection.execute("SAVEPOINT migrate_contents_visual_signature_fields")
    try:
        existing_columns = _existing_columns(connection)
        for column_name, column_type in VISUAL_SIGNATURE_COLUMNS.items():
            if column_name not in existing_columns:
                connection.execute(
                    f"ALTER TABLE contents ADD COLUMN {column_name} {column_type}"
                )
    except Exception:
        connection.execute("ROLLBACK TO migrate_contents_visual_signature_fields")
        connection.execute("RELEASE migrate_contents_visual_signature_fields")
        raise
    else:
        connection.execute("RELEASE migrate_contents_visual_signature_fields")


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
        existing_run_columns = _existing_columns(connection, "metrics_collection_runs")
        for column_name, column_type in METRICS_COLLECTION_RUN_COLUMNS.items():
            if column_name not in existing_run_columns:
                connection.execute(
                    "ALTER TABLE metrics_collection_runs "
                    f"ADD COLUMN {column_name} {column_type}"
                )
        connection.execute(
            """
            DELETE FROM metrics_collection_runs
            WHERE rowid IN (
                SELECT rowid
                FROM (
                    SELECT
                        rowid,
                        ROW_NUMBER() OVER (
                            PARTITION BY execution_date
                            ORDER BY
                                CASE
                                    WHEN status IN ('success', 'partial_success')
                                    THEN 0
                                    ELSE 1
                                END,
                                CASE
                                    WHEN completed_at IS NOT NULL
                                    THEN 0
                                    ELSE 1
                                END,
                                COALESCE(completed_at, '') DESC,
                                COALESCE(started_at, '') DESC,
                                rowid DESC
                        ) AS duplicate_rank
                    FROM metrics_collection_runs
                )
                WHERE duplicate_rank > 1
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                idx_metrics_collection_runs_execution_date
            ON metrics_collection_runs(execution_date)
            """
        )
    except Exception:
        connection.execute("ROLLBACK TO migrate_metrics_collection_schema")
        connection.execute("RELEASE migrate_metrics_collection_schema")
        raise
    else:
        connection.execute("RELEASE migrate_metrics_collection_schema")


def deduplicate_content_post_ids(connection: sqlite3.Connection) -> None:
    existing_columns = _existing_columns(connection)
    if "post_id" not in existing_columns:
        return

    connection.execute("SAVEPOINT deduplicate_content_post_ids")
    try:
        order_terms: list[str] = []
        if "status" in existing_columns:
            order_terms.append(
                "CASE WHEN status = 'published' THEN 0 ELSE 1 END"
            )
        if "published_at" in existing_columns:
            order_terms.extend(
                [
                    "CASE WHEN published_at IS NOT NULL THEN 0 ELSE 1 END",
                    "COALESCE(published_at, '') DESC",
                ]
            )
        if "created_at" in existing_columns:
            order_terms.append("COALESCE(created_at, '') DESC")
        order_terms.append("content_id ASC")
        set_terms = ["post_id = NULL"]
        if "url" in existing_columns:
            set_terms.append("url = NULL")

        connection.execute(
            f"""
            UPDATE contents
            SET {", ".join(set_terms)}
            WHERE rowid IN (
                SELECT rowid
                FROM (
                    SELECT
                        rowid,
                        ROW_NUMBER() OVER (
                            PARTITION BY post_id
                            ORDER BY {", ".join(order_terms)}
                        ) AS duplicate_rank
                    FROM contents
                    WHERE post_id IS NOT NULL
                )
                WHERE duplicate_rank > 1
            )
            """
        )
    except Exception:
        connection.execute("ROLLBACK TO deduplicate_content_post_ids")
        connection.execute("RELEASE deduplicate_content_post_ids")
        raise
    else:
        connection.execute("RELEASE deduplicate_content_post_ids")


def migrate_topic_generation_schema(connection: sqlite3.Connection) -> None:
    connection.execute("SAVEPOINT migrate_topic_generation_schema")
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS trend_signals (
                signal_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_url TEXT,
                raw_title TEXT,
                normalized_signal TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                signal_name TEXT NOT NULL,
                domain TEXT NOT NULL,
                subdomain TEXT NOT NULL,
                why_now TEXT NOT NULL,
                domain_translation TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                avoid_topics TEXT NOT NULL DEFAULT '[]',
                confidence REAL NOT NULL,
                active_from TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                collected_at TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_trend_signals_scope_active
            ON trend_signals(domain, subdomain, active_from, expires_at)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS trend_collection_runs (
                collection_date TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                collected_signals INTEGER NOT NULL DEFAULT 0,
                error_summary TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS topic_generation_traces (
                run_id TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                subdomain TEXT NOT NULL,
                trends_num INTEGER NOT NULL,
                signals_used TEXT NOT NULL,
                creative_briefs_sampled TEXT NOT NULL,
                generated_candidates_count INTEGER NOT NULL,
                filtered_candidates_count INTEGER NOT NULL,
                final_trends TEXT NOT NULL,
                diversity_metrics TEXT NOT NULL,
                degraded_reason TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
    except Exception:
        connection.execute("ROLLBACK TO migrate_topic_generation_schema")
        connection.execute("RELEASE migrate_topic_generation_schema")
        raise
    else:
        connection.execute("RELEASE migrate_topic_generation_schema")
