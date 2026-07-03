from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.nodes import node_p_content_writer as module


class _FakeManager:
    def __init__(self, *args, **kwargs):
        self.saved_records = []
        self.embedding_records = []
        self.closed = False

    def init_db(self, schema_path):
        self.schema_path = schema_path

    def save_generated_content(self, record):
        self.saved_records.append(record)

    def save_embedding_content(self, record):
        self.embedding_records.append(record)

    def get_content_by_id(self, content_id):
        return {"content_id": content_id} if self.saved_records else None

    def get_embedding_content_by_id(self, content_id):
        return content_id == "content-123"


def _publish_package(**overrides):
    package = {
        "topic_id": "tp_001",
        "topic": "睡眠改善",
        "angle_id": "ag_001",
        "angle": "睡眠策略",
        "target_group": "上班族",
        "core_pain": "熬夜后疲惫",
        "title": "睡眠改善指南",
        "cover_copy": "cover",
        "content": "body",
        "hashtags": ["#睡眠"],
        "storyboards": ["frame-1"],
        "images": [{"image_url": "/tmp/image-1.png"}],
        "domain": "wellness",
        "subdomain": "sleep",
        "content_intent": "how_to",
        "risk_level": "medium",
        "risk_flags": ["medical-adjacent"],
    }
    package.update(overrides)
    return package


def test_content_writer_requires_approved_review_before_writing(monkeypatch):
    def fail_manager(*args, **kwargs):
        raise AssertionError("manager should not be constructed before approval")

    monkeypatch.setattr(module, "XHSMemoryManager", fail_manager)

    with pytest.raises(ValueError, match="approved"):
        module.content_writer_node(
            {
                "review_status": "pending",
                "publish_package": _publish_package(),
                "domain_context": {"profile_version": "wellness-v1"},
            }
        )


def test_content_writer_uses_deterministic_metadata_and_r2_compliance_status(monkeypatch):
    fake_manager = _FakeManager()
    captured = {}

    def build_manager(*args, **kwargs):
        return fake_manager

    monkeypatch.setattr(module, "XHSMemoryManager", build_manager)
    monkeypatch.setattr(module, "make_content_id", lambda: "content-123")
    monkeypatch.setattr(module, "utc_now_iso", lambda: "2026-07-03T10:00:00+08:00")

    def capture_save(record):
        captured["record"] = record
        fake_manager.saved_records.append(record)

    fake_manager.save_generated_content = capture_save

    result = module.content_writer_node(
        {
            "review_status": "approved",
            "publish_package": _publish_package(),
            "domain_context": {"profile_version": "wellness-v1"},
            "r2_output": SimpleNamespace(
                compliance_audit=SimpleNamespace(compliance_status="high_risk_detected")
            ),
        }
    )

    record = captured["record"]
    assert record.domain == "wellness"
    assert record.subdomain == "sleep"
    assert record.content_intent == "how_to"
    assert record.profile_version == "wellness-v1"
    assert record.risk_level == "medium"
    assert record.compliance_status == "high_risk_detected"
    assert record.metadata == {
        "domain": "wellness",
        "subdomain": "sleep",
        "content_intent": "how_to",
        "profile_version": "wellness-v1",
        "risk_level": "medium",
    }
    assert result == {"data_writed": True}


def test_content_writer_uses_legacy_compliance_fallback_when_r2_is_missing(monkeypatch):
    fake_manager = _FakeManager()
    captured = {}

    monkeypatch.setattr(module, "XHSMemoryManager", lambda *args, **kwargs: fake_manager)
    monkeypatch.setattr(module, "make_content_id", lambda: "content-123")
    monkeypatch.setattr(module, "utc_now_iso", lambda: "2026-07-03T10:00:00+08:00")

    def capture_save(record):
        captured["record"] = record
        fake_manager.saved_records.append(record)

    fake_manager.save_generated_content = capture_save

    module.content_writer_node(
        {
            "review_status": "approved",
            "publish_package": _publish_package(compliance_status="compliant_with_minor_edits"),
            "domain_context": {"profile_version": "wellness-v1"},
        }
    )

    assert captured["record"].compliance_status == "compliant_with_minor_edits"
