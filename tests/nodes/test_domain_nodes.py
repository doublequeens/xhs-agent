import importlib
import sqlite3
from types import SimpleNamespace

import pytest

from memory.models import MemoryContext
from src.domain.models import DomainContext
from src.schemas.angle import AngleStrategy, ContentAngle
from src.domain import build_content_policy, get_domain_profile
from src.domain.router import resolve_domain
from src.schemas.narrative import NarrativePlan
from src.schemas.novelty_guard import NoveltyCheckResults
from src.nodes.node_a_00_domain_confirmation import domain_confirmation_node
from src.nodes.node_a_01_retrieve_memory import retrieve_memory_node
from src.nodes.node_b_novelty_guard import get_memory_matches, novelty_guard_node
from src.nodes.node_a_00_domain_router import domain_router_node


def narrative_plan(narrative_form="scenario_story", *, closing_mode="reflection"):
    beats = [
        {"beat_id": "hook", "kind": "hook", "purpose": "建立阅读承诺"},
        {"beat_id": "scene", "kind": "scene", "purpose": "呈现具体场景"},
        {"beat_id": "reveal", "kind": "reveal", "purpose": "揭示关键发现"},
        {"beat_id": "lesson", "kind": "summary", "purpose": "总结可保存结论"},
    ]
    return NarrativePlan(
        narrative_form=narrative_form,
        beats=beats,
        saveable_beat=beats[-1],
        closing_mode=closing_mode,
    )


def invoke_angle_strategist_node(monkeypatch, *, narrative_forms):
    from src.nodes import node_b_angle_strategist as module

    class FakeModel:
        def execute(self, _messages):
            return [
                {
                    "topic_id": "tp_001",
                    "topic": "睡前仪式",
                    "target_group": "上班族",
                    "core_pain": "入睡慢",
                    "angles": [
                        {
                            "angle_id": f"ag_{index:03d}",
                            "angle": f"角度 {index}",
                            "opening_hook": "今晚先别急着改变全部习惯",
                            "value_promise": "找到一个可执行的睡前调整",
                            "suggested_structure": "从具体场景展开并给出边界清晰的建议",
                            "narrative_plan": narrative_plan(
                                narrative_form
                            ).model_dump(mode="json"),
                        }
                        for index, narrative_form in enumerate(
                            narrative_forms,
                            start=1,
                        )
                    ],
                }
            ]

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())
    return module.angle_strategist_node(
        {
            "trends": [],
            "domain_context": {
                "domain": "wellness",
                "profile_version": "wellness-v1",
            },
            "content_policy": {},
        }
    )


def test_angle_strategist_rejects_one_repeated_narrative_form(monkeypatch):
    with pytest.raises(
        ValueError,
        match="at least two distinct narrative forms",
    ):
        invoke_angle_strategist_node(
            monkeypatch,
            narrative_forms=["scenario_story"] * 3,
        )


def test_angle_strategist_accepts_two_narrative_forms_across_three_angles(
    monkeypatch,
):
    result = invoke_angle_strategist_node(
        monkeypatch,
        narrative_forms=[
            "scenario_story",
            "cognitive_correction",
            "scenario_story",
        ],
    )

    assert {
        angle.narrative_plan.narrative_form
        for angle in result["angles"][0].angles
    } == {"scenario_story", "cognitive_correction"}


def invoke_outline_node(monkeypatch, *, narrative, model_narrative=None):
    from src.nodes import node_d_outline_architect as module

    output_plan = model_narrative or narrative

    class FakeModel:
        def execute(self, _messages):
            return [
                {
                    "outline_id": "outline_001",
                    "outline_md": "她先观察场景，再记录关键变化，最后自然结束。",
                    "topic_id": "tp_001",
                    "topic": "睡前仪式",
                    "angle_id": "ag_001",
                    "angle": "场景观察",
                    "target_group": "上班族",
                    "core_pain": "入睡慢",
                    "narrative_plan": output_plan.model_dump(mode="json"),
                }
            ]

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())
    result = module.outline_architect_node(
        {
            "scores": [
                {
                    "topic_id": "tp_001",
                    "angle_id": "ag_001",
                    "narrative_plan": narrative,
                }
            ],
            "domain_context": {
                "domain": "wellness",
                "profile_version": "wellness-v1",
            },
            "content_policy": {},
            "evidence_briefs": {},
        }
    )
    return result["outlines"][0]


