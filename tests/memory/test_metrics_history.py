from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import memory.memory_manager as memory_manager_module
from memory.memory_manager import XHSMemoryManager
from memory.models import ContentRecord, MetricsRecord


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "memory" / "schema.sql"


@pytest.fixture
def manager(tmp_path):
    memory_manager = XHSMemoryManager(tmp_path / "memory.db")
    memory_manager.init_db(SCHEMA_PATH)
    yield memory_manager
    memory_manager.close()


def save_content(
    manager: XHSMemoryManager,
    content_id: str,
    *,
    title: str | None = "A useful title",
    created_at: str = "2026-07-01T10:00:00+08:00",
    published_at: str | None = None,
    post_id: str | None = None,
) -> None:
    manager.save_generated_content(
        ContentRecord(
            content_id=content_id,
            topic="sleep",
            title=title,
            created_at=created_at,
            published_at=published_at,
            post_id=post_id,
        )
    )


def test_metrics_record_preserves_old_positions_and_accepts_unavailable_raw_values():
    positional_record = MetricsRecord(
        "content-1",
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
        "2026-07-05T10:00:00+08:00",
    )
    unavailable_record = MetricsRecord("content-2", views=None, impressions=None)

    assert positional_record.like_rate == 0.1
    assert positional_record.performance_level == "high"
    assert positional_record.updated_at == "2026-07-05T10:00:00+08:00"
    assert unavailable_record.views is None
    assert unavailable_record.impressions is None


def test_batch_update_writes_latest_and_history_with_merged_calculations(manager):
    save_content(manager, "content-1")
    manager.update_metrics("content-1", 100, 10, 5, 2, 1, 1, impressions=1000)

    result = manager.update_metrics_batch(
        [
            MetricsRecord(
                content_id="content-1",
                impressions=None,
                views=200,
                cover_click_rate=0.2,
                likes=None,
                saves=8,
                comments=4,
                shares=2,
                followers_gained=None,
                avg_watch_time_seconds=17,
                danmaku_count=0,
            )
        ],
        collected_date="2026-07-05",
        source="creator_center_note_export_v1",
    )

    latest = manager.get_metrics("content-1")
    history = manager.get_metrics_history("content-1")
    assert latest is not None
    assert latest["impressions"] == 1000
    assert latest["likes"] == 10
    assert latest["views"] == 200
    assert latest["avg_watch_time_seconds"] == 17
    assert result[0].engagement_rate == pytest.approx((10 + 8 + 4 + 2) / 200)
    assert history == [
        {
            **history[0],
            "impressions": None,
            "likes": None,
            "followers_gained": None,
            "views": 200,
            "engagement_rate": pytest.approx((10 + 8 + 4 + 2) / 200),
            "source": "creator_center_note_export_v1",
            "collected_date": "2026-07-05",
        }
    ]


def test_none_preserves_latest_and_zero_overwrites(manager):
    save_content(manager, "content-1")
    manager.update_metrics(
        "content-1",
        100,
        10,
        5,
        2,
        1,
        3,
        impressions=1000,
        cover_click_rate=0.1,
        avg_watch_time_seconds=12,
        danmaku_count=4,
    )

    preserved = manager.update_metrics(
        "content-1",
        None,
        None,
        None,
        None,
        None,
        None,
        impressions=None,
        cover_click_rate=None,
        avg_watch_time_seconds=None,
        danmaku_count=None,
    )
    assert preserved.views == 100
    assert preserved.impressions == 1000
    assert preserved.avg_watch_time_seconds == 12

    overwritten = manager.update_metrics(
        "content-1",
        0,
        0,
        0,
        0,
        0,
        0,
        impressions=0,
        cover_click_rate=0,
        avg_watch_time_seconds=0,
        danmaku_count=0,
    )
    assert overwritten.views == 0
    assert overwritten.impressions == 0
    assert overwritten.cover_click_rate == 0
    assert overwritten.engagement_rate == 0


