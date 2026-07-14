import importlib
import sqlite3
from types import SimpleNamespace

import pytest

from memory.models import MemoryContext
from src.domain.models import DomainContext
from src.schemas.angle import AngleStrategy, ContentAngle
from src.domain import build_content_policy, get_domain_profile
from src.domain.router import resolve_domain
from src.nodes.node_a_00_domain_confirmation import domain_confirmation_node
from src.nodes.node_a_01_retrieve_memory import retrieve_memory_node
from src.nodes.node_b_novelty_guard import get_memory_matches, novelty_guard_node
from src.nodes.node_a_00_domain_router import domain_router_node


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


def test_human_review_exposes_images_contact_sheet_qa_proxy_and_pending_assets(
    monkeypatch,
):
    module = importlib.import_module("src.nodes.node_q_human_review")
    captured = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return {
            "approved": False,
            "asset_decisions": {"pending-1": "rejected"},
            "feedback": "reject candidate",
        }

    replacement_manifest = {"items": [{"status": "fallback", "slot_id": "slot-1"}]}
    monkeypatch.setattr(module, "interrupt", fake_interrupt)
    monkeypatch.setattr(
        module,
        "_apply_asset_decisions",
        lambda _state, _manifest, decisions, _feedback: (
            replacement_manifest,
            "editorial_carousel_renderer",
        ),
    )

    result = module.human_review_node(
        {
            "publish_package": {"title": "x", "rendered_image_paths": ["01-cover.png"]},
            "visual_plan": {"design_system": "beauty_editorial_v1"},
            "asset_manifest": {
                "items": [
                    {
                        "status": "pending_external",
                        "pending_id": "pending-1",
                        "provider": "pexels",
                        "provider_asset_id": "42",
                        "unresolved_safety_checks": ["allowed_for_publishing"],
                    }
                ]
            },
            "render_manifest": {
                "pages": [{"path": "01-cover.png"}],
                "contact_sheet_path": "contact-sheet.png",
            },
            "carousel_qa_result": {"passed": True, "issues": []},
            "render_qa_result": {
                "passed": True,
                "issues": [],
                "metric_kind": "deterministic_proxy",
                "metric_note": "measured proxy; human review still required",
            },
            "review_round": 0,
            "final_policy_issues": [],
        }
    )

    payload = captured["payload"]
    assert payload["images"] == ["01-cover.png"]
    assert payload["render_manifest"]["contact_sheet_path"] == "contact-sheet.png"
    assert payload["asset_manifest"]["items"]
    assert payload["carousel_qa_result"]["passed"] is True
    assert payload["render_qa_result"]["passed"] is True
    assert payload["proxy_metric_label"] == "deterministic_proxy"
    assert payload["pending_assets"][0]["decision_id"] == "pending-1"
    assert result["asset_manifest"] == replacement_manifest
    assert result["review_route"] == "editorial_carousel_renderer"
    assert result["review_status"] == "pending"


def test_asset_approval_promotes_pending_and_rechecks_render_qa(monkeypatch):
    module = importlib.import_module("src.nodes.node_q_human_review")
    pending_item = SimpleNamespace(
        status="pending_external",
        pending_id="run-42-slot-pexels-1",
        asset_id=None,
        provider="pexels",
        provider_asset_id="1",
        run_id="run-42",
        metadata_path="/tmp/pending-1.json",
    )
    catalogs = iter(["review-catalog", "refreshed-catalog"])
    calls = []
    monkeypatch.setattr(
        module,
        "AssetManifest",
        SimpleNamespace(
            model_validate=lambda _value: SimpleNamespace(items=[pending_item])
        ),
    )
    monkeypatch.setattr(
        module,
        "load_asset_catalog_for_state",
        lambda _state, **kwargs: calls.append(("catalog", kwargs))
        or next(catalogs),
    )
    monkeypatch.setattr(
        module,
        "review_pending_asset_batch",
        lambda catalog, items, decisions, **kwargs: calls.append(
            ("batch", catalog, items, decisions, kwargs["rejection_reason"])
        )
        or SimpleNamespace(
            any_rejected=False,
            finalized_value=kwargs["finalize"](),
        ),
    )
    monkeypatch.setattr(
        module.VisualPlan,
        "model_validate",
        lambda value: calls.append(("plan", value)) or "validated-plan",
    )
    monkeypatch.setattr(
        module,
        "resolve_assets",
        lambda plan, catalog: calls.append(("resolve", plan, catalog))
        or "approved-manifest",
    )
    state = {"visual_plan": {"frame_plan": []}}

    manifest, route = module._apply_asset_decisions(
        state,
        {"items": []},
        {pending_item.pending_id: {"decision": "approved"}},
        None,
    )

    assert manifest == "approved-manifest"
    assert route == "render_qa"
    assert any(call[0] == "batch" for call in calls)
    assert [call for call in calls if call[0] == "catalog"] == [
        ("catalog", {"run_id": "run-42", "allow_external": False}),
        ("catalog", {"run_id": "run-42", "allow_external": False}),
    ]


