from collections import Counter
from datetime import datetime
import math
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo

from openpyxl import load_workbook

from metrics_collector.matcher import normalize_title
from metrics_collector.models import ExportedMetrics


class WorkbookFormatError(ValueError):
    pass


HEADERS = (
    "笔记标题",
    "首次发布时间",
    "体裁",
    "曝光",
    "观看量",
    "封面点击率",
    "点赞",
    "评论",
    "收藏",
    "涨粉",
    "分享",
    "人均观看时长",
    "弹幕",
)

_COUNT_FIELDS = {
    "曝光": "impressions",
    "观看量": "views",
    "点赞": "likes",
    "评论": "comments",
    "收藏": "saves",
    "涨粉": "followers_gained",
    "分享": "shares",
    "弹幕": "danmaku_count",
}
_INTEGER_STRING = re.compile(r"(?:\d+|\d{1,3}(?:,\d{3})+)")
_DURATION_STRING = re.compile(r"(\d+)\s*(?:s|秒)")
_PUBLICATION_FORMATS = (
    "%Y年%m月%d日%H时%M分%S秒",
    "%Y年%m月%d日%H时%M分",
    "%Y-%m-%d %H:%M",
)


def _is_unavailable(value: Any) -> bool:
    return value is None or (
        isinstance(value, str) and value.strip() in {"", "-"}
    )


def _is_empty_row(row: tuple[Any, ...]) -> bool:
    return all(
        value is None or (isinstance(value, str) and not value.strip())
        for value in row
    )


def _error(row_number: int, field: str, detail: str) -> WorkbookFormatError:
    return WorkbookFormatError(
        f"row {row_number} field {field}: {detail}"
    )


def _find_header(
    rows: list[tuple[Any, ...]],
) -> tuple[int, dict[str, int]]:
    required = set(HEADERS)
    candidates = []
    for row_number, row in enumerate(rows, start=1):
        counts = Counter(value for value in row if value in required)
        candidates.append((len(counts), row_number, row, counts))

    complete = [
        candidate
        for candidate in candidates
        if candidate[0] == len(HEADERS)
    ]
    if len(complete) > 1:
        row_numbers = ", ".join(str(candidate[1]) for candidate in complete)
        raise _error(
            complete[0][1],
            "headers",
            f"multiple header rows found at rows {row_numbers}",
        )

    if complete:
        _, row_number, row, counts = complete[0]
    else:
        _, row_number, row, counts = max(
            candidates,
            default=(0, 0, (), Counter()),
            key=lambda candidate: candidate[0],
        )
        duplicates = [
            header for header in HEADERS if counts.get(header, 0) > 1
        ]
        if duplicates:
            raise _error(
                row_number,
                duplicates[0],
                f"duplicate required header: {duplicates[0]}",
            )
        missing = [header for header in HEADERS if header not in counts]
        raise _error(
            row_number,
            "headers",
            f"missing required headers: {', '.join(missing)}",
        )

    duplicates = [header for header in HEADERS if counts[header] > 1]
    if duplicates:
        raise _error(
            row_number,
            duplicates[0],
            f"duplicate required header: {duplicates[0]}",
        )

    return row_number, {
        header: next(
            index for index, value in enumerate(row) if value == header
        )
        for header in HEADERS
    }


