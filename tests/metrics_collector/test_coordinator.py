from __future__ import annotations

import os
import stat
from dataclasses import replace
from datetime import datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from memory.models import MetricsRecord
from metrics_collector.browser import (
    AccessBlocked,
    AuthenticationRequired,
    VerificationRequired,
)
from metrics_collector.config import CollectorConfig
from metrics_collector.coordinator import (
    CollectionCoordinator,
    preserve_diagnostic_workbook,
    scheduled_date_for,
)
from metrics_collector.models import (
    ContentCandidate,
    ExportedMetrics,
    MatchResult,
    NoteIdentity,
)
from metrics_collector.workbook import WorkbookFormatError


TZ = ZoneInfo("Asia/Shanghai")
AT_09 = datetime(2026, 7, 6, 9, 0, tzinfo=TZ)
AT_22 = datetime(2026, 7, 6, 22, 0, tzinfo=TZ)
AT_23 = datetime(2026, 7, 6, 23, 0, tzinfo=TZ)
POST_ID = "0123456789abcdef01234567"


class FakeManager:
    def __init__(self) -> None:
        self.completed_execution_dates: set[str] = set()
        self.unbound_candidates: list[dict[str, object]] = []
        self.start_calls: list[tuple[str, str]] = []
        self.finish_summaries: list[dict[str, object]] = []
        self.bind_calls: list[dict[str, object]] = []
        self.update_calls: list[dict[str, object]] = []
        self.raise_on_update: Exception | None = None
        self.latest: dict[str, MetricsRecord] = {}
        self.history: list[dict[str, object]] = []

    def has_completed_execution_date(self, execution_date: str) -> bool:
        return execution_date in self.completed_execution_dates

    def start_collection_run(
        self,
        scheduled_date: str,
        execution_date: str,
    ) -> None:
        self.start_calls.append((scheduled_date, execution_date))

    def finish_collection_run(self, summary: dict[str, object]) -> None:
        self.finish_summaries.append(dict(summary))
        if summary["status"] in {"success", "partial_success"}:
            self.completed_execution_dates.add(str(summary["execution_date"]))

    def get_unbound_published_candidates(self) -> list[dict[str, object]]:
        return list(self.unbound_candidates)

    def bind_post_identity(
        self,
        content_id: str,
        post_id: str,
        url: str,
        published_at: str,
    ) -> None:
        self.bind_calls.append(
            {
                "content_id": content_id,
                "post_id": post_id,
                "url": url,
                "published_at": published_at,
            }
        )

    def update_metrics_batch(
        self,
        records: list[MetricsRecord],
        collected_date: str,
        source: str,
    ) -> list[MetricsRecord]:
        self.update_calls.append(
            {
                "records": list(records),
                "collected_date": collected_date,
                "source": source,
            }
        )
        if self.raise_on_update is not None:
            raise self.raise_on_update
        for record in records:
            self.latest[record.content_id] = record
            self.history.append(
                {
                    "content_id": record.content_id,
                    "collected_date": collected_date,
                    "source": source,
                }
            )
        return records


class FakeBrowser:
    def __init__(self) -> None:
        self.page = SimpleNamespace(name="page")
        self.navigate_calls: list[str] = []
        self.raise_on_url: dict[str, Exception] = {}
        self.enter_calls = 0
        self.exit_calls = 0

    def __enter__(self) -> "FakeBrowser":
        self.enter_calls += 1
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.exit_calls += 1
        return False

    def navigate(self, url: str) -> None:
        self.navigate_calls.append(url)
        if url in self.raise_on_url:
            raise self.raise_on_url[url]


class FakeBrowserFactory:
    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser
        self.calls = 0

    def __call__(self) -> FakeBrowser:
        self.calls += 1
        return self.browser


class FakeIdentityCollector:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.identities: list[NoteIdentity] = []

    def __call__(self, page, max_pages, timezone, stop_when=None):
        self.calls.append(
            {
                "page": page,
                "max_pages": max_pages,
                "timezone": timezone,
                "stop_when": stop_when,
            }
        )
        return list(self.identities)


class FakeExporter:
    def __init__(self, workbook_path: Path) -> None:
        self.calls: list[object] = []
        self.workbook_path = workbook_path

    def export(self, page) -> Path:
        self.calls.append(page)
        return self.workbook_path


class FakeParser:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.rows: list[ExportedMetrics] = []
        self.error: Exception | None = None

    def __call__(self, path: Path, timezone) -> list[ExportedMetrics]:
        self.calls.append({"path": path, "timezone": timezone})
        if self.error is not None:
            raise self.error
        return list(self.rows)


class FakeMatcher:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.results_by_title: dict[str, MatchResult] = {}

    def match(
        self,
        title: str,
        published_at: datetime,
        candidates: list[ContentCandidate],
    ) -> MatchResult:
        self.calls.append(
            {
                "title": title,
                "published_at": published_at,
                "candidates": list(candidates),
            }
        )
        return self.results_by_title.get(
            title,
            MatchResult("matched", "content-1", 1.0, ("content-1",)),
        )