def test_human_focus_keyword_edit_invalidates_downstream_artifacts_and_reruns_r2(
    monkeypatch,
):
    module = importlib.import_module("src.nodes.node_q_human_review")
    package = {
        "focus_keyword": "防晒搓泥",
        "focus_keyword_cli_present": True,
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
        "storyboards": [],
        "content_contract": {
            "audience": "通勤人群",
            "trigger_situation": "早晨上班前",
            "decision_problem": "如何避免搓泥",
            "first_screen_promise": "三步避免搓泥",
            "screenshot_asset": "步骤清单",
            "proof_asset": "质地图",
            "visual_mode": "text_card",
            "content_job": "diagnose_and_adjust",
            "primary_visual_family": "beauty_editorial",
            "primary_visual_subject": "serum_texture",
            "proof_mode": "product_texture",
            "recommended_frame_count": 5,
        },
    }
    monkeypatch.setattr(
        module,
        "interrupt",
        lambda _payload: {
            "approved": True,
            "edited_publish_package": {"focus_keyword": "人工换词"},
            "feedback": "change keyword",
        },
    )

    result = module.human_review_node(
        {
            "focus_keyword": "防晒搓泥",
            "focus_keyword_cli_present": True,
            "publish_package": package,
            "asset_manifest": {"items": []},
            "visual_plan": {"frame_plan": []},
            "render_manifest": {"pages": []},
            "carousel_qa_result": {"passed": True, "issues": []},
            "render_qa_result": {"passed": True, "issues": []},
            "review_round": 0,
            "final_policy_issues": [],
        }
    )

    assert result["review_status"] == "needs_r2_recheck"
    assert result["review_route"] == "r2_compliance"
    assert result["visual_plan"] is None
    assert result["render_manifest"] is None


def test_asset_rejection_reresolves_without_external_provider_calls(monkeypatch):
    module = importlib.import_module("src.nodes.node_q_human_review")
    pending_item = SimpleNamespace(
        status="pending_external",
        pending_id="run-42-slot-pexels-1",
        asset_id=None,
        provider="pexels",
        provider_asset_id="1",
        run_id="run-42",
        metadata_path="/tmp/pending-1.json",
    )
    catalogs = iter(["review-catalog", "no-provider-catalog"])
    calls = []
    monkeypatch.setattr(
        module,
        "AssetManifest",
        SimpleNamespace(
            model_validate=lambda _value: SimpleNamespace(items=[pending_item])
        ),
    )
    monkeypatch.setattr(
        module,
        "load_asset_catalog_for_state",
        lambda _state, **kwargs: calls.append(("catalog", kwargs))
        or next(catalogs),
    )
    monkeypatch.setattr(
        module,
        "review_pending_asset_batch",
        lambda catalog, items, decisions, **kwargs: calls.append(
            ("batch", catalog, items, decisions, kwargs["rejection_reason"])
        )
        or SimpleNamespace(
            any_rejected=True,
            finalized_value=kwargs["finalize"](),
        ),
    )
    monkeypatch.setattr(module.VisualPlan, "model_validate", lambda _value: "plan")
    monkeypatch.setattr(
        module,
        "resolve_assets",
        lambda plan, catalog: calls.append(("resolve", plan, catalog))
        or "next-downloaded-or-fallback-manifest",
    )

    manifest, route = module._apply_asset_decisions(
        {"visual_plan": {"frame_plan": []}},
        {"items": []},
        {pending_item.pending_id: {"decision": "rejected"}},
        "visible logo",
    )

    assert manifest == "next-downloaded-or-fallback-manifest"
    assert route == "editorial_carousel_renderer"
    assert ("resolve", "plan", "no-provider-catalog") in calls
    assert [call for call in calls if call[0] == "catalog"] == [
        ("catalog", {"run_id": "run-42", "allow_external": False}),
        ("catalog", {"run_id": "run-42", "allow_external": False}),
    ]


