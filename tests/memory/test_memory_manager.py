from __future__ import annotations

from pathlib import Path

from memory.memory_manager import XHSMemoryManager
from memory.models import ContentRecord


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "memory" / "schema.sql"


def test_connections_are_keyed_by_resolved_path_and_close_methods_are_isolated(tmp_path):
    db1 = tmp_path / "one" / "memory.db"
    db2 = tmp_path / "two" / "memory.db"

    manager1 = XHSMemoryManager(db1)
    manager2 = XHSMemoryManager(db2)

    conn1 = manager1.connect()
    conn2 = manager2.connect()

    assert conn1 is not conn2
    assert db1.resolve() in manager1.connections
    assert db2.resolve() in manager2.connections

    manager1.close()

    assert db1.resolve() not in manager1.connections
    assert db2.resolve() in manager2.connections

    XHSMemoryManager.close_all()

    assert manager1.connections == {}


def test_save_generated_content_roundtrips_domain_metadata(tmp_path):
    manager = XHSMemoryManager(tmp_path / "memory.db")
    manager.init_db(SCHEMA_PATH)

    record = ContentRecord(
        content_id="content-1",
        topic="睡眠改善",
        created_at="2026-07-03T10:00:00+08:00",
        status="reviewed",
        platform="xiaohongshu",
        topic_id="tp_001",
        angle_id="ag_001",
        angle="睡眠策略",
        target_group="上班族",
        core_pain="熬夜后疲惫",
        title="睡眠改善指南",
        cover_copy="cover",
        content="body",
        hashtags=["#睡眠"],
        content_format="educational_cards",
        visual_style="domain_editorial",
        card_count=6,
        storyboards=["frame-1", "frame-2"],
        image_paths=["/tmp/image-1.png"],
        strategy_tags=["sleep", "wellness"],
        compliance_status="compliant_with_minor_edits",
        embedding_text="睡眠改善 睡眠策略 上班族",
        domain="wellness",
        subdomain="sleep",
        content_intent="how_to",
        profile_version="wellness-v1",
        risk_level="medium",
        metadata={
            "domain": "wellness",
            "subdomain": "sleep",
            "content_intent": "how_to",
            "profile_version": "wellness-v1",
            "risk_level": "medium",
        },
    )

    manager.save_generated_content(record)
    content = manager.get_content_by_id("content-1")

    assert content is not None
    assert content["domain"] == "wellness"
    assert content["subdomain"] == "sleep"
    assert content["content_intent"] == "how_to"
    assert content["profile_version"] == "wellness-v1"
    assert content["risk_level"] == "medium"
    assert content["hashtags"] == ["#睡眠"]
    assert content["storyboards"] == ["frame-1", "frame-2"]
    assert content["image_paths"] == ["/tmp/image-1.png"]
    assert content["strategy_tags"] == ["sleep", "wellness"]
    assert content["compliance_status"] == "compliant_with_minor_edits"
    assert content["metadata"] == {
        "domain": "wellness",
        "subdomain": "sleep",
        "content_intent": "how_to",
        "profile_version": "wellness-v1",
        "risk_level": "medium",
    }
