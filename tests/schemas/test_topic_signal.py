from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.schemas.topic import TopicItem
from src.schemas.topic_signal import (
    CreativeBrief,
    CreativeSeed,
    TopicGenerationTrace,
    TopicSignal,
)


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


def test_topic_signal_requires_valid_confidence():
    signal = TopicSignal(
        signal_id="sig_001",
        source="calendar",
        signal_type="seasonal",
        signal_name="高温天",
        normalized_signal="高温天",
        domain="healthy_lifestyle",
        subdomain="hydration",
        why_now="夏季高温提升饮水相关内容的时机感。",
        domain_translation="转译为低风险饮水提醒。",
        risk_level="low",
        avoid_topics=["中暑治疗建议"],
        confidence=0.9,
        active_from=date(2026, 6, 15),
        expires_at=date(2026, 8, 31),
        collected_at=datetime(2026, 7, 7, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        metadata={},
    )

    assert signal.signal_name == "高温天"


def test_topic_signal_rejects_invalid_confidence():
    with pytest.raises(ValueError):
        TopicSignal(
            signal_id="sig_bad",
            source="calendar",
            signal_type="seasonal",
            signal_name="bad",
            normalized_signal="bad",
            domain="healthy_lifestyle",
            subdomain="daily_habits",
            why_now="bad",
            domain_translation="bad",
            risk_level="low",
            avoid_topics=[],
            confidence=1.5,
            active_from=date(2026, 1, 1),
            expires_at=date(2026, 1, 2),
            collected_at=datetime(2026, 1, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
            metadata={},
        )


def test_topic_item_requires_creative_seed():
    seed = CreativeSeed(
        signal_type="weather",
        signal_name="高温天",
        why_now="上海高温天让低门槛补水提醒更有时机感。",
        domain_translation="转译为健康生活方式下的饮水习惯提醒。",
        evergreen_pain="忙起来容易忘记喝水。",
        timely_framing="高温天更容易注意到补水问题。",
    )

    item = TopicItem(
        topic_id="tp_001",
        topic="高温通勤日，上班族的低门槛补水提醒",
        target_group="上班族",
        core_pain="忙起来忘记喝水",
        hook="不是猛灌水，而是把提醒放进通勤和办公节奏里。",
        content_form="checklist",
        risk_note="不涉及疾病治疗或补剂建议。",
        domain="healthy_lifestyle",
        subdomain="hydration",
        content_intent="checklist",
        risk_level="low",
        risk_flags=[],
        content_contract=_content_contract(),
        creative_seed=seed,
    )

    assert item.creative_seed.signal_name == "高温天"


def test_generation_trace_records_diversity_metrics():
    trace = TopicGenerationTrace(
        run_id="tg_001",
        domain="healthy_lifestyle",
        subdomain="daily_habits",
        trends_num=10,
        signals_used=["sig_001"],
        creative_briefs_sampled=["br_001"],
        generated_candidates_count=20,
        filtered_candidates_count=10,
        final_trends=["tp_001"],
        diversity_metrics={"unique_signal_count": 1},
        degraded_reason=None,
        created_at=datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert trace.diversity_metrics["unique_signal_count"] == 1
