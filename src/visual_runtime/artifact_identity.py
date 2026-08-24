"""Descriptor-relative, immutable v4 artifact identity and file primitives.

The public API is intentionally small.  The resolver and artifact binder share
the private directory-descriptor primitives below so a lexical path check is
never followed by an unrelated path-based write.
"""

from __future__ import annotations

import hashlib
import os
import stat
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterator


class ArtifactIdentityError(ValueError):
    """Raised when an artifact identity or path boundary is unsafe."""


class ArtifactBindingError(RuntimeError):
    """Raised when a reused artifact cannot be bound immutably."""


_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_DIR_FLAGS = os.O_RDONLY | _DIRECTORY | _NOFOLLOW


def _validate_component(value: str, field_name: str) -> str:
    if type(value) is not str or not value:
        raise ArtifactIdentityError(f"{field_name} must be a non-empty string")
    if value in {".", ".."}:
        raise ArtifactIdentityError(f"{field_name} cannot be a traversal component")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ArtifactIdentityError(f"{field_name} contains a control character")
    if any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for char in value
    ):
        raise ArtifactIdentityError(
            f"{field_name} must contain only ASCII letters, digits, '.', '_' or '-'")
    if "/" in value or "\\" in value or Path(value).is_absolute():
        raise ArtifactIdentityError(f"{field_name} cannot contain a path separator")
    return value


def _safe_name(value: str, field_name: str = "path component") -> str:
    try:
        return _validate_component(value, field_name)
    except ArtifactIdentityError as error:
        raise ArtifactBindingError(str(error)) from error


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
    """Lexical paths plus the trusted identity of the established base root."""

    base_root: Path
    identity: ArtifactIdentity
    run_root: Path
    candidate_root: Path
    revision_root: Path
    asset_root: Path
    render_root: Path
    review_root: Path
    artifact_root: Path
    trusted_base_identity: tuple[int, int] | None = None

    @property
    def base_identity(self) -> tuple[int, int] | None:
        """Compatibility/readability alias for the pinned base stat identity."""

        return self.trusted_base_identity


@dataclass(frozen=True, slots=True)
class ArtifactBinding:
    """A hash/size-bound copy of a source asset in a revision."""

    destination: Path
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    raw: bytes
    sha256: str
    size: int
    identity: tuple[int, int]


def _lexical_absolute(path: str | os.PathLike[str]) -> Path:
    try:
        # abspath normalizes ``..`` lexically without resolving user symlinks.
        return Path(os.path.abspath(os.fspath(path)))
    except (TypeError, ValueError) as error:
        raise ArtifactIdentityError("artifact root must be a filesystem path") from error


def _canonical_open_path(path: Path) -> Path:
    """Return a lexical spelling, permitting only macOS's fixed ``/var`` alias."""

    lexical = _lexical_absolute(path)
    if sys.platform != "darwin":
        return lexical
    var = Path("/var")
    try:
        relative = lexical.relative_to(var)
    except ValueError:
        return lexical
    try:
        link_target = var.readlink()
        var_info = var.lstat()
        private_var = Path("/private/var")
        private_info = private_var.lstat()
    except OSError:
        return lexical
    if (
        not stat.S_ISLNK(var_info.st_mode)
        or link_target not in {Path("private/var"), private_var}
        or stat.S_ISLNK(private_info.st_mode)
        or not stat.S_ISDIR(private_info.st_mode)
    ):
        return lexical
    return private_var / relative


def _check_existing_chain(path: Path, *, require_directory: bool = False) -> None:
    """Reject user-controlled symlinks in every existing path component."""

    canonical = _canonical_open_path(path)
    current = canonical
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
        if stat.S_ISLNK(info.st_mode):
            raise ArtifactIdentityError(f"artifact path contains symlink: {current}")
        if require_directory and current == canonical and not stat.S_ISDIR(info.st_mode):
            raise ArtifactIdentityError(f"artifact path is not a directory: {current}")
        if current.parent == current:
            break
        current = current.parent


