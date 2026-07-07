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
import metrics_collector.coordinator as coordinator_module
from metrics_collector.browser import (
    AccessBlocked,
    AuthenticationRequired,
    VerificationRequired,
)
from metrics_collector.config import CollectorConfig
from metrics_collector.coordinator import (
    CollectionCoordinator,
    DiagnosticPreservationError,
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
from memory.memory_manager import CollectionRunAlreadyClaimed


TZ = ZoneInfo("Asia/Shanghai")
AT_09 = datetime(2026, 7, 6, 9, 0, tzinfo=TZ)
AT_22 = datetime(2026, 7, 6, 22, 0, tzinfo=TZ)
AT_23 = datetime(2026, 7, 6, 23, 0, tzinfo=TZ)
POST_ID = "0123456789abcdef01234567"


class FakeManager:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.completed_execution_dates: set[str] = set()
        self.attempted_execution_dates: set[str] = set()
        self.unbound_candidates: list[dict[str, object]] = []
        self.metric_match_candidates: list[dict[str, object]] = [
            candidate_dict()
        ]
        self.start_calls: list[tuple[str, str]] = []
        self.finish_summaries: list[dict[str, object]] = []
        self.bind_calls: list[dict[str, object]] = []
        self.update_calls: list[dict[str, object]] = []
        self.raise_on_start: Exception | None = None
        self.raise_on_update: Exception | None = None
        self.latest: dict[str, MetricsRecord] = {}
        self.history: list[dict[str, object]] = []

    def has_completed_execution_date(self, execution_date: str) -> bool:
        return execution_date in self.completed_execution_dates

    def has_attempted_execution_date(self, execution_date: str) -> bool:
        return execution_date in self.attempted_execution_dates

    def start_collection_run(
        self,
        scheduled_date: str,
        execution_date: str,
    ) -> None:
        if self.raise_on_start is not None:
            raise self.raise_on_start
        self.attempted_execution_dates.add(execution_date)
        self.start_calls.append((scheduled_date, execution_date))

    def finish_collection_run(self, summary: dict[str, object]) -> None:
        self.finish_summaries.append(dict(summary))
        if summary["status"] in {"success", "partial_success"}:
            self.completed_execution_dates.add(str(summary["execution_date"]))

    def get_unbound_published_candidates(self) -> list[dict[str, object]]:
        self.events.append("get_candidates")
        return list(self.unbound_candidates)

    def get_metric_match_candidates(self) -> list[dict[str, object]]:
        self.events.append("get_metric_candidates")
        return list(self.metric_match_candidates)

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
    def __init__(self, events: list[str]) -> None:
        self.events = events
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
        self.events.append(f"navigate:{url}")
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
    def __init__(self, workbook_path: Path, events: list[str]) -> None:
        self.events = events
        self.calls: list[object] = []
        self.workbook_path = workbook_path

    def export(self, page) -> Path:
        self.events.append("export")
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
    events: list[str] = []
    workbook_path = tmp_path / "downloaded.xlsx"
    workbook_path.write_bytes(b"fake workbook")
    config = replace(
        CollectorConfig.default(home=tmp_path),
        download_dir=tmp_path / "downloads",
        diagnostics_dir=tmp_path / "diagnostics",
    )
    manager = FakeManager(events)
    browser = FakeBrowser(events)
    browser_factory = FakeBrowserFactory(browser)
    identity_collector = FakeIdentityCollector()
    exporter = FakeExporter(workbook_path, events)
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
        events=events,
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


def test_candidate_list_accepts_legacy_non_padded_hour_reference_time():
    candidates = coordinator_module._candidate_list(
        [
            candidate_dict()
            | {"reference_time": "2026-05-08T7:00:00+08:00"}
        ]
    )

    assert candidates[0].reference_time == datetime(
        2026,
        5,
        8,
        7,
        0,
        tzinfo=TZ,
    )


def test_completed_today_skips_browser(deps):
    deps.manager.completed_execution_dates.add(AT_22.date().isoformat())

    result = deps.coordinator.collect(now=AT_22)

    assert result.status == "skipped_already_completed"
    assert deps.manager.start_calls == []
    assert deps.browser_factory.calls == 0


def test_attempted_today_after_failure_skips_browser(deps):
    deps.browser.raise_on_url[deps.config.data_analysis_url] = (
        AuthenticationRequired("login required")
    )
    first = deps.coordinator.collect(now=AT_09)
    deps.browser.raise_on_url = {}
    deps.browser_factory.calls = 0

    second = deps.coordinator.collect(now=AT_22)

    assert first.status == "auth_required"
    assert second.status == "skipped_already_attempted"
    assert deps.browser_factory.calls == 0
    assert deps.manager.start_calls == [("2026-07-05", "2026-07-06")]


def test_duplicate_claim_skips_without_browser(deps):
    deps.manager.raise_on_start = CollectionRunAlreadyClaimed("claimed token=secret")

    result = deps.coordinator.collect(now=AT_22)

    assert result.status == "skipped_already_claimed"
    assert deps.browser_factory.calls == 0
    assert deps.manager.finish_summaries == []


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
    assert deps.events == [
        f"navigate:{deps.config.data_analysis_url}",
        "get_candidates",
        "get_metric_candidates",
        "export",
    ]


def test_already_bound_metric_candidate_updates_without_note_manager(deps):
    deps.manager.unbound_candidates = []
    deps.manager.metric_match_candidates = [
        candidate_dict("bound-content", "bound title")
        | {"post_id": POST_ID}
    ]
    deps.parser.rows = [exported_row("bound title")]
    deps.matcher.results_by_title["bound title"] = MatchResult(
        "matched",
        "bound-content",
        1.0,
        ("bound-content",),
    )

    result = deps.coordinator.collect(now=AT_22)

    assert result.status == "success"
    assert deps.identity_collector.calls == []
    assert deps.browser.navigate_calls == [deps.config.data_analysis_url]
    assert deps.manager.update_calls[0]["records"][0].content_id == "bound-content"
    metric_candidates = deps.matcher.calls[-1]["candidates"]
    assert metric_candidates == [
        ContentCandidate(
            content_id="bound-content",
            title="bound title",
            reference_time=datetime.fromisoformat("2026-07-05T12:00:00+08:00"),
            post_id=POST_ID,
        )
    ]


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

    assert deps.browser.navigate_calls == [
        deps.config.data_analysis_url,
        deps.config.note_manager_url,
        deps.config.data_analysis_url,
    ]
    assert deps.events == [
        f"navigate:{deps.config.data_analysis_url}",
        "get_candidates",
        f"navigate:{deps.config.note_manager_url}",
        f"navigate:{deps.config.data_analysis_url}",
        "get_metric_candidates",
        "export",
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


def test_identity_batch_skips_all_sources_with_conflicting_content_ids(deps):
    deps.manager.unbound_candidates = [
        candidate_dict("content-1", "first conflict"),
        candidate_dict("content-2", "unique"),
        candidate_dict("content-3", "repeated source"),
    ]
    first_conflict = NoteIdentity(
        post_id="111111111111111111111111",
        title="first conflict",
        published_at=datetime(2026, 7, 5, 10, 0, tzinfo=TZ),
    )
    unique = NoteIdentity(
        post_id="222222222222222222222222",
        title="unique",
        published_at=datetime(2026, 7, 5, 11, 0, tzinfo=TZ),
    )
    second_conflict = NoteIdentity(
        post_id="333333333333333333333333",
        title="second conflict",
        published_at=datetime(2026, 7, 5, 13, 0, tzinfo=TZ),
    )
    repeated = NoteIdentity(
        post_id="444444444444444444444444",
        title="repeated source",
        published_at=datetime(2026, 7, 5, 14, 0, tzinfo=TZ),
    )
    deps.identity_collector.identities = [
        first_conflict,
        unique,
        second_conflict,
        repeated,
        repeated,
    ]
    deps.matcher.results_by_title.update(
        {
            "first conflict": MatchResult(
                "matched", "content-1", 0.99, ("content-1",)
            ),
            "unique": MatchResult(
                "matched", "content-2", 0.98, ("content-2",)
            ),
            "second conflict": MatchResult(
                "matched", "content-1", 0.97, ("content-1",)
            ),
            "repeated source": MatchResult(
                "matched", "content-3", 0.96, ("content-3",)
            ),
        }
    )

    result = deps.coordinator.collect(now=AT_22)

    assert deps.manager.bind_calls == [
        {
            "content_id": "content-2",
            "post_id": unique.post_id,
            "url": deps.config.note_url(unique.post_id),
            "published_at": unique.published_at.isoformat(),
        }
    ]
    assert result.matched_post_ids == 1
    assert [call["title"] for call in deps.matcher.calls] == [
        "first conflict",
        "unique",
        "second conflict",
        "repeated source",
        "repeated source",
    ]


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
    assert record.content_id == "content-1"
    assert record.published_at == "2026-07-05T12:00:00+08:00"
    assert record.post_id is None
    assert record.url is None
    assert replace(
        record,
        published_at=None,
    ) == MetricsRecord(
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


def test_matched_metric_rows_carry_publication_metadata_for_content_backfill(deps):
    deps.manager.metric_match_candidates = [
        candidate_dict("bound-content", "bound title")
        | {"post_id": POST_ID}
    ]
    deps.parser.rows = [
        replace(
            exported_row("bound title"),
            published_at=datetime(2026, 7, 5, 13, 29, tzinfo=TZ),
        )
    ]
    deps.matcher.results_by_title["bound title"] = MatchResult(
        "matched",
        "bound-content",
        1.0,
        ("bound-content",),
    )

    deps.coordinator.collect(now=AT_22)

    record = deps.manager.update_calls[0]["records"][0]
    assert record.content_id == "bound-content"
    assert record.published_at == "2026-07-05T13:29:00+08:00"
    assert record.post_id == POST_ID
    assert record.url == deps.config.note_url(POST_ID)


def test_metrics_batch_skips_all_rows_with_conflicting_content_ids(deps):
    first_conflict = exported_row("first conflict")
    unique = exported_row("unique")
    second_conflict = replace(
        exported_row("second conflict"),
        published_at=datetime(2026, 7, 5, 13, 0, tzinfo=TZ),
    )
    repeated = exported_row("repeated source")
    deps.parser.rows = [
        first_conflict,
        unique,
        second_conflict,
        repeated,
        repeated,
    ]
    deps.matcher.results_by_title.update(
        {
            "first conflict": MatchResult(
                "matched", "content-1", 0.99, ("content-1",)
            ),
            "unique": MatchResult(
                "matched", "content-2", 0.98, ("content-2",)
            ),
            "second conflict": MatchResult(
                "matched", "content-1", 0.97, ("content-1",)
            ),
            "repeated source": MatchResult(
                "matched", "content-3", 0.96, ("content-3",)
            ),
        }
    )

    result = deps.coordinator.collect(now=AT_22)

    assert result.status == "partial_success"
    assert result.exported_rows == 5
    assert result.updated_rows == 1
    assert result.ambiguous_rows == 4
    assert result.skipped_rows == 4
    assert [
        record.content_id
        for record in deps.manager.update_calls[0]["records"]
    ] == ["content-2"]
    assert [call["title"] for call in deps.matcher.calls] == [
        "first conflict",
        "unique",
        "second conflict",
        "repeated source",
        "repeated source",
    ]


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
    assert result.error_summary == "workbook validation failed"


def test_successful_collection_prunes_old_diagnostics(deps):
    diagnostics_dir = deps.config.diagnostics_dir
    diagnostics_dir.mkdir()
    old_diagnostic = diagnostics_dir / "old.xlsx"
    new_diagnostic = diagnostics_dir / "new.xlsx"
    old_diagnostic.write_bytes(b"old")
    new_diagnostic.write_bytes(b"new")
    old_mtime = (AT_22 - timedelta(days=8)).timestamp()
    new_mtime = (AT_22 - timedelta(days=6, hours=23)).timestamp()
    os.utime(old_diagnostic, (old_mtime, old_mtime))
    os.utime(new_diagnostic, (new_mtime, new_mtime))

    result = deps.coordinator.collect(now=AT_22)

    assert result.status == "success"
    assert not old_diagnostic.exists()
    assert new_diagnostic.exists()


def test_workbook_validation_error_summary_does_not_leak_path_or_token(
    deps,
    tmp_path,
):
    secret_path = tmp_path / "token-secret.xlsx"
    deps.parser.error = WorkbookFormatError(
        f"workbook {secret_path}: missing headers token=secret"
    )

    result = deps.coordinator.collect(now=AT_22)

    assert result.status == "failed"
    assert result.error_summary == "workbook validation failed"
    assert str(secret_path) not in str(result.error_summary)
    assert "secret" not in str(result.error_summary)


def test_diagnostic_preservation_failure_still_finishes_run(deps, tmp_path):
    deps.parser.error = WorkbookFormatError("missing required headers token=secret")
    unsafe_target = tmp_path / "unsafe-target"
    unsafe_target.mkdir()
    unsafe_link = tmp_path / "diagnostics-link"
    unsafe_link.symlink_to(unsafe_target, target_is_directory=True)
    deps.config = replace(deps.config, diagnostics_dir=unsafe_link)
    deps.coordinator.config = deps.config

    result = deps.coordinator.collect(now=AT_22)

    assert result.status == "failed"
    assert deps.manager.finish_summaries[-1]["status"] == "failed"
    assert "diagnostic preservation failed" in str(result.error_summary)
    assert "secret" not in str(result.error_summary)
    assert str(unsafe_link) not in str(result.error_summary)


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


def test_diagnostic_preservation_does_not_use_shutil_move(tmp_path, monkeypatch):
    workbook = tmp_path / "failed.xlsx"
    workbook.write_bytes(b"failed")

    def fail_move(*args, **kwargs):
        raise AssertionError("shutil.move should not be used")

    monkeypatch.setattr(coordinator_module.shutil, "move", fail_move)

    preserved = preserve_diagnostic_workbook(
        workbook,
        tmp_path / "diagnostics",
        retention_days=7,
        now=AT_22,
    )

    assert not workbook.exists()
    assert preserved.read_bytes() == b"failed"


def test_diagnostic_destination_is_created_relative_to_verified_dir_fd(
    tmp_path,
    monkeypatch,
):
    workbook = tmp_path / "failed.xlsx"
    workbook.write_bytes(b"failed")
    original_open = coordinator_module.os.open
    open_calls = []

    def tracking_open(path, flags, mode=0o777, *, dir_fd=None):
        open_calls.append((path, flags, dir_fd))
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(coordinator_module.os, "open", tracking_open)

    preserved = preserve_diagnostic_workbook(
        workbook,
        tmp_path / "diagnostics",
        retention_days=7,
        now=AT_22,
    )

    assert preserved.name == "20260706T220000-failed.xlsx"
    assert any(
        path == preserved.name and dir_fd is not None
        for path, _flags, dir_fd in open_calls
    )


def test_diagnostic_preservation_uses_verified_dir_fd_after_path_replacement(
    tmp_path,
    monkeypatch,
):
    workbook = tmp_path / "failed.xlsx"
    workbook.write_bytes(b"failed")
    diagnostics_dir = tmp_path / "diagnostics"
    verified_dir = tmp_path / "verified-diagnostics"
    attacker_dir = tmp_path / "attacker"
    attacker_dir.mkdir()
    original_open = coordinator_module.os.open
    replaced = False

    def tracking_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal replaced
        fd = original_open(path, flags, mode, dir_fd=dir_fd)
        if (
            not replaced
            and dir_fd is None
            and Path(path) == diagnostics_dir
            and flags & getattr(coordinator_module.os, "O_DIRECTORY", 0)
        ):
            diagnostics_dir.rename(verified_dir)
            diagnostics_dir.symlink_to(attacker_dir, target_is_directory=True)
            replaced = True
        return fd

    monkeypatch.setattr(coordinator_module.os, "open", tracking_open)

    with pytest.raises(
        DiagnosticPreservationError,
        match="diagnostic preservation failed",
    ):
        preserve_diagnostic_workbook(
            workbook,
            diagnostics_dir,
            retention_days=7,
            now=AT_22,
        )

    preserved_name = "20260706T220000-failed.xlsx"
    assert (verified_dir / preserved_name).read_bytes() == b"failed"
    assert not (attacker_dir / preserved_name).exists()
    assert not (diagnostics_dir / preserved_name).exists()


def test_diagnostic_workbook_rejects_symlinked_diagnostics_dir(tmp_path):
    workbook = tmp_path / "failed.xlsx"
    workbook.write_bytes(b"failed")
    target = tmp_path / "target"
    target.mkdir()
    symlinked_diagnostics = tmp_path / "diagnostics"
    symlinked_diagnostics.symlink_to(target, target_is_directory=True)

    with pytest.raises(
        DiagnosticPreservationError,
        match="diagnostic preservation failed",
    ):
        preserve_diagnostic_workbook(
            workbook,
            symlinked_diagnostics,
            retention_days=7,
            now=AT_22,
        )

    assert workbook.exists()


def test_diagnostic_workbook_rejects_symlinked_source(tmp_path):
    target = tmp_path / "target.xlsx"
    target.write_bytes(b"target")
    source = tmp_path / "source.xlsx"
    source.symlink_to(target)

    with pytest.raises(
        DiagnosticPreservationError,
        match="diagnostic preservation failed",
    ):
        preserve_diagnostic_workbook(
            source,
            tmp_path / "diagnostics",
            retention_days=7,
            now=AT_22,
        )

    assert source.is_symlink()
    assert target.read_bytes() == b"target"


def test_diagnostic_workbook_rejects_non_regular_source(tmp_path):
    source = tmp_path / "source-directory"
    source.mkdir()

    with pytest.raises(
        DiagnosticPreservationError,
        match="diagnostic preservation failed",
    ):
        preserve_diagnostic_workbook(
            source,
            tmp_path / "diagnostics",
            retention_days=7,
            now=AT_22,
        )

    assert source.is_dir()


def test_diagnostic_pruning_does_not_follow_symlinked_entries(tmp_path):
    diagnostics_dir = tmp_path / "diagnostics"
    diagnostics_dir.mkdir()
    workbook = tmp_path / "failed.xlsx"
    workbook.write_bytes(b"failed")
    outside = tmp_path / "outside.xlsx"
    outside.write_bytes(b"outside")
    symlinked_entry = diagnostics_dir / "outside-link.xlsx"
    symlinked_entry.symlink_to(outside)
    old_mtime = (AT_22 - timedelta(days=8)).timestamp()
    os.utime(outside, (old_mtime, old_mtime))

    preserve_diagnostic_workbook(
        workbook,
        diagnostics_dir,
        retention_days=7,
        now=AT_22,
    )

    assert symlinked_entry.is_symlink()
    assert outside.exists()