def test_concurrent_disjoint_metric_updates_are_serialized(manager, monkeypatch):
    save_content(manager, "content-1")
    manager.update_metrics("content-1", 100, 10, 5, 2, 1, 3)
    merge_barrier = threading.Barrier(2)
    original_upsert = manager._upsert_metrics

    def overlap_old_read_merge_write(connection, record):
        try:
            merge_barrier.wait(timeout=0.25)
        except threading.BrokenBarrierError:
            pass
        original_upsert(connection, record)

    monkeypatch.setattr(manager, "_upsert_metrics", overlap_old_read_merge_write)

    def update_views():
        manager.update_metrics(
            "content-1",
            200,
            None,
            None,
            None,
            None,
            None,
        )

    def update_likes():
        manager.update_metrics(
            "content-1",
            None,
            20,
            None,
            None,
            None,
            None,
        )

    errors = []
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(update_views), executor.submit(update_likes)]
            for future in futures:
                try:
                    future.result()
                except Exception as error:
                    errors.append(error)
        latest = manager.get_metrics("content-1")
    finally:
        XHSMemoryManager.close_path(manager.db_path)

    assert errors == []
    assert latest is not None
    assert latest["views"] == 200
    assert latest["likes"] == 20
    assert not any(
        key[0] == manager.db_path.resolve()
        for key in XHSMemoryManager.connections
    )


def test_new_unavailable_values_persist_null_but_calculate_as_zero(manager):
    save_content(manager, "content-1")

    record = manager.update_metrics(
        "content-1",
        None,
        None,
        None,
        None,
        None,
        None,
    )

    latest = manager.get_metrics("content-1")
    assert latest is not None
    assert latest["views"] is None
    assert latest["likes"] is None
    assert record.like_rate == 0
    assert record.performance_level == "low"


def test_same_day_history_is_upserted_and_getter_orders_by_date(manager):
    save_content(manager, "content-1")
    manager.update_metrics_batch(
        [MetricsRecord(content_id="content-1", views=100, likes=1)],
        "2026-07-06",
        "first",
    )
    manager.update_metrics_batch(
        [MetricsRecord(content_id="content-1", views=80, likes=2)],
        "2026-07-05",
        "older",
    )
    manager.update_metrics_batch(
        [MetricsRecord(content_id="content-1", views=120, likes=3)],
        "2026-07-06",
        "replacement",
    )

    history = manager.get_metrics_history("content-1")
    assert [item["collected_date"] for item in history] == [
        "2026-07-05",
        "2026-07-06",
    ]
    assert history[1]["views"] == 120
    assert history[1]["source"] == "replacement"
    assert manager.get_metrics("missing") is None
    assert manager.get_metrics_history("missing") == []