def invoke_draft_node(
    monkeypatch,
    *,
    outline,
    draft_md,
    model_narrative=None,
):
    from src.nodes import node_e_draft_writer as module

    output_plan = model_narrative or outline.narrative_plan

    class FakeModel:
        def execute(self, _messages):
            return [
                {
                    "draft_id": "draft_001",
                    "draft_md": draft_md,
                    "topic_id": outline.topic_id,
                    "topic": outline.topic,
                    "angle_id": outline.angle_id,
                    "angle": outline.angle,
                    "target_group": outline.target_group,
                    "core_pain": outline.core_pain,
                    "narrative_plan": output_plan.model_dump(mode="json"),
                }
            ]

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())
    result = module.draft_writer_node(
        {
            "outlines": [outline],
            "domain_context": {
                "domain": "wellness",
                "profile_version": "wellness-v1",
            },
            "content_policy": {},
            "evidence_briefs": {},
        }
    )
    return result["drafts"][0]


def test_outline_and_draft_preserve_none_closing_mode(monkeypatch):
    narrative = narrative_plan("scenario_story", closing_mode="none")

    outline = invoke_outline_node(monkeypatch, narrative=narrative)
    draft = invoke_draft_node(
        monkeypatch,
        outline=outline,
        draft_md="她停下来观察变化，然后按边界结束。",
    )

    assert outline.narrative_plan == narrative
    assert draft.narrative_plan == narrative
    assert "你呢" not in draft.draft_md
    assert "评论区" not in draft.draft_md


def test_outline_rejects_model_rewritten_narrative_plan(monkeypatch):
    with pytest.raises(ValueError, match="must preserve the selected narrative_plan"):
        invoke_outline_node(
            monkeypatch,
            narrative=narrative_plan(),
            model_narrative=narrative_plan("cognitive_correction"),
        )


def test_draft_rejects_model_rewritten_narrative_plan(monkeypatch):
    outline = invoke_outline_node(monkeypatch, narrative=narrative_plan())

    with pytest.raises(ValueError, match="must preserve the selected narrative_plan"):
        invoke_draft_node(
            monkeypatch,
            outline=outline,
            draft_md="正文",
            model_narrative=narrative_plan("cognitive_correction"),
        )


