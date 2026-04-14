from typing import Literal

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver

import sqlite3
from src.schemas import AgentState
from src.nodes import (
    assembler_node,
    angle_strategist_node,
    decision_engine_node,
    draft_writer_node,
    hashtag_node,
    image_qa_node,
    image_sourcing_node,
    outline_architect_node,
    r1_reflector_node,      
    r2_compliance_node,
    title_lab_node,
    title_ranker_node,
    trend_scout_node,
    virality_scorer_node,
    visual_director_node,
)
conn = sqlite3.connect("checkpoints.sqlite", check_same_thread=False)
MEMORY = SqliteSaver(conn)
MEMORY.setup() # 必须调用 setup 初始化数据库表结构，否则无法落盘

def next_node(state:AgentState)-> Literal["R1_REFLECTOR", "R2_COMPLIANCE", "HASHTAG_SEO"]:
    next_node_value = state["decision_output"].next_node
    return next_node_value

def create_graph():
    """
    Builds the LangGraph workflow.
    """
    builder = StateGraph(AgentState)
    builder.add_node("trend_scout", trend_scout_node)
    builder.add_node("angle_strategist", angle_strategist_node)
    builder.add_node("virality_score", virality_scorer_node)
    builder.add_node("outline_architect", outline_architect_node)
    builder.add_node("draft_writer", draft_writer_node)
    builder.add_node("title_lab", title_lab_node)
    builder.add_node("title_ranker", title_ranker_node)
    builder.add_node("decision_engine", decision_engine_node)
    builder.add_node("r1_reflector", r1_reflector_node)
    builder.add_node("r2_compliance", r2_compliance_node)
    builder.add_node("hashtag", hashtag_node)
    builder.add_node("visual_director", visual_director_node)
    builder.add_node("image_sourcing", image_sourcing_node)
    builder.add_node("image_qa", image_qa_node)
    builder.add_node("assembler", assembler_node)
    builder.add_edge("trend_scout", "angle_strategist")
    builder.add_edge("angle_strategist", "virality_score")
    builder.add_edge("virality_score", "outline_architect")
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
    builder.add_edge("hashtag", "visual_director")
    builder.add_edge("visual_director", "image_sourcing")
    builder.add_edge("image_sourcing", "image_qa")
    builder.add_edge("image_qa", "assembler")
    builder.add_edge("assembler", END)

    builder.set_entry_point("trend_scout")

    return builder.compile(checkpointer=MEMORY)