def test_asset_resolver_node_is_a_thin_validating_adapter(monkeypatch):
    module = importlib.import_module("src.nodes.node_p_asset_resolver")
    calls = []
    monkeypatch.setattr(
        module.VisualPlan,
        "model_validate",
        lambda value: calls.append(("validate", value)) or "validated-plan",
    )
    monkeypatch.setattr(
        module,
        "load_asset_catalog_for_state",
        lambda state: calls.append(("catalog", state)) or "catalog",
    )
    monkeypatch.setattr(
        module,
        "resolve_assets",
        lambda plan, catalog: calls.append(("resolve", plan, catalog))
        or "manifest",
    )
    state = {"visual_plan": {"design_system": "beauty_editorial_v1"}}

    result = module.asset_resolver_node(state)

    assert result == {
        "asset_manifest": "manifest",
        "current_node": "ASSET_RESOLVER",
    }
    assert calls == [
        ("validate", state["visual_plan"]),
        ("catalog", state),
        ("resolve", "validated-plan", "catalog"),
    ]


def test_editorial_renderer_node_calls_deep_renderer_once_and_persists_page_paths(
    monkeypatch,
):
    module = importlib.import_module(
        "src.nodes.node_p_editorial_carousel_renderer"
    )
    calls = []
    monkeypatch.setattr(
        module.VisualPlan,
        "model_validate",
        lambda value: calls.append(("plan", value)) or "plan",
    )
    monkeypatch.setattr(
        module.CarouselPayload,
        "model_validate",
        lambda value: calls.append(("storyboard", value)) or "storyboard",
    )
    monkeypatch.setattr(
        module.AssetManifest,
        "model_validate",
        lambda value: calls.append(("assets", value)) or "assets",
    )
    monkeypatch.setattr(
        module,
        "render_output_directory",
        lambda package: calls.append(("output", package)) or "output-dir",
    )
    rendered = SimpleNamespace(
        pages=[SimpleNamespace(path="01-cover.png"), SimpleNamespace(path="02-save.png")]
    )
    monkeypatch.setattr(
        module,
        "render_carousel",
        lambda plan, storyboard, assets, output: calls.append(
            ("render", plan, storyboard, assets, output)
        )
        or rendered,
    )
    state = {
        "visual_plan": {"frame_plan": []},
        "asset_manifest": {"items": []},
        "publish_package": {"title": "carousel", "storyboards": []},
    }

    result = module.editorial_carousel_renderer_node(state)

    assert result["render_manifest"] is rendered
    assert result["publish_package"]["rendered_image_paths"] == [
        "01-cover.png",
        "02-save.png",
    ]
    assert [call[0] for call in calls] == [
        "plan",
        "storyboard",
        "assets",
        "output",
        "render",
    ]


def test_graph_builder_wires_domain_nodes(monkeypatch):
    graph_module = importlib.import_module("src.graph")
    added_nodes = []
    added_edges = []
    entry_points = []
    fake_node = object()

    class FakeBuilder:
        def __init__(self, state_type):
            self.state_type = state_type

        def add_node(self, name, node):
            added_nodes.append(name)

        def add_edge(self, source, target):
            added_edges.append((source, target))

        def add_conditional_edges(self, source, fn, mapping):
            added_edges.append((source, tuple(sorted(mapping.items()))))

        def set_entry_point(self, name):
            entry_points.append(name)

        def compile(self, checkpointer=None):
            return SimpleNamespace(checkpointer=checkpointer)

    monkeypatch.setattr(graph_module, "StateGraph", FakeBuilder)
    monkeypatch.setattr(
        graph_module,
        "nodes",
        SimpleNamespace(
            domain_router_node=fake_node,
            domain_confirmation_node=fake_node,
            retrieve_memory_node=fake_node,
            topic_signal_collector_node=fake_node,
            creative_brief_builder_node=fake_node,
            topic_ideator_node=fake_node,
            topic_diversity_filter_node=fake_node,
            angle_strategist_node=fake_node,
            novelty_guard_node=fake_node,
            virality_scorer_node=fake_node,
            evidence_brief_node=fake_node,
            outline_architect_node=fake_node,
            draft_writer_node=fake_node,
            title_lab_node=fake_node,
            title_ranker_node=fake_node,
            decision_engine_node=fake_node,
            r1_reflector_node=fake_node,
            r2_compliance_node=fake_node,
            hashtag_node=fake_node,
            assembler_node=fake_node,
            human_review_node=fake_node,
            final_policy_guard_node=fake_node,
            content_writer_node=fake_node,
            storyboards_generator_node=fake_node,
            visual_strategy_planner_node=fake_node,
            asset_resolver_node=fake_node,
            carousel_qa_node=fake_node,
            editorial_carousel_renderer_node=fake_node,
            text_card_renderer_node=fake_node,
            render_qa_node=fake_node,
        ),
    )

    graph_module.create_graph(checkpointer=object())

    assert "domain_router" in added_nodes
    assert "domain_confirmation" in added_nodes
    assert "evidence_brief" in added_nodes
    assert ("domain_router", "domain_confirmation") in added_edges
    assert ("domain_confirmation", "memory_retriever") in added_edges
    assert ("virality_score", "evidence_brief") in added_edges
    assert ("evidence_brief", "outline_architect") in added_edges
    assert ("virality_score", "outline_architect") not in added_edges
    assert ("assembler", "visual_strategy_planner") in added_edges
    assert ("visual_strategy_planner", "storyboard_generator") in added_edges
    assert (
        "storyboard_generator",
        (
            ("asset_resolver", "asset_resolver"),
            ("carousel_qa", "carousel_qa"),
        ),
    ) in added_edges
    assert ("asset_resolver", "carousel_qa") in added_edges
    assert ("storyboard_generator", "human_review") not in added_edges
    assert (
        "carousel_qa",
        (
            ("editorial_carousel_renderer", "editorial_carousel_renderer"),
            ("r1_reflector", "r1_reflector"),
        ),
    ) in added_edges
    assert ("editorial_carousel_renderer", "render_qa") in added_edges
    assert (
        "render_qa",
        (("human_review", "human_review"), ("r1_reflector", "r1_reflector")),
    ) in added_edges
    assert ("human_review", "final_policy_guard") not in added_edges
    assert (
        "human_review",
        (
            ("editorial_carousel_renderer", "editorial_carousel_renderer"),
            ("final_policy_guard", "final_policy_guard"),
            ("r2_compliance", "r2_compliance"),
            ("render_qa", "render_qa"),
        ),
    ) in added_edges
    assert (
        "final_policy_guard",
        (("content_writer", "content_writer"), ("human_review", "human_review")),
    ) in added_edges
    assert entry_points == ["domain_router"]