def test_virality_scorer_rejects_model_rewritten_narrative_plan(monkeypatch):
    from src.nodes import node_c_virality_scorer as module

    authoritative_plan = narrative_plan()
    novelty_results = NoveltyCheckResults(
        novelty_results=[
            {
                "topic_id": "tp_001",
                "topic": "睡前仪式",
                "target_group": "上班族",
                "core_pain": "入睡慢",
                "angle_id": "ag_001",
                "angle": "场景观察",
                "opening_hook": "hook",
                "value_promise": "promise",
                "suggested_structure": "structure",
                "narrative_plan": authoritative_plan,
                "decision": "keep",
                "novelty_score": 0.9,
                "max_similarity": 0.0,
                "matched_history": [],
                "reason": "足够新颖",
                "revision_suggestions": [],
                "memory_signal": {
                    "decision": "keep",
                    "novelty_score": 0.9,
                    "max_similarity": 0.0,
                    "rejected_by_memory": False,
                    "similar_to_recent_content": False,
                    "similar_to_high_performing_pattern": False,
                    "similar_to_low_performing_pattern": False,
                    "recommended_for_virality_scorer": True,
                },
            }
        ]
    )

    class FakeModel:
        def execute(self, _messages):
            return [
                {
                    "total_score": 8.5,
                    "breakdown": {
                        "click_potential": 8,
                        "save_value": 9,
                        "comment_potential": 7,
                        "execution_barrier": 3,
                        "compliance_safety": 9,
                        "memory_fit_score": 8,
                    },
                    "strengths": ["场景明确"],
                    "weaknesses": ["篇幅需控制"],
                    "optimization_suggestions": ["保留边界"],
                    "absorbed_memory_suggestions": [],
                    "memory_decision": "keep",
                    "novelty_score": 0.9,
                    "max_similarity": 0.0,
                    "topic_id": "tp_001",
                    "topic": "睡前仪式",
                    "target_group": "上班族",
                    "core_pain": "入睡慢",
                    "angle_id": "ag_001",
                    "angle": "场景观察",
                    "opening_hook": "hook",
                    "value_promise": "promise",
                    "suggested_structure": "structure",
                    "narrative_plan": narrative_plan(
                        "cognitive_correction"
                    ).model_dump(mode="json"),
                }
            ]

    monkeypatch.setattr(module, "get_model", lambda: FakeModel())

    with pytest.raises(ValueError, match="must preserve the selected narrative_plan"):
        module.virality_scorer_node(
            {
                "novelty_check_results": novelty_results,
                "trends": [],
                "domain_context": {
                    "domain": "wellness",
                    "profile_version": "wellness-v1",
                },
                "content_policy": {},
            }
        )


def test_domain_router_node_returns_context_and_policy():
    result = domain_router_node({"domain": None, "focus_keyword": "久坐办公怎么活动"})

    assert result["domain_context"].domain == "healthy_lifestyle"
    assert result["domain_context"].subdomain == "sedentary_habits"
    assert result["content_policy"].require_evidence_brief is True
    assert result["content_policy"].risk_level == result["domain_context"].risk_level


def test_domain_router_rejects_out_of_scope_explicit_domain():
    from src.creator_profile import COMMUTING_BEAUTY_WOMEN_V1

    with pytest.raises(ValueError, match="outside creator profile scope"):
        domain_router_node(
            {
                "creator_profile": COMMUTING_BEAUTY_WOMEN_V1,
                "domain": "healthy_lifestyle",
                "subdomain": "daily_habits",
                "focus_keyword": "久坐",
            }
        )


def test_domain_router_uses_creator_profile_defaults_when_scope_is_omitted():
    from src.creator_profile import COMMUTING_BEAUTY_WOMEN_V1

    result = domain_router_node(
        {
            "creator_profile": COMMUTING_BEAUTY_WOMEN_V1,
            "domain": None,
            "subdomain": None,
            "focus_keyword": "久坐",
        }
    )

    assert result["domain_context"].domain == "beauty"
    assert result["domain_context"].subdomain == "skincare"


def test_domain_confirmation_rejects_resume_outside_creator_profile_scope(monkeypatch):
    from src.creator_profile import COMMUTING_BEAUTY_WOMEN_V1

    context = resolve_domain(domain="beauty", focus_keyword="防晒")
    monkeypatch.setattr(
        "src.nodes.node_a_00_domain_confirmation.interrupt",
        lambda _payload: {"domain": "wellness", "subdomain": "sleep"},
    )

    with pytest.raises(ValueError, match="outside creator profile scope"):
        domain_confirmation_node(
            {"domain_context": context, "creator_profile": COMMUTING_BEAUTY_WOMEN_V1}
        )


def test_domain_confirmation_payload_limits_choices_to_creator_profile(monkeypatch):
    from src.creator_profile import COMMUTING_BEAUTY_WOMEN_V1

    context = resolve_domain(domain="beauty", focus_keyword="防晒")
    captured = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return {"domain": "beauty", "subdomain": "makeup_basics"}

    monkeypatch.setattr(
        "src.nodes.node_a_00_domain_confirmation.interrupt", fake_interrupt
    )

    result = domain_confirmation_node(
        {"domain_context": context, "creator_profile": COMMUTING_BEAUTY_WOMEN_V1}
    )

    assert captured["payload"]["allowed_domains"] == ("beauty",)
    assert captured["payload"]["allowed_subdomains"] == (
        "skincare",
        "makeup_basics",
    )
    assert result["domain_context"].subdomain == "makeup_basics"