@pytest.fixture
def deps(tmp_path):
    workbook_path = tmp_path / "downloaded.xlsx"
    workbook_path.write_bytes(b"fake workbook")
    config = replace(
        CollectorConfig.default(home=tmp_path),
        download_dir=tmp_path / "downloads",
        diagnostics_dir=tmp_path / "diagnostics",
    )
    manager = FakeManager()
    browser = FakeBrowser()
    browser_factory = FakeBrowserFactory(browser)
    identity_collector = FakeIdentityCollector()
    exporter = FakeExporter(workbook_path)
    parser = FakeParser()
    matcher = FakeMatcher()
    coordinator = CollectionCoordinator(
        config=config,
        manager=manager,
        browser_factory=browser_factory,
        matcher=matcher,
        identity_collector=identity_collector,
        exporter=exporter,
        parser=parser,
    )
    return SimpleNamespace(
        config=config,
        manager=manager,
        browser=browser,
        browser_factory=browser_factory,
        identity_collector=identity_collector,
        exporter=exporter,
        parser=parser,
        matcher=matcher,
        coordinator=coordinator,
        workbook_path=workbook_path,
    )


def exported_row(title: str, content_id: str = "content-1") -> ExportedMetrics:
    del content_id
    return ExportedMetrics(
        title=title,
        published_at=datetime(2026, 7, 5, 12, 0, tzinfo=TZ),
        impressions=1000,
        views=200,
        cover_click_rate=0.2,
        likes=20,
        comments=3,
        saves=8,
        followers_gained=2,
        shares=4,
        avg_watch_time_seconds=17,
        danmaku_count=1,
    )


def candidate_dict(content_id: str = "content-1", title: str = "标题"):
    return {
        "content_id": content_id,
        "title": title,
        "reference_time": "2026-07-05T12:00:00+08:00",
        "post_id": None,
    }


def test_scheduled_date_for_uses_previous_date_before_cutoff():
    assert scheduled_date_for(AT_09, time(22, 0)) == AT_09.date() - timedelta(days=1)
    assert scheduled_date_for(AT_22, time(22, 0)) == AT_22.date()
    assert scheduled_date_for(AT_23, time(22, 0)) == AT_23.date()


def test_completed_today_skips_browser(deps):
    deps.manager.completed_execution_dates.add(AT_22.date().isoformat())

    result = deps.coordinator.collect(now=AT_22)

    assert result.status == "skipped_already_completed"
    assert deps.manager.start_calls == []
    assert deps.browser_factory.calls == 0


def test_first_ever_run_at_load_invocation_is_due(deps):
    deps.coordinator.collect(now=AT_09)

    assert deps.manager.start_calls == [
        ("2026-07-05", "2026-07-06"),
    ]
    assert deps.browser_factory.calls == 1


def test_before_22_missed_prior_scheduled_date_is_due(deps):
    deps.coordinator.collect(now=AT_09)

    assert deps.manager.start_calls[0] == ("2026-07-05", "2026-07-06")


def test_after_catch_up_success_same_local_date_22_skips(deps):
    catch_up = deps.coordinator.collect(now=AT_09)
    deps.browser_factory.calls = 0

    scheduled = deps.coordinator.collect(now=AT_22)

    assert catch_up.status == "success"
    assert scheduled.status == "skipped_already_completed"
    assert deps.browser_factory.calls == 0


def test_no_unbound_content_skips_note_manager(deps):
    deps.manager.unbound_candidates = []

    result = deps.coordinator.collect(now=AT_22)

    assert result.status == "success"
    assert deps.identity_collector.calls == []
    assert deps.exporter.calls == [deps.browser.page]
    assert deps.browser.navigate_calls == [deps.config.data_analysis_url]


def test_unbound_content_reads_list_and_generates_stable_url(deps):
    deps.manager.unbound_candidates = [candidate_dict()]
    identity = NoteIdentity(
        post_id=POST_ID,
        title="标题",
        published_at=datetime(2026, 7, 5, 12, 0, tzinfo=TZ),
    )
    deps.identity_collector.identities = [identity]
    deps.matcher.results_by_title["标题"] = MatchResult(
        "matched",
        "content-1",
        1.0,
        ("content-1",),
    )

    deps.coordinator.collect(now=AT_22)

    assert deps.browser.navigate_calls[:2] == [
        deps.config.note_manager_url,
        deps.config.data_analysis_url,
    ]
    assert deps.manager.bind_calls == [
        {
            "content_id": "content-1",
            "post_id": POST_ID,
            "url": deps.config.note_url(POST_ID),
            "published_at": identity.published_at.isoformat(),
        }
    ]
    assert deps.manager.finish_summaries[-1]["matched_post_ids"] == 1


def test_auth_failure_stops_before_export(deps):
    deps.browser.raise_on_url[deps.config.data_analysis_url] = (
        AuthenticationRequired("login required token=secret")
    )

    result = deps.coordinator.collect(now=AT_22)

    assert result.status == "auth_required"
    assert deps.exporter.calls == []
    assert deps.manager.update_calls == []
    assert deps.manager.finish_summaries[-1]["status"] == "auth_required"
    assert "secret" not in str(deps.manager.finish_summaries[-1]["error_summary"])


