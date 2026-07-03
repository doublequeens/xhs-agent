import importlib
import sqlite3
from types import SimpleNamespace

import pytest

from memory.models import MemoryContext
from src.domain import build_content_policy, get_domain_profile
from src.domain.router import resolve_domain
from src.nodes.node_a_00_domain_confirmation import domain_confirmation_node
from src.nodes.node_a_01_retrieve_memory import retrieve_memory_node
from src.nodes.node_a_00_domain_router import domain_router_node


def test_domain_router_node_returns_context_and_policy():
    result = domain_router_node({"domain": None, "focus_keyword": "久坐办公怎么活动"})

    assert result["domain_context"].domain == "healthy_lifestyle"
    assert result["domain_context"].subdomain == "sedentary_habits"
    assert result["content_policy"].require_evidence_brief is True
    assert result["content_policy"].risk_level == result["domain_context"].risk_level


def test_domain_confirmation_node_skips_interrupt_for_high_confidence(monkeypatch):
    context = resolve_domain(domain="beauty", focus_keyword="改善睡眠")

    def fail_interrupt(_payload):
        raise AssertionError("interrupt should not be called")

    monkeypatch.setattr("src.nodes.node_a_00_domain_confirmation.interrupt", fail_interrupt)

    assert domain_confirmation_node({"domain_context": context}) == {}


def test_domain_confirmation_node_interrupts_and_accepts_resume(monkeypatch):
    context = resolve_domain(domain=None, focus_keyword="完全无关的关键词")
    captured = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return {"domain": "wellness", "subdomain": "sleep"}

    monkeypatch.setattr("src.nodes.node_a_00_domain_confirmation.interrupt", fake_interrupt)

    result = domain_confirmation_node({"domain_context": context})

    assert captured["payload"]["kind"] == "domain_confirmation"
    assert "message" in captured["payload"]
    assert result["domain_context"].domain == "wellness"
    assert result["domain_context"].subdomain == "sleep"
    assert result["domain_context"].classification_source == "explicit"
    assert result["domain_context"].classification_confidence == 1
    assert result["domain_context"].profile_version == "wellness-v1"
    assert result["content_policy"] == build_content_policy(get_domain_profile("wellness"))


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
        result = module.human_review_node({"publish_package": {"title": "x"}, "review_round": 0})
    finally:
        module.interrupt = original

    assert captured["payload"]["kind"] == "publish_review"
    assert result["review_status"] == "approved"


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
            trend_scout_node=fake_node,
            angle_strategist_node=fake_node,
            novelty_guard_node=fake_node,
            virality_scorer_node=fake_node,
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
            content_writer_node=fake_node,
            storyboards_generator_node=fake_node,
        ),
    )

    graph_module.create_graph(checkpointer=object())

    assert "domain_router" in added_nodes
    assert "domain_confirmation" in added_nodes
    assert ("domain_router", "domain_confirmation") in added_edges
    assert ("domain_confirmation", "memory_retriever") in added_edges
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
            trend_scout_node=fake_node,
            angle_strategist_node=fake_node,
            novelty_guard_node=fake_node,
            virality_scorer_node=fake_node,
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
            content_writer_node=fake_node,
            storyboards_generator_node=fake_node,
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
    captured = {}

    class FakeManager:
        def __init__(self, db_path):
            captured["db_path"] = db_path

        def init_db(self, schema_path):
            captured["schema_path"] = schema_path

        def build_memory_context(self, *, domain, subdomain, recent_days):
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
    }
    assert result["memory_context"]["same_subdomain_recent"] == [{"content_id": "wellness-sleep-1"}]