def test_batch_failure_rolls_back_every_content(manager, monkeypatch):
    save_content(manager, "content-1")
    save_content(manager, "content-2")
    original = manager._insert_metrics_history
    call_count = 0

    def fail_on_second_call(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("history write failed")
        return original(*args, **kwargs)

    monkeypatch.setattr(manager, "_insert_metrics_history", fail_on_second_call)

    with pytest.raises(RuntimeError, match="history write failed"):
        manager.update_metrics_batch(
            [
                MetricsRecord(content_id="content-1", views=100),
                MetricsRecord(content_id="content-2", views=200),
            ],
            "2026-07-05",
            "creator_center_note_export_v1",
        )

    assert manager.get_metrics("content-1") is None
    assert manager.get_metrics("content-2") is None
    assert manager.get_metrics_history("content-1") == []
    event_count = manager.connect().execute(
        "SELECT COUNT(*) FROM memory_events WHERE event_type = 'metrics_updated'"
    ).fetchone()[0]
    assert event_count == 0


def test_bind_post_identity_updates_content_and_event_and_rejects_missing(manager):
    save_content(manager, "content-1")

    manager.bind_post_identity(
        "content-1",
        "post-1",
        "https://www.xiaohongshu.com/explore/post-1",
        "2026-07-04T09:30:00+08:00",
    )

    content = manager.get_content_by_id("content-1")
    assert content is not None
    assert content["status"] == "published"
    assert content["post_id"] == "post-1"
    assert content["url"] == "https://www.xiaohongshu.com/explore/post-1"
    assert content["published_at"] == "2026-07-04T09:30:00+08:00"
    event = manager.connect().execute(
        """
        SELECT event_type
        FROM memory_events
        WHERE content_id = ?
        ORDER BY event_time DESC
        LIMIT 1
        """,
        ("content-1",),
    ).fetchone()
    assert event["event_type"] == "content_published"

    with pytest.raises(ValueError, match="missing"):
        manager.bind_post_identity(
            "missing",
            "post-2",
            "https://www.xiaohongshu.com/explore/post-2",
            "2026-07-04T09:30:00+08:00",
        )


def test_bind_post_identity_rejects_overwriting_existing_identity(manager):
    save_content(manager, "content-1")
    manager.bind_post_identity(
        "content-1",
        "post-1",
        "https://example.com/post-1",
        "2026-07-04T09:30:00+08:00",
    )

    with pytest.raises(ValueError, match="already bound"):
        manager.bind_post_identity(
            "content-1",
            "post-2",
            "https://example.com/post-2",
            "2026-07-05T09:30:00+08:00",
        )

    content = manager.get_content_by_id("content-1")
    assert content is not None
    assert content["post_id"] == "post-1"
    assert content["url"] == "https://example.com/post-1"
    event_count = manager.connect().execute(
        """
        SELECT COUNT(*)
        FROM memory_events
        WHERE content_id = ? AND event_type = 'content_published'
        """,
        ("content-1",),
    ).fetchone()[0]
    assert event_count == 1


def test_bind_post_identity_rejects_post_owned_by_another_content(manager):
    save_content(manager, "content-1")
    save_content(manager, "content-2")
    manager.bind_post_identity(
        "content-1",
        "post-1",
        "https://example.com/post-1",
        "2026-07-04T09:30:00+08:00",
    )

    with pytest.raises(ValueError, match="another content"):
        manager.bind_post_identity(
            "content-2",
            "post-1",
            "https://example.com/post-1",
            "2026-07-04T09:30:00+08:00",
        )

    content = manager.get_content_by_id("content-2")
    assert content is not None
    assert content["post_id"] is None
    event_count = manager.connect().execute(
        """
        SELECT COUNT(*)
        FROM memory_events
        WHERE content_id = ? AND event_type = 'content_published'
        """,
        ("content-2",),
    ).fetchone()[0]
    assert event_count == 0


def test_bind_post_identity_is_idempotent_without_duplicate_event(manager):
    save_content(manager, "content-1")
    first_url = "https://example.com/post-1"
    first_published_at = "2026-07-04T09:30:00+08:00"
    manager.bind_post_identity(
        "content-1",
        "post-1",
        first_url,
        first_published_at,
    )

    manager.bind_post_identity(
        "content-1",
        "post-1",
        "https://example.com/replayed",
        "2026-07-05T09:30:00+08:00",
    )

    content = manager.get_content_by_id("content-1")
    assert content is not None
    assert content["url"] == first_url
    assert content["published_at"] == first_published_at
    event_count = manager.connect().execute(
        """
        SELECT COUNT(*)
        FROM memory_events
        WHERE content_id = ? AND event_type = 'content_published'
        """,
        ("content-1",),
    ).fetchone()[0]
    assert event_count == 1


def test_mark_published_rejects_overwriting_existing_identity(manager):
    save_content(manager, "content-1")
    manager.mark_published(
        "content-1",
        "post-1",
        "https://example.com/post-1",
        "2026-07-04T09:30:00+08:00",
    )

    with pytest.raises(ValueError, match="already bound"):
        manager.mark_published(
            "content-1",
            "post-2",
            "https://example.com/post-2",
            "2026-07-05T09:30:00+08:00",
        )

    content = manager.get_content_by_id("content-1")
    assert content is not None
    assert content["post_id"] == "post-1"
    assert content["url"] == "https://example.com/post-1"
    assert content["published_at"] == "2026-07-04T09:30:00+08:00"
    event_count = manager.connect().execute(
        """
        SELECT COUNT(*)
        FROM memory_events
        WHERE content_id = ? AND event_type = 'content_published'
        """,
        ("content-1",),
    ).fetchone()[0]
    assert event_count == 1


def test_mark_published_same_identity_is_idempotent_without_duplicate_event(manager):
    save_content(manager, "content-1")
    original_url = "https://example.com/post-1"
    original_published_at = "2026-07-04T09:30:00+08:00"
    manager.mark_published(
        "content-1",
        "post-1",
        original_url,
        original_published_at,
    )

    manager.mark_published(
        "content-1",
        "post-1",
        "https://example.com/replayed",
        "2026-07-05T09:30:00+08:00",
    )

    content = manager.get_content_by_id("content-1")
    assert content is not None
    assert content["url"] == original_url
    assert content["published_at"] == original_published_at
    event_count = manager.connect().execute(
        """
        SELECT COUNT(*)
        FROM memory_events
        WHERE content_id = ? AND event_type = 'content_published'
        """,
        ("content-1",),
    ).fetchone()[0]
    assert event_count == 1


def test_init_db_enforces_unique_non_null_post_ids(manager):
    save_content(manager, "content-1")
    save_content(manager, "content-2")
    connection = manager.connect()
    connection.execute(
        "UPDATE contents SET post_id = ? WHERE content_id = ?",
        ("post-1", "content-1"),
    )

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE contents SET post_id = ? WHERE content_id = ?",
            ("post-1", "content-2"),
        )


