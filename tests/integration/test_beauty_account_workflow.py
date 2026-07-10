from datetime import date, datetime

import pytest
from langgraph.checkpoint.memory import InMemorySaver

import src.graph as graph_module
from src.creator_profile import COMMUTING_BEAUTY_WOMEN_V1
from src.schemas.content_contract import ContentContract
from src.schemas.decision import DecisionOutput, NormalizedInput
from src.schemas.topic import TopicItem
from src.schemas.topic_signal import CreativeSeed, TopicSignal


@pytest.fixture
def beauty_account_workflow():
    contract = ContentContract(
        audience=COMMUTING_BEAUTY_WOMEN_V1.audience,
        trigger_situation="早高峰上班前",
        decision_problem="防晒和底妆如何避免搓泥",
        first_screen_promise="通勤前 3 步避开防晒搓泥",
        screenshot_asset="防晒与底妆搭配清单",
        proof_asset="产品质地实拍",
        visual_mode="text_card",
    )
    signal = TopicSignal(
        signal_id="signal_sunscreen_commute",
        source="integration_fixture",
        signal_type="evergreen_context",
        signal_name="通勤防晒",
        normalized_signal="commute sunscreen",
        domain="beauty",
        subdomain="skincare",
        why_now="早高峰出门前需要快速完成底妆。",
        domain_translation="防晒成膜后再上底妆的通勤决策。",
        risk_level="low",
        confidence=1.0,
        active_from=date(2026, 7, 10),
        expires_at=date(2026, 7, 11),
        collected_at=datetime(2026, 7, 10, 9, 0),
    )
    topic = TopicItem(
        topic_id="tp_sunscreen_commute",
        topic="通勤防晒底妆不搓泥",
        target_group=COMMUTING_BEAUTY_WOMEN_V1.audience,
        core_pain="防晒后底妆搓泥",
        hook="出门前少等几分钟，也能减少搓泥。",
        content_form="cards",
        risk_note="不承诺产品效果。",
        domain="beauty",
        subdomain="skincare",
        content_intent="how_to",
        risk_level="low",
        risk_flags=[],
        content_contract=contract,
        creative_seed=CreativeSeed(
            signal_type=signal.signal_type,
            signal_name=signal.signal_name,
            why_now=signal.why_now,
            domain_translation=signal.domain_translation,
            evergreen_pain="通勤前没有时间反复补救搓泥。",
            timely_framing="早高峰前的一次性判断清单。",
        ),
    )
    storyboards = [
        {
            "frame_id": f"frame_{index:03d}",
            "frame_title": f"第 {index} 张",
            "visual_description": "高对比文字信息卡",
            "scene_background": "干净浅色背景",
            "composition": "清晰分区",
            "text_area": "顶部标题区",
            "on_image_copy": (
                contract.first_screen_promise if index == 1 else f"第 {index} 个要点"
            ),
            "narration": f"第 {index} 步说明",
            "image_prompt_cn": "手机端可读的文字卡",
            "image_prompt_en": "readable mobile text card",
            "card_role": "cover" if index == 1 else "step",
            "is_screenshot_asset": index == 4,
            "visual_mode": contract.visual_mode,
        }
        for index in range(1, 7)
    ]
    state = {
        "creator_profile": COMMUTING_BEAUTY_WOMEN_V1,
        "topic_signals": [signal],
        "trends": [topic],
    }
    package = {
        "draft_id": "draft_sunscreen_commute",
        "topic_id": topic.topic_id,
        "topic": topic.topic,
        "angle_id": "ag_sunscreen_order",
        "angle": "防晒与底妆顺序",
        "target_group": topic.target_group,
        "core_pain": topic.core_pain,
        "title": "通勤防晒底妆不搓泥",
        "content": "先给防晒成膜时间，再上底妆。",
        "cover_copy": contract.first_screen_promise,
        "storyboards": storyboards,
        "domain": topic.domain,
        "subdomain": topic.subdomain,
    }
    return {**state, "publish_package": package}


class _ReachedWorkflowNode(Exception):
    pass


def _install_controlled_upstream_nodes(monkeypatch, reached_nodes):
    def passthrough(_state):
        return {}

    def route_to_hashtag(_state):
        return {
            "decision_output": DecisionOutput(
                next_node="HASHTAG_SEO",
                normalized_input=NormalizedInput(),
            )
        }

    def record_reached(node_name):
        def node(_state):
            reached_nodes.append(node_name)
            raise _ReachedWorkflowNode(node_name)

        return node

    for node_name in (
        "domain_router_node",
        "domain_confirmation_node",
        "retrieve_memory_node",
        "topic_signal_collector_node",
        "creative_brief_builder_node",
        "topic_ideator_node",
        "topic_diversity_filter_node",
        "angle_strategist_node",
        "novelty_guard_node",
        "virality_scorer_node",
        "evidence_brief_node",
        "outline_architect_node",
        "draft_writer_node",
        "title_lab_node",
        "title_ranker_node",
        "hashtag_node",
        "assembler_node",
        "storyboards_generator_node",
    ):
        monkeypatch.setattr(graph_module.nodes, node_name, passthrough)

    monkeypatch.setattr(graph_module.nodes, "decision_engine_node", route_to_hashtag)
    monkeypatch.setattr(
        graph_module.nodes,
        "human_review_node",
        record_reached("human_review"),
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "r1_reflector_node",
        record_reached("r1_reflector"),
    )


def _run_carousel_path(monkeypatch, state):
    reached_nodes = []
    _install_controlled_upstream_nodes(monkeypatch, reached_nodes)
    graph = graph_module.create_graph(checkpointer=InMemorySaver())

    with pytest.raises(_ReachedWorkflowNode):
        graph.invoke(state, config={"configurable": {"thread_id": "carousel-path"}})

    return reached_nodes


def test_beauty_package_reaches_human_review_with_account_contract(
    beauty_account_workflow,
    monkeypatch,
):
    state = beauty_account_workflow
    package = state["publish_package"]

    assert state["creator_profile"].profile_id == "commuting_beauty_women_v1"
    assert state["topic_signals"][0].domain == "beauty"
    assert state["topic_signals"][0].subdomain == "skincare"
    assert package["domain"] in state["creator_profile"].allowed_domains
    assert package["subdomain"] in state["creator_profile"].allowed_subdomains
    assert 6 <= len(package["storyboards"]) <= 8
    assert (
        package["storyboards"][0]["on_image_copy"]
        == state["trends"][0].content_contract.first_screen_promise
    )
    assert any(frame["is_screenshot_asset"] for frame in package["storyboards"])
    assert _run_carousel_path(monkeypatch, state) == ["human_review"]


def test_invalid_beauty_carousel_reaches_r1_through_compiled_graph(
    beauty_account_workflow,
    monkeypatch,
):
    state = beauty_account_workflow
    package = state["publish_package"]
    package["storyboards"][0]["on_image_copy"] = "泛泛的护肤建议"

    assert _run_carousel_path(monkeypatch, state) == ["r1_reflector"]
