from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import runpy
import threading

import pytest

import memory.memory_manager as memory_manager_module
from memory.memory_manager import XHSMemoryManager
from memory.models import ContentRecord


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "memory" / "schema.sql"


class FakeScopedVectorMemory:
    def __init__(self, fail_on_call: int | None = None):
        self.fail_on_call = fail_on_call
        self.upsert_calls: list[dict] = []
        self.records: dict[str, dict] = {}

    def upsert_content(self, *, content_id: str, embedding_text: str, metadata: dict) -> None:
        self.upsert_calls.append(
            {
                "content_id": content_id,
                "embedding_text": embedding_text,
                "metadata": metadata,
            }
        )
        if self.fail_on_call is not None and len(self.upsert_calls) == self.fail_on_call:
            raise RuntimeError("vector boom")
        self.records[content_id] = {
            "content_id": content_id,
            "document": embedding_text,
            "metadata": metadata,
            "similarity": 0.99,
        }

    def query_similar(
        self,
        *,
        query_text: str,
        domain: str,
        subdomain: str,
        allow_global: bool = False,
        **_kwargs,
    ) -> list[dict]:
        assert allow_global is False
        return [
            record
            for record in self.records.values()
            if record["metadata"].get("domain") == domain
            and record["metadata"].get("subdomain") == subdomain
        ]


def _seed_legacy_structured_row(
    db_path: Path,
    *,
    content_id: str,
    topic: str,
    created_at: str,
    angle: str = "旧角度",
    title: str = "旧标题",
    embedding_text: str | None = None,
) -> None:
    connection = sqlite3.connect(db_path)
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    connection.execute(
        """
        INSERT INTO contents(
            content_id, status, created_at, topic, angle, title,
            target_group, core_pain, hashtags_json, embedding_text,
            domain, subdomain, content_intent, profile_version, risk_level
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            content_id,
            "published",
            created_at,
            topic,
            angle,
            title,
            "上班族",
            "旧痛点",
            json.dumps(["#旧标签"], ensure_ascii=False),
            embedding_text,
            None,
            None,
            None,
            None,
            None,
        ),
    )
    connection.execute(
        """
        INSERT INTO metrics(
            content_id, views, likes, saves, comments, shares, followers_gained,
            like_rate, save_rate, comment_rate, share_rate, engagement_rate,
            performance_level, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            content_id,
            100,
            10,
            5,
            2,
            1,
            3,
            0.1,
            0.05,
            0.02,
            0.01,
            0.18,
            "high",
            created_at,
        ),
    )
    connection.commit()
    connection.close()


def test_connections_are_keyed_by_resolved_path_and_close_methods_are_isolated(tmp_path):
    db1 = tmp_path / "one" / "memory.db"
    db2 = tmp_path / "two" / "memory.db"

    manager1 = XHSMemoryManager(db1)
    manager2 = XHSMemoryManager(db2)

    conn1 = manager1.connect()
    conn2 = manager2.connect()

    assert conn1 is not conn2
    assert (db1.resolve(), threading.get_ident()) in manager1.connections
    assert (db2.resolve(), threading.get_ident()) in manager2.connections

    manager1.close()

    assert all(key[0] != db1.resolve() for key in manager1.connections)
    assert any(key[0] == db2.resolve() for key in manager2.connections)

    XHSMemoryManager.close_all()

    assert manager1.connections == {}


