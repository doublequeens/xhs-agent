from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from src.visual_runtime.artifact_identity import (
    ArtifactBindingError,
    ArtifactIdentity,
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
