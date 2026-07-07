from langgraph.checkpoint.memory import InMemorySaver

from src.graph import create_graph


def test_graph_contains_signal_driven_topic_nodes():
    graph = create_graph(checkpointer=InMemorySaver())
    nodes = set(graph.get_graph().nodes)

    assert "topic_signal_collector" in nodes
    assert "creative_brief_builder" in nodes
    assert "topic_ideator" in nodes
    assert "topic_diversity_filter" in nodes


def test_graph_no_longer_routes_through_trend_scout():
    graph = create_graph(checkpointer=InMemorySaver())
    nodes = set(graph.get_graph().nodes)

    assert "trend_scout" not in nodes