def _snapshot_existing_chain(path: Path) -> dict[Path, tuple[int, int] | None]:
    """Capture existing directory identities before descriptor traversal."""

    snapshot: dict[Path, tuple[int, int] | None] = {}
    current = _canonical_open_path(path)
    components: list[Path] = []
    while True:
        components.append(current)
        if current.parent == current:
            break
        current = current.parent
    for component in reversed(components):
        try:
            info = component.lstat()
        except FileNotFoundError:
            snapshot[component] = None
            continue
        except OSError as error:
            raise ArtifactIdentityError(f"cannot inspect artifact path {component}") from error
        if stat.S_ISLNK(info.st_mode):
            raise ArtifactIdentityError(f"artifact path contains symlink: {component}")
        snapshot[component] = (info.st_dev, info.st_ino)
    return snapshot


def _assert_contained(path: Path, base_root: Path) -> None:
    base = _canonical_open_path(_lexical_absolute(base_root))
    candidate = _lexical_absolute(path)
    try:
        candidate.relative_to(base)
    except ValueError as error:
        raise ArtifactIdentityError("artifact path escapes the explicit base root") from error
    _check_existing_chain(candidate, require_directory=True)
    try:
        candidate.resolve(strict=False).relative_to(base.resolve(strict=False))
    except (OSError, RuntimeError, ValueError) as error:
        raise ArtifactIdentityError("resolved artifact path escapes the explicit base root") from error


def resolve_artifact_paths(
    base_root: str | os.PathLike[str], identity: ArtifactIdentity
) -> ArtifactPaths:
    """Derive v4 paths without creating anything or following a link."""

    if not isinstance(identity, ArtifactIdentity):
        raise ArtifactIdentityError("identity must be an ArtifactIdentity")
    base = _canonical_open_path(_lexical_absolute(base_root))
    _check_existing_chain(base, require_directory=True)
    if base.exists() and not base.is_dir():
        raise ArtifactIdentityError("artifact base root is not a directory")
    trusted_identity: tuple[int, int] | None = None
    if base.exists():
        info = base.lstat()
        trusted_identity = (info.st_dev, info.st_ino)

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
        trusted_base_identity=trusted_identity,
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


def _close_fd_once(fd: int | None) -> OSError | None:
    """Close one owned descriptor; callers must clear ownership first."""

    if fd is None:
        return None
    try:
        os.close(fd)
    except OSError as error:
        return error
    return None


def _attach_cleanup_error(primary: BaseException, cleanup: OSError | None) -> None:
    if cleanup is not None:
        primary.add_note(f"descriptor cleanup failed: {cleanup}")


