from dataclasses import FrozenInstanceError
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from metrics_collector.config import CollectorConfig
from metrics_collector.models import (
    CollectionSummary,
    ContentCandidate,
    ExportedMetrics,
    MatchResult,
    NoteIdentity,
)


def test_collector_config_defaults(tmp_path):
    config = CollectorConfig.default(home=tmp_path)
    state_dir = tmp_path / ".xhs-agent"

    assert config.db_path == Path("data/xhs_memory.db")
    assert config.schema_path == Path("memory/schema.sql")
    assert config.profile_dir == state_dir / "browser-profile"
    assert config.download_dir == state_dir / "downloads"
    assert config.diagnostics_dir == state_dir / "diagnostics"
    assert config.timezone == ZoneInfo("Asia/Shanghai")
    assert config.schedule_time == time(22, 0)
    assert config.max_note_manager_pages == 3
    assert config.diagnostic_retention_days == 7
    assert config.headless is False
    assert config.browser_channel == "chrome"
    assert config.title_similarity_threshold == 0.82
    assert config.combined_score_threshold == 0.80
    assert config.winner_margin == 0.05
    assert config.data_analysis_url == (
        "https://creator.xiaohongshu.com/statistics/data-analysis"
    )
    assert config.note_manager_url == (
        "https://creator.xiaohongshu.com/new/note-manager"
    )


def test_collector_config_default_uses_path_home(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    config = CollectorConfig.default()

    assert config.profile_dir == tmp_path / ".xhs-agent" / "browser-profile"


def test_collector_config_is_frozen(tmp_path):
    config = CollectorConfig.default(home=tmp_path)

    with pytest.raises(FrozenInstanceError):
        config.headless = True


def test_note_url_is_stable_and_contains_no_token(tmp_path):
    config = CollectorConfig.default(home=tmp_path)
    post_id = "0123456789abcdef01234567"

    assert config.note_url(post_id) == (
        f"https://www.xiaohongshu.com/explore/{post_id}"
    )


@pytest.mark.parametrize(
    "post_id",
    [
        "",
        "?xsec_token=abc",
        "6a49/evil",
        "ABCDEF0123456789ABCDEF01",
        "abc123",
        "gggggggggggggggggggggggg",
    ],
)
def test_note_url_rejects_invalid_post_ids(tmp_path, post_id):
    config = CollectorConfig.default(home=tmp_path)

    with pytest.raises(ValueError, match="^invalid Xiaohongshu post_id$"):
        config.note_url(post_id)


@pytest.mark.parametrize(
    "result",
    [
        MatchResult("matched", "content-1", 0.95, ("content-1",)),
        MatchResult("ambiguous", None, 0.80, ("content-1", "content-2")),
        MatchResult("unmatched", None, None, ()),
    ],
)
def test_match_result_accepts_valid_states(result):
    assert result.status in {"matched", "ambiguous", "unmatched"}


@pytest.mark.parametrize(
    ("status", "content_id", "score", "message"),
    [
        ("matched", None, 0.95, "matched result requires content_id"),
        ("matched", "content-1", None, "matched result requires score"),
        (
            "ambiguous",
            "content-1",
            0.80,
            "ambiguous result requires content_id to be None",
        ),
        (
            "unmatched",
            "content-1",
            None,
            "unmatched result requires content_id to be None",
        ),
    ],
)
def test_match_result_rejects_contradictory_states(
    status, content_id, score, message
):
    with pytest.raises(ValueError, match=f"^{message}$"):
        MatchResult(status, content_id, score, ("content-1",))


def test_collector_models_are_constructible_and_frozen():
    published_at = datetime(2026, 7, 5, 12, 30)
    candidate = ContentCandidate("content-1", "Title", published_at)
    identity = NoteIdentity("post-1", "Title", published_at)
    metrics = ExportedMetrics(
        title="Title",
        published_at=published_at,
        impressions=None,
        views=10,
        cover_click_rate=0.25,
        likes=2,
        comments=None,
        saves=1,
        followers_gained=None,
        shares=3,
        avg_watch_time_seconds=12,
        danmaku_count=None,
    )
    match = MatchResult("matched", "content-1", 0.95, ("content-1",))
    summary = CollectionSummary(
        scheduled_date=date(2026, 7, 5),
        execution_date=date(2026, 7, 5),
        status="completed",
    )

    assert candidate.post_id is None
    assert identity.post_id == "post-1"
    assert metrics.impressions is None
    assert match.candidate_ids == ("content-1",)
    assert summary.exported_rows == 0
    assert summary.error_summary is None

    with pytest.raises(FrozenInstanceError):
        candidate.title = "Changed"
