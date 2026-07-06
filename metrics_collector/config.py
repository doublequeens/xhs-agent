import re
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo


_POST_ID_PATTERN = re.compile(r"[0-9a-f]{24}")


@dataclass(frozen=True)
class CollectorConfig:
    db_path: Path
    schema_path: Path
    profile_dir: Path
    download_dir: Path
    diagnostics_dir: Path
    timezone: ZoneInfo
    schedule_time: time
    max_note_manager_pages: int
    diagnostic_retention_days: int
    headless: bool
    browser_channel: str
    title_similarity_threshold: float
    combined_score_threshold: float
    winner_margin: float
    data_analysis_url: str
    note_manager_url: str

    @classmethod
    def default(cls, home: Path | None = None) -> "CollectorConfig":
        state_dir = (home if home is not None else Path.home()) / ".xhs-agent"
        return cls(
            db_path=Path("data/xhs_memory.db"),
            schema_path=Path("memory/schema.sql"),
            profile_dir=state_dir / "browser-profile",
            download_dir=state_dir / "downloads",
            diagnostics_dir=state_dir / "diagnostics",
            timezone=ZoneInfo("Asia/Shanghai"),
            schedule_time=time(22, 0),
            max_note_manager_pages=3,
            diagnostic_retention_days=7,
            headless=False,
            browser_channel="chrome",
            title_similarity_threshold=0.82,
            combined_score_threshold=0.80,
            winner_margin=0.05,
            data_analysis_url=(
                "https://creator.xiaohongshu.com/statistics/data-analysis"
            ),
            note_manager_url="https://creator.xiaohongshu.com/new/note-manager",
        )

    def note_url(self, post_id: str) -> str:
        if _POST_ID_PATTERN.fullmatch(post_id) is None:
            raise ValueError("invalid Xiaohongshu post_id")
        return f"https://www.xiaohongshu.com/explore/{post_id}"
