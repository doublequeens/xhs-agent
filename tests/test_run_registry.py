from datetime import datetime, timezone

import pytest

from src.run_registry import RunRegistry, RunRegistryError, exception_summary, format_run


@pytest.fixture
def registry(tmp_path):
    instance = RunRegistry(tmp_path / "agent_runs.sqlite")
    yield instance
    instance.close()


def test_create_and_update_run_preserves_identity_and_uses_utc(registry):
    created = registry.create_run("thread-a", "通勤防晒")
    updated = registry.update_run(
        "thread-a",
        status="interrupted",
        domain="beauty",
        subdomain="skincare",
        topic_summary="防晒后底妆卡粉怎么办",
        last_node="TITLE_RANKER",
        error_summary="TimeoutError: request timed out",
    )

    assert created.run_id == updated.run_id
    assert updated.status == "interrupted"
    assert updated.title is None
    assert updated.topic_summary == "防晒后底妆卡粉怎么办"
    assert datetime.fromisoformat(updated.created_at.replace("Z", "+00:00")).tzinfo == timezone.utc


def test_resumable_filter_order_and_completed_history(registry):
    registry.create_run("thread-first", "A")
    registry.create_run("thread-second", "B")
    registry.update_run("thread-first", status="completed")
    registry.update_run("thread-second", status="awaiting_review")

    assert [run.thread_id for run in registry.list_resumable()] == ["thread-second"]
    assert [run.thread_id for run in registry.list_recent()] == ["thread-second", "thread-first"]


def test_same_thread_resume_updates_one_registry_record_through_completion(registry):
    created = registry.create_run("thread-resume", "合成回归")
    registry.update_run(
        "thread-resume",
        status="awaiting_review",
        last_node="ASSET_RESOLVER",
    )
    registry.update_run(
        "thread-resume",
        status="interrupted",
        last_node="EDITORIAL_CAROUSEL_RENDERER",
    )
    completed = registry.update_run(
        "thread-resume",
        status="completed",
        last_node="MEMORY_UPDATER",
    )

    recent = registry.list_recent()
    assert len(recent) == 1
    assert completed.run_id == created.run_id == recent[0].run_id
    assert recent[0].status == "completed"
    assert recent[0].last_node == "MEMORY_UPDATER"


def test_unique_thread_id_and_legacy_upsert_keep_existing_fields(registry):
    registry.create_run("legacy-thread", "旧关键词")

    with pytest.raises(RunRegistryError, match="already exists"):
        registry.create_run("legacy-thread", "重复")

    run = registry.upsert_run(
        "legacy-thread",
        status="running",
        title="通勤底妆指南",
        domain="beauty",
    )
    assert run.focus_keyword == "旧关键词"
    assert run.title == "通勤底妆指南"
    assert run.domain == "beauty"


def test_error_truncation_and_compact_display_hide_full_thread_id(registry):
    summary = exception_summary(TimeoutError("x" * 400))
    run = registry.create_run("xhs_conversation_20260713T063200_abcdef", "通勤防晒")
    run = registry.update_run(
        run.thread_id,
        status="interrupted",
        last_node="TITLE_RANKER",
        error_summary=summary,
    )

    assert summary == "TimeoutError: " + "x" * 240
    assert "TITLE_RANKER" in format_run(run)
    assert run.thread_id not in format_run(run)
    assert "xhs_conversation_20260713T0632..." in format_run(run)
    assert run.thread_id in format_run(run, verbose=True)


def test_compact_display_keeps_ids_through_33_characters(registry):
    short = registry.create_run("a" * 33, "通勤防晒")
    long = registry.create_run("b" * 34, "通勤防晒")

    assert f"ID：{short.thread_id}" in format_run(short)
    assert long.thread_id not in format_run(long)
    assert f"ID：{'b' * 30}..." in format_run(long)


def test_initialization_wraps_uncreatable_registry_parent(tmp_path):
    parent_file = tmp_path / "not-a-directory"
    parent_file.touch()
    registry_path = parent_file / "agent_runs.sqlite"

    with pytest.raises(RunRegistryError) as exc_info:
        RunRegistry(registry_path)

    assert str(registry_path) in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, OSError)


def test_delete_run_removes_only_named_thread(registry):
    registry.create_run("thread-a", "A")
    registry.create_run("thread-b", "B")

    assert registry.delete_run("thread-a") is True
    assert registry.get_by_thread_id("thread-a") is None
    assert registry.get_by_thread_id("thread-b") is not None
    # deleting a missing thread is a no-op, not an error
    assert registry.delete_run("thread-a") is False


def test_delete_all_removes_every_run(registry):
    registry.create_run("thread-a", "A")
    registry.create_run("thread-b", "B")
    registry.update_run("thread-b", status="completed")

    assert registry.delete_all() == 2
    assert registry.list_recent() == []


def test_delete_all_with_status_filter_keeps_others(registry):
    registry.create_run("thread-a", "A")
    registry.create_run("thread-b", "B")
    registry.update_run("thread-a", status="completed")
    registry.update_run("thread-b", status="interrupted")

    assert registry.delete_all(statuses=("completed",)) == 1
    remaining = [r.thread_id for r in registry.list_recent()]
    assert remaining == ["thread-b"]
