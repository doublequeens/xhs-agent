"""Real SQLite checkpoint tests for the graph-free v4 review CLI entry.

Task 16B closes the last review finding: the real ``main()`` review CLI must
load one WAITING_HUMAN v4 run's exact review contracts, external workspace
reference, and publish package from the production LangGraph SQLite
checkpoint — without a test-injected loader, and without starting a graph,
memory manager, publisher, network, or browser.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from src.run_registry import RunRegistry
from src.schemas.v4.content import canonical_sha256_v4
from src.schemas.v4.review import (
    HumanReviewDecisionReferenceV4,
    ReviewWorkspaceReferenceV4,
)
from src.review.v4_workspace import build_review_workspace, load_review_workspace

from tests.review.test_v4_workspace import _inputs
from tests.test_main import _load_main


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _write_checkpoint(
    path: Path,
    thread_id: str,
    channels: dict,
    *,
    checkpoint_id: str | None = None,
) -> None:
    """Write one real LangGraph SQLite checkpoint with the production serializer."""

    from langgraph.checkpoint.sqlite import SqliteSaver
    from src.checkpoint_serde import checkpoint_serializer

    conn = sqlite3.connect(path)
    try:
        saver = SqliteSaver(conn, serde=checkpoint_serializer())
        saver.setup()
        saver.put(
            {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
            {
                "v": 4,
                "id": checkpoint_id or ("c" * 31 + "1"),
                "ts": "2026-08-26T00:00:00+00:00",
                "channel_values": dict(channels),
                "channel_versions": {name: "1" for name in channels},
                "versions_seen": {},
            },
            {"source": "loop", "step": 1, "writes": None, "parents": {}},
            [],
        )
    finally:
        conn.close()


def _channels(inputs, workspace, *, thread_id: str, extra=None) -> dict:
    """One production-shaped WAITING_HUMAN v4 channel set."""

    channels = {
        "run_id": thread_id,
        "artifact_paths": inputs.artifact_paths,
        "content_lock": inputs.content_lock,
        "content_atom_set": inputs.content_atom_set,
        "semantic_content_model": inputs.semantic_content_model,
        "carousel_narrative": inputs.carousel_narrative,
        "page_brief_set": inputs.page_brief_set,
        "visual_direction_plan": inputs.visual_direction_plan,
        "asset_manifest": inputs.asset_manifest,
        "carousel_design_plan_v4": inputs.carousel_design_plan,
        "design_plan_qa_result_v4": inputs.design_plan_qa,
        "render_manifest_v4": inputs.render_manifest,
        "render_qa_result_v4": inputs.render_qa,
        "visual_critique_v4": inputs.visual_critique,
        "asset_resolution_result_v4": inputs.asset_resolution_result,
        "review_workspace_reference": workspace.reference,
        "publish_package": inputs.content_lock.model_dump(mode="python"),
    }
    if extra:
        channels.update(extra)
    return channels


def _world(tmp_path: Path, *, thread_id: str = "thread-1", revision: int = 1):
    inputs = _inputs(tmp_path, revision=revision, run_id=thread_id)
    workspace = build_review_workspace(inputs)
    return inputs, workspace


def _waiting_registry(tmp_path: Path, thread_id: str) -> RunRegistry:
    registry = RunRegistry(tmp_path / "runs.sqlite")
    registry.create_run(
        thread_id,
        workflow_version="llm_scene_v4",
        status="awaiting_review",
        execution_state="WAITING_HUMAN",
    )
    return registry


# ---------------------------------------------------------------------------
# the real default entry
# ---------------------------------------------------------------------------


def test_default_loader_show_submit_verify_from_real_checkpoint(tmp_path, monkeypatch):
    main = _load_main(monkeypatch)
    thread_id = "thread-1"
    inputs, workspace = _world(tmp_path, thread_id=thread_id)
    cp = tmp_path / "checkpoints.sqlite"
    _write_checkpoint(cp, thread_id, _channels(inputs, workspace, thread_id=thread_id))
    registry = _waiting_registry(tmp_path, thread_id)

    show_out: list[str] = []
    shown = main.run_v4_review_cli(
        main.parse_cli_args(["--review-show", thread_id]),
        registry,
        checkpoint_path=cp,
        output_fn=show_out.append,
    )
    assert type(shown).__name__ == "ReviewWorkspaceV4"
    assert show_out == [(workspace.root / "index.html").as_uri()]

    intent_path = tmp_path / "intent.json"
    intent_path.write_text(json.dumps({"action": "APPROVE"}), encoding="utf-8")
    submit_out: list[str] = []
    result = main.run_v4_review_cli(
        main.parse_cli_args(
            ["--review-submit", thread_id, "--review-intent", str(intent_path)]
        ),
        registry,
        checkpoint_path=cp,
        output_fn=submit_out.append,
    )
    reference = HumanReviewDecisionReferenceV4.model_validate_json(submit_out[0])
    assert reference == result.reference
    assert reference.run_id == thread_id
    assert (
        reference.candidate_id,
        reference.revision_id,
    ) == (
        inputs.artifact_paths.identity.candidate_id,
        inputs.artifact_paths.identity.revision_id,
    )

    reference_path = tmp_path / "reference.json"
    reference_path.write_text(submit_out[0], encoding="utf-8")
    verify_out: list[str] = []
    checked = main.run_v4_review_cli(
        main.parse_cli_args(
            ["--review-verify", thread_id, "--review-reference", str(reference_path)]
        ),
        registry,
        checkpoint_path=cp,
        output_fn=verify_out.append,
    )
    assert checked.run_id == thread_id
    summary = json.loads(verify_out[0])
    assert summary == {
        "workflow_version": "llm_scene_v4",
        "run_id": thread_id,
        "candidate_id": reference.candidate_id,
        "revision_id": reference.revision_id,
        "decision_id": reference.decision_id,
        "decision_canonical_sha256": checked.canonical_sha256,
        "action": "APPROVE",
    }
    # CLI output carries ids and hashes only; no absolute asset paths or blobs.
    assert str(tmp_path) not in submit_out[0]
    assert str(tmp_path) not in verify_out[0]
    registry.close()


def test_main_entry_review_show_uses_real_loader_without_injection(
    tmp_path, monkeypatch, capsys
):
    main = _load_main(monkeypatch)
    thread_id = "thread-1"
    inputs, workspace = _world(tmp_path, thread_id=thread_id)
    cp = tmp_path / "checkpoints.sqlite"
    _write_checkpoint(cp, thread_id, _channels(inputs, workspace, thread_id=thread_id))
    registry = _waiting_registry(tmp_path, thread_id)
    registry.close()

    graph_calls: list[str] = []

    def _forbidden(*_args, **_kwargs):
        graph_calls.append("called")
        raise AssertionError("the review CLI must not start a graph or memory manager")

    monkeypatch.setattr(main, "RUN_REGISTRY_PATH", tmp_path / "runs.sqlite")
    monkeypatch.setattr(main, "DEFAULT_CHECKPOINT_PATH", cp)
    monkeypatch.setattr(main, "create_graph", _forbidden)
    monkeypatch.setattr(main, "XHSMemoryManager", _forbidden)
    monkeypatch.setattr(sys, "argv", ["main.py", "--review-show", thread_id])

    main.main()

    assert graph_calls == []
    assert (workspace.root / "index.html").as_uri() in capsys.readouterr().out


# ---------------------------------------------------------------------------
# identity binding
# ---------------------------------------------------------------------------


def test_default_loader_binds_thread_run_and_artifact_identity(tmp_path, monkeypatch):
    main = _load_main(monkeypatch)
    # state run_id differs from registry thread_id -> fail closed
    inputs, workspace = _world(tmp_path, thread_id="run-other")
    cp = tmp_path / "cp.sqlite"
    _write_checkpoint(cp, "thread-1", _channels(inputs, workspace, thread_id="run-other"))
    registry = RunRegistry(tmp_path / "runs.sqlite")
    for thread in ("thread-1", "run-other"):
        registry.create_run(
            thread,
            workflow_version="llm_scene_v4",
            status="awaiting_review",
            execution_state="WAITING_HUMAN",
        )
    with pytest.raises(main.RunRegistryError, match="unavailable"):
        main.run_v4_review_cli(
            main.parse_cli_args(["--review-show", "thread-1"]),
            registry,
            checkpoint_path=cp,
        )

    # artifact identity differs from the state run_id -> fail closed
    inputs2, workspace2 = _world(tmp_path / "second", thread_id="thread-1")
    channels = _channels(inputs2, workspace2, thread_id="thread-1")
    channels["run_id"] = "run-other"
    cp2 = tmp_path / "cp2.sqlite"
    _write_checkpoint(cp2, "thread-1", channels)
    with pytest.raises(main.RunRegistryError, match="unavailable"):
        main.run_v4_review_cli(
            main.parse_cli_args(["--review-show", "thread-1"]),
            registry,
            checkpoint_path=cp2,
        )
    registry.close()


# ---------------------------------------------------------------------------
# fail-closed matrix
# ---------------------------------------------------------------------------


def test_default_loader_fails_closed_for_missing_or_inexact_checkpoints(
    tmp_path, monkeypatch
):
    main = _load_main(monkeypatch)
    thread_id = "thread-1"
    inputs, workspace = _world(tmp_path, thread_id=thread_id)
    registry = _waiting_registry(tmp_path, thread_id)
    channels = _channels(inputs, workspace, thread_id=thread_id)

    forged_hash_reference = ReviewWorkspaceReferenceV4.create(
        run_id=thread_id,
        candidate_id=inputs.artifact_paths.identity.candidate_id,
        revision_id=inputs.artifact_paths.identity.revision_id,
        anchor_raw_sha256="0" * 64,
        anchor_canonical_sha256="1" * 64,
    )
    wrong_revision_reference = ReviewWorkspaceReferenceV4.create(
        run_id=thread_id,
        candidate_id=inputs.artifact_paths.identity.candidate_id,
        revision_id="revision-9",
        anchor_raw_sha256=workspace.reference.anchor_raw_sha256,
        anchor_canonical_sha256=workspace.reference.anchor_canonical_sha256,
    )

    def drop(name):
        mutated = dict(channels)
        mutated.pop(name)
        return mutated

    cases: dict[str, tuple[Path, dict]] = {}

    missing = dict(channels)
    cases["missing-file"] = (tmp_path / "absent.sqlite", missing)
    wrong_thread_cp = tmp_path / "wrong-thread.sqlite"
    _write_checkpoint(wrong_thread_cp, thread_id, {})
    _write_checkpoint(wrong_thread_cp, "thread-other", channels, checkpoint_id="c" * 31 + "2")
    cases["wrong-thread"] = (wrong_thread_cp, missing)
    cases["empty-channels"] = (tmp_path / "empty.sqlite", {"run_id": thread_id})
    cases["missing-reference"] = (tmp_path / "noref.sqlite", drop("review_workspace_reference"))
    cases["missing-contract"] = (tmp_path / "noqa.sqlite", drop("render_qa_result_v4"))
    cases["missing-package"] = (tmp_path / "nopkg.sqlite", drop("publish_package"))
    cases["wrong-anchor-reference"] = (
        tmp_path / "badref.sqlite",
        {**channels, "review_workspace_reference": forged_hash_reference},
    )
    cases["wrong-identity-reference"] = (
        tmp_path / "wrongid.sqlite",
        {**channels, "review_workspace_reference": wrong_revision_reference},
    )
    tampered_cp = tmp_path / "tampered.sqlite"
    _write_checkpoint(tampered_cp, thread_id, channels)
    index = workspace.root / "index.html"
    index.write_bytes(index.read_bytes() + b"<!-- tampered -->")
    cases["tampered-workspace"] = (tampered_cp, channels)

    failures: list[str] = []
    for label, (cp_path, payload) in cases.items():
        if label != "missing-file":
            _write_checkpoint(cp_path, thread_id, payload)
        try:
            main.run_v4_review_cli(
                main.parse_cli_args(["--review-show", thread_id]),
                registry,
                checkpoint_path=cp_path,
            )
        except main.RunRegistryError:
            continue
        failures.append(label)
    assert failures == []
    registry.close()


# ---------------------------------------------------------------------------
# connection lifecycle and read-only behavior
# ---------------------------------------------------------------------------


def test_default_loader_closes_connections_and_never_writes(tmp_path, monkeypatch):
    main = _load_main(monkeypatch)
    thread_id = "thread-1"
    inputs, workspace = _world(tmp_path, thread_id=thread_id)
    cp = tmp_path / "checkpoints.sqlite"
    _write_checkpoint(cp, thread_id, _channels(inputs, workspace, thread_id=thread_id))
    _write_checkpoint(
        cp, "ghost-row", {"run_id": "ghost-row"}, checkpoint_id="c" * 31 + "2"
    )
    registry = _waiting_registry(tmp_path, thread_id)
    registry.create_run(
        "ghost-row",
        workflow_version="llm_scene_v4",
        status="awaiting_review",
        execution_state="WAITING_HUMAN",
    )

    opened: list[sqlite3.Connection] = []

    class CountingConnection(sqlite3.Connection):
        closed = False

        def close(self):
            self.closed = True
            super().close()

    real_connect = sqlite3.connect

    def counting_connect(*args, **kwargs):
        kwargs.setdefault("factory", CountingConnection)
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", counting_connect)
    digest_before = hashlib.sha256(cp.read_bytes()).hexdigest()

    main.run_v4_review_cli(
        main.parse_cli_args(["--review-show", thread_id]),
        registry,
        checkpoint_path=cp,
    )
    with pytest.raises(main.RunRegistryError):
        main.run_v4_review_cli(
            main.parse_cli_args(["--review-show", "ghost-row"]),
            registry,
            checkpoint_path=cp,
        )
    # A v3 registry row must be rejected before any checkpoint connection opens.
    registry.create_run("v3-thread")
    with pytest.raises(main.RunRegistryError, match="llm_scene_v4"):
        main.run_v4_review_cli(
            main.parse_cli_args(["--review-show", "v3-thread"]),
            registry,
            checkpoint_path=cp,
        )

    assert len(opened) == 2
    assert [conn.closed for conn in opened] == [True, True]
    assert hashlib.sha256(cp.read_bytes()).hexdigest() == digest_before
    # A read-only reader on a WAL-mode database materializes the SQLite
    # coordination files; the guarantee is that no frame is ever checkpointed
    # into the database (digest above) and the WAL stays empty.
    wal_sidecar = tmp_path / "checkpoints.sqlite-wal"
    if wal_sidecar.exists():
        assert wal_sidecar.stat().st_size == 0
    registry.close()


# ---------------------------------------------------------------------------
# visible-copy package binding through the checkpoint
# ---------------------------------------------------------------------------


def test_visible_copy_submit_binds_merged_package_from_checkpoint(tmp_path, monkeypatch):
    main = _load_main(monkeypatch)
    thread_id = "thread-1"
    inputs, workspace = _world(tmp_path, thread_id=thread_id)
    cp = tmp_path / "checkpoints.sqlite"
    original_package = inputs.content_lock.model_dump(mode="python")
    assert original_package["title"]
    merged_package = {**original_package, "title": "全新标题"}
    channels = _channels(
        inputs, workspace, thread_id=thread_id, extra={"publish_package": original_package}
    )
    _write_checkpoint(cp, thread_id, channels)
    registry = _waiting_registry(tmp_path, thread_id)

    intent_path = tmp_path / "intent.json"
    intent_path.write_text(
        json.dumps(
            {
                "action": "VISIBLE_COPY_EDIT",
                "visible_copy_payload": json.dumps({"title": "全新标题"}, ensure_ascii=False),
            }
        ),
        encoding="utf-8",
    )
    submit_out: list[str] = []
    result = main.run_v4_review_cli(
        main.parse_cli_args(
            ["--review-submit", thread_id, "--review-intent", str(intent_path)]
        ),
        registry,
        checkpoint_path=cp,
        output_fn=submit_out.append,
    )
    assert result.route == "r2_compliance"
    assert result.decision.visible_copy_result_sha256 == canonical_sha256_v4(merged_package)

    reference_path = tmp_path / "reference.json"
    reference_path.write_text(submit_out[0], encoding="utf-8")

    # The checkpoint still carries the ORIGINAL package: verification of the
    # merged-package hash must fail closed until the resumed graph persists
    # the edited package (Task 18 wiring).
    with pytest.raises(main.RunRegistryError):
        main.run_v4_review_cli(
            main.parse_cli_args(
                ["--review-verify", thread_id, "--review-reference", str(reference_path)]
            ),
            registry,
            checkpoint_path=cp,
        )
    tampered = {**merged_package, "title": "无关标题"}
    _write_checkpoint(
        cp, thread_id, {**channels, "publish_package": tampered}, checkpoint_id="c" * 31 + "2"
    )
    with pytest.raises(main.RunRegistryError):
        main.run_v4_review_cli(
            main.parse_cli_args(
                ["--review-verify", thread_id, "--review-reference", str(reference_path)]
            ),
            registry,
            checkpoint_path=cp,
        )
    _write_checkpoint(
        cp, thread_id, {**channels, "publish_package": merged_package}, checkpoint_id="c" * 31 + "3"
    )
    verify_out: list[str] = []
    main.run_v4_review_cli(
        main.parse_cli_args(
            ["--review-verify", thread_id, "--review-reference", str(reference_path)]
        ),
        registry,
        checkpoint_path=cp,
        output_fn=verify_out.append,
    )
    assert json.loads(verify_out[0])["action"] == "VISIBLE_COPY_EDIT"
    registry.close()


# ---------------------------------------------------------------------------
# previous revision workspace rehydration
# ---------------------------------------------------------------------------


def test_default_loader_rehydrates_previous_revision_workspace(tmp_path, monkeypatch):
    main = _load_main(monkeypatch)
    thread_id = "thread-1"
    previous = build_review_workspace(_inputs(tmp_path, revision=1, run_id=thread_id))
    loaded_previous = load_review_workspace(previous.artifact_paths, previous.reference)
    current_inputs = _inputs(tmp_path, revision=2, run_id=thread_id).model_copy(
        update={"previous_review_workspace": loaded_previous}
    )
    current = build_review_workspace(current_inputs)
    cp = tmp_path / "checkpoints.sqlite"
    _write_checkpoint(
        cp,
        thread_id,
        _channels(
            current_inputs,
            current,
            thread_id=thread_id,
            extra={"previous_review_workspace_v4": loaded_previous},
        ),
    )
    registry = _waiting_registry(tmp_path, thread_id)

    shown = main.run_v4_review_cli(
        main.parse_cli_args(["--review-show", thread_id]),
        registry,
        checkpoint_path=cp,
    )
    assert shown.root == current.root
    assert shown.manifest.previous_revision_id == previous.manifest.revision_id
    registry.close()


# ---------------------------------------------------------------------------
# graph-free and local-only guarantees
# ---------------------------------------------------------------------------


def test_default_loader_never_mutates_a_crashed_writers_database(tmp_path, monkeypatch):
    """A crashed writer's WAL must be read, never checkpointed or deleted.

    The graph's SQLite checkpointer runs in WAL mode.  A read-write reader
    connection would, on close, checkpoint the leftover WAL into the main
    database and delete the sidecars — silently mutating exactly the crash
    evidence a review CLI must preserve.  The loader must instead read the
    last committed state and leave the database and WAL bytes untouched.
    """

    main = _load_main(monkeypatch)
    thread_id = "thread-1"
    inputs, workspace = _world(tmp_path, thread_id=thread_id)
    cp = tmp_path / "checkpoints.sqlite"
    _write_checkpoint(cp, thread_id, _channels(inputs, workspace, thread_id=thread_id))
    registry = _waiting_registry(tmp_path, thread_id)

    crash = (
        "import os, sqlite3\n"
        f"conn = sqlite3.connect({str(cp)!r})\n"
        # A tiny page cache forces real page spills into the WAL so the
        # crashed transaction leaves frames behind.
        "conn.execute('PRAGMA cache_size=1')\n"
        "conn.execute('BEGIN IMMEDIATE')\n"
        "conn.execute('CREATE TABLE crash_marker(x)')\n"
        "conn.executemany('INSERT INTO crash_marker VALUES (?)', [(b'x' * 4096,)] * 200)\n"
        "os._exit(9)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", crash], capture_output=True, check=False
    )
    assert completed.returncode == 9
    wal = cp.with_name(cp.name + "-wal")
    assert wal.exists() and wal.stat().st_size > 0, "crash must leave WAL frames"
    db_digest = hashlib.sha256(cp.read_bytes()).hexdigest()
    wal_digest = hashlib.sha256(wal.read_bytes()).hexdigest()

    # The committed checkpoint stays readable while the uncommitted frames
    # are ignored — no silent recovery, no exception.
    output: list[str] = []
    main.run_v4_review_cli(
        main.parse_cli_args(["--review-show", thread_id]),
        registry,
        checkpoint_path=cp,
        output_fn=output.append,
    )
    assert output == [(workspace.root / "index.html").as_uri()]
    assert hashlib.sha256(cp.read_bytes()).hexdigest() == db_digest
    assert wal.exists(), "a read-only loader must not checkpoint or delete the WAL"
    assert hashlib.sha256(wal.read_bytes()).hexdigest() == wal_digest
    registry.close()


def test_v4_checkpoint_loader_module_is_graph_free_and_local_only():
    import inspect

    import src.review.v4_checkpoint as loader

    source = inspect.getsource(loader)
    for banned in (
        "src.graph",
        "create_graph",
        "XHSMemoryManager",
        "memory.memory_manager",
        "src.publishing",
        "playwright",
        "requests",
        "urllib",
        "http",
    ):
        assert banned not in source, banned
    assert hasattr(loader, "load_v4_review_checkpoint_bundle")
