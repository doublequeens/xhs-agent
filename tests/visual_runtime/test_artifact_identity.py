from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

from src.visual_runtime.artifact_identity import (
    ArtifactBindingError,
    ArtifactIdentity,
    _open_absolute_directory,
    _read_file_at,
    bind_reused_artifact,
    resolve_artifact_paths,
)


def test_revision_paths_include_run_candidate_and_revision(tmp_path: Path):
    identity = ArtifactIdentity("run-1", "candidate-2", "revision-3")
    paths = resolve_artifact_paths(tmp_path, identity)

    assert paths.render_root.relative_to(tmp_path).parts[-4:] == (
        "run-1",
        "candidate-2",
        "revision-3",
        "render",
    )
    assert paths.revision_root == tmp_path / "run-1" / "candidate-2" / "revision-3"
    assert paths.asset_root == paths.revision_root / "assets"


@pytest.mark.parametrize("value", ["", ".", "..", "a/b", "a\\b", "a\x00b", "ｒｕｎ", "/tmp/run"])
def test_identity_rejects_unsafe_path_components(value: str):
    with pytest.raises(ValueError):
        ArtifactIdentity(value, "candidate", "revision")


def test_paths_reject_symlinked_base_or_existing_ancestor(tmp_path: Path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        resolve_artifact_paths(link, ArtifactIdentity("run", "candidate", "revision"))


def test_parallel_identities_have_disjoint_revision_roots(tmp_path: Path):
    left = resolve_artifact_paths(tmp_path, ArtifactIdentity("run", "a", "r"))
    right = resolve_artifact_paths(tmp_path, ArtifactIdentity("run", "b", "r"))
    another = resolve_artifact_paths(tmp_path, ArtifactIdentity("run", "a", "r-2"))

    assert left.revision_root != right.revision_root
    assert left.revision_root != another.revision_root


def test_reuse_requires_matching_bytes(tmp_path: Path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    revision_root = tmp_path / "revision"
    revision_root.mkdir()

    with pytest.raises(ArtifactBindingError, match="sha256"):
        bind_reused_artifact(
            source,
            declared_sha256="0" * 64,
            destination=revision_root / "assets" / "copy.bin",
            revision_root=revision_root,
        )


def test_reuse_binds_bytes_without_mutating_source(tmp_path: Path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    source_before = source.read_bytes()
    revision_root = tmp_path / "revision"
    destination = revision_root / "assets" / "copy.bin"
    digest = hashlib.sha256(source_before).hexdigest()

    binding = bind_reused_artifact(
        source,
        declared_sha256=digest,
        destination=destination,
        revision_root=revision_root,
    )

    assert binding.destination == destination
    assert binding.sha256 == digest
    assert binding.size == len(source_before)
    assert destination.read_bytes() == source_before
    assert source.read_bytes() == source_before


def test_reuse_rejects_symlink_source_and_destination_escape(tmp_path: Path):
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    source_link = tmp_path / "source-link"
    source_link.symlink_to(outside)
    revision_root = tmp_path / "revision"
    revision_root.mkdir()
    digest = hashlib.sha256(outside.read_bytes()).hexdigest()

    with pytest.raises(ArtifactBindingError, match="symlink"):
        bind_reused_artifact(
            source_link,
            declared_sha256=digest,
            destination=revision_root / "copy.bin",
            revision_root=revision_root,
        )

    with pytest.raises(ArtifactBindingError, match="contain"):
        bind_reused_artifact(
            outside,
            declared_sha256=digest,
            destination=tmp_path / "escape.bin",
            revision_root=revision_root,
        )


def test_reuse_does_not_overwrite_existing_target(tmp_path: Path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"source")
    revision_root = tmp_path / "revision"
    revision_root.mkdir()
    destination = revision_root / "copy.bin"
    destination.write_bytes(b"existing")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    with pytest.raises(ArtifactBindingError, match="exists"):
        bind_reused_artifact(
            source,
            declared_sha256=digest,
            destination=destination,
            revision_root=revision_root,
        )
    assert destination.read_bytes() == b"existing"


def test_reuse_rejects_symlinked_source_ancestor(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    source = outside / "source.bin"
    source.write_bytes(b"source")
    source_parent = tmp_path / "source-parent"
    source_parent.symlink_to(outside, target_is_directory=True)
    revision_root = tmp_path / "revision"
    revision_root.mkdir()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    with pytest.raises(ArtifactBindingError, match="symlink"):
        bind_reused_artifact(
            source_parent / "source.bin",
            declared_sha256=digest,
            destination=revision_root / "copy.bin",
            revision_root=revision_root,
        )


def test_reuse_close_failure_is_typed_and_never_retries_fd(tmp_path: Path, monkeypatch):
    from src.visual_runtime import artifact_identity as module

    source = tmp_path / "source.bin"
    source.write_bytes(b"source")
    revision_root = tmp_path / "revision"
    revision_root.mkdir()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    original_close = module.os.close
    calls: list[int] = []

    def close_once(fd: int):
        calls.append(fd)
        if len(calls) == 1:
            raise OSError("close sentinel")
        return original_close(fd)

    monkeypatch.setattr(module.os, "close", close_once)
    with pytest.raises(ArtifactBindingError, match="close"):
        bind_reused_artifact(
            source,
            declared_sha256=digest,
            destination=revision_root / "copy.bin",
            revision_root=revision_root,
        )
    assert len(calls) == len(set(calls))


def test_read_primary_error_survives_file_close_error(tmp_path: Path, monkeypatch):
    from src.visual_runtime import artifact_identity as module

    source = tmp_path / "source.bin"
    source.write_bytes(b"source")
    lease = _open_absolute_directory(tmp_path, create=False)
    original_close_once = module._close_fd_once
    close_calls: list[int] = []

    def close_with_secondary_error(fd: int):
        close_calls.append(fd)
        if len(close_calls) == 1:
            return OSError("close secondary")
        return original_close_once(fd)

    monkeypatch.setattr(module, "_close_fd_once", close_with_secondary_error)
    monkeypatch.setattr(module.os, "read", lambda *_args: (_ for _ in ()).throw(OSError("body primary")))
    try:
        with pytest.raises(ArtifactBindingError, match="unreadable") as exc_info:
            _read_file_at(lease.fd, (source.name,))
    finally:
        monkeypatch.undo()
        lease.close()

    assert isinstance(exc_info.value.__cause__, OSError)
    assert "body primary" in str(exc_info.value.__cause__)
    assert any(
        "descriptor cleanup failed" in note
        for note in getattr(exc_info.value.__cause__, "__notes__", ())
    )
    assert len(close_calls) == len(set(close_calls))


@pytest.mark.skipif(sys.platform != "darwin", reason="/var alias is macOS-specific")
def test_macos_var_alias_is_accepted_but_user_symlink_is_not(tmp_path: Path):
    private_var = Path("/private/var")
    if not Path("/var").is_symlink() or not tmp_path.is_relative_to(private_var):
        pytest.skip("host does not expose the macOS /var alias")

    alias = Path("/var") / tmp_path.relative_to(private_var)
    paths = resolve_artifact_paths(alias, ArtifactIdentity("run", "candidate", "revision"))
    assert paths.base_root == tmp_path

    user_real = tmp_path / "real"
    user_real.mkdir()
    user_link = tmp_path / "user-link"
    user_link.symlink_to(user_real, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        resolve_artifact_paths(
            user_link,
            ArtifactIdentity("run", "candidate", "revision"),
        )