def test_save_generated_content_roundtrips_domain_metadata(tmp_path):
    manager = XHSMemoryManager(tmp_path / "memory.db")
    manager.init_db(SCHEMA_PATH)

    record = ContentRecord(
        content_id="content-1",
        topic="睡眠改善",
        created_at="2026-07-03T10:00:00+08:00",
        status="reviewed",
        platform="xiaohongshu",
        topic_id="tp_001",
        angle_id="ag_001",
        angle="睡眠策略",
        target_group="上班族",
        core_pain="熬夜后疲惫",
        title="睡眠改善指南",
        cover_copy="cover",
        content="body",
        hashtags=["#睡眠"],
        content_format="educational_cards",
        visual_style="domain_editorial",
        card_count=6,
        storyboards=["frame-1", "frame-2"],
        image_paths=["/tmp/image-1.png"],
        strategy_tags=["sleep", "wellness"],
        compliance_status="compliant_with_minor_edits",
        embedding_text="睡眠改善 睡眠策略 上班族",
        domain="wellness",
        subdomain="sleep",
        content_intent="how_to",
        profile_version="wellness-v1",
        risk_level="medium",
        metadata={
            "domain": "wellness",
            "subdomain": "sleep",
            "content_intent": "how_to",
            "profile_version": "wellness-v1",
            "risk_level": "medium",
        },
    )

    manager.save_generated_content(record)
    content = manager.get_content_by_id("content-1")

    assert content is not None
    assert content["domain"] == "wellness"
    assert content["subdomain"] == "sleep"
    assert content["content_intent"] == "how_to"
    assert content["profile_version"] == "wellness-v1"
    assert content["risk_level"] == "medium"
    assert content["hashtags"] == ["#睡眠"]
    assert content["storyboards"] == ["frame-1", "frame-2"]
    assert content["image_paths"] == ["/tmp/image-1.png"]
    assert content["strategy_tags"] == ["sleep", "wellness"]
    assert content["compliance_status"] == "compliant_with_minor_edits"
    assert content["metadata"] == {
        "domain": "wellness",
        "subdomain": "sleep",
        "content_intent": "how_to",
        "profile_version": "wellness-v1",
        "risk_level": "medium",
    }


def test_save_generated_content_rolls_back_when_event_insert_fails(tmp_path, monkeypatch):
    manager = XHSMemoryManager(tmp_path / "memory.db")
    manager.init_db(SCHEMA_PATH)

    record = ContentRecord(
        content_id="content-rollback",
        topic="睡眠改善",
        created_at="2026-07-03T10:00:00+08:00",
    )

    def fail_insert_event(*args, **kwargs):
        raise RuntimeError("event boom")

    monkeypatch.setattr(memory_manager_module, "_insert_event", fail_insert_event)

    with pytest.raises(RuntimeError, match="event boom"):
        manager.save_generated_content(record)

    assert manager.get_content_by_id("content-rollback") is None
    row = manager.connect().execute(
        """
        SELECT COUNT(*)
        FROM memory_events
        WHERE content_id = ?
        """,
        ("content-rollback",),
    ).fetchone()
    assert row[0] == 0


def test_log_event_is_thread_safe_across_workers(tmp_path):
    manager = XHSMemoryManager(tmp_path / "memory.db")
    manager.init_db(SCHEMA_PATH)

    event_count = 64
    worker_count = 16

    def write_event(index: int) -> str:
        return manager.log_event("threaded_log_event", payload={"index": index})

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = list(executor.map(write_event, range(event_count)))

    assert len(results) == event_count
    assert len(set(results)) == event_count

    row = manager.connect().execute(
        """
        SELECT COUNT(*)
        FROM memory_events
        WHERE event_type = ?
        """,
        ("threaded_log_event",),
    ).fetchone()

    assert row[0] == event_count


def test_delete_content_by_id_removes_saved_record(tmp_path):
    manager = XHSMemoryManager(tmp_path / "memory.db")
    manager.init_db(SCHEMA_PATH)

    record = ContentRecord(
        content_id="content-delete",
        topic="睡眠改善",
        created_at="2026-07-03T10:00:00+08:00",
    )

    manager.save_generated_content(record)
    assert manager.get_content_by_id("content-delete") is not None

    manager.delete_content_by_id("content-delete")

    assert manager.get_content_by_id("content-delete") is None


def test_delete_content_by_id_missing_twice_records_attempts_without_fk(tmp_path):
    manager = XHSMemoryManager(tmp_path / "memory.db")
    manager.init_db(SCHEMA_PATH)

    manager.delete_content_by_id("missing-content")
    manager.delete_content_by_id("missing-content")

    rows = manager.connect().execute(
        """
        SELECT content_id, payload_json
        FROM memory_events
        WHERE event_type = ?
        ORDER BY event_time
        """,
        ("content_deleted",),
    ).fetchall()

    assert len(rows) == 2
    assert all(row[0] is None for row in rows)
    assert all(json.loads(row[1]) == {"deleted_content_id": "missing-content"} for row in rows)


