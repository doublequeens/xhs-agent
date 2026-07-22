import atexit
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Literal

from pydantic import BaseModel

from langgraph.graph import StateGraph, END
try:
    from langgraph.checkpoint.sqlite import SqliteSaver
except ModuleNotFoundError:  # pragma: no cover - exercised in tests via injection
    SqliteSaver = None
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from src.schemas import AgentState
import src.nodes as nodes
from src.nodes.node_q_01_final_policy_guard import route_after_final_guard
from src.nodes.node_q_human_review import route_after_human_review
from src.nodes.node_p_carousel_qa import route_after_carousel_qa
from src.nodes.node_p_render_qa import route_after_render_qa

DEFAULT_CHECKPOINT_PATH = Path("checkpoints.sqlite")
_CHECKPOINTERS: dict[Path, tuple[sqlite3.Connection, object]] = {}
_CHECKPOINTER_LOCK = Lock()


def next_node(state:AgentState)-> Literal["R1_REFLECTOR", "R2_COMPLIANCE", "HASHTAG_SEO"]:
    next_node_value = state["decision_output"].next_node
    if next_node_value == "HASHTAG_SEO" and state.get("current_node") == "R2_COMPLIANCE":
        r2_output = state.get("r2_output")
        compliance_audit = getattr(r2_output, "compliance_audit", None)
        if compliance_audit is None and isinstance(r2_output, dict):
            compliance_audit = r2_output.get("compliance_audit")
        if compliance_audit is not None:
            block_publish = getattr(compliance_audit, "block_publish", None)
            if block_publish is None and isinstance(compliance_audit, dict):
                block_publish = compliance_audit.get("block_publish", False)
            if block_publish:
                return "R1_REFLECTOR"
    return next_node_value


