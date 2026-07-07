from src.schemas.topic import TopicItem
from src.topic_signals.diversity import filter_topic_candidates


def _topic(topic_id, topic, signal_name, content_intent="checklist"):
    return TopicItem(
        topic_id=topic_id,
        topic=topic,
        target_group="上班族",
        core_pain=f"{topic}痛点",
        hook="hook",
        content_form="list",
        risk_note="low risk",
        domain="healthy_lifestyle",
        subdomain="daily_habits",
        content_intent=content_intent,
        risk_level="low",
        risk_flags=[],
        creative_seed={
            "signal_type": "calendar",
            "signal_name": signal_name,
            "why_now": "当前有效。",
            "domain_translation": "转译为生活习惯。",
            "evergreen_pain": "长期痛点。",
            "timely_framing": "当前时机。",
        },
    )


def test_filter_topic_candidates_removes_near_duplicates():
    selected, metrics = filter_topic_candidates(
        [
            _topic("tp_001", "高温天上班族补水提醒", "高温天"),
            _topic("tp_002", "高温天上班族补水清单", "高温天"),
            _topic("tp_003", "周一开工低门槛拉伸", "周一开工", "how_to"),
        ],
        trends_num=2,
    )
    assert [item.topic_id for item in selected] == ["tp_001", "tp_003"]
    assert metrics["unique_signal_count"] == 2
