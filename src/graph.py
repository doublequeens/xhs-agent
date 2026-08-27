import atexit
import os
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any, Literal, Mapping

from pydantic import BaseModel

from langgraph.graph import StateGraph, END
try:
    from langgraph.checkpoint.sqlite import SqliteSaver
except ModuleNotFoundError:  # pragma: no cover - exercised in tests via injection
    SqliteSaver = None

from src.checkpoint_serde import checkpoint_serializer, trusted_schema_classes

from src.schemas import AgentState
import src.nodes as nodes
from src.nodes.node_q_01_final_policy_guard import route_after_final_guard
from src.nodes.node_q_human_review import route_after_human_review
from src.nodes.node_p_design_plan_qa import route_after_design_plan_qa
from src.nodes.node_p_render_qa import route_after_render_qa
from src.nodes.node_p_visual_critic import route_after_visual_critic

from src.editorial_carousel.graph_common import add_content_chain
from src.editorial_carousel.graph_common import next_node  # noqa: F401 - shared-chain re-export

DEFAULT_CHECKPOINT_PATH = Path("checkpoints.sqlite")
_CHECKPOINTERS: dict[Path, tuple[sqlite3.Connection, object]] = {}
_CHECKPOINTER_LOCK = Lock()

# ---------------------------------------------------------------------------
# llm_scene_v3 dynamic visual production wiring helpers
# ---------------------------------------------------------------------------
#
# The structured-model visual nodes (visual_director, page_designer,
# design_reviser, visual_critic) require an injected ``StructuredVisualModel``.
# It is constructed lazily on first invocation so ``create_graph`` stays
# usable offline (topology/migration tests, no Gemini credentials required at
# build time). ``visual_route_override`` is the dedicated, always-cleared
# channel that carries the transient ``"route"`` override returned by
# ``design_reviser`` (family/page-sequence replan) and ``visual_critic``
# (render-QA hard-fail guard) so the downstream conditional edges never
# misroute on a stale value.

_VISUAL_MODEL: Any = None


def _get_visual_model() -> Any:
    """Return a process-wide structured visual model, built on first use."""

    global _VISUAL_MODEL
    if _VISUAL_MODEL is None:
        # Local import keeps the Gemini SDK out of the topology-test import
        # graph; the model is only built when a node actually runs.
        from src.visual_ai import get_structured_visual_model

        _VISUAL_MODEL = get_structured_visual_model()
    return _VISUAL_MODEL


def _structured_visual_node(node_fn):
    """Bind a structured-model visual node with lazy model construction."""

    def _action(state):
        return node_fn(state, model=_get_visual_model())

    return _action


def _structured_visual_node_with_route_override(node_fn):
    """Like ``_structured_visual_node`` but also normalizes a route override.

    ``design_reviser`` returns ``{"route": "visual_director"}`` ONLY on a
    family/page-sequence replan; otherwise it returns a revised
    ``CarouselDesignPlan``. ``visual_critic`` returns ``{"route":
    "design_reviser"}`` ONLY when render QA already failed (no critique is
    produced). LangGraph conditional edges read state, not the returned dict,
    so the override is surfaced through the dedicated
    ``visual_route_override`` channel. It is always written (``None`` clears
    any stale value) so a leftover override from a previous round can never
    misroute a later, normal revision.
    """

    def _action(state):
        result = node_fn(state, model=_get_visual_model())
        override = result.pop("route", None)
        result["visual_route_override"] = override
        return result

    return _action


def _asset_resolver_run_id(state: Mapping[str, Any]) -> str:
    trace = state.get("topic_generation_trace")
    run_id = getattr(trace, "run_id", None)
    if isinstance(run_id, str) and run_id:
        return run_id
    package = state.get("publish_package") or {}
    identity = "|".join(
        str(package.get(name) or "")
        for name in ("topic_id", "draft_id", "angle_id")
    )
    import hashlib

    return "editorial-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def _asset_resolver_node(node_fn):
    """Bind asset resolver providers/transaction identity lazily.

    The Visual Director may emit asset directives that require licensed search
    or Gemini image generation, so the real providers are constructed lazily
    (cached for the process) and injected. ``search_provider`` uses Pexels
    when ``PEXELS_API_KEY`` is set (the resolver accepts a single search
    provider); ``generation_provider`` is the Gemini image provider. Providers
    that are not configured stay ``None`` and the resolver fails loudly only
    if a directive actually needs them. ``transaction_root`` is derived per-run
    so the resolver's evidence directory is reproducible.
    """
    cached: dict[str, object] = {}

    def _action(state):
        if not cached:
            from src.asset_resolver.providers import PexelsProvider
            from src.visual_ai import get_image_generation_provider

            pexels_key = os.environ.get("PEXELS_API_KEY")
            cached["search"] = PexelsProvider(pexels_key) if pexels_key else None
            cached["generation"] = get_image_generation_provider()
        run_id = _asset_resolver_run_id(state)
        transaction_root = Path("data") / "asset_transactions" / run_id
        transaction_root.mkdir(parents=True, exist_ok=True)
        return node_fn(
            state,
            search_provider=cached["search"],
            generation_provider=cached["generation"],
            transaction_root=transaction_root,
            transaction_id=run_id,
        )

    return _action