def _parse_count(value: Any, row_number: int, field: str) -> int | None:
    if _is_unavailable(value):
        return None
    if isinstance(value, bool):
        raise _error(row_number, field, "expected a nonnegative integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise _error(row_number, field, "expected a nonnegative integer")
        parsed = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if _INTEGER_STRING.fullmatch(text) is None:
            raise _error(row_number, field, "expected a nonnegative integer")
        parsed = int(text.replace(",", ""))
    else:
        raise _error(row_number, field, "expected a nonnegative integer")
    if parsed < 0:
        raise _error(row_number, field, "expected a nonnegative integer")
    return parsed


def _parse_percent(
    value: Any,
    row_number: int,
    field: str,
) -> float | None:
    if _is_unavailable(value):
        return None
    if isinstance(value, bool):
        raise _error(row_number, field, "expected a percentage from 0 to 1")

    try:
        if isinstance(value, (int, float)):
            parsed = float(value)
        elif isinstance(value, str):
            text = value.strip()
            if text.endswith("%"):
                parsed = float(text[:-1].strip()) / 100
            else:
                parsed = float(text)
        else:
            raise TypeError
    except (TypeError, ValueError):
        raise _error(
            row_number,
            field,
            "expected a percentage from 0 to 1",
        ) from None

    if not math.isfinite(parsed) or not 0 <= parsed <= 1:
        raise _error(row_number, field, "expected a percentage from 0 to 1")
    return parsed


def _parse_publication_time(
    value: Any,
    supplied_timezone: ZoneInfo,
    row_number: int,
    field: str,
) -> datetime:
    if _is_unavailable(value):
        raise _error(row_number, field, "publication time is required")
    if isinstance(value, bool):
        raise _error(row_number, field, "invalid publication time")

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        parsed = None
        for date_format in _PUBLICATION_FORMATS:
            try:
                parsed = datetime.strptime(text, date_format)
                break
            except ValueError:
                continue
        if parsed is None:
            raise _error(row_number, field, "invalid publication time")
    else:
        raise _error(row_number, field, "invalid publication time")

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=supplied_timezone)
    return parsed.astimezone(supplied_timezone)


def _parse_duration(value: Any, row_number: int, field: str) -> int | None:
    if _is_unavailable(value):
        return None
    if isinstance(value, bool):
        raise _error(row_number, field, "expected nonnegative seconds")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise _error(row_number, field, "expected nonnegative seconds")
        parsed = int(value)
    elif isinstance(value, str):
        match = _DURATION_STRING.fullmatch(value.strip())
        if match is None:
            raise _error(row_number, field, "expected nonnegative seconds")
        parsed = int(match.group(1))
    else:
        raise _error(row_number, field, "expected nonnegative seconds")
    if parsed < 0:
        raise _error(row_number, field, "expected nonnegative seconds")
    return parsed


def _cell(
    row: tuple[Any, ...],
    columns: dict[str, int],
    field: str,
) -> Any:
    index = columns[field]
    return row[index] if index < len(row) else None


def _parse_row(
    row: tuple[Any, ...],
    row_number: int,
    columns: dict[str, int],
    supplied_timezone: ZoneInfo,
) -> ExportedMetrics:
    title_value = _cell(row, columns, "笔记标题")
    if not isinstance(title_value, str) or not title_value.strip():
        raise _error(row_number, "笔记标题", "title is required")
    title = title_value.strip()
    published_at = _parse_publication_time(
        _cell(row, columns, "首次发布时间"),
        supplied_timezone,
        row_number,
        "首次发布时间",
    )

    parsed_counts = {
        attribute: _parse_count(
            _cell(row, columns, field),
            row_number,
            field,
        )
        for field, attribute in _COUNT_FIELDS.items()
    }
    return ExportedMetrics(
        title=title,
        published_at=published_at,
        cover_click_rate=_parse_percent(
            _cell(row, columns, "封面点击率"),
            row_number,
            "封面点击率",
        ),
        avg_watch_time_seconds=_parse_duration(
            _cell(row, columns, "人均观看时长"),
            row_number,
            "人均观看时长",
        ),
        **parsed_counts,
    )


def parse_metrics_workbook(
    path: Path,
    timezone: ZoneInfo,
) -> list[ExportedMetrics]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        rows = list(workbook.active.iter_rows(values_only=True))
        header_row_number, columns = _find_header(rows)
        parsed_rows = []
        identities: set[tuple[str, datetime]] = set()
        for row_number, row in enumerate(
            rows[header_row_number:],
            start=header_row_number + 1,
        ):
            if _is_empty_row(row):
                continue
            parsed = _parse_row(row, row_number, columns, timezone)
            identity = (normalize_title(parsed.title), parsed.published_at)
            if identity in identities:
                raise _error(
                    row_number,
                    "笔记标题",
                    "duplicate title and publication time",
                )
            identities.add(identity)
            parsed_rows.append(parsed)
        return parsed_rows
    finally:
        workbook.close()
