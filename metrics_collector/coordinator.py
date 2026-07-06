from __future__ import annotations

from datetime import date, datetime, time, timedelta
import os
from pathlib import Path
import shutil
import stat
from typing import Any, Callable

from memory.memory_manager import CollectionRunAlreadyClaimed
from memory.models import MetricsRecord
from metrics_collector.browser import (
    AccessBlocked,
    AuthenticationRequired,
    BrowserNavigationError,
    BrowserSession,
    VerificationRequired,
)
from metrics_collector.config import CollectorConfig
from metrics_collector.exporter import MetricsExporter
from metrics_collector.identity import collect_note_identities
from metrics_collector.matcher import ContentMatcher
from metrics_collector.models import (
    CollectionSummary,
    ContentCandidate,
    ExportedMetrics,
    NoteIdentity,
)
from metrics_collector.workbook import WorkbookFormatError, parse_metrics_workbook


METRICS_SOURCE = "creator_center_note_export_v1"


class DiagnosticPreservationError(RuntimeError):
    pass


def scheduled_date_for(now: datetime, schedule_time: time) -> date:
    local_time = now.timetz().replace(tzinfo=None)
    cutoff = schedule_time.replace(tzinfo=None)
    if local_time >= cutoff:
        return now.date()
    return now.date() - timedelta(days=1)