@dataclass
class _DirectoryLease:
    paths: list[Path]
    fds: list[int | None]
    identities: list[tuple[int, int]]
    base_index: int
    closed: bool = False
    close_error: OSError | None = None

    @property
    def fd(self) -> int:
        if self.closed or self.fds[-1] is None:
            raise ArtifactIdentityError("directory lease is closed")
        return self.fds[-1]  # type: ignore[return-value]

    @property
    def base_identity(self) -> tuple[int, int]:
        return self.identities[self.base_index]

    def add_child(self, name: str, *, create: bool) -> None:
        if self.closed:
            raise ArtifactIdentityError("directory lease is closed")
        _validate_component(name, "directory name")
        parent_fd = self.fd
        child_fd: int | None = None
        try:
            child_fd = _open_child_directory(parent_fd, name, create=create)
            info = os.fstat(child_fd)
        except BaseException as primary:
            owned = child_fd
            child_fd = None
            _attach_cleanup_error(primary, _close_fd_once(owned))
            raise
        assert child_fd is not None
        self.fds.append(child_fd)
        self.paths.append(self.paths[-1] / name)
        self.identities.append((info.st_dev, info.st_ino))

    def assert_intact(self) -> None:
        if self.closed:
            raise ArtifactIdentityError("directory lease is closed")
        for path, fd, expected in zip(self.paths, self.fds, self.identities):
            if fd is None:
                raise ArtifactIdentityError("directory lease descriptor is unavailable")
            current_fd = os.fstat(fd)
            if (current_fd.st_dev, current_fd.st_ino) != expected:
                raise ArtifactIdentityError("pinned directory identity changed")
            try:
                current_path = path.lstat()
            except OSError as error:
                raise ArtifactIdentityError("pinned directory path disappeared") from error
            if stat.S_ISLNK(current_path.st_mode) or not stat.S_ISDIR(current_path.st_mode):
                raise ArtifactIdentityError("pinned directory path changed type")
            if (current_path.st_dev, current_path.st_ino) != expected:
                raise ArtifactIdentityError("pinned directory ancestor changed")

    def close(self) -> OSError | None:
        if self.closed:
            return self.close_error
        self.closed = True
        errors: list[OSError] = []
        for index in range(len(self.fds) - 1, -1, -1):
            fd = self.fds[index]
            self.fds[index] = None  # ownership is transferred before close
            error = _close_fd_once(fd)
            if error is not None:
                errors.append(error)
        self.close_error = errors[0] if errors else None
        return self.close_error


@contextmanager
def _lease_context(lease: _DirectoryLease) -> Iterator[_DirectoryLease]:
    try:
        yield lease
    except BaseException as primary:
        _attach_cleanup_error(primary, lease.close())
        raise
    else:
        error = lease.close()
        if error is not None:
            raise ArtifactIdentityError("directory descriptor close failed") from error


def _open_child_directory(parent_fd: int, name: str, *, create: bool) -> int:
    _validate_component(name, "directory name")
    try:
        return os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        if not create:
            raise
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        return os.open(name, _DIR_FLAGS, dir_fd=parent_fd)


def _open_absolute_directory(path: Path, *, create: bool) -> _DirectoryLease:
    lexical = _lexical_absolute(path)
    _check_existing_chain(lexical, require_directory=False)
    open_path = _canonical_open_path(lexical)
    expected_chain = _snapshot_existing_chain(open_path)
    if not open_path.is_absolute():
        raise ArtifactIdentityError("directory path must be absolute")
    fds: list[int | None] = []
    paths: list[Path] = []
    identities: list[tuple[int, int]] = []
    try:
        root_fd = os.open(os.sep, _DIR_FLAGS)
        fds.append(root_fd)
        paths.append(Path(os.sep))
        root_info = os.fstat(root_fd)
        identities.append((root_info.st_dev, root_info.st_ino))
        current_fd = root_fd
        current_path = Path(os.sep)
        for component in open_path.parts[1:]:
            if component in {"", "."}:
                continue
            child_fd = _open_child_directory(current_fd, component, create=create)
            try:
                child_info = os.fstat(child_fd)
            except BaseException as primary:
                _attach_cleanup_error(primary, _close_fd_once(child_fd))
                raise
            current_path = current_path / component
            expected = expected_chain.get(current_path)
            actual = (child_info.st_dev, child_info.st_ino)
            if expected is not None and actual != expected:
                primary = ArtifactIdentityError("directory ancestor changed during open")
                _attach_cleanup_error(primary, _close_fd_once(child_fd))
                raise primary
            fds.append(child_fd)
            paths.append(current_path)
            identities.append((child_info.st_dev, child_info.st_ino))
            current_fd = child_fd
        base_index = len(fds) - 1
        return _DirectoryLease(paths, fds, identities, base_index)
    except BaseException as primary:
        for index in range(len(fds) - 1, -1, -1):
            fd = fds[index]
            fds[index] = None
            _attach_cleanup_error(primary, _close_fd_once(fd))
        raise