def test_domain_confirmation_node_skips_interrupt_for_high_confidence_inferred_domain(
    monkeypatch,
):
    context = resolve_domain(domain=None, focus_keyword="改善睡眠")

    def fail_interrupt(_payload):
        raise AssertionError("interrupt should not be called")

    monkeypatch.setattr("src.nodes.node_a_00_domain_confirmation.interrupt", fail_interrupt)

    assert domain_confirmation_node({"domain_context": context}) == {}


def test_domain_confirmation_node_skips_interrupt_for_explicit_domain_with_subdomain(
    monkeypatch,
):
    context = resolve_domain(
        domain="beauty",
        subdomain="skincare",
        focus_keyword="改善睡眠",
    )

    def fail_interrupt(_payload):
        raise AssertionError("interrupt should not be called")

    monkeypatch.setattr("src.nodes.node_a_00_domain_confirmation.interrupt", fail_interrupt)

    assert domain_confirmation_node({"domain_context": context}) == {}


def test_domain_confirmation_node_interrupts_and_accepts_resume_for_default_subdomain(
    monkeypatch,
):
    context = resolve_domain(domain="beauty", focus_keyword="改善睡眠")
    captured = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return {"domain": "wellness", "subdomain": "sleep"}

    monkeypatch.setattr("src.nodes.node_a_00_domain_confirmation.interrupt", fake_interrupt)

    result = domain_confirmation_node({"domain_context": context})

    assert captured["payload"]["kind"] == "domain_confirmation"
    assert "message" in captured["payload"]
    assert captured["payload"]["context"]["classification_source"] == "explicit_domain_default_subdomain"
    assert result["domain_context"].domain == "wellness"
    assert result["domain_context"].subdomain == "sleep"
    assert result["domain_context"].classification_source == "explicit"
    assert result["domain_context"].classification_confidence == 1
    assert result["domain_context"].profile_version == "wellness-v1"
    assert result["content_policy"] == build_content_policy(get_domain_profile("wellness"))


def test_domain_confirmation_node_still_interrupts_for_interactive_default_subdomain(
    monkeypatch,
):
    context = resolve_domain(domain="beauty", focus_keyword="改善睡眠")
    captured = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return {"domain": "beauty", "subdomain": "makeup_basics"}

    monkeypatch.setattr("src.nodes.node_a_00_domain_confirmation.interrupt", fake_interrupt)

    result = domain_confirmation_node({"domain_context": context, "interactive": True})

    assert captured["payload"]["kind"] == "domain_confirmation"
    assert captured["payload"]["context"]["classification_source"] == "explicit_domain_default_subdomain"
    assert result["domain_context"].domain == "beauty"
    assert result["domain_context"].subdomain == "makeup_basics"
    assert result["domain_context"].classification_source == "explicit"


def test_domain_router_and_confirmation_skip_interrupt_when_non_interactive(monkeypatch):
    routed = domain_router_node(
        {
            "domain": "beauty",
            "subdomain": None,
            "focus_keyword": "改善睡眠",
            "interactive": False,
        }
    )
    captured = {"called": False}

    def fail_interrupt(_payload):
        captured["called"] = True
        raise AssertionError("interrupt should not be called")

    monkeypatch.setattr("src.nodes.node_a_00_domain_confirmation.interrupt", fail_interrupt)

    confirmation_result = domain_confirmation_node(
        {"domain_context": routed["domain_context"], "interactive": False}
    )

    assert routed["domain_context"].classification_source == "explicit_domain_default_subdomain"
    assert routed["domain_context"].classification_confidence == 1
    assert confirmation_result == {}
    assert captured["called"] is False


