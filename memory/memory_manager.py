from __future__ import annotations

import json
import sqlite3
import uuid
import threading
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any, Iterator, Optional

from memory.migrations import (
    deduplicate_content_post_ids,
    migrate_contents_domain_fields,
    migrate_metrics_collection_schema,
)
from memory.models import ContentRecord, MetricsRecord, MemoryContext

VECTOR_DOMAIN_BACKFILL_EVENT = "vector_domain_backfill_v1"
_INIT_DB_SAVEPOINT = "initialize_database"
_TERMINAL_COLLECTION_STATUSES = {
    "success",
    "partial_success",
    "auth_required",
    "verification_required",
    "access_blocked",
    "blocked",
    "failed",
}
_COLLECTION_COUNTER_FIELDS = (
    "exported_rows",
    "updated_rows",
    "skipped_rows",
    "ambiguous_rows",
    "matched_post_ids",
)


class CollectionRunAlreadyClaimed(RuntimeError):
    pass

def utc_now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def json_loads(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _insert_event(
    connection: sqlite3.Connection,
    event_id: str,
    content_id: Optional[str],
    event_type: str,
    event_time: str,
    payload: Optional[dict[str, Any]],
) -> None:
    connection.execute(
        """
        INSERT INTO memory_events (
            event_id, content_id, event_type, event_time, payload_json
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            event_id,
            content_id,
            event_type,
            event_time,
            json_dumps(payload or {}),
        ),
    )


_CONTENT_INDEXES: list[tuple[str, tuple[str, ...], str]] = [
    ("idx_contents_created_at", ("created_at",), "CREATE INDEX IF NOT EXISTS idx_contents_created_at ON contents(created_at)"),
    ("idx_contents_published_at", ("published_at",), "CREATE INDEX IF NOT EXISTS idx_contents_published_at ON contents(published_at)"),
    ("idx_contents_topic", ("topic",), "CREATE INDEX IF NOT EXISTS idx_contents_topic ON contents(topic)"),
    ("idx_contents_angle", ("angle",), "CREATE INDEX IF NOT EXISTS idx_contents_angle ON contents(angle)"),
    ("idx_contents_domain_subdomain", ("domain", "subdomain"), "CREATE INDEX IF NOT EXISTS idx_contents_domain_subdomain ON contents(domain, subdomain)"),
    (
        "idx_contents_domain_subdomain_created_at",
        ("domain", "subdomain", "created_at"),
        "CREATE INDEX IF NOT EXISTS idx_contents_domain_subdomain_created_at ON contents(domain, subdomain, created_at DESC)",
    ),
    (
        "idx_contents_unique_post_id",
        ("post_id",),
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_contents_unique_post_id ON contents(post_id) WHERE post_id IS NOT NULL",
    ),
]

_METRICS_INDEXES: list[tuple[str, tuple[str, ...], str]] = [
    ("idx_metrics_performance_level", ("performance_level",), "CREATE INDEX IF NOT EXISTS idx_metrics_performance_level ON metrics(performance_level)"),
    ("idx_metrics_engagement_rate", ("engagement_rate",), "CREATE INDEX IF NOT EXISTS idx_metrics_engagement_rate ON metrics(engagement_rate)"),
]


class XHSMemoryManager:
    connections: dict[tuple[Path, int], sqlite3.Connection] = {}
    _connections_lock = threading.RLock()

    def __init__(self, db_path: str | Path = "data/xhs_memory.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        key = self._connection_key()
        with self._connections_lock:
            connection = self.connections.get(key)
            if connection is None:
                connection = sqlite3.connect(
                    key[0],
                    check_same_thread=False,
                    timeout=30.0,
                )
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys = ON;")
                connection.execute("PRAGMA busy_timeout = 30000;")
                try:
                    connection.execute("PRAGMA journal_mode = WAL;")
                except sqlite3.OperationalError:
                    pass
                self.connections[key] = connection
        return connection

    def close(self) -> None:
        self.close_path(self.db_path)

    @classmethod
    def close_path(cls, db_path: str | Path) -> None:
        resolved_path = Path(db_path).resolve()
        with cls._connections_lock:
            matching_keys = [key for key in cls.connections if key[0] == resolved_path]
            connections = [cls.connections.pop(key) for key in matching_keys]

        for connection in connections:
            connection.close()

    @classmethod
    def close_all(cls) -> None:
        with cls._connections_lock:
            connections = list(cls.connections.values())
            cls.connections.clear()

        for connection in connections:
            connection.close()

    def init_db(self, schema_path: str | Path = "memory/schema.sql") -> None:
        schema_path = Path(schema_path)
        statements = [
            statement.strip()
            for statement in schema_path.read_text(encoding="utf-8").split(";")
            if statement.strip()
        ]
        with self.connect() as conn:
            for statement in statements:
                if statement.upper().startswith("PRAGMA "):
                    conn.execute(statement)

            conn.execute(f"SAVEPOINT {_INIT_DB_SAVEPOINT}")
            try:
                for statement in statements:
                    if statement.upper().startswith("CREATE TABLE"):
                        conn.execute(statement)
                migrate_contents_domain_fields(conn)
                migrate_metrics_collection_schema(conn)
                deduplicate_content_post_ids(conn)
                self._create_required_indexes(conn)
            except Exception:
                conn.execute(f"ROLLBACK TO {_INIT_DB_SAVEPOINT}")
                conn.execute(f"RELEASE {_INIT_DB_SAVEPOINT}")
                raise
            else:
                conn.execute(f"RELEASE {_INIT_DB_SAVEPOINT}")

    def _create_required_indexes(self, connection: sqlite3.Connection) -> None:
        existing_columns = self._table_columns(connection)
        for _, required_columns, sql in _CONTENT_INDEXES:
            if all(column in existing_columns for column in required_columns):
                connection.execute(sql)

        metrics_columns = self._table_columns(connection, table_name="metrics")
        for _, required_columns, sql in _METRICS_INDEXES:
            if all(column in metrics_columns for column in required_columns):
                connection.execute(sql)

    def _table_columns(self, connection: sqlite3.Connection, table_name: str = "contents") -> set[str]:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")}

    def _connection_key(self) -> tuple[Path, int]:
        return (self.db_path.resolve(), threading.get_ident())

    @contextmanager
    def _immediate_transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        if connection.in_transaction:
            raise RuntimeError("Cannot start an immediate transaction while one is active")

        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()

    def log_event(
        self,
        event_type: str,
        content_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> str:
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        with self.connect() as conn:
            _insert_event(conn, event_id, content_id, event_type, utc_now_iso(), payload)
        return event_id

    def save_generated_content(self, record: ContentRecord) -> None:
        """
        在内容生成完成或 Human Review 通过后写入。
        建议：只有 Human Review approved 后才写正式 memory。
        """
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO contents (
                    content_id,
                    status,
                    platform,
                    created_at,
                    reviewed_at,
                    published_at,
                    post_id,
                    url,
                    topic_id,
                    topic,
                    angle_id,
                    angle,
                    domain,
                    subdomain,
                    content_intent,
                    profile_version,
                    risk_level,
                    target_group,
                    core_pain,
                    title,
                    cover_copy,
                    content,
                    hashtags_json,
                    content_format,
                    visual_style,
                    card_count,
                    storyboards,
                    image_paths_json,
                    strategy_tags_json,
                    compliance_status,
                    embedding_text,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(content_id) DO UPDATE SET
                    status = CASE
                        WHEN contents.post_id IS NOT NULL THEN contents.status
                        ELSE excluded.status
                    END,
                    platform = excluded.platform,
                    created_at = excluded.created_at,
                    reviewed_at = excluded.reviewed_at,
                    published_at = contents.published_at,
                    post_id = contents.post_id,
                    url = contents.url,
                    topic_id = excluded.topic_id,
                    topic = excluded.topic,
                    angle_id = excluded.angle_id,
                    angle = excluded.angle,
                    domain = excluded.domain,
                    subdomain = excluded.subdomain,
                    content_intent = excluded.content_intent,
                    profile_version = excluded.profile_version,
                    risk_level = excluded.risk_level,
                    target_group = excluded.target_group,
                    core_pain = excluded.core_pain,
                    title = excluded.title,
                    cover_copy = excluded.cover_copy,
                    content = excluded.content,
                    hashtags_json = excluded.hashtags_json,
                    content_format = excluded.content_format,
                    visual_style = excluded.visual_style,
                    card_count = excluded.card_count,
                    storyboards = excluded.storyboards,
                    image_paths_json = excluded.image_paths_json,
                    strategy_tags_json = excluded.strategy_tags_json,
                    compliance_status = excluded.compliance_status,
                    embedding_text = excluded.embedding_text,
                    metadata_json = excluded.metadata_json
                """,
                (
                    record.content_id,
                    record.status,
                    record.platform,
                    record.created_at,
                    record.reviewed_at,
                    record.published_at,
                    record.post_id,
                    record.url,
                    record.topic_id,
                    record.topic,
                    record.angle_id,
                    record.angle,
                    record.domain,
                    record.subdomain,
                    record.content_intent,
                    record.profile_version,
                    record.risk_level,
                    record.target_group,
                    record.core_pain,
                    record.title,
                    record.cover_copy,
                    record.content,
                    json_dumps(record.hashtags),
                    record.content_format,
                    record.visual_style,
                    record.card_count,
                    json_dumps(record.storyboards),
                    json_dumps(record.image_paths),
                    json_dumps(record.strategy_tags),
                    record.compliance_status,
                    record.embedding_text,
                    json_dumps(record.metadata),
                ),
            )
            _insert_event(
                conn,
                f"evt_{uuid.uuid4().hex[:12]}",
                record.content_id,
                "content_saved",
                utc_now_iso(),
                {
                    "topic": record.topic,
                    "angle": record.angle,
                    "title": record.title,
                    "status": record.status,
                },
            )
    
    def save_embedding_content(
        self,
        record: ContentRecord,
        *,
        vector_memory=None,
        build_embedding_text_fn=None,
    ) -> None:
        vector_memory = vector_memory or self._create_vector_memory()
        build_embedding_text_fn = build_embedding_text_fn or self._build_embedding_text

        embedding_text = record.embedding_text or build_embedding_text_fn(
            topic=record.topic,
            angle=record.angle,
            title=record.title,
            target_group=record.target_group,
            core_pain=record.core_pain,
            hashtags=record.hashtags,
        )

        metadata = self._build_vector_metadata(
            {
                "content_id": record.content_id,
                "status": record.status,
                "topic": record.topic,
                "angle": record.angle,
                "title": record.title,
                "target_group": record.target_group,
                "created_at": record.created_at,
                "published_at": record.published_at,
                "domain": record.domain,
                "subdomain": record.subdomain,
                "content_intent": record.content_intent,
                "profile_version": record.profile_version,
                "risk_level": record.risk_level,
            }
        )
        vector_memory.upsert_content(
            content_id=record.content_id,
            embedding_text=embedding_text,
            metadata=metadata,
        )

    def sync_content_to_vector_memory(
        self,
        content_id: str,
        *,
        vector_memory=None,
        build_embedding_text_fn=None,
    ) -> None:
        vector_memory = vector_memory or self._create_vector_memory()
        build_embedding_text_fn = build_embedding_text_fn or self._build_embedding_text

        row = self._get_vector_sync_row(content_id)
        if row is None:
            raise ValueError(f"No content found with content_id: {content_id}")

        self._upsert_vector_row(
            row,
            vector_memory=vector_memory,
            build_embedding_text_fn=build_embedding_text_fn,
        )

    def ensure_vector_scope_backfill(
        self,
        *,
        vector_memory=None,
        build_embedding_text_fn=None,
    ) -> bool:
        build_embedding_text_fn = build_embedding_text_fn or self._build_embedding_text
        with self.connect() as conn:
            marker = conn.execute(
                """
                SELECT 1
                FROM memory_events
                WHERE event_type = ?
                LIMIT 1
                """,
                (VECTOR_DOMAIN_BACKFILL_EVENT,),
            ).fetchone()
            if marker is not None:
                return False

            rows = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT
                        c.content_id,
                        c.status,
                        c.topic,
                        c.angle,
                        c.title,
                        c.target_group,
                        c.core_pain,
                        c.created_at,
                        c.published_at,
                        c.hashtags_json,
                        c.embedding_text,
                        c.domain,
                        c.subdomain,
                        c.content_intent,
                        c.profile_version,
                        c.risk_level,
                        m.views,
                        m.likes,
                        m.saves,
                        m.comments,
                        m.shares,
                        m.followers_gained,
                        m.save_rate,
                        m.engagement_rate,
                        m.performance_level
                    FROM contents c
                    LEFT JOIN metrics m ON c.content_id = m.content_id
                    ORDER BY c.created_at ASC, c.content_id ASC
                    """
                ).fetchall()
            ]

        if vector_memory is None and rows:
            vector_memory = self._create_vector_memory()

        if not rows:
            return False

        for row in rows:
            self._upsert_vector_row(
                row,
                vector_memory=vector_memory,
                build_embedding_text_fn=build_embedding_text_fn,
            )

        with self.connect() as conn:
            marker = conn.execute(
                """
                SELECT 1
                FROM memory_events
                WHERE event_type = ?
                LIMIT 1
                """,
                (VECTOR_DOMAIN_BACKFILL_EVENT,),
            ).fetchone()
            if marker is not None:
                return False

            _insert_event(
                conn,
                f"evt_{uuid.uuid4().hex[:12]}",
                None,
                VECTOR_DOMAIN_BACKFILL_EVENT,
                utc_now_iso(),
                {"rows_backfilled": len(rows)},
            )
        return True

    def get_embedding_content_by_id(self, content_id: str) -> bool:
        vector_memory = self._create_vector_memory()
        result = vector_memory.collection.get(ids=[content_id])
        
        return len(result["ids"]) > 0
    
    def delete_content_by_id(self, content_id: str) -> None:
        with self.connect() as conn:
            _delete_result = conn.execute(
                """
                DELETE FROM contents
                WHERE content_id = ?
                """,
                (content_id,),
            )
            _insert_event(
                conn,
                f"evt_{uuid.uuid4().hex[:12]}",
                None,
                "content_deleted",
                utc_now_iso(),
                {"deleted_content_id": content_id},
            )

    def mark_reviewed(self, content_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE contents
                SET status = ?, reviewed_at = ?
                WHERE content_id = ?
                """,
                ("reviewed", utc_now_iso(), content_id),
            )
            _insert_event(
                conn,
                f"evt_{uuid.uuid4().hex[:12]}",
                content_id,
                "content_reviewed",
                utc_now_iso(),
                {"content_id": content_id},
            )

    def mark_published(
        self,
        content_id: str,
        post_id: str,
        url: Optional[str] = None,
        published_at: Optional[str] = None,
    ) -> None:
        self.bind_post_identity(
            content_id,
            post_id,
            url,
            published_at or utc_now_iso(),
        )

    def update_metrics(
        self,
        content_id: str,
        views: Optional[int],
        likes: Optional[int],
        saves: Optional[int],
        comments: Optional[int],
        shares: Optional[int] = 0,
        followers_gained: Optional[int] = 0,
        *,
        impressions: Optional[int] = None,
        cover_click_rate: Optional[float] = None,
        avg_watch_time_seconds: Optional[int] = None,
        danmaku_count: Optional[int] = None,
    ) -> MetricsRecord:
        source_record = MetricsRecord(
            content_id=content_id,
            views=views,
            likes=likes,
            saves=saves,
            comments=comments,
            shares=shares,
            followers_gained=followers_gained,
            impressions=impressions,
            cover_click_rate=cover_click_rate,
            avg_watch_time_seconds=avg_watch_time_seconds,
            danmaku_count=danmaku_count,
        )

        with self._immediate_transaction() as conn:
            record = self._merge_metrics_record(conn, source_record, utc_now_iso())
            self._upsert_metrics(conn, record)
            self._insert_metrics_updated_event(conn, record)

        return record

    def update_metrics_batch(
        self,
        records: list[MetricsRecord],
        collected_date: str,
        source: str,
    ) -> list[MetricsRecord]:
        collected_at = utc_now_iso()
        merged_records: list[MetricsRecord] = []
        with self._immediate_transaction() as conn:
            for source_record in records:
                merged_record = self._merge_metrics_record(
                    conn,
                    source_record,
                    collected_at,
                )
                self._upsert_metrics(conn, merged_record)
                self._insert_metrics_history(
                    conn,
                    source_record,
                    merged_record,
                    collected_date,
                    source,
                    collected_at,
                )
                self._insert_metrics_updated_event(conn, merged_record)
                merged_records.append(merged_record)
        return merged_records

    def _merge_metrics_record(
        self,
        connection: sqlite3.Connection,
        source_record: MetricsRecord,
        updated_at: str,
    ) -> MetricsRecord:
        existing_row = connection.execute(
            "SELECT * FROM metrics WHERE content_id = ?",
            (source_record.content_id,),
        ).fetchone()
        existing = dict(existing_row) if existing_row is not None else {}

        def merged_value(field_name: str):
            source_value = getattr(source_record, field_name)
            return source_value if source_value is not None else existing.get(field_name)

        views = merged_value("views")
        likes = merged_value("likes")
        saves = merged_value("saves")
        comments = merged_value("comments")
        shares = merged_value("shares")
        calculation_values = {
            "views": views or 0,
            "likes": likes or 0,
            "saves": saves or 0,
            "comments": comments or 0,
            "shares": shares or 0,
        }
        rates = self._calculate_rates(**calculation_values)
        performance_level = self._classify_performance(
            views=calculation_values["views"],
            save_rate=rates["save_rate"],
            engagement_rate=rates["engagement_rate"],
        )
        return MetricsRecord(
            content_id=source_record.content_id,
            views=views,
            likes=likes,
            saves=saves,
            comments=comments,
            shares=shares,
            followers_gained=merged_value("followers_gained"),
            like_rate=rates["like_rate"],
            save_rate=rates["save_rate"],
            comment_rate=rates["comment_rate"],
            share_rate=rates["share_rate"],
            engagement_rate=rates["engagement_rate"],
            performance_level=performance_level,
            updated_at=updated_at,
            impressions=merged_value("impressions"),
            cover_click_rate=merged_value("cover_click_rate"),
            avg_watch_time_seconds=merged_value("avg_watch_time_seconds"),
            danmaku_count=merged_value("danmaku_count"),
        )

    def _upsert_metrics(
        self,
        connection: sqlite3.Connection,
        record: MetricsRecord,
    ) -> None:
        connection.execute(
            """
            INSERT INTO metrics (
                content_id,
                impressions,
                views,
                cover_click_rate,
                likes,
                saves,
                comments,
                shares,
                followers_gained,
                avg_watch_time_seconds,
                danmaku_count,
                like_rate,
                save_rate,
                comment_rate,
                share_rate,
                engagement_rate,
                performance_level,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(content_id) DO UPDATE SET
                impressions = COALESCE(excluded.impressions, metrics.impressions),
                views = COALESCE(excluded.views, metrics.views),
                cover_click_rate = COALESCE(
                    excluded.cover_click_rate,
                    metrics.cover_click_rate
                ),
                likes = COALESCE(excluded.likes, metrics.likes),
                saves = COALESCE(excluded.saves, metrics.saves),
                comments = COALESCE(excluded.comments, metrics.comments),
                shares = COALESCE(excluded.shares, metrics.shares),
                followers_gained = COALESCE(
                    excluded.followers_gained,
                    metrics.followers_gained
                ),
                avg_watch_time_seconds = COALESCE(
                    excluded.avg_watch_time_seconds,
                    metrics.avg_watch_time_seconds
                ),
                danmaku_count = COALESCE(
                    excluded.danmaku_count,
                    metrics.danmaku_count
                ),
                like_rate = excluded.like_rate,
                save_rate = excluded.save_rate,
                comment_rate = excluded.comment_rate,
                share_rate = excluded.share_rate,
                engagement_rate = excluded.engagement_rate,
                performance_level = excluded.performance_level,
                updated_at = excluded.updated_at
            """,
            (
                record.content_id,
                record.impressions,
                record.views,
                record.cover_click_rate,
                record.likes,
                record.saves,
                record.comments,
                record.shares,
                record.followers_gained,
                record.avg_watch_time_seconds,
                record.danmaku_count,
                record.like_rate,
                record.save_rate,
                record.comment_rate,
                record.share_rate,
                record.engagement_rate,
                record.performance_level,
                record.updated_at,
            ),
        )

    def _insert_metrics_history(
        self,
        connection: sqlite3.Connection,
        source_record: MetricsRecord,
        merged_record: MetricsRecord,
        collected_date: str,
        source: str,
        collected_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO metrics_history (
                content_id,
                collected_date,
                source,
                impressions,
                views,
                cover_click_rate,
                likes,
                saves,
                comments,
                shares,
                followers_gained,
                avg_watch_time_seconds,
                danmaku_count,
                like_rate,
                save_rate,
                comment_rate,
                share_rate,
                engagement_rate,
                performance_level,
                collected_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(content_id, collected_date) DO UPDATE SET
                source = excluded.source,
                impressions = excluded.impressions,
                views = excluded.views,
                cover_click_rate = excluded.cover_click_rate,
                likes = excluded.likes,
                saves = excluded.saves,
                comments = excluded.comments,
                shares = excluded.shares,
                followers_gained = excluded.followers_gained,
                avg_watch_time_seconds = excluded.avg_watch_time_seconds,
                danmaku_count = excluded.danmaku_count,
                like_rate = excluded.like_rate,
                save_rate = excluded.save_rate,
                comment_rate = excluded.comment_rate,
                share_rate = excluded.share_rate,
                engagement_rate = excluded.engagement_rate,
                performance_level = excluded.performance_level,
                collected_at = excluded.collected_at
            """,
            (
                source_record.content_id,
                collected_date,
                source,
                source_record.impressions,
                source_record.views,
                source_record.cover_click_rate,
                source_record.likes,
                source_record.saves,
                source_record.comments,
                source_record.shares,
                source_record.followers_gained,
                source_record.avg_watch_time_seconds,
                source_record.danmaku_count,
                merged_record.like_rate,
                merged_record.save_rate,
                merged_record.comment_rate,
                merged_record.share_rate,
                merged_record.engagement_rate,
                merged_record.performance_level,
                collected_at,
            ),
        )

    def _insert_metrics_updated_event(
        self,
        connection: sqlite3.Connection,
        record: MetricsRecord,
    ) -> None:
        _insert_event(
            connection,
            f"evt_{uuid.uuid4().hex[:12]}",
            record.content_id,
            "metrics_updated",
            utc_now_iso(),
            {
                "views": record.views,
                "likes": record.likes,
                "saves": record.saves,
                "comments": record.comments,
                "shares": record.shares,
                "performance_level": record.performance_level,
                "like_rate": record.like_rate,
                "save_rate": record.save_rate,
                "comment_rate": record.comment_rate,
                "share_rate": record.share_rate,
                "engagement_rate": record.engagement_rate,
            },
        )

    def bind_post_identity(
        self,
        content_id: str,
        post_id: str,
        url: Optional[str],
        published_at: str,
    ) -> None:
        with self._immediate_transaction() as conn:
            target = conn.execute(
                "SELECT post_id FROM contents WHERE content_id = ?",
                (content_id,),
            ).fetchone()
            if target is None:
                raise ValueError(f"No content found with content_id: {content_id}")

            existing_post_id = target["post_id"]
            if existing_post_id == post_id:
                return
            if existing_post_id is not None:
                raise ValueError(
                    f"Content {content_id} is already bound to post_id: "
                    f"{existing_post_id}"
                )

            owner = conn.execute(
                """
                SELECT content_id
                FROM contents
                WHERE post_id = ?
                LIMIT 1
                """,
                (post_id,),
            ).fetchone()
            if owner is not None:
                raise ValueError(
                    f"post_id {post_id} is already bound to another content: "
                    f"{owner['content_id']}"
                )

            result = conn.execute(
                """
                UPDATE contents
                SET status = ?, post_id = ?, url = ?, published_at = ?
                WHERE content_id = ? AND post_id IS NULL
                """,
                ("published", post_id, url, published_at, content_id),
            )
            if result.rowcount != 1:
                raise ValueError(f"Content {content_id} could not be bound")
            _insert_event(
                conn,
                f"evt_{uuid.uuid4().hex[:12]}",
                content_id,
                "content_published",
                utc_now_iso(),
                {"post_id": post_id, "url": url},
            )

    def get_unbound_published_candidates(self) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    content_id,
                    title,
                    COALESCE(NULLIF(published_at, ''), created_at) AS reference_time,
                    post_id
                FROM contents
                WHERE post_id IS NULL
                  AND title IS NOT NULL
                  AND title <> ''
                ORDER BY reference_time
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_metric_match_candidates(self) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    content_id,
                    title,
                    COALESCE(NULLIF(published_at, ''), created_at) AS reference_time,
                    post_id
                FROM contents
                WHERE title IS NOT NULL
                  AND title <> ''
                ORDER BY reference_time
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def start_collection_run(
        self,
        scheduled_date: str,
        execution_date: str,
    ) -> None:
        with self.connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO metrics_collection_runs (
                        scheduled_date,
                        execution_date,
                        status,
                        started_at
                    )
                    VALUES (?, ?, 'running', ?)
                    """,
                    (scheduled_date, execution_date, utc_now_iso()),
                )
            except sqlite3.IntegrityError as error:
                raise CollectionRunAlreadyClaimed(
                    "Collection run already claimed for "
                    f"scheduled_date={scheduled_date}, "
                    f"execution_date={execution_date}"
                ) from error

    def finish_collection_run(self, summary: dict[str, object]) -> None:
        self._validate_collection_summary(summary)
        scheduled_date = summary["scheduled_date"]
        execution_date = summary["execution_date"]
        with self.connect() as conn:
            result = conn.execute(
                """
                UPDATE metrics_collection_runs
                SET status = ?,
                    completed_at = ?,
                    exported_rows = ?,
                    updated_rows = ?,
                    skipped_rows = ?,
                    ambiguous_rows = ?,
                    matched_post_ids = ?,
                    error_summary = ?
                WHERE scheduled_date = ?
                  AND execution_date = ?
                  AND status = 'running'
                """,
                (
                    summary["status"],
                    utc_now_iso(),
                    summary.get("exported_rows", 0),
                    summary.get("updated_rows", 0),
                    summary.get("skipped_rows", 0),
                    summary.get("ambiguous_rows", 0),
                    summary.get("matched_post_ids", 0),
                    summary.get("error_summary"),
                    scheduled_date,
                    execution_date,
                ),
            )
            if result.rowcount != 1:
                raise ValueError(
                    "No matching running collection run found for "
                    f"scheduled_date={scheduled_date}, "
                    f"execution_date={execution_date}"
                )

    def _validate_collection_summary(self, summary: dict[str, object]) -> None:
        for field_name in ("scheduled_date", "execution_date"):
            if not isinstance(summary.get(field_name), str):
                raise TypeError(f"{field_name} must be a string")

        status = summary.get("status")
        if status not in _TERMINAL_COLLECTION_STATUSES:
            raise ValueError(f"Invalid terminal status: {status}")

        for field_name in _COLLECTION_COUNTER_FIELDS:
            value = summary.get(field_name, 0)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be a nonnegative integer")
            if value < 0:
                raise ValueError(f"{field_name} must be a nonnegative integer")

    def has_completed_execution_date(self, execution_date: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM metrics_collection_runs
                WHERE execution_date = ?
                  AND status IN ('success', 'partial_success')
                LIMIT 1
                """,
                (execution_date,),
            ).fetchone()
        return row is not None

    def has_attempted_execution_date(self, execution_date: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM metrics_collection_runs
                WHERE execution_date = ?
                LIMIT 1
                """,
                (execution_date,),
            ).fetchone()
        return row is not None

    def get_metrics(self, content_id: str) -> Optional[dict[str, object]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM metrics WHERE content_id = ?",
                (content_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_metrics_history(self, content_id: str) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM metrics_history
                WHERE content_id = ?
                ORDER BY collected_date
                """,
                (content_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_contents(
        self,
        *,
        domain: str,
        subdomain: str,
        days: int = 14,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        since = (datetime.now(timezone(timedelta(hours=8))) - timedelta(days=days)).isoformat()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    content_id,
                    status,
                    created_at,
                    published_at,
                    topic,
                    angle,
                    title,
                    domain,
                    subdomain,
                    content_intent,
                    profile_version,
                    risk_level,
                    target_group,
                    core_pain,
                    hashtags_json,
                    strategy_tags_json,
                    content_format,
                    visual_style,
                    card_count
                FROM contents
                WHERE created_at >= ?
                  AND domain = ?
                  AND subdomain = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (since, domain, subdomain, limit),
            ).fetchall()

        return [self._content_row_to_dict(row) for row in rows]

    def get_high_performing_contents(
        self,
        *,
        domain: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.content_id,
                    c.topic,
                    c.angle,
                    c.title,
                    c.domain,
                    c.subdomain,
                    c.content_intent,
                    c.profile_version,
                    c.risk_level,
                    c.target_group,
                    c.strategy_tags_json,
                    c.hashtags_json,
                    c.content_format,
                    c.visual_style,
                    c.card_count,
                    m.views,
                    m.likes,
                    m.saves,
                    m.comments,
                    m.shares,
                    m.followers_gained,
                    m.save_rate,
                    m.engagement_rate,
                    m.performance_level
                FROM contents c
                JOIN metrics m ON c.content_id = m.content_id
                WHERE m.performance_level = 'high'
                  AND c.domain = ?
                ORDER BY m.views DESC
                LIMIT ?
                """,
                (domain, limit),
            ).fetchall()

        return [self._performance_row_to_dict(row) for row in rows]

    def get_low_performing_contents(
        self,
        *,
        domain: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.content_id,
                    c.topic,
                    c.angle,
                    c.title,
                    c.domain,
                    c.subdomain,
                    c.content_intent,
                    c.profile_version,
                    c.risk_level,
                    c.target_group,
                    c.strategy_tags_json,
                    c.hashtags_json,
                    c.content_format,
                    c.visual_style,
                    c.card_count,
                    m.views,
                    m.likes,
                    m.saves,
                    m.comments,
                    m.shares,
                    m.followers_gained,
                    m.save_rate,
                    m.engagement_rate,
                    m.performance_level
                FROM contents c
                JOIN metrics m ON c.content_id = m.content_id
                WHERE m.performance_level = 'low'
                  AND c.domain = ?
                ORDER BY m.views ASC
                LIMIT ?
                """,
                (domain, limit),
            ).fetchall()

        return [self._performance_row_to_dict(row) for row in rows]

    def get_global_format_patterns(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.title,
                    c.content_format,
                    c.visual_style,
                    c.card_count,
                    m.views,
                    m.likes,
                    m.saves,
                    m.comments,
                    m.shares,
                    m.followers_gained,
                    m.like_rate,
                    m.save_rate,
                    m.comment_rate,
                    m.share_rate,
                    m.engagement_rate,
                    m.performance_level
                FROM contents c
                JOIN metrics m ON c.content_id = m.content_id
                ORDER BY c.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [dict(row) for row in rows]

    def get_performance_by_domain(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.domain,
                    c.subdomain,
                    c.content_intent,
                    COUNT(*) AS content_count,
                    AVG(m.views) AS avg_views,
                    AVG(m.save_rate) AS avg_save_rate,
                    AVG(m.engagement_rate) AS avg_engagement_rate
                FROM contents c
                JOIN metrics m ON m.content_id = c.content_id
                GROUP BY c.domain, c.subdomain, c.content_intent
                ORDER BY c.domain, c.subdomain, c.content_intent
                """
            ).fetchall()

        return [dict(row) for row in rows]

    def build_memory_context(
        self,
        *,
        domain: str,
        subdomain: str,
        recent_days: int = 14,
        recent_limit: int = 30,
        performance_limit: int = 20,
        global_format_limit: int = 20,
    ) -> MemoryContext:
        recent_contents = self.get_recent_contents(
            domain=domain,
            subdomain=subdomain,
            days=recent_days,
            limit=recent_limit,
        )
        high_contents = self.get_high_performing_contents(domain=domain, limit=performance_limit)
        low_contents = self.get_low_performing_contents(domain=domain, limit=performance_limit)
        global_format_patterns = self.get_global_format_patterns(limit=global_format_limit)

        recent_topics = self._unique_non_empty([x.get("topic") for x in recent_contents])
        recent_angles = self._unique_non_empty([x.get("angle") for x in recent_contents])

        recent_hashtags = []
        for item in recent_contents:
            recent_hashtags.extend(item.get("hashtags", []))
        recent_hashtags = self._unique_non_empty(recent_hashtags)

        return MemoryContext(
            same_subdomain_recent=recent_contents,
            same_domain_patterns=[
                *self._extract_domain_patterns(high_contents, performance_signal="high"),
                *self._extract_domain_patterns(low_contents, performance_signal="low"),
            ],
            global_format_patterns=self._extract_global_format_patterns(global_format_patterns),
            topics_to_avoid=recent_topics,
            angles_to_avoid=recent_angles,
            recent_hashtags=recent_hashtags,
        )

    def get_content_by_id(self, content_id: str) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM contents
                WHERE content_id = ?
                """,
                (content_id,),
            ).fetchone()

        if row is None:
            return None

        data = dict(row)
        data["hashtags"] = json_loads(data.pop("hashtags_json", None), [])
        data["storyboards"] = json_loads(data.pop("storyboards", None), [])
        data["image_paths"] = json_loads(data.pop("image_paths_json", None), [])
        data["strategy_tags"] = json_loads(data.pop("strategy_tags_json", None), [])
        data["metadata"] = json_loads(data.pop("metadata_json", None), {})
        return data

    def _calculate_rates(
        self,
        views: int,
        likes: int,
        saves: int,
        comments: int,
        shares: int,
    ) -> dict[str, float]:
        if views <= 0:
            return {
                "like_rate": 0.0,
                "save_rate": 0.0,
                "comment_rate": 0.0,
                "share_rate": 0.0,
                "engagement_rate": 0.0,
            }

        return {
            "like_rate": likes / views,
            "save_rate": saves / views,
            "comment_rate": comments / views,
            "share_rate": shares / views,
            "engagement_rate": (likes + saves + comments + shares) / views,
        }

    def _classify_performance(
        self,
        views: int,
        save_rate: float,
        engagement_rate: float,
    ) -> str:
        """
        MVP 阶段用固定阈值即可。
        后面可以改成相对分位数：top 25% = high。
        """
        if views < 10:
            return "low"
        if views >= 10 or save_rate >= 0.02 or engagement_rate >= 0.04:
            return "high"
        
        # The flowing code is not suitable for current level of my redbook account, so I just set a simple threshold based on views. 
        # I will implement the more complex logic later when I have more data.

        # if views < 200:
        #     return "unknown"

        # if save_rate >= 0.06 or engagement_rate >= 0.12:
        #     return "high"

        # if save_rate <= 0.015 and engagement_rate <= 0.04:
        #     return "low"

        # return "medium"

    def _content_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["hashtags"] = json_loads(data.pop("hashtags_json", None), [])
        data["strategy_tags"] = json_loads(data.pop("strategy_tags_json", None), [])
        return data

    def _performance_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["hashtags"] = json_loads(data.pop("hashtags_json", None), [])
        data["strategy_tags"] = json_loads(data.pop("strategy_tags_json", None), [])
        return data

    def _extract_domain_patterns(
        self,
        contents: list[dict[str, Any]],
        *,
        performance_signal: str,
    ) -> list[dict[str, Any]]:
        patterns: list[dict[str, Any]] = []
        for item in contents:
            patterns.append(
                {
                    "content_id": item.get("content_id"),
                    "domain": item.get("domain"),
                    "subdomain": item.get("subdomain"),
                    "topic": item.get("topic"),
                    "angle": item.get("angle"),
                    "title": item.get("title"),
                    "content_intent": item.get("content_intent"),
                    "content_format": item.get("content_format"),
                    "visual_style": item.get("visual_style"),
                    "card_count": item.get("card_count"),
                    "strategy_tags": item.get("strategy_tags", []),
                    "views": item.get("views"),
                    "likes": item.get("likes"),
                    "saves": item.get("saves"),
                    "comments": item.get("comments"),
                    "shares": item.get("shares"),
                    "followers_gained": item.get("followers_gained"),
                    "save_rate": item.get("save_rate"),
                    "engagement_rate": item.get("engagement_rate"),
                    "performance_level": item.get("performance_level"),
                    "performance_signal": performance_signal,
                }
            )
        return patterns

    def _extract_global_format_patterns(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        patterns: list[dict[str, Any]] = []
        for item in rows:
            patterns.append(
                {
                    "title": item.get("title"),
                    "content_format": item.get("content_format"),
                    "visual_style": item.get("visual_style"),
                    "card_count": item.get("card_count"),
                    "views": item.get("views"),
                    "likes": item.get("likes"),
                    "saves": item.get("saves"),
                    "comments": item.get("comments"),
                    "shares": item.get("shares"),
                    "followers_gained": item.get("followers_gained"),
                    "like_rate": item.get("like_rate"),
                    "save_rate": item.get("save_rate"),
                    "comment_rate": item.get("comment_rate"),
                    "share_rate": item.get("share_rate"),
                    "engagement_rate": item.get("engagement_rate"),
                    "performance_level": item.get("performance_level"),
                }
            )
        return patterns

    def _build_embedding_text(self, **kwargs) -> str:
        from memory.embedding import build_embedding_text

        return build_embedding_text(**kwargs)

    def _create_vector_memory(self):
        from memory.vector_memory import XHSVectorMemory

        return XHSVectorMemory("data/chroma")

    def _get_vector_sync_row(self, content_id: str) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    c.content_id,
                    c.status,
                    c.topic,
                    c.angle,
                    c.title,
                    c.target_group,
                    c.core_pain,
                    c.created_at,
                    c.published_at,
                    c.hashtags_json,
                    c.embedding_text,
                    c.domain,
                    c.subdomain,
                    c.content_intent,
                    c.profile_version,
                    c.risk_level,
                    m.views,
                    m.likes,
                    m.saves,
                    m.comments,
                    m.shares,
                    m.followers_gained,
                    m.save_rate,
                    m.engagement_rate,
                    m.performance_level
                FROM contents c
                LEFT JOIN metrics m ON c.content_id = m.content_id
                WHERE c.content_id = ?
                """,
                (content_id,),
            ).fetchone()

        return dict(row) if row is not None else None

    def _upsert_vector_row(
        self,
        row: dict[str, Any],
        *,
        vector_memory,
        build_embedding_text_fn,
    ) -> None:
        hashtags = json_loads(row.get("hashtags_json"), [])
        embedding_text = row.get("embedding_text") or build_embedding_text_fn(
            topic=row.get("topic"),
            angle=row.get("angle"),
            title=row.get("title"),
            target_group=row.get("target_group"),
            core_pain=row.get("core_pain"),
            hashtags=hashtags,
        )
        vector_memory.upsert_content(
            content_id=row["content_id"],
            embedding_text=embedding_text,
            metadata=self._build_vector_metadata(row),
        )

    def _build_vector_metadata(self, row: dict[str, Any]) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "content_id": row.get("content_id", ""),
            "status": row.get("status", ""),
            "topic": row.get("topic", ""),
            "angle": row.get("angle") or "",
            "title": row.get("title") or "",
            "target_group": row.get("target_group") or "",
            "created_at": row.get("created_at", ""),
            "published_at": row.get("published_at") or "",
            "performance_level": row.get("performance_level") or "unknown",
            "domain": row.get("domain") or "",
            "subdomain": row.get("subdomain") or "",
            "content_intent": row.get("content_intent") or "",
            "profile_version": row.get("profile_version") or "",
            "risk_level": row.get("risk_level") or "",
        }
        for field_name in (
            "views",
            "likes",
            "saves",
            "comments",
            "shares",
            "followers_gained",
            "save_rate",
            "engagement_rate",
        ):
            value = row.get(field_name)
            if value is not None:
                metadata[field_name] = value
        return metadata

    def _unique_non_empty(self, values: list[Optional[str]]) -> list[str]:
        seen = set()
        out = []
        for v in values:
            if not v:
                continue
            v = v.strip()
            if not v or v in seen:
                continue
            seen.add(v)
            out.append(v)
        return out
