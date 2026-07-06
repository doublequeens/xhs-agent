from __future__ import annotations

import os
import plistlib
import tempfile
from pathlib import Path
from typing import Any, Mapping


LABEL = "com.xhs-agent.metrics-collector"


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
    launchagents_dir = Path(user_home) / "Library" / "LaunchAgents"
    if launchagents_dir.is_symlink():
        raise ValueError("refusing to use symlink LaunchAgents directory")
    launchagents_dir.mkdir(parents=True, exist_ok=True)
    plist_path = launchagents_dir / f"{LABEL}.plist"
    if plist_path.is_symlink():
        raise ValueError("refusing to replace symlink plist target")

    for key in ("StandardOutPath", "StandardErrorPath"):
        log_dir = Path(payload[key]).parent
        if log_dir.is_symlink():
            raise ValueError("refusing to use symlink log directory")
        log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        log_dir.chmod(0o700)

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{LABEL}.", suffix=".tmp", dir=launchagents_dir
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as plist_file:
            plistlib.dump(dict(payload), plist_file)
            plist_file.flush()
            os.fsync(plist_file.fileno())
        temporary_path.chmod(0o600)
        os.replace(temporary_path, plist_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return plist_path
