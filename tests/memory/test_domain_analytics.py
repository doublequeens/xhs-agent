from pathlib import Path

import pytest

from memory.memory_manager import XHSMemoryManager
from memory.models import ContentRecord


SCHEMA_PATH = Path(__file__).resolve().parents[2] / "memory" / "schema.sql"


def _content(content_id, *, domain, subdomain, content_intent):
    return ContentRecord(
        content_id=content_id,
        topic=f"topic-{content_id}",
        created_at="2026-07-04T10:00:00+08:00",
        domain=domain,
        subdomain=subdomain,
        content_intent=content_intent,
        profile_version=f"{domain.replace('_', '-')}-v1",
        risk_level="low",
    )


def test_get_performance_by_domain_returns_separate_grouped_rows(tmp_path):
    manager = XHSMemoryManager(tmp_path / "memory.db")
    manager.init_db(SCHEMA_PATH)

    manager.save_generated_content(
        _content(
            "beauty-1",
            domain="beauty",
            subdomain="skincare",
            content_intent="experience",
        )
    )
    manager.save_generated_content(
        _content(
            "wellness-1",
            domain="wellness",
            subdomain="sleep",
            content_intent="checklist",
        )
    )
    manager.save_generated_content(
        _content(
            "wellness-2",
            domain="wellness",
            subdomain="sleep",
            content_intent="checklist",
        )
    )
    manager.update_metrics("beauty-1", views=100, likes=10, saves=5, comments=2)
    manager.update_metrics("wellness-1", views=200, likes=20, saves=20, comments=10)
    manager.update_metrics("wellness-2", views=400, likes=40, saves=20, comments=20)

    rows = manager.get_performance_by_domain()

    assert rows == [
        {
            "domain": "beauty",
            "subdomain": "skincare",
            "content_intent": "experience",
            "content_count": 1,
            "avg_views": 100.0,
            "avg_save_rate": pytest.approx(0.05),
            "avg_engagement_rate": pytest.approx(0.17),
        },
        {
            "domain": "wellness",
            "subdomain": "sleep",
            "content_intent": "checklist",
            "content_count": 2,
            "avg_views": 300.0,
            "avg_save_rate": pytest.approx(0.075),
            "avg_engagement_rate": pytest.approx(0.225),
        },
    ]