def test_create_graph_uses_cached_real_sqlite_checkpointer(tmp_path, monkeypatch):
    graph_module = importlib.import_module("src.graph")
    checkpoint_path = tmp_path / "checkpoints.sqlite"
    compiled_checkpointers = []
    fake_node = object()

    class FakeBuilder:
        def __init__(self, _state_type):
            pass

        def add_node(self, _name, _node):
            pass

        def add_edge(self, _source, _target):
            pass

        def add_conditional_edges(self, _source, _fn, _mapping):
            pass

        def set_entry_point(self, _name):
            pass

        def compile(self, checkpointer=None):
            compiled_checkpointers.append(checkpointer)
            return SimpleNamespace(checkpointer=checkpointer)

    monkeypatch.setattr(graph_module, "StateGraph", FakeBuilder)
    monkeypatch.setattr(
        graph_module,
        "nodes",
        SimpleNamespace(
            domain_router_node=fake_node,
            domain_confirmation_node=fake_node,
            retrieve_memory_node=fake_node,
            topic_signal_collector_node=fake_node,
            creative_brief_builder_node=fake_node,
            topic_ideator_node=fake_node,
            topic_diversity_filter_node=fake_node,
            angle_strategist_node=fake_node,
            novelty_guard_node=fake_node,
            virality_scorer_node=fake_node,
            evidence_brief_node=fake_node,
            outline_architect_node=fake_node,
            draft_writer_node=fake_node,
            title_lab_node=fake_node,
            title_ranker_node=fake_node,
            decision_engine_node=fake_node,
            r1_reflector_node=fake_node,
            r2_compliance_node=fake_node,
            hashtag_node=fake_node,
            assembler_node=fake_node,
            human_review_node=fake_node,
            final_policy_guard_node=fake_node,
            content_writer_node=fake_node,
            storyboards_generator_node=fake_node,
            visual_strategy_planner_node=fake_node,
            asset_resolver_node=fake_node,
            carousel_qa_node=fake_node,
            editorial_carousel_renderer_node=fake_node,
            text_card_renderer_node=fake_node,
            render_qa_node=fake_node,
        ),
    )

    try:
        first = graph_module.create_graph(checkpoint_path=checkpoint_path)
        second = graph_module.create_graph(checkpoint_path=checkpoint_path)

        assert checkpoint_path.exists()
        assert first.checkpointer is second.checkpointer
        assert compiled_checkpointers == [first.checkpointer, second.checkpointer]
        first.checkpointer.conn.execute("SELECT 1")
    finally:
        graph_module.close_checkpointers(checkpoint_path)

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        first.checkpointer.conn.execute("SELECT 1")


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
                ),
                ContentAngle(
                    angle_id="ag_002",
                    angle="睡前整理大脑",
                    opening_hook="hook",
                    value_promise="promise",
                    suggested_structure="structure",
                ),
                ContentAngle(
                    angle_id="ag_003",
                    angle="减少夜间清醒",
                    opening_hook="hook",
                    value_promise="promise",
                    suggested_structure="structure",
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
