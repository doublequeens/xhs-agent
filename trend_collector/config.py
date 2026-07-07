from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class TrendCollectorConfig:
    db_path: Path
    schema_path: Path
    profile_dir: Path
    timezone: ZoneInfo
    creator_center_url: str
    events_center_url: str
    inspiration_categories: list[str]
    max_items_per_block: int
    target_domain: str
    target_subdomain: str

    @classmethod
    def default(cls, home: Path | None = None) -> "TrendCollectorConfig":
        state_dir = (home if home is not None else Path.home()) / ".xhs-agent"
        return cls(
            db_path=Path("data/xhs_memory.db"),
            schema_path=Path("memory/schema.sql"),
            profile_dir=state_dir / "browser-profile",
            timezone=ZoneInfo("Asia/Shanghai"),
            creator_center_url="https://creator.xiaohongshu.com/new/inspiration",
            events_center_url="https://creator.xiaohongshu.com/new/events",
            inspiration_categories=["美食", "美妆", "时尚", "出行", "知识", "兴趣爱好"],
            max_items_per_block=20,
            target_domain="healthy_lifestyle",
            target_subdomain="daily_habits",
        )