def test_delete_content_by_id_rolls_back_when_event_insert_fails(tmp_path, monkeypatch):
    manager = XHSMemoryManager(tmp_path / "memory.db")
    manager.init_db(SCHEMA_PATH)

    record = ContentRecord(
        content_id="content-delete-rollback",
        topic="睡眠改善",
        created_at="2026-07-03T10:00:00+08:00",
    )
    manager.save_generated_content(record)

    def fail_insert_event(*args, **kwargs):
        raise RuntimeError("event boom")

    monkeypatch.setattr(memory_manager_module, "_insert_event", fail_insert_event)

    with pytest.raises(RuntimeError, match="event boom"):
        manager.delete_content_by_id("content-delete-rollback")

    assert manager.get_content_by_id("content-delete-rollback") is not None
    row = manager.connect().execute(
        """
        SELECT COUNT(*)
        FROM memory_events
        WHERE content_id = ?
        """,
        ("content-delete-rollback",),
    ).fetchone()
    assert row[0] == 1


def test_mark_reviewed_rolls_back_when_event_insert_fails(tmp_path, monkeypatch):
    manager = XHSMemoryManager(tmp_path / "memory.db")
    manager.init_db(SCHEMA_PATH)

    record = ContentRecord(
        content_id="content-reviewed",
        topic="睡眠改善",
        created_at="2026-07-03T10:00:00+08:00",
    )
    manager.save_generated_content(record)

    monkeypatch.setattr(memory_manager_module, "_insert_event", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("event boom")))

    with pytest.raises(RuntimeError, match="event boom"):
        manager.mark_reviewed("content-reviewed")

    content = manager.get_content_by_id("content-reviewed")
    assert content is not None
    assert content["status"] == "generated"


def test_mark_reviewed_records_event_on_success(tmp_path):
    manager = XHSMemoryManager(tmp_path / "memory.db")
    manager.init_db(SCHEMA_PATH)

    record = ContentRecord(
        content_id="content-reviewed-success",
        topic="睡眠改善",
        created_at="2026-07-03T10:00:00+08:00",
    )
    manager.save_generated_content(record)

    manager.mark_reviewed("content-reviewed-success")

    content = manager.get_content_by_id("content-reviewed-success")
    assert content is not None
    assert content["status"] == "reviewed"
    row = manager.connect().execute(
        """
        SELECT content_id, payload_json
        FROM memory_events
        WHERE event_type = ?
        ORDER BY event_time DESC
        LIMIT 1
        """,
        ("content_reviewed",),
    ).fetchone()
    assert row[0] == "content-reviewed-success"


def test_mark_published_rolls_back_when_event_insert_fails(tmp_path, monkeypatch):
    manager = XHSMemoryManager(tmp_path / "memory.db")
    manager.init_db(SCHEMA_PATH)

    record = ContentRecord(
        content_id="content-published",
        topic="睡眠改善",
        created_at="2026-07-03T10:00:00+08:00",
    )
    manager.save_generated_content(record)

    monkeypatch.setattr(memory_manager_module, "_insert_event", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("event boom")))

    with pytest.raises(RuntimeError, match="event boom"):
        manager.mark_published("content-published", post_id="post-1", url="https://example.com")

    content = manager.get_content_by_id("content-published")
    assert content is not None
    assert content["status"] == "generated"
    assert content["post_id"] is None
    assert content["url"] is None


def test_mark_published_records_event_on_success(tmp_path):
    manager = XHSMemoryManager(tmp_path / "memory.db")
    manager.init_db(SCHEMA_PATH)

    record = ContentRecord(
        content_id="content-published-success",
        topic="睡眠改善",
        created_at="2026-07-03T10:00:00+08:00",
    )
    manager.save_generated_content(record)

    manager.mark_published("content-published-success", post_id="post-1", url="https://example.com")

    content = manager.get_content_by_id("content-published-success")
    assert content is not None
    assert content["status"] == "published"
    assert content["post_id"] == "post-1"
    assert content["url"] == "https://example.com"
    row = manager.connect().execute(
        """
        SELECT content_id
        FROM memory_events
        WHERE event_type = ?
        ORDER BY event_time DESC
        LIMIT 1
        """,
        ("content_published",),
    ).fetchone()
    assert row[0] == "content-published-success"


