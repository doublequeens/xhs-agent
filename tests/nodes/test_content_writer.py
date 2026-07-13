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
        "content_contract": {
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
        },
    }
    package.update(overrides)
    return package


def _topic(topic_id="tp_001"):
    return SimpleNamespace(
        topic_id=topic_id,
        domain="wellness",
        subdomain="sleep",
        content_intent="how_to",
        risk_level="medium",
        risk_flags=["medical-adjacent", "sleep-adjacent"],
        content_contract={
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
        },
    )


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


@pytest.mark.parametrize(
    "state,expected_message",
    [
        (
            {
                "review_status": "approved",
                "publish_package": _publish_package(),
                "domain_context": {"profile_version": "wellness-v1"},
                "r2_output": SimpleNamespace(
                    compliance_audit=SimpleNamespace(compliance_status="high_risk_detected")
                ),
            },
            "state.trends",
        ),
        (
            {
                "review_status": "approved",
                "trends": [_topic()],
                "publish_package": _publish_package(
                    topic_id="",
                ),
                "domain_context": {"profile_version": "wellness-v1"},
                "r2_output": SimpleNamespace(
                    compliance_audit=SimpleNamespace(compliance_status="high_risk_detected")
                ),
            },
            "topic_id",
        ),
    ],
)
def test_content_writer_requires_trends_and_topic_id_before_manager_creation(
    monkeypatch, state, expected_message
):
    def fail_manager(*args, **kwargs):
        raise AssertionError("manager should not be constructed before metadata validation")

    monkeypatch.setattr(module, "XHSMemoryManager", fail_manager)

    with pytest.raises(ValueError, match=expected_message):
        module.content_writer_node(state)


def test_content_writer_uses_state_topic_metadata_over_editable_package_fields(monkeypatch):
    fake_manager = _FakeManager()
    captured = {}
    topic = _topic()
    trends = [topic]

    def build_manager(*args, **kwargs):
        return fake_manager

    def fake_get_topic_metadata(received_trends, topic_id):
        assert received_trends == trends
        assert topic_id == "tp_001"
        return {
            "domain": topic.domain,
            "subdomain": topic.subdomain,
            "content_intent": topic.content_intent,
            "risk_level": topic.risk_level,
            "risk_flags": list(topic.risk_flags),
        }

    monkeypatch.setattr(module, "XHSMemoryManager", build_manager)
    monkeypatch.setattr(module, "get_topic_metadata", fake_get_topic_metadata)
    monkeypatch.setattr(module, "make_content_id", lambda: "content-123")
    monkeypatch.setattr(module, "utc_now_iso", lambda: "2026-07-03T10:00:00+08:00")

    def capture_save(record):
        captured["record"] = record
        fake_manager.saved_records.append(record)

    fake_manager.save_generated_content = capture_save

    result = module.content_writer_node(
        {
            "review_status": "approved",
            "trends": trends,
            "publish_package": _publish_package(
                domain="beauty",
                subdomain="skincare",
                content_intent="experience",
                risk_level="low",
            ),
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
        "content_contract": topic.content_contract,
    }
    assert result == {"data_writed": True}


def test_content_writer_compensates_when_vector_write_fails(monkeypatch):
    class CompensationManager(_FakeManager):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.deleted_content_ids = []

        def save_embedding_content(self, record):
            raise RuntimeError("vector boom")

        def delete_content_by_id(self, content_id):
            self.deleted_content_ids.append(content_id)

    fake_manager = CompensationManager()
    topic = _topic()

    monkeypatch.setattr(module, "XHSMemoryManager", lambda *args, **kwargs: fake_manager)
    monkeypatch.setattr(
        module,
        "get_topic_metadata",
        lambda _trends, _topic_id: {
            "domain": topic.domain,
            "subdomain": topic.subdomain,
            "content_intent": topic.content_intent,
            "risk_level": topic.risk_level,
            "risk_flags": list(topic.risk_flags),
        },
    )
    monkeypatch.setattr(module, "make_content_id", lambda: "content-123")
    monkeypatch.setattr(module, "utc_now_iso", lambda: "2026-07-03T10:00:00+08:00")

    with pytest.raises(Exception, match="vector database chromadb"):
        module.content_writer_node(
            {
                "review_status": "approved",
                "trends": [topic],
                "publish_package": _publish_package(),
                "domain_context": {"profile_version": "wellness-v1"},
                "r2_output": SimpleNamespace(
                    compliance_audit=SimpleNamespace(compliance_status="high_risk_detected")
                ),
            }
        )

    assert fake_manager.deleted_content_ids == ["content-123"]
    assert fake_manager.saved_records
    assert fake_manager.embedding_records == []


def test_content_writer_surfaces_compensation_failure(monkeypatch):
    class FailingCompensationManager(_FakeManager):
        def save_embedding_content(self, record):
            raise RuntimeError("vector boom")

        def delete_content_by_id(self, content_id):
            raise RuntimeError("delete boom")

    fake_manager = FailingCompensationManager()
    topic = _topic()

    monkeypatch.setattr(module, "XHSMemoryManager", lambda *args, **kwargs: fake_manager)
    monkeypatch.setattr(
        module,
        "get_topic_metadata",
        lambda _trends, _topic_id: {
            "domain": topic.domain,
            "subdomain": topic.subdomain,
            "content_intent": topic.content_intent,
            "risk_level": topic.risk_level,
            "risk_flags": list(topic.risk_flags),
        },
    )
    monkeypatch.setattr(module, "make_content_id", lambda: "content-123")
    monkeypatch.setattr(module, "utc_now_iso", lambda: "2026-07-03T10:00:00+08:00")

    with pytest.raises(RuntimeError, match="vector boom.*delete boom"):
        module.content_writer_node(
            {
                "review_status": "approved",
                "trends": [topic],
                "publish_package": _publish_package(),
                "domain_context": {"profile_version": "wellness-v1"},
                "r2_output": SimpleNamespace(
                    compliance_audit=SimpleNamespace(compliance_status="high_risk_detected")
                ),
            }
        )


@pytest.mark.parametrize(
    "state",
    [
        {
            "review_status": "approved",
            "trends": [_topic()],
            "publish_package": _publish_package(
                compliance_status="fully_compliant",
                domain="beauty",
                subdomain="skincare",
                content_intent="experience",
                risk_level="low",
            ),
            "domain_context": {"profile_version": "wellness-v1"},
        },
        {
            "review_status": "approved",
            "trends": [_topic()],
            "publish_package": _publish_package(
                compliance_status="compliant_with_minor_edits",
                domain="beauty",
                subdomain="skincare",
                content_intent="experience",
                risk_level="low",
            ),
            "domain_context": {"profile_version": "wellness-v1"},
            "r2_output": SimpleNamespace(compliance_audit="bad"),
        },
    ],
)
def test_content_writer_requires_real_r2_compliance_before_manager_creation(monkeypatch, state):
    def fail_manager(*args, **kwargs):
        raise AssertionError("manager should not be constructed before R2 validation")

    monkeypatch.setattr(module, "XHSMemoryManager", fail_manager)

    with pytest.raises(ValueError, match="r2_output.compliance_audit.compliance_status"):
        module.content_writer_node(state)
