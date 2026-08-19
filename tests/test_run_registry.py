import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.run_registry import RunRegistry, RunRegistryError, exception_summary, format_run


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "run_registry"


def create_legacy_registry(tmp_path):
    path = tmp_path / "legacy-agent-runs.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(
        (FIXTURE_ROOT / "legacy-v3-schema.sql").read_text(encoding="utf-8")
    )
    connection.close()
    return path


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


def test_legacy_fixture_has_pre_v4_shape_before_registry_initialization(tmp_path):
    path = tmp_path / "legacy-agent-runs.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(
        (FIXTURE_ROOT / "legacy-v3-schema.sql").read_text(encoding="utf-8")
    )

    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(agent_runs)")
    }
    assert {"workflow_version", "run_mode", "execution_state"}.isdisjoint(columns)
    assert connection.execute(
        "SELECT thread_id, status FROM agent_runs"
    ).fetchone() == ("legacy-thread", "awaiting_review")
    connection.close()


def test_existing_registry_rows_backfill_to_v3_production_and_legacy_state(tmp_path):
    path = create_legacy_registry(tmp_path)
    registry = RunRegistry(path)
    try:
        run = registry.get_by_thread_id("legacy-thread")
        assert run is not None
        assert run.workflow_version == "llm_scene_v3"
        assert run.run_mode == "production"
        assert run.execution_state == "WAITING_HUMAN"
    finally:
        registry.close()


def test_additive_migration_preserves_the_legacy_status_check(tmp_path):
    path = create_legacy_registry(tmp_path)
    registry = RunRegistry(path)
    try:
        schema = registry._connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'agent_runs'"
        ).fetchone()[0]
        assert "CHECK (status IN ('running', 'interrupted', 'awaiting_review', 'completed'))" in schema
        with pytest.raises(sqlite3.IntegrityError):
            registry._connection.execute(
                "UPDATE agent_runs SET status = 'FAILED_FATAL' WHERE thread_id = ?",
                ("legacy-thread",),
            )
    finally:
        registry.close()


def test_v4_fatal_and_exhausted_are_not_ordinary_resumable(registry):
    registry.create_run(
        "fatal", workflow_version="llm_scene_v4", execution_state="FAILED_FATAL"
    )
    registry.create_run(
        "exhausted", workflow_version="llm_scene_v4", execution_state="INTERRUPTED_EXHAUSTED"
    )
    registry.create_run(
        "retry", workflow_version="llm_scene_v4", execution_state="INTERRUPTED_RETRYABLE"
    )
    registry.create_run(
        "waiting", workflow_version="llm_scene_v4", execution_state="WAITING_HUMAN"
    )
    registry.create_run("running", workflow_version="llm_scene_v4", execution_state="RUNNING")
    assert {
        run.thread_id for run in registry.list_resumable()
    } == {"waiting", "retry", "running"}


def test_v3_resumability_still_uses_legacy_status_projection(registry):
    registry.create_run("v3-running", workflow_version="llm_scene_v3", status="running")
    registry.create_run("v3-interrupted", workflow_version="llm_scene_v3", status="interrupted")
    registry.create_run("v3-awaiting", workflow_version="llm_scene_v3", status="awaiting_review")
    registry.create_run("v3-completed", workflow_version="llm_scene_v3", status="completed")

    assert {
        run.thread_id for run in registry.list_resumable()
    } == {"v3-running", "v3-interrupted", "v3-awaiting"}


def test_creation_projects_status_and_execution_state_in_both_directions(registry):
    waiting = registry.create_run(
        "v4-waiting", workflow_version="llm_scene_v4", execution_state="WAITING_HUMAN"
    )
    completed = registry.create_run(
        "v4-completed", workflow_version="llm_scene_v4", status="completed"
    )

    assert (waiting.status, waiting.execution_state) == ("awaiting_review", "WAITING_HUMAN")
    assert (completed.status, completed.execution_state) == ("completed", "COMPLETED")


def test_creation_rejects_conflicting_status_and_execution_state(registry):
    with pytest.raises(RunRegistryError, match="conflict"):
        registry.create_run(
            "conflicting", status="running", execution_state="WAITING_HUMAN"
        )
    assert registry.get_by_thread_id("conflicting") is None


def test_execution_state_updates_atomically_project_legacy_status(registry):
    created = registry.create_run("v4-state", workflow_version="llm_scene_v4")

    updated = registry.update_run(
        created.thread_id, execution_state="INTERRUPTED_EXHAUSTED"
    )
    assert (updated.status, updated.execution_state) == (
        "interrupted",
        "INTERRUPTED_EXHAUSTED",
    )

    updated = registry.update_run(
        created.thread_id,
        execution_state="WAITING_HUMAN",
        status="awaiting_review",
    )
    assert (updated.status, updated.execution_state) == (
        "awaiting_review",
        "WAITING_HUMAN",
    )


@pytest.mark.parametrize(
    ("execution_state", "differing_status"),
    [
        ("FAILED_FATAL", "running"),
        ("INTERRUPTED_EXHAUSTED", "awaiting_review"),
    ],
)
def test_v4_differing_status_only_update_rejects_without_partial_write(
    registry, execution_state, differing_status
):
    created = registry.create_run(
        f"status-only-update-{execution_state}",
        workflow_version="llm_scene_v4",
        execution_state=execution_state,
    )
    before = registry.get_by_thread_id(created.thread_id)

    with pytest.raises(RunRegistryError, match="execution_state"):
        registry.update_run(
            created.thread_id,
            status=differing_status,
            title="must not be written",
        )

    assert registry.get_by_thread_id(created.thread_id) == before


