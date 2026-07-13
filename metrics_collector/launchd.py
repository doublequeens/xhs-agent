from __future__ import annotations

import os
import plistlib
import secrets
import stat
from pathlib import Path
from typing import Any, Mapping


LABEL = "com.xhs-agent.metrics-collector"


def ensure_launchagent_timezone(
    expected_timezone: str,
    *,
    localtime_path: Path | str = Path("/etc/localtime"),
) -> None:
    path = Path(localtime_path)
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError(
            "cannot verify macOS system timezone for LaunchAgent"
        ) from exc
    if not path.is_symlink() or not resolved.as_posix().endswith(
        f"/{expected_timezone}"
    ):
        raise ValueError(
            "LaunchAgent StartCalendarInterval uses macOS system local time; "
            f"set system timezone to {expected_timezone} before installing"
        )


def build_launchagent_payload(
    python_path: Path | str,
    repo_root: Path | str,
    log_dir: Path | str,
) -> dict[str, Any]:
    logs = Path(log_dir)
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(python_path),
            "-m",
            "metrics_collector",
            "collect",
        ],
        "WorkingDirectory": str(repo_root),
        "StartCalendarInterval": {"Hour": 22, "Minute": 0},
        "RunAtLoad": True,
        "ProcessType": "Background",
        "StandardOutPath": str(logs / "collector.out.log"),
        "StandardErrorPath": str(logs / "collector.err.log"),
    }


def install_launchagent(
    payload: Mapping[str, Any], user_home: Path | str
) -> Path:
    home = Path(os.path.abspath(user_home))
    home.mkdir(parents=True, exist_ok=True)
    home_fd = _open_directory(home)
    launchagents_fd = -1
    try:
        library_fd = _open_or_create_directory(home_fd, "Library")
        try:
            launchagents_fd = _open_or_create_directory(
                library_fd, "LaunchAgents"
            )
        finally:
            os.close(library_fd)

        state_fd = _open_or_create_directory(
            home_fd, ".xhs-agent", mode=0o700
        )
        os.close(state_fd)
        _prepare_log_directories(payload, home, home_fd)

        _write_plist(payload, launchagents_fd)
    finally:
        if launchagents_fd >= 0:
            os.close(launchagents_fd)
        os.close(home_fd)

    launchagents_dir = home / "Library" / "LaunchAgents"
    plist_path = launchagents_dir / f"{payload['Label']}.plist"
    return plist_path


def _prepare_log_directories(
    payload: Mapping[str, Any], home: Path, home_fd: int
) -> None:
    for key in ("StandardOutPath", "StandardErrorPath"):
        log_dir = Path(os.path.abspath(payload[key])).parent
        try:
            relative = log_dir.relative_to(home)
        except ValueError as exc:
            raise ValueError("log path must remain within user home") from exc
        if not relative.parts:
            raise ValueError("log path must use a directory within user home")

        parent_fd = os.dup(home_fd)
        try:
            for component in relative.parts:
                child_fd = _open_or_create_directory(parent_fd, component)
                os.close(parent_fd)
                parent_fd = child_fd
            os.fchmod(parent_fd, 0o700)
        finally:
            os.close(parent_fd)


def _write_plist(payload: Mapping[str, Any], launchagents_fd: int) -> None:
    plist_name = f"{payload['Label']}.plist"
    try:
        target_stat = os.stat(
            plist_name, dir_fd=launchagents_fd, follow_symlinks=False
        )
    except FileNotFoundError:
        target_stat = None
    if target_stat is not None and stat.S_ISLNK(target_stat.st_mode):
        raise ValueError("refusing to replace symlink plist target")

    temporary_name = f".{payload['Label']}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW
    fd = os.open(temporary_name, flags, 0o600, dir_fd=launchagents_fd)
    try:
        os.fchmod(fd, 0o600)
        try:
            plist_file = os.fdopen(fd, "wb")
        except BaseException:
            os.close(fd)
            fd = -1
            raise
        fd = -1
        with plist_file:
            plistlib.dump(dict(payload), plist_file)
            plist_file.flush()
            os.fsync(plist_file.fileno())
        os.replace(
            temporary_name,
            plist_name,
            src_dir_fd=launchagents_fd,
            dst_dir_fd=launchagents_fd,
        )
        os.fsync(launchagents_fd)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary_name, dir_fd=launchagents_fd)
        except FileNotFoundError:
            pass
        raise


def _open_directory(path: Path) -> int:
    try:
        return os.open(path, os.O_RDONLY | _DIRECTORY | _NOFOLLOW)
    except OSError as exc:
        raise ValueError("refusing symlink or non-directory user home") from exc


def _open_or_create_directory(
    parent_fd: int, name: str, mode: int = 0o755
) -> int:
    try:
        os.mkdir(name, mode=mode, dir_fd=parent_fd)
    except FileExistsError:
        pass
    try:
        directory_fd = os.open(
            name,
            os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
            dir_fd=parent_fd,
        )
    except OSError as exc:
        raise ValueError(
            f"refusing symlink or non-directory path component: {name}"
        ) from exc
    try:
        if mode == 0o700:
            os.fchmod(directory_fd, mode)
    except BaseException:
        os.close(directory_fd)
        raise
    return directory_fd


_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