def test_conflicting_content_save_preserves_owner_and_dependents(manager):
    save_content(
        manager,
        "owner",
        title="Owner",
        post_id="post-1",
        published_at="2026-07-04T09:30:00+08:00",
    )
    manager.update_metrics_batch(
        [MetricsRecord(content_id="owner", views=100, likes=10)],
        "2026-07-05",
        "creator_center_note_export_v1",
    )
    manager.log_event("owner_audit", "owner", {"preserve": True})

    owner_before = manager.get_content_by_id("owner")
    metrics_before = manager.get_metrics("owner")
    history_before = manager.get_metrics_history("owner")
    events_before = [
        dict(row)
        for row in manager.connect().execute(
            """
            SELECT event_id, content_id, event_type, event_time, payload_json
            FROM memory_events
            ORDER BY event_id
            """
        ).fetchall()
    ]

    with pytest.raises(sqlite3.IntegrityError):
        manager.save_generated_content(
            ContentRecord(
                content_id="challenger",
                topic="changed topic",
                title="Changed challenger",
                created_at="2026-07-06T10:00:00+08:00",
                post_id="post-1",
            )
        )

    assert manager.get_content_by_id("challenger") is None
    assert manager.get_content_by_id("owner") == owner_before
    assert manager.get_metrics("owner") == metrics_before
    assert manager.get_metrics_history("owner") == history_before
    events_after = [
        dict(row)
        for row in manager.connect().execute(
            """
            SELECT event_id, content_id, event_type, event_time, payload_json
            FROM memory_events
            ORDER BY event_id
            """
        ).fetchall()
    ]
    assert events_after == events_before


@pytest.mark.parametrize(
    ("incoming_post_id", "incoming_url", "incoming_published_at"),
    [
        (None, None, None),
        (
            "post-different",
            "https://example.com/post-different",
            "2026-07-07T12:00:00+08:00",
        ),
    ],
)
def test_save_generated_content_updates_all_mutable_fields_for_same_content_id(
    manager,
    incoming_post_id,
    incoming_url,
    incoming_published_at,
):
    save_content(manager, "content-1", title="Original")
    original_url = "https://example.com/post-original"
    original_published_at = "2026-07-05T12:00:00+08:00"
    manager.bind_post_identity(
        "content-1",
        "post-original",
        original_url,
        original_published_at,
    )
    replacement = ContentRecord(
        content_id="content-1",
        topic="updated topic",
        created_at="2026-07-06T10:00:00+08:00",
        status="generated",
        platform="xiaohongshu-updated",
        reviewed_at="2026-07-06T11:00:00+08:00",
        published_at=incoming_published_at,
        post_id=incoming_post_id,
        url=incoming_url,
        topic_id="topic-updated",
        angle_id="angle-updated",
        angle="updated angle",
        domain="updated domain",
        subdomain="updated subdomain",
        content_intent="updated intent",
        profile_version="v2",
        risk_level="low",
        target_group="updated group",
        core_pain="updated pain",
        title="Updated title",
        cover_copy="Updated cover",
        content="Updated content",
        hashtags=["#updated"],
        content_format="updated format",
        visual_style="updated style",
        card_count=7,
        storyboards=["updated storyboard"],
        image_paths=["updated.png"],
        strategy_tags=["updated strategy"],
        compliance_status="approved",
        embedding_text="updated embedding",
        metadata={"updated": True},
    )

    manager.save_generated_content(replacement)

    saved = manager.get_content_by_id("content-1")
    assert saved is not None
    for field_name in (
        "platform",
        "created_at",
        "reviewed_at",
        "topic_id",
        "topic",
        "angle_id",
        "angle",
        "domain",
        "subdomain",
        "content_intent",
        "profile_version",
        "risk_level",
        "target_group",
        "core_pain",
        "title",
        "cover_copy",
        "content",
        "hashtags",
        "content_format",
        "visual_style",
        "card_count",
        "storyboards",
        "image_paths",
        "strategy_tags",
        "compliance_status",
        "embedding_text",
        "metadata",
    ):
        assert saved[field_name] == getattr(replacement, field_name)
    assert saved["status"] == "published"
    assert saved["post_id"] == "post-original"
    assert saved["url"] == original_url
    assert saved["published_at"] == original_published_at


