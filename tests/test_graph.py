from langgraph.checkpoint.memory import InMemorySaver

from src.graph import create_graph


def test_graph_contains_signal_driven_topic_nodes():
    graph = create_graph(checkpointer=InMemorySaver())
    nodes = set(graph.get_graph().nodes)

    assert "topic_signal_collector" in nodes
    assert "creative_brief_builder" in nodes
    assert "topic_ideator" in nodes
    assert "topic_diversity_filter" in nodes


def test_graph_routes_storyboards_through_render_qa_before_human_review():
    graph = create_graph(checkpointer=InMemorySaver())
    graph_view = graph.get_graph()

    assert "carousel_qa" in graph_view.nodes
    assert "visual_strategy_planner" in graph_view.nodes
    assert "asset_resolver" in graph_view.nodes
    assert "editorial_carousel_renderer" in graph_view.nodes
    assert "render_qa" in graph_view.nodes
    assert any(
        edge.source == "assembler" and edge.target == "visual_strategy_planner"
        for edge in graph_view.edges
    )
    assert any(
        edge.source == "editorial_carousel_renderer" and edge.target == "render_qa"
        for edge in graph_view.edges
    )
    assert not any(
        edge.source == "carousel_qa" and edge.target == "human_review"
        for edge in graph_view.edges
    )


def test_graph_places_asset_resolution_before_carousel_render():
    graph = create_graph(checkpointer=InMemorySaver())
    edges: dict[str, set[str]] = {}
    for edge in graph.get_graph().edges:
        edges.setdefault(edge.source, set()).add(edge.target)

    assert edges["assembler"] == {"visual_strategy_planner"}
    assert edges["visual_strategy_planner"] == {"storyboard_generator"}
    assert edges["storyboard_generator"] == {"asset_resolver", "carousel_qa"}
    assert edges["asset_resolver"] == {"carousel_qa"}
    assert edges["carousel_qa"] == {
        "editorial_carousel_renderer",
        "r1_reflector",
    }


def test_graph_no_longer_routes_through_trend_scout():
    graph = create_graph(checkpointer=InMemorySaver())
    nodes = set(graph.get_graph().nodes)

    assert "trend_scout" not in nodes
