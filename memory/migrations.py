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


def _existing_columns(connection: sqlite3.Connection) -> set[str]:
    return {row[1] for row in connection.execute("PRAGMA table_info(contents)")}


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
