"""Shadow exporter: a non-publish evaluation bundle with hard isolation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from src.schemas.v4.publishing import V4_CANONICAL_CONTRACT_FILES

from tests.v4_review_state import reviewed_state


def _shadow_state(tmp_path):
    return reviewed_state(tmp_path / "world")


def test_shadow_export_writes_a_non_publish_evaluation_bundle(tmp_path):
    from src.publishing.shadow_artifacts import export_v4_shadow_bundle

    state, inputs, workspace, result = _shadow_state(tmp_path)
    shadow_root = tmp_path / "outputs" / "shadow"

    bundle = export_v4_shadow_bundle(state, shadow_root=shadow_root)

    assert bundle.bundle_directory.parent == shadow_root
    assert bundle.bundle_directory.is_dir()
    # Evaluation contracts and pages are present for comparison ...
    for name in V4_CANONICAL_CONTRACT_FILES:
        assert (bundle.bundle_directory / name).is_file(), name
    for name in bundle.shadow_manifest.page_sha256:
        assert (bundle.bundle_directory / name).is_file(), name
    # ... but the bundle is explicitly not a publish package.
    assert not (bundle.bundle_directory / "publish-attestation.json").exists()
    manifest = json.loads(
        (bundle.bundle_directory / "shadow-manifest.json").read_text("utf-8")
    )
    assert manifest["workflow_version"] == "llm_scene_v4"
    assert manifest["run_mode"] == "shadow"
    assert manifest["publishable"] is False
    for name, digest in manifest["page_sha256"].items():
        data = (bundle.bundle_directory / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest


def test_shadow_export_never_writes_publish_memory_or_chroma(tmp_path, monkeypatch):
    from src.publishing import shadow_artifacts, v4_artifacts

    state, *_ = _shadow_state(tmp_path)
    publish_sentinel = tmp_path / "outputs" / "publish"
    chroma_sentinel = tmp_path / "data" / "chroma"
    chroma_sentinel.mkdir(parents=True)
    marker = chroma_sentinel / "marker.txt"
    marker.write_text("untouched", encoding="utf-8")

    monkeypatch.setattr(v4_artifacts, "V4_PUBLISH_ROOT", publish_sentinel)

    sqlite_targets: list[str] = []
    real_connect = sqlite3.connect

    def spying_connect(*args, **kwargs):
        sqlite_targets.append(str(args[0] if args else kwargs.get("database", "")))
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spying_connect)

    def forbidden_memory(*_args, **_kwargs):
        raise AssertionError("shadow export must never start the memory manager")

    import memory.memory_manager as memory_module

    monkeypatch.setattr(memory_module, "XHSMemoryManager", forbidden_memory)

    shadow_artifacts.export_v4_shadow_bundle(
        state, shadow_root=tmp_path / "outputs" / "shadow"
    )

    assert not publish_sentinel.exists()
    assert not [
        target
        for target in sqlite_targets
        if "xhs_memory" in target or "chroma" in target
    ]
    assert marker.read_text(encoding="utf-8") == "untouched"
    assert list(chroma_sentinel.iterdir()) == [marker]


def test_shadow_writer_node_is_terminal_and_records_the_bundle(tmp_path, monkeypatch):
    from src.nodes.v4 import shadow_writer as shadow_writer_module

    state, *_ = _shadow_state(tmp_path)
    shadow_root = tmp_path / "outputs" / "shadow"
    monkeypatch.setattr(shadow_writer_module, "SHADOW_ROOT", shadow_root)

    patch = shadow_writer_module.shadow_writer_node(state)

    assert patch["current_node"] == "SHADOW_ARTIFACT_WRITER"
    bundle_path = Path(patch["shadow_bundle_path"])
    assert bundle_path.parent == shadow_root
    assert (bundle_path / "shadow-manifest.json").is_file()
    # The terminal patch adds only shadow evidence, never publish artifacts.
    assert not [key for key in patch if key.startswith("publish")]
    assert not (bundle_path / "publish-attestation.json").exists()


def test_shadow_modules_are_local_only_and_graph_free():
    import inspect

    from src.nodes.v4 import shadow_writer
    from src.publishing import shadow_artifacts

    for module in (shadow_writer, shadow_artifacts):
        source = inspect.getsource(module)
        for banned in (
            "create_graph",
            "XHSMemoryManager",
            "content_writer",
            "publish_package=state",
            "outputs/publish",
        ):
            assert banned not in source, (module.__name__, banned)