def test_update_metrics_rolls_back_when_event_insert_fails(tmp_path, monkeypatch):
    manager = XHSMemoryManager(tmp_path / "memory.db")
    manager.init_db(SCHEMA_PATH)

    record = ContentRecord(
        content_id="content-metrics",
        topic="睡眠改善",
        created_at="2026-07-03T10:00:00+08:00",
    )
    manager.save_generated_content(record)

    monkeypatch.setattr(memory_manager_module, "_insert_event", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("event boom")))

    with pytest.raises(RuntimeError, match="event boom"):
        manager.update_metrics("content-metrics", views=100, likes=10, saves=5, comments=1)

    row = manager.connect().execute(
        """
        SELECT COUNT(*)
        FROM metrics
        WHERE content_id = ?
        """,
        ("content-metrics",),
    ).fetchone()
    assert row[0] == 0


def test_update_metrics_records_event_on_success(tmp_path):
    manager = XHSMemoryManager(tmp_path / "memory.db")
    manager.init_db(SCHEMA_PATH)

    record = ContentRecord(
        content_id="content-metrics-success",
        topic="睡眠改善",
        created_at="2026-07-03T10:00:00+08:00",
    )
    manager.save_generated_content(record)

    metrics = manager.update_metrics("content-metrics-success", views=100, likes=10, saves=5, comments=1)

    assert metrics.performance_level in {"high", "medium", "low"}
    row = manager.connect().execute(
        """
        SELECT content_id
        FROM memory_events
        WHERE event_type = ?
        ORDER BY event_time DESC
        LIMIT 1
        """,
        ("metrics_updated",),
    ).fetchone()
    assert row[0] == "content-metrics-success"


def test_save_and_delete_create_exactly_one_event_each(tmp_path):
    manager = XHSMemoryManager(tmp_path / "memory.db")
    manager.init_db(SCHEMA_PATH)

    save_record = ContentRecord(
        content_id="content-event-save",
        topic="睡眠改善",
        created_at="2026-07-03T10:00:00+08:00",
    )
    delete_record = ContentRecord(
        content_id="content-event-delete",
        topic="防晒",
        created_at="2026-07-03T10:00:00+08:00",
    )

    manager.save_generated_content(save_record)
    manager.save_generated_content(delete_record)
    manager.delete_content_by_id("content-event-delete")

    row = manager.connect().execute(
        """
        SELECT event_type, COUNT(*)
        FROM memory_events
        GROUP BY event_type
        ORDER BY event_type
        """,
    ).fetchall()

    assert [(item[0], item[1]) for item in row] == [
        ("content_deleted", 1),
        ("content_saved", 2),
    ]


def test_backfill_vector_scope_upserts_legacy_rows_marks_once_and_supports_scoped_query(tmp_path):
    db_path = tmp_path / "legacy.db"
    _seed_legacy_structured_row(
        db_path,
        content_id="legacy-1",
        topic="防晒",
        created_at="2026-07-03T10:00:00+08:00",
    )
    manager = XHSMemoryManager(db_path)
    manager.init_db(SCHEMA_PATH)
    vector_memory = FakeScopedVectorMemory()

    did_backfill = manager.ensure_vector_scope_backfill(
        vector_memory=vector_memory,
        build_embedding_text_fn=lambda **kwargs: f"embed::{kwargs['topic']}",
    )

    assert did_backfill is True
    assert vector_memory.upsert_calls == [
        {
            "content_id": "legacy-1",
            "embedding_text": "embed::防晒",
            "metadata": {
                "content_id": "legacy-1",
                "status": "published",
                "topic": "防晒",
                "angle": "旧角度",
                "title": "旧标题",
                "target_group": "上班族",
                "created_at": "2026-07-03T10:00:00+08:00",
                "published_at": "",
                "performance_level": "high",
                "domain": "beauty",
                "subdomain": "skincare",
                "content_intent": "",
                "profile_version": "legacy-v1",
                "risk_level": "low",
                "views": 100,
                "likes": 10,
                "saves": 5,
                "comments": 2,
                "shares": 1,
                "followers_gained": 3,
                "save_rate": 0.05,
                "engagement_rate": 0.18,
            },
        }
    ]
    assert vector_memory.query_similar(
        query_text="anything",
        domain="beauty",
        subdomain="skincare",
    )[0]["content_id"] == "legacy-1"

    event_rows = manager.connect().execute(
        """
        SELECT event_type, content_id
        FROM memory_events
        WHERE event_type = 'vector_domain_backfill_v1'
        """
    ).fetchall()
    assert [(row[0], row[1]) for row in event_rows] == [("vector_domain_backfill_v1", None)]

    did_backfill_again = manager.ensure_vector_scope_backfill(
        vector_memory=vector_memory,
        build_embedding_text_fn=lambda **kwargs: f"embed::{kwargs['topic']}",
    )
    assert did_backfill_again is False
    assert len(vector_memory.upsert_calls) == 1


