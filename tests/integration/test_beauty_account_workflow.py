from datetime import date, datetime
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver

import src.graph as graph_module
from src.creator_profile import COMMUTING_BEAUTY_WOMEN_V1
from src.schemas.content_contract import ContentContract
from src.schemas.decision import DecisionOutput, HashTagInput, NormalizedInput
from src.schemas.hashtag import HashTagOutput
from src.schemas.topic import TopicItem
from src.schemas.topic_signal import CreativeSeed, TopicSignal


def _schema_valid_storyboards(contract: ContentContract) -> list[dict]:
    common = {"theme": "soft_blue", "footer": "按需微调"}
    return [
        {"frame_id": "frame_001", **common, "template": "cover_statement", "kicker": "封面", "headline": contract.first_screen_promise},
        {"frame_id": "frame_002", **common, "template": "wrong_vs_right", "kicker": "对照", "headline": "避免搓泥", "wrong_items": ["立刻上妆", "厚涂粉底"], "right_items": ["等待成膜", "少量点涂"]},
        {"frame_id": "frame_003", **common, "template": "step_timeline", "kicker": "步骤", "headline": "三步上妆", "steps": [{"name": "防晒", "hint": "薄涂全脸"}, {"name": "等待", "hint": "静置三分钟"}, {"name": "底妆", "hint": "少量点涂"}]},
        {"frame_id": "frame_004", **common, "template": "saveable_checklist", "kicker": "保存", "headline": "上妆清单", "checklist_items": ["薄涂防晒", "等待成膜", "少量点涂"]},
        {"frame_id": "frame_005", **common, "template": "decision_rule", "kicker": "判断", "headline": "出现搓泥时", "condition": "底妆开始搓泥", "recommendation": "减少用量等待"},
        {"frame_id": "frame_006", **common, "template": "question_closer", "kicker": "讨论", "headline": "你的习惯", "question": "你最常在哪步搓泥？"},
    ]


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
    final_content = HashTagInput(
        final_title="通勤防晒底妆不搓泥",
        final_md="先给防晒成膜时间，再上底妆。",
        topic_id=topic.topic_id,
        angle_id="ag_sunscreen_order",
        topic=topic.topic,
        angle="防晒与底妆顺序",
        domain=topic.domain,
        subdomain=topic.subdomain,
        content_intent=topic.content_intent,
        risk_level=topic.risk_level,
        risk_flags=[],
        target_group=topic.target_group,
        core_pain=topic.core_pain,
        best_cover_copy=contract.first_screen_promise,
    )
    return {
        "creator_profile": COMMUTING_BEAUTY_WOMEN_V1,
        "topic_signals": [signal],
        "trends": [topic],
        "domain_context": {
            "domain": "beauty",
            "subdomain": "skincare",
            "profile_version": "beauty-v1",
        },
        "final_content": final_content,
        "hashtags": HashTagOutput(hashtags=["#通勤底妆"]),
        "final_images": SimpleNamespace(image_final_choices=[]),
    }


class _ReachedWorkflowNode(Exception):
    pass


def _install_controlled_models(monkeypatch, storyboards, captured):
    from src.nodes import node_o_assembler as assembler_module
    from src.nodes import node_o_storyboards_generator as storyboard_module

    class FakeAssemblerModel:
        def execute(self, _messages):
            captured["assembler_calls"] = captured.get("assembler_calls", 0) + 1
            return {
                "images": [],
                "hashtags": ["#model-output"],
                "notes": [],
                "storyboard_strategy": "checklist",
            }

    class FakeStoryboardModel:
        def execute(self, messages):
            captured["storyboard_calls"] = captured.get("storyboard_calls", 0) + 1
            captured["storyboard_prompt"] = messages[1].content
            return {"storyboards": storyboards}

    monkeypatch.setattr(assembler_module, "get_model", lambda: FakeAssemblerModel())
    monkeypatch.setattr(storyboard_module, "get_model", lambda: FakeStoryboardModel())


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


def _run_carousel_path(monkeypatch, state, storyboards):
    reached_nodes = []
    captured = {}
    _install_controlled_models(monkeypatch, storyboards, captured)
    _install_controlled_upstream_nodes(monkeypatch, reached_nodes)
    graph = graph_module.create_graph(checkpointer=InMemorySaver())

    with pytest.raises(_ReachedWorkflowNode):
        graph.invoke(state, config={"configurable": {"thread_id": "carousel-path"}})

    return reached_nodes, captured


def test_beauty_package_reaches_human_review_with_account_contract(
    beauty_account_workflow,
    monkeypatch,
):
    state = beauty_account_workflow
    contract = state["trends"][0].content_contract

    assert state["creator_profile"].profile_id == "commuting_beauty_women_v1"
    assert state["topic_signals"][0].domain == "beauty"
    assert state["topic_signals"][0].subdomain == "skincare"
    assert len(_schema_valid_storyboards(contract)) == 6

    reached_nodes, captured = _run_carousel_path(
        monkeypatch, state, _schema_valid_storyboards(contract)
    )

    assert reached_nodes == ["human_review"]
    assert captured["assembler_calls"] == 1
    assert captured["storyboard_calls"] == 1
    assert '"content_contract"' in captured["storyboard_prompt"]
    assert contract.first_screen_promise in captured["storyboard_prompt"]


def test_invalid_beauty_carousel_reaches_r1_through_compiled_graph(
    beauty_account_workflow,
    monkeypatch,
):
    state = beauty_account_workflow
    storyboards = _schema_valid_storyboards(state["trends"][0].content_contract)
    storyboards[0]["headline"] = "泛泛的护肤建议"

    reached_nodes, captured = _run_carousel_path(monkeypatch, state, storyboards)

    assert reached_nodes == ["r1_reflector"]
    assert captured["assembler_calls"] == 1
    assert captured["storyboard_calls"] == 1
