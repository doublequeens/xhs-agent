import atexit
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Literal

from langgraph.graph import StateGraph, END
try:
    from langgraph.checkpoint.sqlite import SqliteSaver
except ModuleNotFoundError:  # pragma: no cover - exercised in tests via injection
    SqliteSaver = None

from src.schemas import AgentState
import src.nodes as nodes

DEFAULT_CHECKPOINT_PATH = Path("checkpoints.sqlite")
_CHECKPOINTERS: dict[Path, tuple[sqlite3.Connection, object]] = {}
_CHECKPOINTER_LOCK = Lock()


def next_node(state:AgentState)-> Literal["R1_REFLECTOR", "R2_COMPLIANCE", "HASHTAG_SEO"]:
    next_node_value = state["decision_output"].next_node
    return next_node_value


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

        conn = sqlite3.connect(resolved_path, check_same_thread=False)
        checkpointer = SqliteSaver(conn)
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
    builder.add_node("trend_scout", nodes.trend_scout_node)
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
    builder.add_node("storyboard_generator", nodes.storyboards_generator_node)
    # builder.add_node("visual_director", visual_director_node)
    # builder.add_node("image_sourcing", image_sourcing_node)
    # builder.add_node("image_qa", image_qa_node)
    builder.add_node("assembler", nodes.assembler_node)
    builder.add_node("human_review", nodes.human_review_node)
    builder.add_node("content_writer", nodes.content_writer_node)
    builder.add_edge("domain_router", "domain_confirmation")
    builder.add_edge("domain_confirmation", "memory_retriever")
    builder.add_edge("memory_retriever", "trend_scout")
    builder.add_edge("trend_scout", "angle_strategist")
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
    # builder.add_edge("visual_director", "image_sourcing")
    # builder.add_edge("image_sourcing", "image_qa")
    # builder.add_edge("image_qa", "assembler")
    builder.add_edge("assembler", "storyboard_generator")
    builder.add_edge("storyboard_generator", "human_review")
    builder.add_edge("human_review", "content_writer")
    builder.add_edge("content_writer", END)
    builder.set_entry_point("domain_router")

    if checkpointer is None:
        checkpointer = _create_checkpointer(checkpoint_path)
    return builder.compile(checkpointer=checkpointer)
