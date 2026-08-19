import json
from enum import Enum
from types import SimpleNamespace

from pydantic import BaseModel, HttpUrl

from src.evidence import EvidenceBrief, EvidenceItem
from src.nodes import node_q_human_review as review_module
from src.schemas.decision import HashTagInput
from src.schemas.narrative import NarrativePlan


class _ReviewPolicyStatus(str, Enum):
    BLOCKED = "blocked"


class _NestedReviewMetadata(BaseModel):
    source_url: HttpUrl
    status: _ReviewPolicyStatus
    tags: list[str]


class _MatchedPolicyRule(BaseModel):
    rule_id: str
    details: _NestedReviewMetadata


def _assembler_state(*, focus_keyword: str, focus_keyword_cli_present: bool) -> dict:
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
        topic="高温通勤后直接赴约：3步清爽补妆流程清单",
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
    return {
        "final_content": final_content,
        "hashtags": SimpleNamespace(hashtags=["#通勤防晒"]),
        "focus_keyword": focus_keyword,
        "focus_keyword_cli_present": focus_keyword_cli_present,
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
    }


def test_assembler_falls_back_focus_keyword_to_topic_when_no_cli_keyword(
    monkeypatch,
):
    from src.nodes import node_o_assembler as assembler_module

    state = _assembler_state(focus_keyword="", focus_keyword_cli_present=False)
    monkeypatch.setattr(
        assembler_module,
        "get_model",
        lambda: SimpleNamespace(
            execute=lambda _messages: {
                "images": [],
                "hashtags": ["#通勤防晒"],
                "notes": [],
            }
        ),
    )

    result = assembler_module.assembler_node(state)

    assert result["publish_package"]["focus_keyword"] == (
        "高温通勤后直接赴约：3步清爽补妆流程清单"
    )


def test_assembler_preserves_explicit_cli_focus_keyword(monkeypatch):
    from src.nodes import node_o_assembler as assembler_module

    state = _assembler_state(
        focus_keyword="通勤补妆", focus_keyword_cli_present=True
    )
    monkeypatch.setattr(
        assembler_module,
        "get_model",
        lambda: SimpleNamespace(
            execute=lambda _messages: {
                "images": [],
                "hashtags": ["#通勤防晒"],
                "notes": [],
            }
        ),
    )

    result = assembler_module.assembler_node(state)

    assert result["publish_package"]["focus_keyword"] == "通勤补妆"


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


def test_publish_review_metadata_is_deep_json_ready_and_read_only(monkeypatch):
    captured = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return {"approved": True}

    monkeypatch.setattr(review_module, "interrupt", fake_interrupt)
    issue_details = _NestedReviewMetadata(
        source_url="https://example.com/issue",
        status=_ReviewPolicyStatus.BLOCKED,
        tags=["issue-state"],
    )
    risk_details = {
        "source_url": issue_details.source_url,
        "status": _ReviewPolicyStatus.BLOCKED,
        "tags": ["risk-state"],
    }
    evidence_metadata = {
        "source_url": issue_details.source_url,
        "status": _ReviewPolicyStatus.BLOCKED,
        "tags": ["evidence-state"],
    }
    matched_rule_details = _NestedReviewMetadata(
        source_url="https://example.com/rule",
        status=_ReviewPolicyStatus.BLOCKED,
        tags=["rule-state"],
    )
    matched_rule = _MatchedPolicyRule(
        rule_id="medical_treatment",
        details=matched_rule_details,
    )
    final_policy_issues = [{"rule_id": "guaranteed_outcome", "details": issue_details}]
    evidence_item = {
        "topic_id": "inner-topic-id",
        "claim": "规律作息与睡眠健康相关。",
        "summary": "公共健康机构建议保持规律作息。",
        "source_title": "Sleep guidance",
        "source_url": issue_details.source_url,
        "source_type": "professional",
        "metadata": evidence_metadata,
    }

    review_module.human_review_node(
        {
            "publish_package": {
                "title": "作息调整清单",
                "domain": "wellness",
                "subdomain": "sleep",
                "content_intent": "checklist",
                "risk_level": "medium",
                "risk_flags": [risk_details],
                "profile_version": "wellness-v1",
            },
            "review_round": 0,
            "final_policy_issues": final_policy_issues,
            "r2_output": SimpleNamespace(
                compliance_audit=SimpleNamespace(
                    matched_policy_rules=[matched_rule]
                )
            ),
            "evidence_briefs": {
                "outer-topic-id": SimpleNamespace(items=[evidence_item])
            },
        }
    )

    payload = captured["payload"]
    metadata = {
        field: payload[field]
        for field in (
            "final_policy_issues",
            "risk_context",
            "matched_policy_rules",
            "evidence_items",
        )
    }
    json.dumps(metadata)
    assert payload["evidence_items"][0]["topic_id"] == "outer-topic-id"

    payload["final_policy_issues"][0]["details"]["tags"].append("payload")
    payload["risk_context"]["risk_flags"][0]["tags"].append("payload")
    payload["matched_policy_rules"][0]["details"]["tags"].append("payload")
    payload["evidence_items"][0]["metadata"]["tags"].append("payload")

    assert issue_details.tags == ["issue-state"]
    assert risk_details["tags"] == ["risk-state"]
    assert matched_rule_details.tags == ["rule-state"]
    assert evidence_metadata["tags"] == ["evidence-state"]
