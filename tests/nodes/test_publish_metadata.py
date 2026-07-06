from types import SimpleNamespace

from src.evidence import EvidenceBrief, EvidenceItem
from src.nodes import node_q_human_review as review_module


def test_publish_review_includes_risk_rules_and_serialized_evidence(monkeypatch):
    captured = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return {"approved": True}

    monkeypatch.setattr(review_module, "interrupt", fake_interrupt)
    evidence = EvidenceItem(
        claim="规律作息与睡眠健康相关。",
        summary="公共健康机构建议保持规律作息。",
        source_title="Sleep guidance",
        source_url="https://www.who.int/example",
        source_type="public_health",
    )
    publish_package = {
        "topic_id": "tp_001",
        "topic": "睡眠改善",
        "angle_id": "ag_001",
        "angle": "作息清单",
        "target_group": "上班族",
        "core_pain": "晚睡后疲惫",
        "title": "作息调整清单",
        "content": "记录晚睡诱因，逐步调整。",
        "cover_copy": "作息调整",
        "hashtags": ["#睡眠习惯"],
        "storyboards": [],
        "domain": "wellness",
        "subdomain": "sleep",
        "content_intent": "checklist",
        "profile_version": "wellness-v1",
        "risk_level": "medium",
        "risk_flags": ["medical-adjacent"],
    }

    review_module.human_review_node(
        {
            "publish_package": publish_package,
            "review_round": 0,
            "final_policy_issues": [],
            "r2_output": SimpleNamespace(
                compliance_audit=SimpleNamespace(
                    matched_policy_rules=["medical_treatment"]
                )
            ),
            "evidence_briefs": {
                "tp_001": EvidenceBrief(topic_id="tp_001", items=[evidence])
            },
        }
    )

    payload = captured["payload"]
    assert payload["risk_context"] == {
        "domain": "wellness",
        "subdomain": "sleep",
        "content_intent": "checklist",
        "risk_level": "medium",
        "risk_flags": ["medical-adjacent"],
        "profile_version": "wellness-v1",
    }
    assert payload["matched_policy_rules"] == ["medical_treatment"]
    assert payload["evidence_items"] == [
        {
            "topic_id": "tp_001",
            "claim": "规律作息与睡眠健康相关。",
            "summary": "公共健康机构建议保持规律作息。",
            "source_title": "Sleep guidance",
            "source_url": "https://www.who.int/example",
            "source_type": "public_health",
            "provenance_type": "search_snippet",
            "verified": False,
        }
    ]