def test_domain_confirmation_node_rejects_invalid_subdomain(monkeypatch):
    context = resolve_domain(domain=None, focus_keyword="完全无关的关键词")

    monkeypatch.setattr(
        "src.nodes.node_a_00_domain_confirmation.interrupt",
        lambda _payload: {"domain": "wellness", "subdomain": "skincare"},
    )

    with pytest.raises(ValueError, match="Unsupported subdomain: skincare for domain wellness"):
        domain_confirmation_node({"domain_context": context})


def test_domain_confirmation_node_rejects_non_dict_resume(monkeypatch):
    context = resolve_domain(domain=None, focus_keyword="完全无关的关键词")

    monkeypatch.setattr("src.nodes.node_a_00_domain_confirmation.interrupt", lambda _payload: "bad")

    with pytest.raises(ValueError, match="Domain confirmation resume payload must be a dict"):
        domain_confirmation_node({"domain_context": context})


def test_human_review_interrupt_payload_has_kind():
    module = importlib.import_module("src.nodes.node_q_human_review")
    captured = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return {"approved": True, "edited_publish_package": None, "feedback": "ok"}

    original = module.interrupt
    module.interrupt = fake_interrupt
    try:
        result = module.human_review_node(
            {
                "publish_package": {
                    "title": "x",
                    "domain": "wellness",
                    "subdomain": "sleep",
                    "content_intent": "how_to",
                    "risk_level": "medium",
                    "risk_flags": ["medical-adjacent"],
                    "profile_version": "wellness-v1",
                },
                "review_round": 0,
                "final_policy_issues": [{"rule_id": "guaranteed_outcome"}],
                "domain_context": {"profile_version": "wellness-v1"},
            }
        )
    finally:
        module.interrupt = original

    assert captured["payload"]["kind"] == "publish_review"
    assert captured["payload"]["final_policy_issues"] == [{"rule_id": "guaranteed_outcome"}]
    assert captured["payload"]["risk_context"]["risk_level"] == "medium"
    assert captured["payload"]["risk_context"]["profile_version"] == "wellness-v1"
    assert result["review_status"] == "approved"


def test_human_focus_keyword_edit_invalidates_downstream_artifacts_and_reruns_r2(
    monkeypatch,
):
    module = importlib.import_module("src.nodes.node_q_human_review")
    package = {
        "title": "通勤底妆指南",
        "content": "正文",
        "cover_copy": "先看这里",
        "hashtags": ["#通勤底妆"],
        "topic_id": "topic-1",
        "topic": "通勤底妆",
        "angle_id": "angle-1",
        "angle": "成膜顺序",
        "target_group": "通勤人群",
        "core_pain": "防晒后搓泥",
        "narrative_plan": narrative_plan().model_dump(mode="json"),
    }
    monkeypatch.setattr(
        module,
        "interrupt",
        lambda _payload: {
            "approved": True,
            "edited_publish_package": {"title": "人工换标题"},
            "feedback": "change title",
        },
    )

    visual_artifacts = {
        "content_atom_set": {"canonical_sha256": "old-atoms", "atoms": []},
        "visual_direction_plan": {
            "template_family": "white_quote",
            "page_count": 5,
            "art_direction": "editorial",
        },
        "asset_manifest": {"items": []},
        "carousel_design_plan": {"pages": []},
        "design_plan_qa_result": {"passed": True, "issues": []},
        "render_manifest": {"pages": []},
        "render_qa_result": {"passed": True, "issues": []},
        "visual_critique": {"passed": True, "issues": []},
    }
    result = module.human_review_node(
        {
            "publish_package": package,
            **visual_artifacts,
            "review_round": 0,
            "final_policy_issues": [],
        }
    )

    assert result["review_status"] == "needs_r2_recheck"
    assert result["review_route"] == "r2_compliance"
    assert result["publish_package"]["title"] == "人工换标题"
    assert {
        key: result[key]
        for key in visual_artifacts
    } == {key: None for key in visual_artifacts}
    assert (
        result["decision_output"]
        .normalized_input.r2_input.content_snapshot.narrative_plan
        == narrative_plan()
    )