def route_after_content_atomizer(
    state: AgentState,
) -> Literal["visual_director", "r2_compliance"]:
    """Route on the atomizer's forbidden-system-copy verdict.

    A forbidden-copy finding (disclaimer/AI-disclosure in visible text) routes
    to R2 compliance for removal; the normal path proceeds to the visual
    director. The atomizer writes its verdict into ``content_atomization_route``.
    """

    route = state.get("content_atomization_route", "visual_director")
    if route not in ("visual_director", "r2_compliance"):
        route = "visual_director"
    return route


def route_after_design_reviser(
    state: AgentState,
) -> Literal["design_plan_qa", "visual_director"]:
    """Route a normal revision back to QA, or a replan to the visual director.

    The replan signal is carried by ``visual_route_override`` (written by the
    design_reviser wrapper); any other outcome loops back to design_plan_qa so
    the revised plan is re-validated before rendering.
    """

    override = state.get("visual_route_override")
    if override == "visual_director":
        return "visual_director"
    return "design_plan_qa"


def _route_after_visual_critic(
    state: AgentState,
) -> Literal["human_review", "design_reviser"]:
    """Route after the critic, honoring a render-QA hard-fail override.

    ``visual_critic`` short-circuits with ``visual_route_override=
    "design_reviser"`` when render QA already failed (no critique is
    produced). Otherwise the critic's own ``route_after_visual_critic`` reads
    the ``visual_critique`` and drives the two-round aesthetic loop.
    """

    override = state.get("visual_route_override")
    if override == "design_reviser":
        return "design_reviser"
    return route_after_visual_critic(state)


def _trusted_schema_classes() -> list[type[BaseModel]]:
    """Backward-compatible delegate to the shared serializer factory."""

    return trusted_schema_classes()


def _create_checkpointer(checkpoint_path=DEFAULT_CHECKPOINT_PATH):
    if SqliteSaver is None:
        raise ModuleNotFoundError(
            "langgraph.checkpoint.sqlite is required unless create_graph receives a checkpointer."
        )
    resolved_path = Path(checkpoint_path).expanduser().resolve()
    with _CHECKPOINTER_LOCK:
        cached = _CHECKPOINTERS.get(resolved_path)
        if cached is not None:
            return cached[1]

        # Allow our own pydantic schema classes to deserialize from checkpoint
        # without LangGraph's per-node "unregistered type" warning.
        serde = checkpoint_serializer()
        conn = sqlite3.connect(resolved_path, check_same_thread=False)
        checkpointer = SqliteSaver(conn, serde=serde)
        checkpointer.setup()
        _CHECKPOINTERS[resolved_path] = (conn, checkpointer)
        return checkpointer


# Tables SqliteSaver may create that are keyed by thread_id. Older versions also
# keep a separate ``checkpoint_blobs`` table; we delete from whichever exist so a
# clear works across checkpoint schema versions.
_CHECKPOINT_TABLES = ("checkpoints", "writes", "checkpoint_blobs")


def _existing_checkpoint_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?, ?)",
        _CHECKPOINT_TABLES,
    ).fetchall()
    return [row[0] for row in rows]


def delete_checkpoint_thread(thread_id: str, checkpoint_path=DEFAULT_CHECKPOINT_PATH) -> None:
    """Delete all checkpoints + writes for one thread_id."""
    checkpointer = _create_checkpointer(checkpoint_path)
    checkpointer.delete_thread(thread_id)


