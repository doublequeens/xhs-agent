from __future__ import annotations

from pathlib import Path
from typing import Any

from metrics_collector.launchd import install_launchagent


LABEL = "com.xhs-agent.trend-collector"


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
            "trend_collector",
            "collect",
        ],
        "WorkingDirectory": str(repo_root),
        "StartCalendarInterval": {"Hour": 16, "Minute": 30},
        "RunAtLoad": False,
        "ProcessType": "Background",
        "StandardOutPath": str(logs / "trend_collector.out.log"),
        "StandardErrorPath": str(logs / "trend_collector.err.log"),
    }


def install_trend_launchagent(payload: dict[str, Any], user_home: Path | str) -> Path:
    return install_launchagent(payload, user_home)