def test_get_unbound_published_candidates_filters_and_uses_reference_time(manager):
    save_content(
        manager,
        "published-time",
        published_at="2026-07-04T09:30:00+08:00",
    )
    save_content(manager, "created-time", created_at="2026-07-02T10:00:00+08:00")
    save_content(manager, "empty-title", title="")
    save_content(manager, "already-bound", post_id="post-existing")

    candidates = manager.get_unbound_published_candidates()

    assert {item["content_id"] for item in candidates} == {
        "published-time",
        "created-time",
    }
    by_id = {item["content_id"]: item for item in candidates}
    assert by_id["published-time"]["reference_time"] == "2026-07-04T09:30:00+08:00"
    assert by_id["created-time"]["reference_time"] == "2026-07-02T10:00:00+08:00"
    assert by_id["created-time"]["post_id"] is None


def test_get_metric_match_candidates_includes_bound_and_unbound_content(manager):
    save_content(
        manager,
        "published-time",
        published_at="2026-07-04T09:30:00+08:00",
    )
    save_content(manager, "created-time", created_at="2026-07-02T10:00:00+08:00")
    save_content(manager, "empty-title", title="")
    save_content(
        manager,
        "already-bound",
        published_at="2026-07-03T08:00:00+08:00",
        post_id="post-existing",
    )

    candidates = manager.get_metric_match_candidates()

    assert {item["content_id"] for item in candidates} == {
        "published-time",
        "created-time",
        "already-bound",
    }
    by_id = {item["content_id"]: item for item in candidates}
    assert by_id["published-time"]["reference_time"] == "2026-07-04T09:30:00+08:00"
    assert by_id["created-time"]["reference_time"] == "2026-07-02T10:00:00+08:00"
    assert by_id["created-time"]["post_id"] is None
    assert by_id["already-bound"]["reference_time"] == "2026-07-03T08:00:00+08:00"
    assert by_id["already-bound"]["post_id"] == "post-existing"


@pytest.mark.parametrize("completed_status", ["success", "partial_success"])
def test_run_ledger_start_finish_and_completed_semantics(manager, completed_status):
    manager.start_collection_run("2026-07-05", "2026-07-06")
    manager.finish_collection_run(
        {
            "scheduled_date": "2026-07-05",
            "execution_date": "2026-07-06",
            "status": completed_status,
            "exported_rows": 10,
            "updated_rows": 7,
            "skipped_rows": 2,
            "ambiguous_rows": 1,
            "matched_post_ids": 3,
            "error_summary": None,
        }
    )

    row = dict(
        manager.connect().execute(
            "SELECT * FROM metrics_collection_runs WHERE scheduled_date = ?",
            ("2026-07-05",),
        ).fetchone()
    )
    assert row["status"] == completed_status
    assert row["completed_at"] is not None
    assert row["updated_rows"] == 7
    assert row["error_summary"] is None
    assert manager.has_completed_execution_date("2026-07-06") is True
    assert manager.has_attempted_execution_date("2026-07-06") is True
    assert manager.has_completed_execution_date("2026-07-05") is False
    assert manager.has_attempted_execution_date("2026-07-05") is False


