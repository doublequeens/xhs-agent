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
    assert "text_card_renderer" in graph_view.nodes
    assert "render_qa" in graph_view.nodes
    assert any(
        edge.source == "storyboard_generator" and edge.target == "carousel_qa"
        for edge in graph_view.edges
    )
    assert any(
        edge.source == "text_card_renderer" and edge.target == "render_qa"
        for edge in graph_view.edges
    )
    assert not any(
        edge.source == "carousel_qa" and edge.target == "human_review"
        for edge in graph_view.edges
    )


def test_graph_no_longer_routes_through_trend_scout():
    graph = create_graph(checkpointer=InMemorySaver())
    nodes = set(graph.get_graph().nodes)

    assert "trend_scout" not in nodes