def _pin_artifact_paths(paths: ArtifactPaths, *, create: bool) -> _DirectoryLease:
    lease = _open_absolute_directory(paths.base_root, create=create)
    try:
        for name in (
            paths.identity.run_id,
            paths.identity.candidate_id,
            paths.identity.revision_id,
            "assets",
        ):
            lease.add_child(name, create=create)
        lease.assert_intact()
        return lease
    except BaseException as primary:
        _attach_cleanup_error(primary, lease.close())
        raise


def ensure_artifact_paths(paths: ArtifactPaths) -> ArtifactPaths:
    """Create only the revision/asset roots using descriptor-relative mkdirat."""

    if not isinstance(paths, ArtifactPaths):
        raise ArtifactIdentityError("paths must be ArtifactPaths")
    expected = resolve_artifact_paths(paths.base_root, paths.identity)
    with _lease_context(_pin_artifact_paths(expected, create=True)) as lease:
        lease.assert_intact()
        return replace(expected, trusted_base_identity=lease.base_identity)


def revalidate_artifact_paths(paths: ArtifactPaths) -> ArtifactPaths:
    """Rebuild and pin a complete identity path, rejecting candidate drift."""

    if not isinstance(paths, ArtifactPaths):
        raise ArtifactIdentityError("paths must be ArtifactPaths")
    expected = resolve_artifact_paths(paths.base_root, paths.identity)
    for field in (
        "base_root",
        "run_root",
        "candidate_root",
        "revision_root",
        "asset_root",
        "render_root",
        "review_root",
        "artifact_root",
    ):
        if getattr(paths, field) != getattr(expected, field):
            raise ArtifactIdentityError(f"artifact path field drifted: {field}")
    if paths.trusted_base_identity is None:
        raise ArtifactIdentityError("artifact paths have no trusted base identity")
    with _lease_context(_pin_artifact_paths(expected, create=False)) as lease:
        if lease.base_identity != paths.trusted_base_identity:
            raise ArtifactIdentityError("artifact base identity changed")
        lease.assert_intact()
        return replace(expected, trusted_base_identity=lease.base_identity)


