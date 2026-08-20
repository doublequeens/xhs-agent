"""Immutable, containment-safe identity and artifact bindings for v4.

The v4 visual pipeline treats a candidate revision as an append-only artifact
boundary.  This module deliberately does not sanitize identifiers: changing a
caller supplied value while deriving a path would make two identities collide.
Invalid components are rejected instead.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path


class ArtifactIdentityError(ValueError):
    """Raised when an artifact identity or path boundary is unsafe."""


class ArtifactBindingError(RuntimeError):
    """Raised when a reused artifact cannot be bound immutably."""


def _validate_component(value: str, field_name: str) -> str:
    if type(value) is not str or not value:
        raise ArtifactIdentityError(f"{field_name} must be a non-empty string")
    if value in {".", ".."}:
        raise ArtifactIdentityError(f"{field_name} cannot be a traversal component")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ArtifactIdentityError(f"{field_name} contains a control character")
    # Keep the grammar explicit rather than relying on platform Path rules.
    # This also rejects Unicode lookalikes/homoglyphs and encoded separators.
    if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in value):
        raise ArtifactIdentityError(
            f"{field_name} must contain only ASCII letters, digits, '.', '_' or '-'")
    if "/" in value or "\\" in value:
        raise ArtifactIdentityError(f"{field_name} cannot contain a path separator")
    if Path(value).is_absolute():
        raise ArtifactIdentityError(f"{field_name} cannot be absolute")
    return value


@dataclass(frozen=True, slots=True)
class ArtifactIdentity:
    """Strict identity for one v4 run/candidate/revision artifact set."""

    run_id: str
    candidate_id: str
    revision_id: str

    def __post_init__(self) -> None:
        _validate_component(self.run_id, "run_id")
        _validate_component(self.candidate_id, "candidate_id")
        _validate_component(self.revision_id, "revision_id")


@dataclass(frozen=True, slots=True)
class ArtifactPaths:
    """Lexical artifact paths derived from one immutable identity."""

    base_root: Path
    identity: ArtifactIdentity
    run_root: Path
    candidate_root: Path
    revision_root: Path
    asset_root: Path
    render_root: Path
    review_root: Path
    artifact_root: Path


@dataclass(frozen=True, slots=True)
class ArtifactBinding:
    """A hash/size-bound copy of a source asset in a revision."""

    destination: Path
    sha256: str
    size: int


def _lexical_absolute(path: str | os.PathLike[str]) -> Path:
    try:
        return Path(path).absolute()
    except (TypeError, ValueError) as error:
        raise ArtifactIdentityError("artifact root must be a filesystem path") from error


def _check_existing_chain(path: Path, *, require_directory: bool = False) -> None:
    """Reject symlinks in every existing component of ``path``.

    ``Path.resolve`` alone is insufficient here: it follows a link and would
    allow a later mkdir/write to cross an explicitly selected root.
    """

    current = path
    while True:
        try:
            info = current.lstat()
        except FileNotFoundError:
            if current.parent == current:
                break
            current = current.parent
            continue
        except OSError as error:
            raise ArtifactIdentityError(f"cannot inspect artifact path {current}") from error
        # macOS exposes the temporary directory through the system ``/var``
        # compatibility link.  Treat that fixed OS alias as the same explicit
        # root, while still rejecting every user-controlled symlink.
        trusted_darwin_var = (
            current == Path("/var")
            and Path("/private/var").is_dir()
            and current.resolve(strict=False) == Path("/private/var")
        )
        if stat.S_ISLNK(info.st_mode) and not trusted_darwin_var:
            raise ArtifactIdentityError(f"artifact path contains symlink: {current}")
        if require_directory and current == path and not stat.S_ISDIR(info.st_mode):
            raise ArtifactIdentityError(f"artifact root is not a directory: {current}")
        if current.parent == current:
            break
        current = current.parent


def _assert_contained(path: Path, base_root: Path) -> None:
    try:
        path.relative_to(base_root)
    except ValueError as error:
        raise ArtifactIdentityError("artifact path escapes the explicit base root") from error
    _check_existing_chain(path, require_directory=True)
    try:
        resolved_base = base_root.resolve(strict=False)
        resolved_path = path.resolve(strict=False)
        resolved_path.relative_to(resolved_base)
    except (OSError, RuntimeError, ValueError) as error:
        raise ArtifactIdentityError("resolved artifact path escapes the explicit base root") from error


def resolve_artifact_paths(
    base_root: str | os.PathLike[str], identity: ArtifactIdentity
) -> ArtifactPaths:
    """Derive all v4 artifact paths without creating or writing anything."""

    if not isinstance(identity, ArtifactIdentity):
        raise ArtifactIdentityError("identity must be an ArtifactIdentity")
    base = _lexical_absolute(base_root)
    _check_existing_chain(base, require_directory=True)
    if base.exists() and not base.is_dir():
        raise ArtifactIdentityError("artifact base root is not a directory")

    run_root = base / identity.run_id
    candidate_root = run_root / identity.candidate_id
    revision_root = candidate_root / identity.revision_id
    paths = ArtifactPaths(
        base_root=base,
        identity=identity,
        run_root=run_root,
        candidate_root=candidate_root,
        revision_root=revision_root,
        asset_root=revision_root / "assets",
        render_root=revision_root / "render",
        review_root=revision_root / "review",
        artifact_root=revision_root / "artifacts",
    )
    for path in (
        paths.run_root,
        paths.candidate_root,
        paths.revision_root,
        paths.asset_root,
        paths.render_root,
        paths.review_root,
        paths.artifact_root,
    ):
        _assert_contained(path, base)
    return paths


def _mkdir_secure(path: Path) -> None:
    """Create one directory while rejecting symlink/file collisions."""

    _check_existing_chain(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            # Another writer won the race; inspect the winner without
            # following a potentially malicious replacement.
            _check_existing_chain(path)
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise ArtifactIdentityError(f"artifact directory collision: {path}")
        except OSError as error:
            raise ArtifactIdentityError(f"cannot create artifact directory: {path}") from error
        return
    except OSError as error:
        raise ArtifactIdentityError(f"cannot inspect artifact directory: {path}") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ArtifactIdentityError(f"artifact directory collision: {path}")


def ensure_artifact_paths(paths: ArtifactPaths) -> ArtifactPaths:
    """Create and revalidate a v4 path tree without following symlinks."""

    if not isinstance(paths, ArtifactPaths):
        raise ArtifactIdentityError("paths must be ArtifactPaths")
    checked = resolve_artifact_paths(paths.base_root, paths.identity)
    for path in (
        checked.base_root,
        checked.run_root,
        checked.candidate_root,
        checked.revision_root,
        checked.asset_root,
        checked.render_root,
        checked.review_root,
        checked.artifact_root,
    ):
        _mkdir_secure(path)
        _check_existing_chain(path, require_directory=True)
    return checked


def _read_source_bytes(source: Path) -> tuple[bytes, tuple[int, int]]:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        try:
            _check_existing_chain(source)
        except ArtifactIdentityError as error:
            raise ArtifactBindingError("source path contains a symlink") from error
        before = source.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ArtifactBindingError("source must be a regular non-symlink file")
        try:
            descriptor = os.open(source, os.O_RDONLY | nofollow)
        except OSError as error:
            raise ArtifactBindingError("source cannot be opened without following links") from error
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ArtifactBindingError("source identity changed during read")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after_fd = os.fstat(descriptor)
        try:
            after_path = source.lstat()
        except OSError as error:
            raise ArtifactBindingError("source disappeared during read") from error
        if (after_fd.st_dev, after_fd.st_ino) != (before.st_dev, before.st_ino) or (
            after_path.st_dev,
            after_path.st_ino,
        ) != (before.st_dev, before.st_ino):
            raise ArtifactBindingError("source identity changed during read")
        return b"".join(chunks), (before.st_dev, before.st_ino)
    except ArtifactBindingError:
        raise
    except OSError as error:
        raise ArtifactBindingError("source is unreadable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _destination_for(
    source: Path,
    destination: str | os.PathLike[str],
    revision_root: str | os.PathLike[str] | None,
) -> tuple[Path, Path]:
    destination_path = _lexical_absolute(destination)
    if destination_path.exists() and destination_path.is_dir():
        revision = (
            destination_path
            if revision_root is None
            else _lexical_absolute(revision_root)
        )
        target = destination_path / source.name
    else:
        revision = _lexical_absolute(revision_root) if revision_root is not None else destination_path.parent
        target = destination_path
    _check_existing_chain(revision, require_directory=True)
    if not revision.exists():
        _mkdir_secure(revision)
    try:
        target.relative_to(revision)
    except ValueError as error:
        raise ArtifactBindingError("destination containment violation: escapes revision root") from error
    _check_existing_chain(target)
    try:
        if not target.resolve(strict=False).relative_to(revision.resolve(strict=False)):
            raise ArtifactBindingError("destination containment violation: escapes revision root")
    except (OSError, RuntimeError, ValueError) as error:
        if isinstance(error, ArtifactBindingError):
            raise
        raise ArtifactBindingError("destination containment violation: escapes revision root") from error
    parent = target.parent
    # Build only directories below the already validated revision.  A symlink
    # at any level is rejected before a file is created.
    relative_parts = parent.relative_to(revision).parts
    current = revision
    for part in relative_parts:
        current = current / part
        _mkdir_secure(current)
    try:
        info = target.lstat()
    except FileNotFoundError:
        pass
    except OSError as error:
        raise ArtifactBindingError("destination cannot be inspected") from error
    else:
        if stat.S_ISLNK(info.st_mode):
            raise ArtifactBindingError("destination is a symlink")
        raise ArtifactBindingError("destination already exists")
    return revision, target


def bind_reused_artifact(
    source: str | os.PathLike[str],
    declared_sha256: str,
    destination: str | os.PathLike[str],
    revision_root: str | os.PathLike[str] | None = None,
) -> ArtifactBinding:
    """Copy source bytes into a new revision target with no-follow guarantees."""

    source_path = _lexical_absolute(source)
    if type(declared_sha256) is not str or len(declared_sha256) != 64:
        raise ArtifactBindingError("declared sha256 must be a 64-character digest")
    try:
        int(declared_sha256, 16)
    except ValueError as error:
        raise ArtifactBindingError("declared sha256 must be hexadecimal") from error

    raw, _identity = _read_source_bytes(source_path)
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != declared_sha256.lower():
        raise ArtifactBindingError("source sha256 does not match declared sha256")
    revision, target = _destination_for(source_path, destination, revision_root)

    temporary_name: str | None = None
    descriptor: int | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=revision if target.parent == revision else target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        os.fchmod(descriptor, 0o600)
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise ArtifactBindingError("temporary artifact write made no progress")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        # link(2) is atomic and fails with EEXIST; unlike rename/replace it
        # cannot silently overwrite a target created by a racing writer.
        try:
            os.link(temporary_name, target, follow_symlinks=False)
        except FileExistsError as error:
            raise ArtifactBindingError("destination already exists") from error
        except OSError as error:
            raise ArtifactBindingError("cannot atomically publish artifact") from error
        os.unlink(temporary_name)
        temporary_name = None
        directory_descriptor = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except ArtifactBindingError:
        raise
    except OSError as error:
        raise ArtifactBindingError("cannot persist artifact binding") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
    return ArtifactBinding(destination=target, sha256=actual_sha256, size=len(raw))


__all__ = [
    "ArtifactBinding",
    "ArtifactBindingError",
    "ArtifactIdentity",
    "ArtifactIdentityError",
    "ArtifactPaths",
    "bind_reused_artifact",
    "ensure_artifact_paths",
    "resolve_artifact_paths",
]
