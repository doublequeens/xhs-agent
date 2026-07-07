from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path
from typing import Sequence

from trend_collector.coordinator import TrendCollectionCoordinator
from trend_collector.launchd import (
    build_launchagent_payload,
    install_trend_launchagent,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m trend_collector",
        description="Collect creator-center trend signals.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("collect", help="run one trend signal collection")
    subparsers.add_parser(
        "install-launchagent",
        help="install the daily trend collector LaunchAgent plist",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "collect":
        summary = TrendCollectionCoordinator().collect()
        print(
            f"status={summary.status} collected_signals={summary.collected_signals}"
        )
        if summary.error_summary:
            print(f"error={summary.error_summary}")
        return 0 if summary.status in {"success", "skipped"} else 1
    if args.command == "install-launchagent":
        user_home = Path.home()
        repo_root = Path(__file__).resolve().parent.parent
        payload = build_launchagent_payload(
            sys.executable,
            repo_root,
            user_home / ".xhs-agent" / "logs",
        )
        plist_path = install_trend_launchagent(payload, user_home)
        print(
            shlex.join(
                [
                    "launchctl",
                    "bootstrap",
                    f"gui/{os.getuid()}",
                    str(plist_path),
                ]
            )
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
