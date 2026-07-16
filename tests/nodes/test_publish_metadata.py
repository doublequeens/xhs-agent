from types import SimpleNamespace

from src.evidence import EvidenceBrief, EvidenceItem
from src.nodes import node_q_human_review as review_module
from src.schemas.decision import HashTagInput
from src.schemas.narrative import NarrativePlan


def test_pending_human_patch_cannot_overwrite_assembler_narrative_metadata(
    monkeypatch,
):
    from src.nodes import node_o_assembler as assembler_module

    narrative_plan = NarrativePlan.model_validate(
        {
            "narrative_form": "comparison",
            "beats": [
                {"beat_id": "hook", "kind": "hook", "purpose": "建立阅读承诺"},
                {"beat_id": "left", "kind": "comparison", "purpose": "说明常见做法"},
                {"beat_id": "right", "kind": "comparison", "purpose": "说明推荐做法"},
                {"beat_id": "boundary", "kind": "boundary", "purpose": "总结适用边界"},
            ],
            "saveable_beat": {
                "beat_id": "right",
                "kind": "comparison",
                "purpose": "说明推荐做法",
            },
            "closing_mode": "boundary",
        }
    )
    final_content = HashTagInput(
        final_title="通勤防晒对比",
        final_md="先比较使用场景，再选择适合自己的方案。",
        topic_id="tp_001",
        topic="通勤防晒",
        angle_id="ag_001",
        angle="两种补涂方式对比",
        domain="beauty",
        subdomain="skincare",
        content_intent="how_to",
        risk_level="low",
        risk_flags=[],
        target_group="通勤女性",
        core_pain="不知道如何选择补涂方式",
        best_cover_copy="两种补涂方式怎么选",
        narrative_plan=narrative_plan,
    )

    monkeypatch.setattr(
        assembler_module,
        "get_model",
        lambda: SimpleNamespace(
            execute=lambda _messages: {
                "images": [],
                "hashtags": ["#通勤防晒"],
                "notes": ["model note"],
            }
        ),
    )

    result = assembler_module.assembler_node(
        {
            "final_content": final_content,
            "hashtags": SimpleNamespace(hashtags=["#通勤防晒"]),
            "trends": [
                {
                    "topic_id": "tp_001",
                    "content_contract": {"content_job": "compare_and_choose"},
                }
            ],
            "domain_context": {
                "domain": "beauty",
                "profile_version": "beauty-v1",
            },
            "content_policy": {},
            "pending_human_publish_patch": {
                "narrative_plan": {
                    "narrative_form": "story_reversal",
                    "beats": [],
                    "saveable_beat": {},
                    "closing_mode": "none",
                },
                "narrative_form": "story_reversal",
                "closing_mode": "none",
                "notes": ["human note"],
            },
        }
    )

    package = result["publish_package"]
    assert package["narrative_plan"] == narrative_plan.model_dump(mode="json")
    assert package["narrative_form"] == "comparison"
    assert package["closing_mode"] == "boundary"
    assert package["notes"] == ["human note"]


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
