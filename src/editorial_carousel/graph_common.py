"""The shared content-production chain used by both graph versions.

Domain routing through assembler (including the R1/R2 reflection loop around
``decision_engine``) is version-independent: both the frozen ``llm_scene_v3``
graph and ``src.graph_v4`` build this chain through this module so the
content side can never drift between versions.  Visual production routing is
deliberately NOT shared — each version owns its own visual nodes and edges.

Node functions are resolved through the ``src.nodes`` package attribute at
build time (as the v3 graph always did), so integration tests may monkeypatch
a node before building either graph.
"""

from __future__ import annotations

from typing import Literal

import src.nodes as nodes
from src.schemas import AgentState


def next_node(state: AgentState) -> Literal["R1_REFLECTOR", "R2_COMPLIANCE", "HASHTAG_SEO"]:
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


def add_content_chain(builder) -> None:
    """Add the shared domain/topic/writing chain and its edges to ``builder``."""

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
    builder.add_node("assembler", nodes.assembler_node)

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
    builder.add_conditional_edges(
        "decision_engine",
        next_node,
        {
            "R1_REFLECTOR": "r1_reflector",
            "R2_COMPLIANCE": "r2_compliance",
            "HASHTAG_SEO": "hashtag",
        },
    )
    builder.add_edge("hashtag", "assembler")
    builder.set_entry_point("domain_router")


__all__ = ["add_content_chain"]
