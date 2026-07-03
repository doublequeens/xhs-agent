from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import pytest

import memory.memory_manager as memory_manager_module
from memory.memory_manager import XHSMemoryManager
from memory.models import ContentRecord


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "memory" / "schema.sql"


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