def _read_file_at(parent_fd: int, relative_parts: tuple[str, ...]) -> _FileSnapshot:
    if not relative_parts:
        raise ArtifactBindingError("file path must contain a leaf")
    transient: list[int | None] = []
    current_fd = parent_fd
    try:
        for component in relative_parts[:-1]:
            _safe_name(component)
            child_fd = _open_child_directory(current_fd, component, create=False)
            transient.append(child_fd)
            current_fd = child_fd
        leaf = _safe_name(relative_parts[-1], "file name")
        file_fd: int | None = os.open(leaf, os.O_RDONLY | _NOFOLLOW, dir_fd=current_fd)
        body_primary: BaseException | None = None
        try:
            before = os.fstat(file_fd)
            if not stat.S_ISREG(before.st_mode):
                raise ArtifactBindingError("file is not regular")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(file_fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(file_fd)
            if (after.st_dev, after.st_ino, after.st_size) != (
                before.st_dev,
                before.st_ino,
                before.st_size,
            ):
                raise ArtifactBindingError("file identity changed during read")
            entry = os.stat(leaf, dir_fd=current_fd, follow_symlinks=False)
            if (entry.st_dev, entry.st_ino) != (before.st_dev, before.st_ino):
                raise ArtifactBindingError("file directory entry changed during read")
            raw = b"".join(chunks)
            if len(raw) != after.st_size:
                raise ArtifactBindingError("file size changed during read")
            snapshot = _FileSnapshot(
                raw=raw,
                sha256=hashlib.sha256(raw).hexdigest(),
                size=len(raw),
                identity=(after.st_dev, after.st_ino),
            )
            return snapshot
        except BaseException as error:
            body_primary = error
            raise
        finally:
            owned = file_fd
            file_fd = None
            close_error = _close_fd_once(owned)
            if close_error is not None:
                if body_primary is not None:
                    _attach_cleanup_error(body_primary, close_error)
                else:
                    raise ArtifactBindingError("file descriptor close failed") from close_error
    except BaseException as primary:
        for index in range(len(transient) - 1, -1, -1):
            owned = transient[index]
            transient[index] = None
            _attach_cleanup_error(primary, _close_fd_once(owned))
        if isinstance(primary, OSError):
            if getattr(primary, "errno", None) == getattr(os, "ELOOP", 62):
                raise ArtifactBindingError("source path contains a symlink") from primary
            raise ArtifactBindingError("source file is unreadable") from primary
        raise
    else:
        close_errors: list[OSError] = []
        for index in range(len(transient) - 1, -1, -1):
            owned = transient[index]
            transient[index] = None
            error = _close_fd_once(owned)
            if error is not None:
                close_errors.append(error)
        if close_errors:
            raise ArtifactBindingError("directory descriptor close failed") from close_errors[0]


def read_verified_artifact(
    source: str | os.PathLike[str],
    declared_sha256: str,
    *,
    containment_root: str | os.PathLike[str] | None = None,
) -> bytes:
    """Read one immutable artifact through pinned no-follow descriptors.

    The caller may provide a root (for example a revision's ``assets``
    directory); both lexical and resolved containment are checked before the
    source's parent chain is opened descriptor-relatively.  The file and its
    directory entry are snapshotted before and after the read by
    :func:`_read_file_at`, so a path substitution cannot be mistaken for the
    declared bytes.
    """

    try:
        source_path = _lexical_absolute(source)
    except ArtifactIdentityError as error:
        raise ArtifactBindingError(str(error)) from error
    if type(declared_sha256) is not str or len(declared_sha256) != 64:
        raise ArtifactBindingError("declared sha256 must be a 64-character digest")
    try:
        int(declared_sha256, 16)
    except ValueError as error:
        raise ArtifactBindingError("declared sha256 must be hexadecimal") from error
    if containment_root is not None:
        try:
            root = _canonical_open_path(_lexical_absolute(containment_root))
            _check_existing_chain(root, require_directory=True)
            source_path.relative_to(root)
            source_path.resolve(strict=False).relative_to(root.resolve(strict=False))
        except (ArtifactIdentityError, OSError, RuntimeError, ValueError) as error:
            raise ArtifactBindingError("source path escapes its containment root") from error
    try:
        source_parent = _open_absolute_directory(source_path.parent, create=False)
        with _lease_context(source_parent) as lease:
            snapshot = _read_file_at(lease.fd, (source_path.name,))
            lease.assert_intact()
    except ArtifactBindingError:
        raise
    except (ArtifactIdentityError, OSError) as error:
        raise ArtifactBindingError("source artifact is unreadable or unstable") from error
    if snapshot.sha256 != declared_sha256.lower():
        raise ArtifactBindingError("source sha256 does not match declared sha256")
    return snapshot.raw


@contextmanager
def _open_file_at(parent_fd: int, relative_parts: tuple[str, ...]) -> Iterator[int]:
    """Yield one regular file descriptor opened below a pinned directory."""

    if not relative_parts:
        raise ArtifactBindingError("file path must contain a leaf")
    transient: list[int | None] = []
    current_fd = parent_fd
    file_fd: int | None = None
    body_primary: BaseException | None = None
    cleanup_errors: list[OSError] = []
    try:
        for component in relative_parts[:-1]:
            _safe_name(component)
            child_fd = _open_child_directory(current_fd, component, create=False)
            transient.append(child_fd)
            current_fd = child_fd
        leaf = _safe_name(relative_parts[-1], "file name")
        file_fd = os.open(leaf, os.O_RDONLY | _NOFOLLOW, dir_fd=current_fd)
        opened = os.fstat(file_fd)
        if not stat.S_ISREG(opened.st_mode):
            raise ArtifactBindingError("file is not regular")
        entry = os.stat(leaf, dir_fd=current_fd, follow_symlinks=False)
        if (entry.st_dev, entry.st_ino) != (opened.st_dev, opened.st_ino):
            raise ArtifactBindingError("file directory entry changed during open")
        yield file_fd
    except BaseException as error:
        body_primary = error
        raise
    finally:
        owned = file_fd
        file_fd = None
        close_error = _close_fd_once(owned)
        if close_error is not None:
            if body_primary is not None:
                _attach_cleanup_error(body_primary, close_error)
            else:
                cleanup_errors.append(close_error)
        for index in range(len(transient) - 1, -1, -1):
            owned = transient[index]
            transient[index] = None
            error = _close_fd_once(owned)
            if error is not None:
                if body_primary is not None:
                    _attach_cleanup_error(body_primary, error)
                else:
                    cleanup_errors.append(error)
        if body_primary is None and cleanup_errors:
            raise ArtifactBindingError("file descriptor close failed") from cleanup_errors[0]


def _descriptor_path(fd: int) -> Path:
    """Return a pathname for synchronous use while the caller-owned fd is open.

    The returned path is valid only during the current synchronous consumer
    call.  Callers must not retain it or use it from an asynchronous task after
    ownership of ``fd`` has been transferred/closed.
    """

    for prefix in (Path("/proc/self/fd"), Path("/dev/fd")):
        if prefix.is_dir():
            return prefix / str(fd)
    raise ArtifactBindingError("platform has no descriptor pathname")


def _atomic_write_at(
    parent_fd: int,
    relative_parts: tuple[str, ...],
    content: bytes,
    *,
    replace_existing: bool = False,
) -> None:
    """Publish bytes below a pinned directory with an explicit replace policy."""

    if not relative_parts:
        raise ArtifactBindingError("artifact path must contain a leaf")
    transient: list[int | None] = []
    current_fd = parent_fd
    temporary_name: str | None = None
    temp_fd: int | None = None
    try:
        for component in relative_parts[:-1]:
            _safe_name(component)
            child_fd = _open_child_directory(current_fd, component, create=True)
            transient.append(child_fd)
            current_fd = child_fd
        leaf = _safe_name(relative_parts[-1], "file name")
        temporary_name = f".{leaf}.{uuid.uuid4().hex}.tmp"
        temp_fd = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW,
            0o600,
            dir_fd=current_fd,
        )
        view = memoryview(content)
        while view:
            written = os.write(temp_fd, view)
            if written <= 0:
                raise ArtifactBindingError("artifact write made no progress")
            view = view[written:]
        os.fsync(temp_fd)
        owned = temp_fd
        temp_fd = None
        close_error = _close_fd_once(owned)
        if close_error is not None:
            raise ArtifactBindingError("temporary artifact close failed") from close_error
        if replace_existing:
            os.replace(
                temporary_name,
                leaf,
                src_dir_fd=current_fd,
                dst_dir_fd=current_fd,
            )
        else:
            try:
                os.link(
                    temporary_name,
                    leaf,
                    src_dir_fd=current_fd,
                    dst_dir_fd=current_fd,
                    follow_symlinks=False,
                )
            except FileExistsError as error:
                raise ArtifactBindingError("artifact destination already exists") from error
            os.unlink(temporary_name, dir_fd=current_fd)
        temporary_name = None
        os.fsync(current_fd)
        if current_fd != parent_fd:
            os.fsync(parent_fd)
    except BaseException as primary:
        if temp_fd is not None:
            owned = temp_fd
            temp_fd = None
            _attach_cleanup_error(primary, _close_fd_once(owned))
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=current_fd)
            except OSError as cleanup_error:
                _attach_cleanup_error(primary, cleanup_error)
        for index in range(len(transient) - 1, -1, -1):
            owned = transient[index]
            transient[index] = None
            _attach_cleanup_error(primary, _close_fd_once(owned))
        if isinstance(primary, ArtifactBindingError):
            raise
        raise ArtifactBindingError("artifact publication failed") from primary
    else:
        close_errors: list[OSError] = []
        for index in range(len(transient) - 1, -1, -1):
            owned = transient[index]
            transient[index] = None
            error = _close_fd_once(owned)
            if error is not None:
                close_errors.append(error)
        if close_errors:
            raise ArtifactBindingError("directory descriptor close failed") from close_errors[0]


