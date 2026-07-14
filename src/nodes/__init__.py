from importlib import import_module

_EXPORTS = {
    "domain_router_node": "src.nodes.node_a_00_domain_router",
    "domain_confirmation_node": "src.nodes.node_a_00_domain_confirmation",
    "retrieve_memory_node": "src.nodes.node_a_01_retrieve_memory",
    "trend_scout_node": "src.nodes.node_a_trend_scout",
    "angle_strategist_node": "src.nodes.node_b_angle_strategist",
    "novelty_guard_node": "src.nodes.node_b_novelty_guard",
    "virality_scorer_node": "src.nodes.node_c_virality_scorer",
    "evidence_brief_node": "src.nodes.node_c_01_evidence_brief",
    "outline_architect_node": "src.nodes.node_d_outline_architect",
    "draft_writer_node": "src.nodes.node_e_draft_writer",
    "title_lab_node": "src.nodes.node_f_title_lab",
    "title_ranker_node": "src.nodes.node_g_title_ranker",
    "r1_reflector_node": "src.nodes.node_h_r1_reflector",
    "decision_engine_node": "src.nodes.node_j_decision_engine",
    "r2_compliance_node": "src.nodes.node_i_r2_compliance",
    "hashtag_node": "src.nodes.node_k_hashtag_seo",
    "visual_director_node": "src.nodes.node_l_visual_director",
    "image_sourcing_node": "src.nodes.node_m_image_sourcing",
    "image_qa_node": "src.nodes.node_n_image_qa",
    "assembler_node": "src.nodes.node_o_assembler",
    "storyboards_generator_node": "src.nodes.node_o_storyboards_generator",
    "visual_strategy_planner_node": "src.nodes.node_p_visual_strategy_planner",
    "asset_resolver_node": "src.nodes.node_p_asset_resolver",
    "carousel_qa_node": "src.nodes.node_p_carousel_qa",
    "editorial_carousel_renderer_node": "src.nodes.node_p_editorial_carousel_renderer",
    "text_card_renderer_node": "src.nodes.node_p_text_card_renderer",
    "render_qa_node": "src.nodes.node_p_render_qa",
    "content_writer_node": "src.nodes.node_p_content_writer",
    "human_review_node": "src.nodes.node_q_human_review",
    "final_policy_guard_node": "src.nodes.node_q_01_final_policy_guard",
    "topic_ideator_node": "src.nodes.node_a_04_topic_ideator",
    "topic_diversity_filter_node": "src.nodes.node_a_05_topic_diversity_filter",
    "topic_signal_collector_node": "src.nodes.node_a_02_topic_signal_collector",
    "creative_brief_builder_node": "src.nodes.node_a_03_creative_brief_builder",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    try:
        module_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