def delete_all_checkpoints(checkpoint_path=DEFAULT_CHECKPOINT_PATH) -> int:
    """Delete every checkpoint/write row. Returns the count of deleted checkpoint rows.

    Opens a short-lived connection rather than mutating the cached checkpointer so
    the wipe is a single transaction.
    """
    resolved_path = Path(checkpoint_path).expanduser().resolve()
    conn = sqlite3.connect(resolved_path)
    try:
        tables = _existing_checkpoint_tables(conn)
        deleted = 0
        with conn:
            for table in tables:
                if table == "checkpoints":
                    cur = conn.execute(f"DELETE FROM {table}")
                    deleted = cur.rowcount
                else:
                    conn.execute(f"DELETE FROM {table}")
        return deleted
    finally:
        conn.close()


def close_checkpointers(checkpoint_path=None) -> None:
    with _CHECKPOINTER_LOCK:
        if checkpoint_path is None:
            cached_items = list(_CHECKPOINTERS.items())
            _CHECKPOINTERS.clear()
        else:
            resolved_path = Path(checkpoint_path).expanduser().resolve()
            cached = _CHECKPOINTERS.pop(resolved_path, None)
            cached_items = [] if cached is None else [(resolved_path, cached)]

    for _path, (conn, _checkpointer) in cached_items:
        conn.close()


atexit.register(close_checkpointers)


def create_graph(checkpointer=None, checkpoint_path=DEFAULT_CHECKPOINT_PATH):
    """
    Builds the LangGraph workflow with the llm_scene_v3 dynamic visual
    production path.
    """
    builder = StateGraph(AgentState)
    # Shared content chain (domain routing through assembler); identical in
    # every workflow version.
    add_content_chain(builder)
    # --- llm_scene_v3 dynamic visual production nodes ---
    builder.add_node("content_atomizer", nodes.content_atomizer_node)
    builder.add_node(
        "visual_director",
        _structured_visual_node(nodes.visual_director_node),
    )
    builder.add_node("asset_resolver", _asset_resolver_node(nodes.asset_resolver_node))
    builder.add_node(
        "page_designer",
        _structured_visual_node(nodes.page_designer_node),
    )
    builder.add_node("design_plan_qa", nodes.design_plan_qa_node)
    builder.add_node(
        "design_reviser",
        _structured_visual_node_with_route_override(nodes.design_reviser_node),
    )
    builder.add_node("generic_scene_renderer", nodes.generic_scene_renderer_node)
    builder.add_node("render_qa", nodes.render_qa_node)
    builder.add_node(
        "visual_critic",
        _structured_visual_node_with_route_override(nodes.visual_critic_node),
    )
    builder.add_node("human_review", nodes.human_review_node)
    builder.add_node("final_policy_guard", nodes.final_policy_guard_node)
    builder.add_node("content_writer", nodes.content_writer_node)
    # --- dynamic visual production chain ---
    builder.add_edge("assembler", "content_atomizer")
    builder.add_conditional_edges(
        "content_atomizer",
        route_after_content_atomizer,
        {
            "visual_director": "visual_director",
            "r2_compliance": "r2_compliance",
        },
    )
    builder.add_edge("visual_director", "asset_resolver")
    builder.add_edge("asset_resolver", "page_designer")
    builder.add_edge("page_designer", "design_plan_qa")
    builder.add_conditional_edges(
        "design_plan_qa",
        route_after_design_plan_qa,
        {
            "generic_scene_renderer": "generic_scene_renderer",
            "design_reviser": "design_reviser",
        },
    )
    builder.add_edge("generic_scene_renderer", "render_qa")
    builder.add_conditional_edges(
        "render_qa",
        route_after_render_qa,
        {"visual_critic": "visual_critic", "design_reviser": "design_reviser"},
    )
    builder.add_conditional_edges(
        "visual_critic",
        _route_after_visual_critic,
        {"human_review": "human_review", "design_reviser": "design_reviser"},
    )
    builder.add_conditional_edges(
        "design_reviser",
        route_after_design_reviser,
        {
            "design_plan_qa": "design_plan_qa",
            "visual_director": "visual_director",
        },
    )
    builder.add_conditional_edges(
        "human_review",
        route_after_human_review,
        {
            "r2_compliance": "r2_compliance",
            "asset_resolver": "asset_resolver",
            "design_reviser": "design_reviser",
            "final_policy_guard": "final_policy_guard",
        },
    )
    builder.add_conditional_edges(
        "final_policy_guard",
        route_after_final_guard,
        {
            "human_review": "human_review",
            "content_writer": "content_writer",
        },
    )
    builder.add_edge("content_writer", END)

    if checkpointer is None:
        checkpointer = _create_checkpointer(checkpoint_path)
    return builder.compile(checkpointer=checkpointer)