def test_backfill_vector_scope_retries_when_partial_upserts_fail(tmp_path):
    db_path = tmp_path / "retry.db"
    _seed_legacy_structured_row(
        db_path,
        content_id="legacy-1",
        topic="防晒",
        created_at="2026-07-03T10:00:00+08:00",
    )
    _seed_legacy_structured_row(
        db_path,
        content_id="legacy-2",
        topic="修护",
        created_at="2026-07-03T11:00:00+08:00",
    )
    manager = XHSMemoryManager(db_path)
    manager.init_db(SCHEMA_PATH)

    failing_vector = FakeScopedVectorMemory(fail_on_call=2)
    with pytest.raises(RuntimeError, match="vector boom"):
        manager.ensure_vector_scope_backfill(
            vector_memory=failing_vector,
            build_embedding_text_fn=lambda **kwargs: f"embed::{kwargs['topic']}",
        )

    marker = manager.connect().execute(
        """
        SELECT COUNT(*)
        FROM memory_events
        WHERE event_type = 'vector_domain_backfill_v1'
        """
    ).fetchone()
    assert marker[0] == 0

    healthy_vector = FakeScopedVectorMemory()
    did_backfill = manager.ensure_vector_scope_backfill(
        vector_memory=healthy_vector,
        build_embedding_text_fn=lambda **kwargs: f"embed::{kwargs['topic']}",
    )
    assert did_backfill is True
    assert [call["content_id"] for call in healthy_vector.upsert_calls] == ["legacy-1", "legacy-2"]


def test_backfill_vector_scope_defers_marker_until_structured_rows_exist(tmp_path):
    db_path = tmp_path / "empty.db"
    manager = XHSMemoryManager(db_path)
    manager.init_db(SCHEMA_PATH)
    vector_memory = FakeScopedVectorMemory()

    first_call = manager.ensure_vector_scope_backfill(
        vector_memory=vector_memory,
        build_embedding_text_fn=lambda **kwargs: "unused",
    )

    assert first_call is False
    assert vector_memory.upsert_calls == []
    marker = manager.connect().execute(
        """
        SELECT COUNT(*)
        FROM memory_events
        WHERE event_type = 'vector_domain_backfill_v1'
        """
    ).fetchone()
    assert marker[0] == 0

    _seed_legacy_structured_row(
        db_path,
        content_id="legacy-late",
        topic="晚到旧内容",
        created_at="2026-07-04T10:00:00+08:00",
    )

    second_call = manager.ensure_vector_scope_backfill(
        vector_memory=vector_memory,
        build_embedding_text_fn=lambda **kwargs: f"embed::{kwargs['topic']}",
    )

    assert second_call is True
    assert [call["content_id"] for call in vector_memory.upsert_calls] == ["legacy-late"]
    marker = manager.connect().execute(
        """
        SELECT COUNT(*)
        FROM memory_events
        WHERE event_type = 'vector_domain_backfill_v1'
        """
    ).fetchone()
    assert marker[0] == 1

    third_call = manager.ensure_vector_scope_backfill(
        vector_memory=vector_memory,
        build_embedding_text_fn=lambda **kwargs: f"embed::{kwargs['topic']}",
    )
    assert third_call is False
    assert len(vector_memory.upsert_calls) == 1


def test_examples_import_without_running_main():
    runpy.run_path(str(ROOT / "examples" / "memory_demo.py"), run_name="__test__")
    runpy.run_path(str(ROOT / "examples" / "vector_memory_demo.py"), run_name="__test__")
