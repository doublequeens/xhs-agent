from datetime import date, datetime
from zoneinfo import ZoneInfo

from memory.memory_manager import XHSMemoryManager
from src.schemas.topic_signal import TopicGenerationTrace, TopicSignal


TZ = ZoneInfo("Asia/Shanghai")


def _manager(tmp_path):
    manager = XHSMemoryManager(tmp_path / "memory.db")
    manager.init_db("memory/schema.sql")
    return manager


def test_upsert_and_query_active_trend_signals(tmp_path):
    manager = _manager(tmp_path)
    signal = TopicSignal(
        signal_id="sig_001",
        source="calendar",
        signal_type="seasonal",
        signal_name="高温天",
        normalized_signal="高温天",
        domain="healthy_lifestyle",
        subdomain="hydration",
        why_now="夏季高温提升饮水提醒的时机感。",
        domain_translation="转译为低风险饮水习惯提醒。",
        risk_level="low",
        avoid_topics=["中暑治疗建议"],
        confidence=0.9,
        active_from=date(2026, 6, 15),
        expires_at=date(2026, 8, 31),
        collected_at=datetime(2026, 7, 7, tzinfo=TZ),
        metadata={"source_rank": 1},
    )

    manager.upsert_trend_signals([signal])

    rows = manager.get_active_trend_signals(
        domain="healthy_lifestyle",
        subdomain="hydration",
        today="2026-07-07",
    )

    assert len(rows) == 1
    assert rows[0]["signal_id"] == "sig_001"
    assert rows[0]["avoid_topics"] == ["中暑治疗建议"]


def test_active_trend_signals_exclude_expired_low_confidence_and_high_risk(tmp_path):
    manager = _manager(tmp_path)
    base = {
        "source": "creator_center",
        "signal_type": "creator_center",
        "signal_name": "活动话题",
        "normalized_signal": "活动话题",
        "domain": "healthy_lifestyle",
        "subdomain": "daily_habits",
        "why_now": "当前活动中心展示。",
        "domain_translation": "转译为生活习惯场景。",
        "avoid_topics": [],
        "active_from": date(2026, 7, 1),
        "collected_at": datetime(2026, 7, 7, tzinfo=TZ),
        "metadata": {},
    }
    manager.upsert_trend_signals([
        TopicSignal(signal_id="sig_ok", risk_level="low", confidence=0.8, expires_at=date(2026, 7, 10), **base),
        TopicSignal(signal_id="sig_old", risk_level="low", confidence=0.8, expires_at=date(2026, 7, 1), **base),
        TopicSignal(signal_id="sig_low", risk_level="low", confidence=0.5, expires_at=date(2026, 7, 10), **base),
        TopicSignal(signal_id="sig_high", risk_level="high", confidence=0.8, expires_at=date(2026, 7, 10), **base),
    ])

    rows = manager.get_active_trend_signals(
        domain="healthy_lifestyle",
        subdomain="daily_habits",
        today="2026-07-07",
    )

    assert [row["signal_id"] for row in rows] == ["sig_ok"]


def test_save_topic_generation_trace(tmp_path):
    manager = _manager(tmp_path)
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
        created_at=datetime(2026, 7, 7, tzinfo=TZ),
    )

    manager.save_topic_generation_trace(trace)

    row = manager.connect().execute(
        "SELECT * FROM topic_generation_traces WHERE run_id = ?",
        ("tg_001",),
    ).fetchone()

    assert row["domain"] == "healthy_lifestyle"


def test_record_and_query_successful_trend_collection_run(tmp_path):
    manager = _manager(tmp_path)

    assert manager.has_successful_trend_collection("2026-07-07") is False

    manager.record_trend_collection_run(
        {
            "collection_date": "2026-07-07",
            "status": "success",
            "started_at": "2026-07-07T22:00:00+08:00",
            "completed_at": "2026-07-07T22:01:00+08:00",
            "collected_signals": 2,
            "error_summary": None,
        }
    )

    assert manager.has_successful_trend_collection("2026-07-07") is True
    row = manager.connect().execute(
        """
        SELECT status, collected_signals
        FROM trend_collection_runs
        WHERE collection_date = ?
        """,
        ("2026-07-07",),
    ).fetchone()
    assert tuple(row) == ("success", 2)