def _relative_parts(path: Path, root: Path) -> tuple[str, ...]:
    try:
        relative = _lexical_absolute(path).relative_to(_lexical_absolute(root))
    except ValueError as error:
        raise ArtifactBindingError("destination containment violation") from error
    parts = relative.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ArtifactBindingError("destination contains unsafe path components")
    return tuple(_safe_name(part) for part in parts)


def _resolve_destination(
    source: Path,
    destination: Path,
    revision_root: Path | None,
) -> tuple[Path, tuple[str, ...]]:
    destination = _lexical_absolute(destination)
    revision = _lexical_absolute(revision_root) if revision_root is not None else None
    if destination.exists() and destination.is_dir():
        if revision is None:
            revision = destination
        target = destination / source.name
    else:
        if revision is None:
            revision = destination.parent
        target = destination
    assert revision is not None
    _check_existing_chain(revision, require_directory=False)
    try:
        target.relative_to(revision)
    except ValueError as error:
        raise ArtifactBindingError("destination containment violation") from error
    return target, _relative_parts(target, revision)


def bind_reused_artifact(
    source: str | os.PathLike[str],
    declared_sha256: str,
    destination: str | os.PathLike[str],
    revision_root: str | os.PathLike[str] | None = None,
) -> ArtifactBinding:
    """Copy a verified source into a new revision target atomically."""

    try:
        source_path = _lexical_absolute(source)
        destination_path = _lexical_absolute(destination)
        revision_path = _lexical_absolute(revision_root) if revision_root is not None else None
    except ArtifactIdentityError as error:
        raise ArtifactBindingError(str(error)) from error
    if type(declared_sha256) is not str or len(declared_sha256) != 64:
        raise ArtifactBindingError("declared sha256 must be a 64-character digest")
    try:
        int(declared_sha256, 16)
    except ValueError as error:
        raise ArtifactBindingError("declared sha256 must be hexadecimal") from error

    try:
        source_parent = _open_absolute_directory(source_path.parent, create=False)
    except ArtifactIdentityError as error:
        raise ArtifactBindingError(str(error)) from error
    try:
        with _lease_context(source_parent) as source_lease:
            source_snapshot = _read_file_at(source_lease.fd, (source_path.name,))
            source_lease.assert_intact()
    except ArtifactBindingError:
        raise
    except ArtifactIdentityError as error:
        raise ArtifactBindingError(str(error)) from error
    if source_snapshot.sha256 != declared_sha256.lower():
        raise ArtifactBindingError("source sha256 does not match declared sha256")

    target, relative_parts = _resolve_destination(
        source_path,
        destination_path,
        revision_path,
    )
    revision = revision_path if revision_path is not None else target.parent
    if target.exists() and target.is_dir() and target != revision:
        raise ArtifactBindingError("destination must be a file")
    try:
        revision_lease = _open_absolute_directory(revision, create=True)
        with _lease_context(revision_lease) as lease:
            lease.assert_intact()
            _atomic_write_at(lease.fd, relative_parts, source_snapshot.raw)
            lease.assert_intact()
    except ArtifactBindingError:
        raise
    except (ArtifactIdentityError, OSError) as error:
        raise ArtifactBindingError(str(error)) from error
    return ArtifactBinding(destination=target, sha256=source_snapshot.sha256, size=source_snapshot.size)


