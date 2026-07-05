from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal


@dataclass(frozen=True)
class ContentCandidate:
    content_id: str
    title: str
    reference_time: datetime
    post_id: str | None = None


@dataclass(frozen=True)
class NoteIdentity:
    post_id: str
    title: str
    published_at: datetime


@dataclass(frozen=True)
class ExportedMetrics:
    title: str
    published_at: datetime
    impressions: int | None
    views: int | None
    cover_click_rate: float | None
    likes: int | None
    comments: int | None
    saves: int | None
    followers_gained: int | None
    shares: int | None
    avg_watch_time_seconds: int | None
    danmaku_count: int | None


@dataclass(frozen=True)
class MatchResult:
    status: Literal["matched", "ambiguous", "unmatched"]
    content_id: str | None
    score: float | None
    candidate_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in {"matched", "ambiguous", "unmatched"}:
            raise ValueError("invalid match status")
        if self.status == "matched":
            if self.content_id is None:
                raise ValueError("matched result requires content_id")
            if self.score is None:
                raise ValueError("matched result requires score")
        elif self.content_id is not None:
            raise ValueError(
                f"{self.status} result requires content_id to be None"
            )


@dataclass(frozen=True)
class CollectionSummary:
    scheduled_date: date
    execution_date: date
    status: str
    exported_rows: int = 0
    updated_rows: int = 0
    skipped_rows: int = 0
    ambiguous_rows: int = 0
    matched_post_ids: int = 0
    error_summary: str | None = None
