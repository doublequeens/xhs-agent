from src.schemas.topic import TopicItem
from src.topic_signals.diversity import filter_topic_candidates


def _content_contract():
    return {
        "audience": "上班族",
        "trigger_situation": "通勤前",
        "decision_problem": "如何安排日常习惯",
        "first_screen_promise": "通勤前快速掌握基础步骤",
        "screenshot_asset": "步骤清单截图",
        "proof_asset": "执行前后对比",
        "visual_mode": "text_card",
        "content_job": "save_and_check",
        "primary_visual_family": "saveable_reference",
        "primary_visual_subject": "checklist",
        "proof_mode": "diagram",
        "recommended_frame_count": 6,
    }


def _topic(
    topic_id,
    topic,
    signal_name,
    content_intent="checklist",
    signal_type="calendar",
    evergreen_pain="长期痛点。",
):
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
        content_contract=_content_contract(),
        creative_seed={
            "signal_type": signal_type,
            "signal_name": signal_name,
            "why_now": "当前有效。",
            "domain_translation": "转译为生活习惯。",
            "evergreen_pain": evergreen_pain,
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


def test_filter_topic_candidates_reports_real_signal_mix_metrics():
    selected, metrics = filter_topic_candidates(
        [
            _topic(
                "tp_001",
                "高温天上班族补水提醒",
                "上海高温天",
                signal_type="weather",
            ),
            _topic(
                "tp_002",
                "长期久坐人群活动提醒",
                "通用生活场景",
                signal_type="evergreen_context",
                evergreen_pain="",
            ),
        ],
        trends_num=2,
    )

    assert [item.topic_id for item in selected] == ["tp_001", "tp_002"]
    assert metrics["timely_signal_ratio"] == 0.5
    assert metrics["evergreen_pain_ratio"] == 0.5