def _trusted_schema_classes() -> list[type[BaseModel]]:
    """Pydantic models defined in our own packages that we allow to round-trip
    through the SQLite checkpoint.

    LangGraph's checkpoint serializer encodes every custom pydantic class stored
    in state as a typed ``(module, class, data)`` blob. On read-back it warns for
    any type not on its built-in safe list — once per node, every run — because
    the whole state is deserialized at the start of each node. Registering these
    classes via ``allowed_msgpack_modules`` silences the warning while keeping the
    objects intact (no business-code changes).

    We enumerate ``BaseModel`` subclasses under ``src.`` / ``memory.`` rather than
    hand-listing them, so new schema classes are covered automatically. ``AgentState``
    imports every schema type it can store, so importing it (done by this module)
    is enough to populate the subclass tree.
    """
    def _all_subclasses(cls: type):
        for sub in cls.__subclasses__():
            yield sub
            yield from _all_subclasses(sub)

    trusted: list[type[BaseModel]] = []
    seen: set[type] = set()
    for cls in _all_subclasses(BaseModel):
        module = getattr(cls, "__module__", "") or ""
        if module.startswith(("src.", "memory.")) and cls not in seen:
            seen.add(cls)
            trusted.append(cls)
    return trusted


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
        serde = JsonPlusSerializer(allowed_msgpack_modules=_trusted_schema_classes())
        conn = sqlite3.connect(resolved_path, check_same_thread=False)
        checkpointer = SqliteSaver(conn, serde=serde)
        checkpointer.setup()
        _CHECKPOINTERS[resolved_path] = (conn, checkpointer)
        return checkpointer


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
    Builds the LangGraph workflow.
    """
    builder = StateGraph(AgentState)
    builder.add_node("domain_router", nodes.domain_router_node)
    builder.add_node("domain_confirmation", nodes.domain_confirmation_node)
    builder.add_node("memory_retriever", nodes.retrieve_memory_node)
    builder.add_node("topic_signal_collector", nodes.topic_signal_collector_node)
    builder.add_node("creative_brief_builder", nodes.creative_brief_builder_node)
    builder.add_node("topic_ideator", nodes.topic_ideator_node)
    builder.add_node("topic_diversity_filter", nodes.topic_diversity_filter_node)
    builder.add_node("angle_strategist", nodes.angle_strategist_node)
    builder.add_node("novelty_guard", nodes.novelty_guard_node)
    builder.add_node("virality_score", nodes.virality_scorer_node)
    builder.add_node("evidence_brief", nodes.evidence_brief_node)
    builder.add_node("outline_architect", nodes.outline_architect_node)
    builder.add_node("draft_writer", nodes.draft_writer_node)
    builder.add_node("title_lab", nodes.title_lab_node)
    builder.add_node("title_ranker", nodes.title_ranker_node)
    builder.add_node("decision_engine", nodes.decision_engine_node)
    builder.add_node("r1_reflector", nodes.r1_reflector_node)
    builder.add_node("r2_compliance", nodes.r2_compliance_node)
    builder.add_node("hashtag", nodes.hashtag_node)
    builder.add_node("visual_strategy_planner", nodes.visual_strategy_planner_node)
    builder.add_node("storyboard_generator", nodes.storyboards_generator_node)
    builder.add_node("asset_resolver", nodes.asset_resolver_node)
    builder.add_node("carousel_qa", nodes.carousel_qa_node)
    builder.add_node(
        "editorial_carousel_renderer",
        nodes.editorial_carousel_renderer_node,
    )
    builder.add_node("render_qa", nodes.render_qa_node)
    builder.add_node("assembler", nodes.assembler_node)
    builder.add_node("human_review", nodes.human_review_node)
    builder.add_node("final_policy_guard", nodes.final_policy_guard_node)
    builder.add_node("content_writer", nodes.content_writer_node)
    builder.add_edge("domain_router", "domain_confirmation")
    builder.add_edge("domain_confirmation", "memory_retriever")
    builder.add_edge("memory_retriever", "topic_signal_collector")
    builder.add_edge("topic_signal_collector", "creative_brief_builder")
    builder.add_edge("creative_brief_builder", "topic_ideator")
    builder.add_edge("topic_ideator", "topic_diversity_filter")
    builder.add_edge("topic_diversity_filter", "angle_strategist")
    builder.add_edge("angle_strategist", "novelty_guard")
    builder.add_edge("novelty_guard", "virality_score")
    builder.add_edge("virality_score", "evidence_brief")
    builder.add_edge("evidence_brief", "outline_architect")
    builder.add_edge("outline_architect", "draft_writer")
    builder.add_edge("draft_writer", "title_lab")
    builder.add_edge("title_lab", "title_ranker")
    builder.add_edge("title_ranker", "decision_engine")
    builder.add_edge("r1_reflector", "decision_engine")
    builder.add_edge("r2_compliance", "decision_engine")
    builder.add_conditional_edges("decision_engine",
                                next_node,
                                {"R1_REFLECTOR": "r1_reflector", 
                                "R2_COMPLIANCE": "r2_compliance", 
                                "HASHTAG_SEO": "hashtag"})
    builder.add_edge("hashtag", "assembler")
    builder.add_edge("assembler", "visual_strategy_planner")
    builder.add_edge("visual_strategy_planner", "storyboard_generator")
    builder.add_edge("storyboard_generator", "asset_resolver")
    builder.add_edge("asset_resolver", "carousel_qa")
    builder.add_conditional_edges(
        "carousel_qa",
        route_after_carousel_qa,
        {
            "r1_reflector": "r1_reflector",
            "editorial_carousel_renderer": "editorial_carousel_renderer",
        },
    )
    builder.add_edge("editorial_carousel_renderer", "render_qa")
    builder.add_conditional_edges(
        "render_qa",
        route_after_render_qa,
        {"r1_reflector": "r1_reflector", "human_review": "human_review"},
    )
    builder.add_conditional_edges(
        "human_review",
        route_after_human_review,
        {
            "r2_compliance": "r2_compliance",
            "final_policy_guard": "final_policy_guard",
            "editorial_carousel_renderer": "editorial_carousel_renderer",
            "render_qa": "render_qa",
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
    builder.set_entry_point("domain_router")

    if checkpointer is None:
        checkpointer = _create_checkpointer(checkpoint_path)
    return builder.compile(checkpointer=checkpointer)