def preserve_diagnostic_workbook(
    path: Path | str,
    diagnostics_dir: Path | str,
    retention_days: int,
    now: datetime,
) -> Path:
    workbook_path = Path(path)
    diagnostics_path = Path(diagnostics_dir)
    try:
        workbook_stat = workbook_path.lstat()
    except OSError as error:
        raise DiagnosticPreservationError(
            "diagnostic preservation failed"
        ) from error
    if not stat.S_ISREG(workbook_stat.st_mode):
        raise DiagnosticPreservationError("diagnostic preservation failed")
    if diagnostics_path.is_symlink():
        raise DiagnosticPreservationError("diagnostic preservation failed")
    diagnostics_path.mkdir(parents=True, exist_ok=True)
    diagnostics_fd = _open_verified_diagnostics_dir(diagnostics_path)

    try:
        source_fd = _open_verified_source(workbook_path, workbook_stat)
        destination, destination_name, destination_fd = (
            _create_diagnostic_destination(
                workbook_path,
                diagnostics_path,
                diagnostics_fd,
                now,
            )
        )
        copied = False
        try:
            with os.fdopen(source_fd, "rb") as source, os.fdopen(
                destination_fd,
                "wb",
            ) as target:
                source_fd = -1
                destination_fd = -1
                shutil.copyfileobj(source, target, length=1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
                os.fchmod(target.fileno(), 0o600)
            copied = True
        finally:
            _close_fd_if_open(source_fd)
            _close_fd_if_open(destination_fd)
            if not copied:
                _unlink_relative_if_present(destination_name, diagnostics_fd)

        try:
            current_source_stat = workbook_path.lstat()
        except OSError as error:
            _unlink_relative_if_present(destination_name, diagnostics_fd)
            raise DiagnosticPreservationError(
                "diagnostic preservation failed"
            ) from error
        if not _same_file_identity(workbook_stat, current_source_stat):
            _unlink_relative_if_present(destination_name, diagnostics_fd)
            raise DiagnosticPreservationError("diagnostic preservation failed")

        now_timestamp = now.timestamp()
        os.utime(
            destination_name,
            (now_timestamp, now_timestamp),
            dir_fd=diagnostics_fd,
            follow_symlinks=False,
        )
        try:
            workbook_path.unlink()
        except OSError as error:
            _unlink_relative_if_present(destination_name, diagnostics_fd)
            raise DiagnosticPreservationError(
                "diagnostic preservation failed"
            ) from error
        _prune_old_diagnostics(diagnostics_fd, retention_days, now_timestamp)
        return _verified_diagnostic_return_path(
            destination,
            destination_name,
            diagnostics_fd,
        )
    finally:
        _close_fd_if_open(diagnostics_fd)


class CollectionCoordinator:
    def __init__(
        self,
        *,
        config: CollectorConfig | None = None,
        manager: Any | None = None,
        browser_factory: Callable[[], Any] | None = None,
        matcher: Any | None = None,
        identity_collector: Callable[..., list[NoteIdentity]] | None = None,
        exporter: Any | None = None,
        parser: Callable[[Path, Any], list[ExportedMetrics]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config or CollectorConfig.default()
        self.manager = manager if manager is not None else _default_manager(self.config)
        self.browser_factory = (
            browser_factory
            if browser_factory is not None
            else lambda: BrowserSession(self.config)
        )
        self.matcher = matcher if matcher is not None else ContentMatcher(
            title_similarity_threshold=self.config.title_similarity_threshold,
            combined_score_threshold=self.config.combined_score_threshold,
            winner_margin=self.config.winner_margin,
        )
        self.identity_collector = identity_collector or collect_note_identities
        self.exporter = exporter if exporter is not None else MetricsExporter(
            self.config.download_dir
        )
        self.parser = parser or parse_metrics_workbook
        self.clock = clock or (lambda: datetime.now(self.config.timezone))

    def collect(self, now: datetime | None = None) -> CollectionSummary:
        current_time = now or self.clock()
        execution_date = current_time.date()
        execution_date_text = execution_date.isoformat()
        scheduled_date = scheduled_date_for(
            current_time,
            self.config.schedule_time,
        )
        scheduled_date_text = scheduled_date.isoformat()

        if self.manager.has_completed_execution_date(execution_date_text):
            return CollectionSummary(
                scheduled_date=scheduled_date,
                execution_date=execution_date,
                status="skipped_already_completed",
            )
        if self.manager.has_attempted_execution_date(execution_date_text):
            return CollectionSummary(
                scheduled_date=scheduled_date,
                execution_date=execution_date,
                status="skipped_already_attempted",
            )

        try:
            self.manager.start_collection_run(
                scheduled_date=scheduled_date_text,
                execution_date=execution_date_text,
            )
        except CollectionRunAlreadyClaimed:
            return CollectionSummary(
                scheduled_date=scheduled_date,
                execution_date=execution_date,
                status="skipped_already_claimed",
            )

        workbook_path: Path | None = None
        try:
            matched_post_ids = 0
            with self.browser_factory() as browser:
                browser.navigate(self.config.data_analysis_url)
                candidates = _candidate_list(
                    self.manager.get_unbound_published_candidates()
                )
                if candidates:
                    browser.navigate(self.config.note_manager_url)
                    matched_post_ids = self._bind_note_identities(
                        browser.page,
                        candidates,
                    )
                    browser.navigate(self.config.data_analysis_url)
                metric_candidates = _candidate_list(
                    self.manager.get_metric_match_candidates()
                )
                workbook_path = self._export(browser.page)

            rows = self.parser(workbook_path, self.config.timezone)
            records, ambiguous_rows, skipped_rows = self._records_from_rows(
                rows,
                metric_candidates,
            )
            self.manager.update_metrics_batch(
                records,
                collected_date=scheduled_date_text,
                source=METRICS_SOURCE,
            )

            status = (
                "partial_success"
                if ambiguous_rows > 0 or skipped_rows > 0
                else "success"
            )
            summary = CollectionSummary(
                scheduled_date=scheduled_date,
                execution_date=execution_date,
                status=status,
                exported_rows=len(rows),
                updated_rows=len(records),
                skipped_rows=skipped_rows,
                ambiguous_rows=ambiguous_rows,
                matched_post_ids=matched_post_ids,
                error_summary=_delete_imported_workbook(workbook_path),
            )
            self._finish(summary)
            return summary
        except AuthenticationRequired as error:
            return self._fail(
                scheduled_date,
                execution_date,
                "auth_required",
                "authentication required",
                error,
            )
        except VerificationRequired as error:
            return self._fail(
                scheduled_date,
                execution_date,
                "verification_required",
                "verification required",
                error,
            )
        except AccessBlocked as error:
            return self._fail(
                scheduled_date,
                execution_date,
                "access_blocked",
                "access blocked",
                error,
            )
        except WorkbookFormatError as error:
            diagnostic_error = _preserve_if_present(
                workbook_path,
                self.config,
                current_time,
            )
            error_summary = (
                "workbook validation failed; diagnostic preservation failed"
                if diagnostic_error is not None
                else _safe_validation_error(error)
            )
            return self._fail(
                scheduled_date,
                execution_date,
                "failed",
                error_summary,
                error,
            )
        except BrowserNavigationError as error:
            return self._fail(
                scheduled_date,
                execution_date,
                "failed",
                "browser navigation failed",
                error,
            )
        except Exception as error:
            diagnostic_error = _preserve_if_present(
                workbook_path,
                self.config,
                current_time,
            )
            error_summary = f"{type(error).__name__}: operation failed"
            if diagnostic_error is not None:
                error_summary += "; diagnostic preservation failed"
            return self._fail(
                scheduled_date,
                execution_date,
                "failed",
                error_summary,
                error,
            )

    def _bind_note_identities(
        self,
        page: Any,
        candidates: list[ContentCandidate],
    ) -> int:
        identities = self.identity_collector(
            page,
            self.config.max_note_manager_pages,
            self.config.timezone,
        )
        matched_count = 0
        for identity in identities:
            match = self.matcher.match(
                identity.title,
                identity.published_at,
                candidates,
            )
            if match.status != "matched" or match.content_id is None:
                continue
            self.manager.bind_post_identity(
                content_id=match.content_id,
                post_id=identity.post_id,
                url=self.config.note_url(identity.post_id),
                published_at=identity.published_at.isoformat(),
            )
            matched_count += 1
        return matched_count

    def _export(self, page: Any) -> Path:
        if hasattr(self.exporter, "export"):
            return Path(self.exporter.export(page))
        return Path(self.exporter(page))

    def _records_from_rows(
        self,
        rows: list[ExportedMetrics],
        candidates: list[ContentCandidate],
    ) -> tuple[list[MetricsRecord], int, int]:
        records: list[MetricsRecord] = []
        ambiguous_rows = 0
        skipped_rows = 0
        for row in rows:
            match = self.matcher.match(row.title, row.published_at, candidates)
            if match.status == "matched" and match.content_id is not None:
                records.append(_metrics_record_from_row(match.content_id, row))
            elif match.status == "ambiguous":
                ambiguous_rows += 1
                skipped_rows += 1
            else:
                skipped_rows += 1
        return records, ambiguous_rows, skipped_rows

    def _finish(self, summary: CollectionSummary) -> None:
        self.manager.finish_collection_run(_summary_dict(summary))

    def _fail(
        self,
        scheduled_date: date,
        execution_date: date,
        status: str,
        error_summary: str,
        _error: Exception,
    ) -> CollectionSummary:
        summary = CollectionSummary(
            scheduled_date=scheduled_date,
            execution_date=execution_date,
            status=status,
            error_summary=error_summary,
        )
        self._finish(summary)
        return summary


def _candidate_list(rows: list[dict[str, object]]) -> list[ContentCandidate]:
    return [_candidate_from_mapping(row) for row in rows]


def _candidate_from_mapping(row: dict[str, object]) -> ContentCandidate:
    reference_time = row["reference_time"]
    if isinstance(reference_time, datetime):
        parsed_reference_time = reference_time
    elif isinstance(reference_time, str):
        parsed_reference_time = datetime.fromisoformat(reference_time)
    else:
        raise TypeError("candidate reference_time must be datetime or ISO string")

    post_id = row.get("post_id")
    return ContentCandidate(
        content_id=str(row["content_id"]),
        title=str(row["title"]),
        reference_time=parsed_reference_time,
        post_id=post_id if isinstance(post_id, str) else None,
    )


def _metrics_record_from_row(
    content_id: str,
    row: ExportedMetrics,
) -> MetricsRecord:
    return MetricsRecord(
        content_id=content_id,
        views=row.views,
        likes=row.likes,
        saves=row.saves,
        comments=row.comments,
        shares=row.shares,
        followers_gained=row.followers_gained,
        impressions=row.impressions,
        cover_click_rate=row.cover_click_rate,
        avg_watch_time_seconds=row.avg_watch_time_seconds,
        danmaku_count=row.danmaku_count,
    )


def _summary_dict(summary: CollectionSummary) -> dict[str, object]:
    return {
        "scheduled_date": summary.scheduled_date.isoformat(),
        "execution_date": summary.execution_date.isoformat(),
        "status": summary.status,
        "exported_rows": summary.exported_rows,
        "updated_rows": summary.updated_rows,
        "skipped_rows": summary.skipped_rows,
        "ambiguous_rows": summary.ambiguous_rows,
        "matched_post_ids": summary.matched_post_ids,
        "error_summary": summary.error_summary,
    }


def _delete_imported_workbook(path: Path) -> str | None:
    try:
        path.unlink()
        return None
    except FileNotFoundError:
        return None
    except OSError:
        return "import succeeded but workbook cleanup failed"


def _preserve_if_present(
    workbook_path: Path | None,
    config: CollectorConfig,
    now: datetime,
) -> str | None:
    if (
        workbook_path is None
        or not workbook_path.exists()
        and not workbook_path.is_symlink()
    ):
        return None
    try:
        preserve_diagnostic_workbook(
            workbook_path,
            config.diagnostics_dir,
            config.diagnostic_retention_days,
            now,
        )
    except Exception:
        return "diagnostic preservation failed"
    return None


def _safe_validation_error(error: WorkbookFormatError) -> str:
    return "workbook validation failed"


def _open_verified_source(workbook_path: Path, expected_stat: os.stat_result) -> int:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        source_fd = os.open(workbook_path, flags)
    except OSError as error:
        raise DiagnosticPreservationError(
            "diagnostic preservation failed"
        ) from error
    try:
        opened_stat = os.fstat(source_fd)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or not _same_file_identity(expected_stat, opened_stat)
        ):
            raise DiagnosticPreservationError("diagnostic preservation failed")
    except Exception:
        _close_fd_if_open(source_fd)
        raise
    return source_fd


def _open_verified_diagnostics_dir(diagnostics_path: Path) -> int:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        diagnostics_fd = os.open(diagnostics_path, flags)
    except OSError as error:
        raise DiagnosticPreservationError(
            "diagnostic preservation failed"
        ) from error
    try:
        diagnostics_stat = os.fstat(diagnostics_fd)
        if not stat.S_ISDIR(diagnostics_stat.st_mode):
            raise DiagnosticPreservationError("diagnostic preservation failed")
        os.fchmod(diagnostics_fd, 0o700)
    except Exception:
        _close_fd_if_open(diagnostics_fd)
        raise
    return diagnostics_fd


def _create_diagnostic_destination(
    workbook_path: Path,
    diagnostics_dir: Path,
    diagnostics_fd: int,
    now: datetime,
) -> tuple[Path, str, int]:
    suffix = workbook_path.suffix or ".xlsx"
    stem = workbook_path.stem or "workbook"
    timestamp = now.strftime("%Y%m%dT%H%M%S")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    for index in range(1000):
        collision_suffix = "" if index == 0 else f"-{index}"
        candidate_name = f"{timestamp}-{stem}{collision_suffix}{suffix}"
        candidate = diagnostics_dir / candidate_name
        try:
            return (
                candidate,
                candidate_name,
                os.open(candidate_name, flags, 0o600, dir_fd=diagnostics_fd),
            )
        except FileExistsError:
            continue
        except OSError as error:
            raise DiagnosticPreservationError(
                "diagnostic preservation failed"
            ) from error
    raise DiagnosticPreservationError("diagnostic preservation failed")


def _same_file_identity(
    left: os.stat_result,
    right: os.stat_result,
) -> bool:
    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


def _close_fd_if_open(fd: int) -> None:
    if fd < 0:
        return
    try:
        os.close(fd)
    except OSError:
        pass


def _unlink_relative_if_present(name: str, dir_fd: int) -> None:
    try:
        os.unlink(name, dir_fd=dir_fd)
    except FileNotFoundError:
        pass


def _verified_diagnostic_return_path(
    destination: Path,
    destination_name: str,
    diagnostics_fd: int,
) -> Path:
    try:
        fd_stat = os.stat(
            destination_name,
            dir_fd=diagnostics_fd,
            follow_symlinks=False,
        )
        path_stat = destination.lstat()
    except OSError as error:
        raise DiagnosticPreservationError(
            "diagnostic preservation failed"
        ) from error
    if not _same_file_identity(fd_stat, path_stat):
        raise DiagnosticPreservationError("diagnostic preservation failed")
    return destination


def _prune_old_diagnostics(
    diagnostics_fd: int,
    retention_days: int,
    now_timestamp: float,
) -> None:
    cutoff = now_timestamp - (retention_days * 24 * 60 * 60)
    try:
        names = os.listdir(diagnostics_fd)
    except OSError as error:
        raise DiagnosticPreservationError(
            "diagnostic preservation failed"
        ) from error
    for name in names:
        try:
            candidate_stat = os.stat(
                name,
                dir_fd=diagnostics_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            continue
        if (
            stat.S_ISLNK(candidate_stat.st_mode)
            or not stat.S_ISREG(candidate_stat.st_mode)
        ):
            continue
        try:
            if candidate_stat.st_mtime < cutoff:
                os.unlink(name, dir_fd=diagnostics_fd)
        except FileNotFoundError:
            continue


def _default_manager(config: CollectorConfig) -> Any:
    from memory.memory_manager import XHSMemoryManager

    return XHSMemoryManager(config.db_path)
