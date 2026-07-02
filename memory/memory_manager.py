from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from memory.models import ContentRecord, MetricsRecord, MemoryContext

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


class XHSMemoryManager:
    _shared_conn = None  # 类属性：在所有的实例化对象之间共享同一个数据库连接

    def __init__(self, db_path: str | Path = "data/xhs_memory.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        # 检查类级别的连接是否已经建立
        if XHSMemoryManager._shared_conn is None:
            XHSMemoryManager._shared_conn = sqlite3.connect(self.db_path, check_same_thread=False)
            XHSMemoryManager._shared_conn.row_factory = sqlite3.Row
            XHSMemoryManager._shared_conn.execute("PRAGMA foreign_keys = ON;")
        return XHSMemoryManager._shared_conn

    def init_db(self, schema_path: str | Path = "memory/schema.sql") -> None:
        schema_path = Path(schema_path)
        with self.connect() as conn:
            conn.executescript(schema_path.read_text(encoding="utf-8"))
            conn.commit()

    def log_event(
        self,
        event_type: str,
        content_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> str:
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        with self.connect() as conn:
            conn.execute(
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
                    utc_now_iso(),
                    json_dumps(payload or {}),
                ),
            )
            conn.commit()
        return event_id

    def save_generated_content(self, record: ContentRecord) -> None:
        """
        在内容生成完成或 Human Review 通过后写入。
        建议：只有 Human Review approved 后才写正式 memory。
        """
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO contents (
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            conn.commit()

        self.log_event(
            event_type="content_saved",
            content_id=record.content_id,
            payload={
                "topic": record.topic,
                "angle": record.angle,
                "title": record.title,
                "status": record.status,
            },
        )
    
    def save_embedding_content(self, record: ContentRecord) -> None:
        from memory.embedding import build_embedding_text
        from memory.vector_memory import XHSVectorMemory

        vector_memory = XHSVectorMemory("data/chroma")
        embedding_text = build_embedding_text(
            topic=record.topic,
            angle=record.angle,
            title=record.title,
            target_group=record.target_group,
            core_pain=record.core_pain,
            hashtags=record.hashtags        
            )

        vector_memory.upsert_content(
            content_id=record.content_id,
            embedding_text=embedding_text,
            metadata={
                "content_id": record.content_id,
                "status": record.status,
                "topic": record.topic,
                "angle": record.angle or "",
                "title": record.title or "",
                "target_group": record.target_group or "",
                "created_at": record.created_at,
                "published_at": record.published_at or "",
                "performance_level": "unknown",
            }
        )

    def get_embedding_content_by_id(self, content_id: str) -> bool:
        from memory.vector_memory import XHSVectorMemory

        vector_memory = XHSVectorMemory("data/chroma")
        result = vector_memory.collection.get(ids=[content_id])
        
        return len(result["ids"]) > 0
    
    def delete_content_by_id(self, content_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                DELETE FROM contents
                WHERE content_id = ?
                """,
                (content_id,),
            )
            conn.commit()

        self.log_event(
            event_type="content_deleted",
            content_id=None,
            payload={"deleted_content_id": content_id},
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
            conn.commit()

        self.log_event("content_reviewed", content_id)

    def mark_published(
        self,
        content_id: str,
        post_id: str,
        url: Optional[str] = None,
        published_at: Optional[str] = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE contents
                SET status = ?, post_id = ?, url = ?, published_at = ?
                WHERE content_id = ?
                """,
                (
                    "published",
                    post_id,
                    url,
                    published_at or utc_now_iso(),
                    content_id,
                ),
            )
            conn.commit()

        self.log_event(
            event_type="content_published",
            content_id=content_id,
            payload={"post_id": post_id, "url": url},
        )

    def update_metrics(
        self,
        content_id: str,
        views: int,
        likes: int,
        saves: int,
        comments: int,
        shares: int = 0,
        followers_gained: int = 0,
    ) -> MetricsRecord:
        rates = self._calculate_rates(
            views=views,
            likes=likes,
            saves=saves,
            comments=comments,
            shares=shares,
        )
        performance_level = self._classify_performance(
            views=views,
            save_rate=rates["save_rate"],
            engagement_rate=rates["engagement_rate"],
        )

        record = MetricsRecord(
            content_id=content_id,
            views=views,
            likes=likes,
            saves=saves,
            comments=comments,
            shares=shares,
            followers_gained=followers_gained,
            like_rate=rates["like_rate"],
            save_rate=rates["save_rate"],
            comment_rate=rates["comment_rate"],
            share_rate=rates["share_rate"],
            engagement_rate=rates["engagement_rate"],
            performance_level=performance_level,
            updated_at=utc_now_iso(),
        )

        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO metrics (
                    content_id,
                    views,
                    likes,
                    saves,
                    comments,
                    shares,
                    followers_gained,
                    like_rate,
                    save_rate,
                    comment_rate,
                    share_rate,
                    engagement_rate,
                    performance_level,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.content_id,
                    record.views,
                    record.likes,
                    record.saves,
                    record.comments,
                    record.shares,
                    record.followers_gained,
                    record.like_rate,
                    record.save_rate,
                    record.comment_rate,
                    record.share_rate,
                    record.engagement_rate,
                    record.performance_level,
                    record.updated_at,
                ),
            )
            conn.commit()

        self.log_event(
            event_type="metrics_updated",
            content_id=content_id,
            payload={
                "views": views,
                "likes": likes,
                "saves": saves,
                "comments": comments,
                "shares": shares,
                "performance_level": performance_level,
                **rates,
            },
        )

        return record

    def get_recent_contents(self, days: int = 14, limit: int = 30) -> list[dict[str, Any]]:
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
                    target_group,
                    core_pain,
                    hashtags_json,
                    strategy_tags_json
                FROM contents
                WHERE created_at >= ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (since, limit),
            ).fetchall()

        return [self._content_row_to_dict(row) for row in rows]

    def get_high_performing_contents(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.content_id,
                    c.topic,
                    c.angle,
                    c.title,
                    c.target_group,
                    c.strategy_tags_json,
                    c.hashtags_json,
                    m.views,
                    m.likes,
                    m.saves,
                    m.comments,
                    m.shares,
                    m.save_rate,
                    m.engagement_rate,
                    m.performance_level
                FROM contents c
                JOIN metrics m ON c.content_id = m.content_id
                WHERE m.performance_level = 'high'
                ORDER BY m.views DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [self._performance_row_to_dict(row) for row in rows]

    def get_low_performing_contents(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.content_id,
                    c.topic,
                    c.angle,
                    c.title,
                    c.target_group,
                    c.strategy_tags_json,
                    c.hashtags_json,
                    m.views,
                    m.likes,
                    m.saves,
                    m.comments,
                    m.shares,
                    m.save_rate,
                    m.engagement_rate,
                    m.performance_level
                FROM contents c
                JOIN metrics m ON c.content_id = m.content_id
                WHERE m.performance_level = 'low'
                ORDER BY m.views ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [self._performance_row_to_dict(row) for row in rows]

    def build_memory_context(
        self,
        recent_days: int = 14,
        recent_limit: int = 30,
        performance_limit: int = 20,
    ) -> MemoryContext:
        recent_contents = self.get_recent_contents(days=recent_days, limit=recent_limit)
        high_contents = self.get_high_performing_contents(limit=performance_limit)
        low_contents = self.get_low_performing_contents(limit=performance_limit)

        recent_topics = self._unique_non_empty([x.get("topic") for x in recent_contents])
        recent_angles = self._unique_non_empty([x.get("angle") for x in recent_contents])

        recent_hashtags = []
        for item in recent_contents:
            recent_hashtags.extend(item.get("hashtags", []))
        recent_hashtags = self._unique_non_empty(recent_hashtags)

        return MemoryContext(
            recent_contents=recent_contents,
            recent_topics_to_avoid=recent_topics,
            recent_angles_to_avoid=recent_angles,
            high_performing_patterns=self._extract_patterns(high_contents),
            low_performing_patterns=self._extract_patterns(low_contents),
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

    def _extract_patterns(self, contents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        MVP：先把高/低表现内容直接转为 pattern。
        后面可以让 LLM 对这些内容做聚类总结。
        """
        patterns: list[dict[str, Any]] = []
        for item in contents:
            patterns.append(
                {
                    "topic": item.get("topic"),
                    "angle": item.get("angle"),
                    "title": item.get("title"),
                    "strategy_tags": item.get("strategy_tags", []),
                    "save_rate": item.get("save_rate"),
                    "engagement_rate": item.get("engagement_rate"),
                    "performance_level": item.get("performance_level"),
                }
            )
        return patterns

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