def test_retrieve_memory_node_requires_domain_context():
    with pytest.raises(ValueError, match="retrieve_memory_node requires state.domain_context with domain and subdomain"):
        retrieve_memory_node({})


def test_retrieve_memory_node_passes_domain_scope_to_memory_manager(monkeypatch):
    captured = {"call_order": []}

    class FakeManager:
        def __init__(self, db_path):
            captured["db_path"] = db_path

        def init_db(self, schema_path):
            captured["schema_path"] = schema_path
            captured["call_order"].append("init_db")

        def ensure_vector_scope_backfill(self):
            captured["call_order"].append("ensure_vector_scope_backfill")

        def build_memory_context(self, *, domain, subdomain, recent_days):
            captured["call_order"].append("build_memory_context")
            captured["build_args"] = {
                "domain": domain,
                "subdomain": subdomain,
                "recent_days": recent_days,
            }
            return MemoryContext(
                same_subdomain_recent=[{"content_id": "wellness-sleep-1"}],
                same_domain_patterns=[{"performance_signal": "high"}],
                global_format_patterns=[{"title": "format"}],
                topics_to_avoid=["睡前仪式"],
                angles_to_avoid=["上班族快速放松"],
                recent_hashtags=["#睡眠改善"],
            )

    monkeypatch.setattr("src.nodes.node_a_01_retrieve_memory.XHSMemoryManager", FakeManager)

    result = retrieve_memory_node({"domain_context": {"domain": "wellness", "subdomain": "sleep"}})

    assert captured == {
        "db_path": "data/xhs_memory.db",
        "schema_path": "memory/schema.sql",
        "build_args": {
            "domain": "wellness",
            "subdomain": "sleep",
            "recent_days": 14,
        },
        "call_order": ["init_db", "ensure_vector_scope_backfill", "build_memory_context"],
    }
    assert result["memory_context"]["same_subdomain_recent"] == [{"content_id": "wellness-sleep-1"}]


def test_get_memory_matches_passes_exact_domain_scope(monkeypatch):
    captured = {}

    class FakeVectorMemory:
        def __init__(self, persist_dir):
            captured["persist_dir"] = persist_dir

        def query_similar(self, **kwargs):
            captured["query_args"] = kwargs
            return [
                {
                    "content_id": "content-1",
                    "similarity": 0.8,
                    "metadata": {
                        "topic": "睡前仪式",
                        "angle": "上班族快速放松",
                        "title": "10分钟睡前放松流程",
                        "created_at": "2026-07-03T10:00:00+08:00",
                        "published_at": "2026-07-03T11:00:00+08:00",
                        "performance_level": "high",
                    },
                }
            ]

    monkeypatch.setattr("src.nodes.node_b_novelty_guard.XHSVectorMemory", FakeVectorMemory)
    monkeypatch.setattr("src.nodes.node_b_novelty_guard.build_embedding_text", lambda **kwargs: "semantic query")

    angle_options = [
        AngleStrategy(
            topic_id="tp_001",
            topic="睡前仪式",
            target_group="上班族",
            core_pain="入睡慢",
            angles=[
                ContentAngle(
                    angle_id="ag_001",
                    angle="上班族快速放松",
                    opening_hook="hook",
                    value_promise="promise",
                    suggested_structure="structure",
                    narrative_plan=narrative_plan(),
                ),
                ContentAngle(
                    angle_id="ag_002",
                    angle="睡前整理大脑",
                    opening_hook="hook",
                    value_promise="promise",
                    suggested_structure="structure",
                    narrative_plan=narrative_plan("cognitive_correction"),
                ),
                ContentAngle(
                    angle_id="ag_003",
                    angle="减少夜间清醒",
                    opening_hook="hook",
                    value_promise="promise",
                    suggested_structure="structure",
                    narrative_plan=narrative_plan(),
                ),
            ],
        )
    ]
    domain_context = DomainContext(
        domain="wellness",
        subdomain="sleep",
        classification_source="explicit",
        classification_confidence=1.0,
        profile_version="wellness-v1",
        risk_level="low",
    )

    get_memory_matches(angle_options, domain_context)

    assert captured["persist_dir"] == "data/chroma"
    assert captured["query_args"] == {
        "query_text": "semantic query",
        "n_results": 3,
        "domain": "wellness",
        "subdomain": "sleep",
    }