def test_ambiguous_rows_are_skipped_but_confident_rows_update(deps):
    deps.parser.rows = [exported_row("confident"), exported_row("ambiguous")]
    deps.matcher.results_by_title["confident"] = MatchResult(
        "matched",
        "content-1",
        0.95,
        ("content-1",),
    )
    deps.matcher.results_by_title["ambiguous"] = MatchResult(
        "ambiguous",
        None,
        0.91,
        ("content-2", "content-3"),
    )

    result = deps.coordinator.collect(now=AT_22)

    assert result.status == "partial_success"
    assert result.exported_rows == 2
    assert result.updated_rows == 1
    assert result.skipped_rows == 1
    assert result.ambiguous_rows == 1
    assert len(deps.manager.update_calls) == 1
    record = deps.manager.update_calls[0]["records"][0]
    assert record == MetricsRecord(
        content_id="content-1",
        views=200,
        likes=20,
        saves=8,
        comments=3,
        shares=4,
        followers_gained=2,
        impressions=1000,
        cover_click_rate=0.2,
        avg_watch_time_seconds=17,
        danmaku_count=1,
    )


def test_workbook_validation_failure_preserves_file_and_writes_no_metrics(deps):
    deps.parser.error = WorkbookFormatError("missing required headers")

    result = deps.coordinator.collect(now=AT_22)

    assert result.status == "failed"
    assert deps.manager.update_calls == []
    assert not deps.workbook_path.exists()
    preserved = list(deps.config.diagnostics_dir.glob("*.xlsx"))
    assert len(preserved) == 1
    assert preserved[0].read_bytes() == b"fake workbook"
    assert stat.S_IMODE(deps.config.diagnostics_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(preserved[0].stat().st_mode) == 0o600
    assert "missing required headers" in str(result.error_summary)


def test_database_batch_failure_marks_failed_and_latest_history_unchanged(deps):
    deps.parser.rows = [exported_row("confident")]
    deps.manager.latest["content-1"] = MetricsRecord("content-1", views=99)
    deps.manager.history.append({"content_id": "content-1", "views": 99})
    latest_before = dict(deps.manager.latest)
    history_before = list(deps.manager.history)
    deps.manager.raise_on_update = RuntimeError("database token should not leak")

    result = deps.coordinator.collect(now=AT_22)

    assert result.status == "failed"
    assert deps.manager.latest == latest_before
    assert deps.manager.history == history_before
    assert deps.manager.finish_summaries[-1]["status"] == "failed"
    assert "token" not in str(deps.manager.finish_summaries[-1]["error_summary"])


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (VerificationRequired("captcha challenge code 123456"), "verification_required"),
        (AccessBlocked("403 cookie abc"), "access_blocked"),
    ],
)
def test_verification_and_access_block_errors_are_sanitized_and_not_retried(
    deps,
    error,
    status,
):
    deps.browser.raise_on_url[deps.config.data_analysis_url] = error

    result = deps.coordinator.collect(now=AT_22)

    assert result.status == status
    assert deps.browser_factory.calls == 1
    assert deps.browser.navigate_calls == [deps.config.data_analysis_url]
    assert deps.exporter.calls == []
    assert "123456" not in str(deps.manager.finish_summaries[-1]["error_summary"])
    assert "cookie" not in str(deps.manager.finish_summaries[-1]["error_summary"])


def test_failed_workbooks_move_to_diagnostics_and_prune_only_old_diagnostics(
    tmp_path,
):
    diagnostics_dir = tmp_path / "diagnostics"
    workbook = tmp_path / "failed.xlsx"
    workbook.write_bytes(b"failed")
    old_diagnostic = diagnostics_dir / "old.xlsx"
    new_diagnostic = diagnostics_dir / "new.xlsx"
    diagnostics_dir.mkdir()
    old_diagnostic.write_bytes(b"old")
    new_diagnostic.write_bytes(b"new")
    unrelated_dir = tmp_path / "unrelated"
    unrelated_dir.mkdir()
    unrelated_old = unrelated_dir / "old.xlsx"
    unrelated_old.write_bytes(b"unrelated")
    now = datetime(2026, 7, 6, 22, 0, tzinfo=TZ)
    old_mtime = (now - timedelta(days=8)).timestamp()
    new_mtime = (now - timedelta(days=6, hours=23)).timestamp()
    os.utime(old_diagnostic, (old_mtime, old_mtime))
    os.utime(new_diagnostic, (new_mtime, new_mtime))
    os.utime(unrelated_old, (old_mtime, old_mtime))

    preserved = preserve_diagnostic_workbook(
        workbook,
        diagnostics_dir,
        retention_days=7,
        now=now,
    )

    assert not workbook.exists()
    assert preserved.exists()
    assert preserved.parent == diagnostics_dir
    assert preserved.read_bytes() == b"failed"
    assert not old_diagnostic.exists()
    assert new_diagnostic.exists()
    assert unrelated_old.exists()
    assert stat.S_IMODE(preserved.stat().st_mode) == 0o600