@pytest.mark.parametrize("execution_state", ["FAILED_FATAL", "INTERRUPTED_EXHAUSTED"])
def test_v4_matching_projected_status_is_a_status_only_noop(registry, execution_state):
    created = registry.create_run(
        f"status-only-noop-{execution_state}",
        workflow_version="llm_scene_v4",
        execution_state=execution_state,
    )

    updated = registry.update_run(created.thread_id, status="interrupted")

    assert updated.status == "interrupted"
    assert updated.execution_state == execution_state


@pytest.mark.parametrize(
    ("execution_state", "differing_status"),
    [
        ("FAILED_FATAL", "running"),
        ("INTERRUPTED_EXHAUSTED", "awaiting_review"),
    ],
)
def test_v4_differing_status_only_upsert_rejects_without_partial_write(
    registry, execution_state, differing_status
):
    created = registry.create_run(
        f"status-only-upsert-{execution_state}",
        workflow_version="llm_scene_v4",
        execution_state=execution_state,
    )
    before = registry.get_by_thread_id(created.thread_id)

    with pytest.raises(RunRegistryError, match="execution_state"):
        registry.upsert_run(
            created.thread_id,
            status=differing_status,
            title="must not be written",
        )

    assert registry.get_by_thread_id(created.thread_id) == before


def test_update_rejects_conflicting_status_and_execution_state_without_partial_write(registry):
    created = registry.create_run("v4-conflict", workflow_version="llm_scene_v4")
    before = registry.get_by_thread_id(created.thread_id)

    with pytest.raises(RunRegistryError, match="conflict"):
        registry.update_run(
            created.thread_id,
            status="completed",
            execution_state="FAILED_FATAL",
            title="must not be written",
        )

    after = registry.get_by_thread_id(created.thread_id)
    assert after == before


def test_workflow_identity_is_immutable_and_rejected_before_other_fields_write(registry):
    created = registry.create_run(
        "immutable", workflow_version="llm_scene_v4", run_mode="shadow"
    )
    before = registry.get_by_thread_id(created.thread_id)

    with pytest.raises(RunRegistryError, match="immutable"):
        registry.update_run(
            created.thread_id,
            workflow_version="llm_scene_v3",
            title="must not be written",
        )

    after_update = registry.get_by_thread_id(created.thread_id)
    assert after_update == before

    with pytest.raises(RunRegistryError, match="immutable"):
        registry.upsert_run(
            created.thread_id,
            run_mode="production",
            title="must not be written",
        )
    assert registry.get_by_thread_id(created.thread_id) == before


def test_upsert_accepts_matching_identity_for_existing_thread(registry):
    created = registry.create_run(
        "upsert-identity", workflow_version="llm_scene_v4", run_mode="shadow"
    )
    updated = registry.upsert_run(
        created.thread_id,
        workflow_version="llm_scene_v4",
        run_mode="shadow",
        execution_state="COMPLETED",
        title="完成",
    )

    assert updated.run_id == created.run_id
    assert updated.title == "完成"
    assert (updated.status, updated.execution_state) == ("completed", "COMPLETED")


def test_persisted_enum_corruption_is_rejected_at_registry_boundary(registry):
    registry.create_run("corrupt", workflow_version="llm_scene_v4")
    registry._connection.execute(
        "UPDATE agent_runs SET execution_state = ? WHERE thread_id = ?",
        ("NOT_A_STATE", "corrupt"),
    )

    with pytest.raises(RunRegistryError, match="execution_state"):
        registry.get_by_thread_id("corrupt")


def test_resumable_listing_validates_only_rows_it_returns(registry):
    registry.create_run(
        "corrupt-excluded", workflow_version="llm_scene_v4", execution_state="FAILED_FATAL"
    )
    registry.create_run(
        "valid-resumable", workflow_version="llm_scene_v4", execution_state="RUNNING"
    )
    registry._connection.execute(
        "UPDATE agent_runs SET execution_state = ? WHERE thread_id = ?",
        ("NOT_A_STATE", "corrupt-excluded"),
    )

    assert [run.thread_id for run in registry.list_resumable()] == ["valid-resumable"]
    with pytest.raises(RunRegistryError, match="execution_state"):
        registry.list_recent()


def test_additive_migration_adds_workflow_execution_updated_index_and_preserves_legacy_indexes(
    tmp_path,
):
    path = create_legacy_registry(tmp_path)
    registry = RunRegistry(path)
    try:
        indexes = {}
        for row in registry._connection.execute("PRAGMA index_list(agent_runs)"):
            index_name = row[1]
            indexes[index_name] = [
                index_row[2]
                for index_row in registry._connection.execute(
                    f"PRAGMA index_info('{index_name}')"
                )
            ]

        assert "idx_agent_runs_status_updated_at" in indexes
        assert "idx_agent_runs_workflow_version_execution_state_updated_at" in indexes
        assert indexes["idx_agent_runs_workflow_version_execution_state_updated_at"] == [
            "workflow_version",
            "execution_state",
            "updated_at",
        ]
    finally:
        registry.close()


def test_public_workflow_projection_constants_are_available():
    import src.run_registry as run_registry

    assert hasattr(run_registry, "WorkflowVersion")
    assert hasattr(run_registry, "RunMode")
    assert hasattr(run_registry, "ExecutionState")
    assert run_registry.EXECUTION_TO_LEGACY_STATUS["FAILED_FATAL"] == "interrupted"
    assert run_registry.LEGACY_STATUS_TO_EXECUTION["awaiting_review"] == "WAITING_HUMAN"
