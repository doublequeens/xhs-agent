from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.schemas.topic_signal import TopicSignal
from src.topic_signals.briefs import build_creative_briefs


def _signal(signal_id, name):
    return TopicSignal(
        signal_id=signal_id,
        source="calendar",
        signal_type="seasonal",
        signal_name=name,
        normalized_signal=name,
        domain="healthy_lifestyle",
        subdomain="daily_habits",
        why_now=f"{name}当前有效。",
        domain_translation="转译为生活习惯场景。",
        risk_level="low",
        avoid_topics=[],
        confidence=0.9,
        active_from=date(2026, 7, 1),
        expires_at=date(2026, 7, 31),
        collected_at=datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
        metadata={},
    )


def test_build_creative_briefs_generates_two_x_trends_num():
    briefs = build_creative_briefs(
        [_signal("sig_1", "高温天"), _signal("sig_2", "周一开工")],
        trends_num=5,
        memory_context={"high_performing_patterns": []},
        seed=7,
    )

    assert len(briefs) == 10
    assert len({brief.signal.signal_id for brief in briefs}) > 1
    assert len({brief.content_intent for brief in briefs}) >= 2
    assert all(brief.brief_id.startswith("br_") for brief in briefs)
