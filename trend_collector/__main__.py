from __future__ import annotations

import argparse
from typing import Sequence

from trend_collector.coordinator import TrendCollectionCoordinator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m trend_collector",
        description="Collect creator-center trend signals.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("collect", help="run one trend signal collection")
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
        return 0 if summary.status == "success" else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