def test_start_collection_run_rejects_duplicate_claim_without_reset(manager):
    manager.start_collection_run("2026-07-05", "2026-07-05")
    manager.finish_collection_run(
        {
            "scheduled_date": "2026-07-05",
            "execution_date": "2026-07-05",
            "status": "failed",
            "exported_rows": 3,
            "updated_rows": 2,
            "skipped_rows": 1,
            "ambiguous_rows": 0,
            "matched_post_ids": 1,
            "error_summary": "safe summary",
        }
    )

    with pytest.raises(
        memory_manager_module.CollectionRunAlreadyClaimed,
        match="2026-07-05",
    ):
        manager.start_collection_run("2026-07-05", "2026-07-07")

    row = dict(
        manager.connect().execute(
            "SELECT * FROM metrics_collection_runs WHERE scheduled_date = ?",
            ("2026-07-05",),
        ).fetchone()
    )
    assert row["execution_date"] == "2026-07-05"
    assert row["status"] == "failed"
    assert row["completed_at"] is not None
    assert row["exported_rows"] == 3
    assert row["updated_rows"] == 2
    assert row["matched_post_ids"] == 1
    assert row["error_summary"] == "safe summary"
    assert manager.has_completed_execution_date("2026-07-07") is False
    assert manager.has_attempted_execution_date("2026-07-05") is True


def test_start_collection_run_rejects_duplicate_execution_date(manager):
    manager.start_collection_run("2026-07-05", "2026-07-06")

    with pytest.raises(
        memory_manager_module.CollectionRunAlreadyClaimed,
        match="2026-07-06",
    ):
        manager.start_collection_run("2026-07-06", "2026-07-06")

    rows = manager.connect().execute(
        "SELECT scheduled_date, execution_date FROM metrics_collection_runs"
    ).fetchall()
    assert [tuple(row) for row in rows] == [("2026-07-05", "2026-07-06")]


def test_finish_collection_run_rejects_wrong_or_stale_completion(manager):
    manager.start_collection_run("2026-07-05", "2026-07-06")
    summary = {
        "scheduled_date": "2026-07-05",
        "execution_date": "2026-07-07",
        "status": "success",
        "exported_rows": 1,
        "updated_rows": 1,
        "skipped_rows": 0,
        "ambiguous_rows": 0,
        "matched_post_ids": 0,
        "error_summary": None,
    }

    with pytest.raises(ValueError, match="running collection run"):
        manager.finish_collection_run(summary)

    row = dict(
        manager.connect().execute(
            "SELECT * FROM metrics_collection_runs WHERE scheduled_date = ?",
            ("2026-07-05",),
        ).fetchone()
    )
    assert row["status"] == "running"
    summary["execution_date"] = "2026-07-06"
    manager.finish_collection_run(summary)

    with pytest.raises(ValueError, match="running collection run"):
        manager.finish_collection_run(summary)


@pytest.mark.parametrize(
    ("summary_update", "error_type", "error_match"),
    [
        ({"status": "running"}, ValueError, "terminal status"),
        ({"updated_rows": -1}, ValueError, "nonnegative integer"),
        ({"exported_rows": 1.5}, TypeError, "nonnegative integer"),
        ({"scheduled_date": 20260705}, TypeError, "scheduled_date"),
        ({"execution_date": None}, TypeError, "execution_date"),
    ],
)
def test_finish_collection_run_validates_summary(
    manager,
    summary_update,
    error_type,
    error_match,
):
    manager.start_collection_run("2026-07-05", "2026-07-06")
    summary = {
        "scheduled_date": "2026-07-05",
        "execution_date": "2026-07-06",
        "status": "failed",
        "exported_rows": 1,
        "updated_rows": 0,
        "skipped_rows": 0,
        "ambiguous_rows": 0,
        "matched_post_ids": 0,
        "error_summary": None,
    }
    summary.update(summary_update)

    with pytest.raises(error_type, match=error_match):
        manager.finish_collection_run(summary)

    row = manager.connect().execute(
        "SELECT status FROM metrics_collection_runs WHERE scheduled_date = ?",
        ("2026-07-05",),
    ).fetchone()
    assert row["status"] == "running"
