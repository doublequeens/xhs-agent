from langgraph.checkpoint.memory import InMemorySaver

from src.graph import create_graph


def _edges_by_source(graph) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = {}
    for edge in graph.get_graph().edges:
        adjacency.setdefault(edge.source, set()).add(edge.target)
    return adjacency


def test_graph_dynamic_visual_production_chain_is_exact_topology():
    graph = create_graph(checkpointer=InMemorySaver())
    graph_view = graph.get_graph()
    nodes = set(graph_view.nodes)
    edges = _edges_by_source(graph)

    # The four retired visual nodes must be absent by name.
    assert "visual_strategy_planner" not in nodes
    assert "storyboard_generator" not in nodes
    assert "carousel_qa" not in nodes
    assert "editorial_carousel_renderer" not in nodes
    assert "text_card_renderer" not in nodes

    # The new dynamic-visual nodes are registered.
    for required in (
        "content_atomizer",
        "visual_director",
        "asset_resolver",
        "page_designer",
        "design_plan_qa",
        "design_reviser",
        "generic_scene_renderer",
        "render_qa",
        "visual_critic",
    ):
        assert required in nodes, f"missing new visual node: {required}"

    # Retained downstream gates/writers are still present.
    for retained in (
        "assembler",
        "human_review",
        "final_policy_guard",
        "content_writer",
    ):
        assert retained in nodes

    # The exact linear chain assembler -> ... -> content_writer.
    assert edges["assembler"] == {"content_atomizer"}
    assert edges["content_atomizer"] == {"visual_director", "r2_compliance"}
    assert edges["visual_director"] == {"asset_resolver"}
    assert edges["asset_resolver"] == {"page_designer"}
    assert edges["page_designer"] == {"design_plan_qa"}
    assert edges["design_plan_qa"] == {"generic_scene_renderer", "design_reviser"}
    assert edges["generic_scene_renderer"] == {"render_qa"}
    assert edges["render_qa"] == {"visual_critic", "design_reviser"}
    assert edges["visual_critic"] == {"human_review", "design_reviser"}
    assert edges["human_review"] == {
        "design_reviser",
        "asset_resolver",
        "r2_compliance",
        "final_policy_guard",
    }
    assert edges["final_policy_guard"] == {"human_review", "content_writer"}
    assert "content_writer" in edges and edges["content_writer"]  # -> END


def test_graph_design_reviser_routes_to_design_plan_qa_or_visual_director():
    graph = create_graph(checkpointer=InMemorySaver())
    edges = _edges_by_source(graph)

    # design_reviser loops back to design_plan_qa on a normal revision, or
    # escalates to visual_director only for family/page-sequence replanning.
    assert edges["design_reviser"] == {"design_plan_qa", "visual_director"}


def test_graph_hashtag_routes_to_assembler_and_assembler_enters_atomizer():
    graph = create_graph(checkpointer=InMemorySaver())
    edges = _edges_by_source(graph)

    assert edges["hashtag"] == {"assembler"}
    # No edge may bypass the atomizer back into a retired visual node.
    assert "visual_strategy_planner" not in edges.get("assembler", set())
    assert "storyboard_generator" not in edges.get("assembler", set())


def test_graph_no_longer_routes_through_trend_scout():
    graph = create_graph(checkpointer=InMemorySaver())
    nodes = set(graph.get_graph().nodes)

    assert "trend_scout" not in nodes


def test_graph_contains_signal_driven_topic_nodes():
    graph = create_graph(checkpointer=InMemorySaver())
    nodes = set(graph.get_graph().nodes)

    assert "topic_signal_collector" in nodes
    assert "creative_brief_builder" in nodes
    assert "topic_ideator" in nodes
    assert "topic_diversity_filter" in nodes


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
