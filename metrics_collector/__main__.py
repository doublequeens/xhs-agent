from __future__ import annotations

import argparse
from typing import Sequence

from memory.memory_manager import XHSMemoryManager
from metrics_collector.browser import BrowserSession
from metrics_collector.config import CollectorConfig
from metrics_collector.coordinator import CollectionCoordinator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m metrics_collector",
        description="Collect Xiaohongshu creator-center metrics.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "auth",
        help="open the dedicated browser profile for manual login",
    )
    subparsers.add_parser(
        "collect",
        help="run one daily metrics collection",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = CollectorConfig.default()

    if args.command == "auth":
        return _run_auth(config)
    if args.command == "collect":
        return _run_collect(config)

    parser.error(f"unknown command: {args.command}")
    return 2


def _run_auth(config: CollectorConfig) -> int:
    with BrowserSession(config) as browser:
        if browser.page is None:
            raise RuntimeError("browser session did not create a page")
        browser.page.goto(config.data_analysis_url, wait_until="domcontentloaded")
        print("Log in manually in the opened browser window.")
        input("Press Enter after login is complete: ")
        browser.navigate(config.data_analysis_url)
    print("Authentication validated.")
    return 0


def _run_collect(config: CollectorConfig) -> int:
    manager = XHSMemoryManager(config.db_path)
    manager.init_db(config.schema_path)
    coordinator = CollectionCoordinator(config=config, manager=manager)
    summary = coordinator.collect()
    print(
        "status={status} scheduled_date={scheduled} execution_date={execution} "
        "exported_rows={exported} updated_rows={updated} skipped_rows={skipped} "
        "ambiguous_rows={ambiguous} matched_post_ids={matched}".format(
            status=summary.status,
            scheduled=summary.scheduled_date.isoformat(),
            execution=summary.execution_date.isoformat(),
            exported=summary.exported_rows,
            updated=summary.updated_rows,
            skipped=summary.skipped_rows,
            ambiguous=summary.ambiguous_rows,
            matched=summary.matched_post_ids,
        )
    )
    if summary.error_summary:
        print(f"error={summary.error_summary}")
    return 0 if summary.status in _OK_STATUSES else 1


_OK_STATUSES = {
    "success",
    "partial_success",
    "skipped_already_completed",
    "skipped_already_attempted",
    "skipped_already_claimed",
}


if __name__ == "__main__":
    raise SystemExit(main())
