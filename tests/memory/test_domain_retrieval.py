from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from memory.memory_context import memory_context_to_prompt_payload
from memory.memory_manager import XHSMemoryManager
from memory.models import ContentRecord


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "memory" / "schema.sql"


def _now_iso(hours_ago: int) -> str:
    now = datetime.now(timezone(timedelta(hours=8)))
    return (now - timedelta(hours=hours_ago)).isoformat()


def _save_content(
    manager: XHSMemoryManager,
    *,
    content_id: str,
    domain: str,
    subdomain: str,
    topic: str,
    angle: str,
    title: str,
    hashtags: list[str],
    content_format: str,
    visual_style: str,
    card_count: int,
    views: int,
    likes: int,
    saves: int,
    comments: int,
    shares: int,
    followers_gained: int,
    hours_ago: int,
) -> None:
    manager.save_generated_content(
        ContentRecord(
            content_id=content_id,
            topic=topic,
            created_at=_now_iso(hours_ago),
            angle=angle,
            title=title,
            hashtags=hashtags,
            content=f"{topic} content body",
            content_format=content_format,
            visual_style=visual_style,
            card_count=card_count,
            domain=domain,
            subdomain=subdomain,
            content_intent="how_to",
            profile_version=f"{domain}-v1",
            risk_level="low",
        )
    )
    manager.update_metrics(
        content_id,
        views=views,
        likes=likes,
        saves=saves,
        comments=comments,
        shares=shares,
        followers_gained=followers_gained,
    )


def test_build_memory_context_partitions_recent_and_pattern_data_by_domain_and_subdomain(tmp_path):
    manager = XHSMemoryManager(tmp_path / "memory.db")
    manager.init_db(SCHEMA_PATH)

    _save_content(
        manager,
        content_id="beauty-skincare-1",
        domain="beauty",
        subdomain="skincare",
        topic="屏障修护",
        angle="成分拆解",
        title="修护屏障的三步法",
        hashtags=["#修护", "#敏感肌"],
        content_format="checklist",
        visual_style="clean_lab",
        card_count=6,
        views=120,
        likes=30,
        saves=12,
        comments=6,
        shares=4,
        followers_gained=8,
        hours_ago=18,
    )
    _save_content(
        manager,
        content_id="wellness-sleep-1",
        domain="wellness",
        subdomain="sleep",
        topic="睡前仪式",
        angle="上班族快速放松",
        title="10分钟睡前放松流程",
        hashtags=["#睡眠改善", "#睡前仪式"],
        content_format="how_to_cards",
        visual_style="soft_coach",
        card_count=7,
        views=180,
        likes=42,
        saves=18,
        comments=9,
        shares=6,
        followers_gained=10,
        hours_ago=3,
    )
    _save_content(
        manager,
        content_id="wellness-recovery-1",
        domain="wellness",
        subdomain="recovery",
        topic="运动后恢复",
        angle="泡沫轴流程",
        title="恢复期别忽略这5分钟",
        hashtags=["#运动恢复", "#泡沫轴"],
        content_format="tutorial",
        visual_style="coach_demo",
        card_count=5,
        views=6,
        likes=1,
        saves=0,
        comments=0,
        shares=0,
        followers_gained=0,
        hours_ago=4,
    )
    _save_content(
        manager,
        content_id="healthy-exercise-1",
        domain="healthy",
        subdomain="exercise",
        topic="工位拉伸",
        angle="午休活动",
        title="办公室拉伸打卡",
        hashtags=["#拉伸", "#久坐"],
        content_format="photo_story",
        visual_style="casual_lifestyle",
        card_count=4,
        views=90,
        likes=20,
        saves=9,
        comments=2,
        shares=3,
        followers_gained=5,
        hours_ago=10,
    )

    context = manager.build_memory_context(domain="wellness", subdomain="sleep", recent_days=14)

    assert [item["content_id"] for item in context.same_subdomain_recent] == ["wellness-sleep-1"]
    assert context.topics_to_avoid == ["睡前仪式"]
    assert context.angles_to_avoid == ["上班族快速放松"]
    assert context.recent_hashtags == ["#睡眠改善", "#睡前仪式"]

    assert {item["domain"] for item in context.same_domain_patterns} == {"wellness"}
    assert {item["subdomain"] for item in context.same_domain_patterns} == {"sleep", "recovery"}
    assert {item["performance_signal"] for item in context.same_domain_patterns} == {"high", "low"}

    format_titles = {item["title"] for item in context.global_format_patterns}
    assert format_titles == {"修护屏障的三步法", "10分钟睡前放松流程", "恢复期别忽略这5分钟", "办公室拉伸打卡"}
    for pattern in context.global_format_patterns:
        assert set(pattern) >= {
            "title",
            "content_format",
            "visual_style",
            "card_count",
            "views",
            "likes",
            "saves",
            "comments",
            "shares",
            "followers_gained",
            "save_rate",
            "engagement_rate",
            "performance_level",
        }
        assert "topic" not in pattern
        assert "angle" not in pattern
        assert "content" not in pattern


def test_memory_context_prompt_payload_preserves_labeled_pattern_signals():
    from memory.models import MemoryContext

    context = MemoryContext(
        same_subdomain_recent=[{"content_id": "wellness-sleep-1", "topic": "睡前仪式"}],
        same_domain_patterns=[
            {"title": "high item", "domain": "wellness", "subdomain": "sleep", "performance_signal": "high"},
            {"title": "low item", "domain": "wellness", "subdomain": "recovery", "performance_signal": "low"},
        ],
        global_format_patterns=[{"title": "format item", "content_format": "cards", "views": 10}],
        topics_to_avoid=["睡前仪式"],
        angles_to_avoid=["上班族快速放松"],
        recent_hashtags=["#睡眠改善"],
    )

    payload = memory_context_to_prompt_payload(context)

    assert payload["same_subdomain_recent"] == [{"content_id": "wellness-sleep-1", "topic": "睡前仪式"}]
    assert payload["topics_to_avoid"] == ["睡前仪式"]
    assert payload["angles_to_avoid"] == ["上班族快速放松"]
    assert payload["recent_hashtags"] == ["#睡眠改善"]
    assert payload["same_domain_patterns"][0]["performance_signal"] == "high"
    assert payload["same_domain_patterns"][1]["performance_signal"] == "low"
    assert payload["global_format_patterns"] == [{"title": "format item", "content_format": "cards", "views": 10}]