def test_novelty_guard_rejects_model_rewritten_narrative_plan(monkeypatch):
    from src.nodes import node_b_novelty_guard as module

    authoritative_plan = narrative_plan()
    rewritten_plan = narrative_plan("cognitive_correction")
    angles = AngleStrategy(
        topic_id="tp_001",
        topic="睡前仪式",
        target_group="上班族",
        core_pain="入睡慢",
        angles=[
            ContentAngle(
                angle_id=f"ag_{index:03d}",
                angle=f"角度 {index}",
                opening_hook="hook",
                value_promise="promise",
                suggested_structure="structure",
                narrative_plan=(
                    authoritative_plan
                    if index == 1
                    else narrative_plan("cognitive_correction")
                ),
            )
            for index in range(1, 4)
        ],
    )

    class FakeVectorMemory:
        def __init__(self, _persist_dir):
            pass

        def query_similar(self, **_kwargs):
            return []

    class FakeModel:
        def execute(self, _messages):
            return {
                "novelty_results": [
                    {
                        "topic_id": "tp_001",
                        "topic": "睡前仪式",
                        "target_group": "上班族",
                        "core_pain": "入睡慢",
                        "angle_id": "ag_001",
                        "angle": "角度 1",
                        "opening_hook": "hook",
                        "value_promise": "promise",
                        "suggested_structure": "structure",
                        "narrative_plan": rewritten_plan.model_dump(mode="json"),
                        "decision": "keep",
                        "novelty_score": 0.9,
                        "max_similarity": 0.0,
                        "matched_history": [],
                        "reason": "足够新颖",
                        "revision_suggestions": [],
                        "memory_signal": {
                            "decision": "keep",
                            "novelty_score": 0.9,
                            "max_similarity": 0.0,
                            "rejected_by_memory": False,
                            "similar_to_recent_content": False,
                            "similar_to_high_performing_pattern": False,
                            "similar_to_low_performing_pattern": False,
                            "recommended_for_virality_scorer": True,
                        },
                    }
                ]
            }

    monkeypatch.setattr(module, "XHSVectorMemory", FakeVectorMemory)
    monkeypatch.setattr(module, "get_model", lambda: FakeModel())

    with pytest.raises(ValueError, match="must preserve the selected narrative_plan"):
        module.novelty_guard_node(
            {
                "angles": [angles],
                "domain_context": DomainContext(
                    domain="wellness",
                    subdomain="sleep",
                    classification_source="explicit",
                    classification_confidence=1.0,
                    profile_version="wellness-v1",
                    risk_level="low",
                ),
                "content_policy": {},
            }
        )


def test_novelty_guard_node_requires_domain_context_before_vector_query(monkeypatch):
    called = {"query": False}

    class FailIfConstructed:
        def __init__(self, *_args, **_kwargs):
            called["query"] = True
            raise AssertionError("vector memory should not be created")

    monkeypatch.setattr("src.nodes.node_b_novelty_guard.XHSVectorMemory", FailIfConstructed)

    with pytest.raises(ValueError, match="novelty_guard_node requires state.domain_context with domain and subdomain"):
        novelty_guard_node({"angles": []})

    assert called["query"] is False
