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
    assert "text_card_renderer" not in graph_view.nodes
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
    assert edges["storyboard_generator"] == {"asset_resolver"}
    assert edges["asset_resolver"] == {"carousel_qa"}
    assert edges["carousel_qa"] == {
        "editorial_carousel_renderer",
        "r1_reflector",
    }


def test_graph_no_longer_routes_through_trend_scout():
    graph = create_graph(checkpointer=InMemorySaver())
    nodes = set(graph.get_graph().nodes)

    assert "trend_scout" not in nodes


def _count(conn, table, thread_id):
    return conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE thread_id = ?", (thread_id,)
    ).fetchone()[0]


def _seed_checkpoint_rows(path, thread_id):
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO checkpoints(thread_id, checkpoint_ns, checkpoint_id, checkpoint)"
        " VALUES (?, '', 'c1', x'00')",
        (thread_id,),
    )
    conn.execute(
        "INSERT INTO writes(thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel)"
        " VALUES (?, '', 'c1', 't1', 0, 'ch')",
        (thread_id,),
    )
    conn.commit()
    conn.close()


def test_delete_checkpoint_thread_removes_only_named_thread(tmp_path):
    from src.graph import close_checkpointers, delete_checkpoint_thread

    path = tmp_path / "checkpoints.sqlite"
    # ensure schema exists via the real checkpointer
    from src.graph import _create_checkpointer

    _create_checkpointer(path).setup()
    _seed_checkpoint_rows(path, "t1")
    _seed_checkpoint_rows(path, "t2")

    delete_checkpoint_thread("t1", path)

    import sqlite3

    conn = sqlite3.connect(path)
    try:
        assert _count(conn, "checkpoints", "t1") == 0
        assert _count(conn, "writes", "t1") == 0
        assert _count(conn, "checkpoints", "t2") == 1
    finally:
        conn.close()
        close_checkpointers(path)


def test_delete_all_checkpoints_wipes_every_thread(tmp_path):
    from src.graph import close_checkpointers, delete_all_checkpoints

    path = tmp_path / "checkpoints.sqlite"
    from src.graph import _create_checkpointer

    _create_checkpointer(path).setup()
    _seed_checkpoint_rows(path, "t1")
    _seed_checkpoint_rows(path, "t2")

    deleted = delete_all_checkpoints(path)

    import sqlite3

    conn = sqlite3.connect(path)
    try:
        assert deleted == 2  # two checkpoint rows seeded
        assert conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM writes").fetchone()[0] == 0
    finally:
        conn.close()
        close_checkpointers(path)
