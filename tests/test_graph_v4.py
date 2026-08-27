"""Topology and frozen-signature tests for the v4 LangGraph wiring."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src.graph import create_graph

SIGNATURE_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "graph" / "v3-signature.json"


def graph_signature(graph) -> dict:
    model = graph.get_graph()
    return {
        "nodes": sorted(model.nodes),
        "edges": sorted(
            f"{edge.source}->{edge.target}{'?' if edge.conditional else ''}"
            for edge in model.edges
        ),
    }


def test_extracting_common_graph_keeps_v3_node_and_edge_snapshot():
    """graph_common extraction must not deform the frozen v3 topology."""

    signature = graph_signature(create_graph(checkpointer=InMemorySaver()))
    frozen = json.loads(SIGNATURE_PATH.read_text(encoding="utf-8"))
    assert signature == frozen


def test_v4_visual_topology_has_no_page_designer_or_design_reviser():
    from src.graph_v4 import create_graph_v4

    graph = create_graph_v4(checkpointer=InMemorySaver())
    nodes = set(graph.get_graph().nodes)
    assert {
        "semantic_modeling",
        "visual_authoring",
        "composition_planning",
        "layout_compiler",
        "asset_resolver",
        "design_plan_qa",
        "render_qa",
        "visual_critic",
        "human_review",
        "final_policy_guard",
        "revision",
        "review_workspace_builder",
    } <= nodes
    # The retired v3 repair nodes must not exist in the v4 graph; typed v4
    # revision routing owns repair re-entry.
    assert {"page_designer", "design_reviser", "visual_director"} .isdisjoint(nodes)
    # Both terminal writers exist; routing selects by run mode.
    assert {"content_writer", "shadow_artifact_writer"} <= nodes


def test_v4_graph_keeps_every_shared_content_chain_node():
    from src.graph_v4 import create_graph_v4

    v3_nodes = set(
        json.loads(SIGNATURE_PATH.read_text(encoding="utf-8"))["nodes"]
    )
    # Everything before assembler in v3 is shared verbatim by v4.
    shared = v3_nodes - {
        "content_atomizer", "visual_director", "asset_resolver", "page_designer",
        "design_plan_qa", "design_reviser", "generic_scene_renderer",
        "render_qa", "visual_critic", "human_review", "final_policy_guard",
        "content_writer", "__end__",
    }
    v4_nodes = set(create_graph_v4(checkpointer=InMemorySaver()).get_graph().nodes)
    assert shared <= v4_nodes
    # The shared chain terminates into the v4 visual entry, not v3's.
    v4_edges = {
        f"{edge.source}->{edge.target}"
        for edge in create_graph_v4(checkpointer=InMemorySaver()).get_graph().edges
    }
    assert "assembler->content_atomizer" in v4_edges


def test_v4_visual_routing_is_not_shared_with_v3():
    """No v3 visual-route function may steer the v4 graph."""

    import inspect

    import src.graph_v4 as graph_v4

    source = inspect.getsource(graph_v4)
    for banned in (
        "route_after_design_plan_qa",
        "_route_after_visual_critic",
        "route_after_design_reviser",
        "route_after_human_review,",  # v3 human-review router import
    ):
        assert banned not in source, banned


def test_composition_planning_node_selects_programs_and_fails_closed(tmp_path):
    from src.nodes.v4.composition import composition_planning_node
    from tests.review.test_v4_workspace import _inputs

    inputs = _inputs(tmp_path, run_id="thread-1")
    state = {
        "visual_direction_plan": inputs.visual_direction_plan,
        "page_brief_set": inputs.page_brief_set,
    }
    patch = composition_planning_node(state)
    assert len(patch["layout_programs"]) == len(inputs.page_brief_set.pages)
    assert patch["family_tokens"].family == inputs.visual_direction_plan.template_family
    assert patch["route"] == "layout_compiler"
    import pytest as _pytest

    with _pytest.raises(ValueError):
        composition_planning_node({"page_brief_set": inputs.page_brief_set})


def test_extract_v3_assembler_copy_validates_profile_and_missing_copy(monkeypatch):
    import main as main_module

    class _State:
        def __init__(self, values):
            self.values = values

    class _Graph:
        def __init__(self, values):
            self._values = values

        def get_state(self, config):
            assert config["configurable"]["thread_id"] == "src"
            return _State(self._values)

    valid = {
        "title": "标题",
        "content": "正文",
        "hashtags": [],
        "focus_keyword": "kw",
        "topic": "t",
        "angle": "a",
        "cover_copy": "c",
        "domain": "beauty",
        "profile_version": "beauty-v1",
    }
    monkeypatch.setattr(main_module, "_create_v3_graph", lambda: _Graph({"publish_package": valid}))
    extracted = main_module._extract_v3_assembler_copy("src")
    assert extracted == valid
    monkeypatch.setattr(
        main_module, "_create_v3_graph", lambda: _Graph({"publish_package": {"title": "无元数据"}})
    )
    import pytest as _pytest

    with _pytest.raises(Exception):
        main_module._extract_v3_assembler_copy("src")
    monkeypatch.setattr(main_module, "_create_v3_graph", lambda: _Graph({}))
    assert main_module._extract_v3_assembler_copy("src") is None
    monkeypatch.setattr(
        main_module,
        "_create_v3_graph",
        lambda: _Graph({"publish_package": {}}),
    )
    assert main_module._extract_v3_assembler_copy("src") is None