def bind_staged_directory(
    source: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    *,
    revision_root: str | os.PathLike[str],
) -> Path:
    """Atomically install one complete staged directory without replacement.

    ``source`` and ``destination`` must be direct children of the same pinned
    revision root.  All canonical render files are written below ``source``
    first; this primitive performs the sole directory-level publication step,
    so a failure before the rename leaves no visible destination directory.
    The destination is checked through the pinned parent descriptor and the
    rename is performed relative to that descriptor, never through an
    untrusted ancestor path.
    """

    try:
        source_path = _lexical_absolute(source)
        destination_path = _lexical_absolute(destination)
        revision_path = _lexical_absolute(revision_root)
    except ArtifactIdentityError as error:
        raise ArtifactBindingError(str(error)) from error
    if source_path.parent != revision_path or destination_path.parent != revision_path:
        raise ArtifactBindingError("staged directory must be a direct revision child")
    if source_path.name == destination_path.name:
        raise ArtifactBindingError("staged and destination directory names must differ")
    try:
        lease = _open_absolute_directory(revision_path, create=False)
        with _lease_context(lease):
            lease.assert_intact()
            source_info = os.stat(source_path.name, dir_fd=lease.fd, follow_symlinks=False)
            if stat.S_ISLNK(source_info.st_mode) or not stat.S_ISDIR(source_info.st_mode):
                raise ArtifactBindingError("staged render is not a regular directory")
            _fsync_staged_tree(lease.fd, source_path.name)
            try:
                os.stat(destination_path.name, dir_fd=lease.fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ArtifactBindingError("artifact destination directory already exists")
            os.rename(
                source_path.name,
                destination_path.name,
                src_dir_fd=lease.fd,
                dst_dir_fd=lease.fd,
            )
            lease.assert_intact()
            os.fsync(lease.fd)
    except ArtifactBindingError:
        raise
    except (ArtifactIdentityError, OSError) as error:
        raise ArtifactBindingError("staged directory publication failed") from error
    return destination_path


def _fsync_staged_tree(parent_fd: int, name: str) -> None:
    """Fsync a complete staged directory tree through one pinned parent fd."""

    root_fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    try:
        for child in os.listdir(root_fd):
            try:
                child_fd = os.open(child, _DIR_FLAGS, dir_fd=root_fd)
            except NotADirectoryError:
                continue
            try:
                os.fsync(child_fd)
            finally:
                close_error = _close_fd_once(child_fd)
                if close_error is not None:
                    raise ArtifactBindingError("staged directory close failed") from close_error
        os.fsync(root_fd)
    finally:
        close_error = _close_fd_once(root_fd)
        if close_error is not None:
            raise ArtifactBindingError("staged directory close failed") from close_error


def _create_staging_directory(asset_fd: int, name: str) -> int:
    _safe_name(name)
    os.mkdir(name, mode=0o700, dir_fd=asset_fd)
    try:
        return os.open(name, _DIR_FLAGS, dir_fd=asset_fd)
    except BaseException as primary:
        try:
            os.rmdir(name, dir_fd=asset_fd)
        except OSError as cleanup_error:
            _attach_cleanup_error(primary, cleanup_error)
        raise


def _remove_tree_at(parent_fd: int, name: str) -> None:
    """Remove a provider staging tree using only parent directory fds."""

    _safe_name(name)
    try:
        directory_fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    except NotADirectoryError:
        os.unlink(name, dir_fd=parent_fd)
        return
    try:
        for child in os.listdir(directory_fd):
            _remove_tree_at(directory_fd, child)
    finally:
        owned = directory_fd
        directory_fd = None
        error = _close_fd_once(owned)
        if error is not None:
            raise ArtifactIdentityError("staging directory close failed") from error
    os.rmdir(name, dir_fd=parent_fd)


__all__ = [
    "ArtifactBinding",
    "ArtifactBindingError",
    "ArtifactIdentity",
    "ArtifactIdentityError",
    "ArtifactPaths",
    "bind_reused_artifact",
    "bind_staged_directory",
    "ensure_artifact_paths",
    "read_verified_artifact",
    "revalidate_artifact_paths",
    "resolve_artifact_paths",
]
