from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from PIL import Image
from pydantic import ValidationError

import src.graph as graph_module
from src.creator_profile import COMMUTING_BEAUTY_WOMEN_V1
from src.editorial_carousel.strategy import ASSET_ADAPTER, build_visual_plan
from src.schemas.content_contract import ContentContract
from src.schemas.decision import DecisionOutput, HashTagInput, NormalizedInput
from src.schemas.hashtag import HashTagOutput
from src.schemas.topic import TopicItem
from src.schemas.topic_signal import CreativeSeed, TopicSignal


def _png(width=1080, height=1440):
    buffer = BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _schema_valid_storyboards(contract: ContentContract) -> list[dict]:
    plan = build_visual_plan(contract, recent_signatures=[])
    requirements = {
        (item.layout, item.role): item for item in plan.required_assets
    }
    frames = []
    for index, planned in enumerate(plan.frame_plan):
        semantic_role = planned.asset_roles[0]
        concrete_role = ASSET_ADAPTER[(planned.layout, semantic_role)][0]
        requirement = requirements[(planned.layout, concrete_role)]
        frames.append(
            {
                "frame_id": planned.frame_id,
                "role": planned.role,
                "layout": planned.layout,
                "headline": (
                    contract.first_screen_promise
                    if index == 0
                    else planned.purpose
                ),
                "kicker": "通勤护肤",
                "content_blocks": [
                    {"block_type": "text", "body": planned.purpose}
                ],
                "emphasis": ["按需微调"],
                "visual_slots": [
                    {
                        "slot_id": requirement.slot_id,
                        "role": semantic_role,
                        "semantic_tags": ["skincare"],
                    }
                ],
                "footer": "按肤感微调",
            }
        )
    return frames


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
        content_job="diagnose_and_adjust",
        primary_visual_family="face_zone_map",
        primary_visual_subject="face_map",
        proof_mode="product_texture",
        recommended_frame_count=6,
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
        "focus_keyword": "防晒搓泥",
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


def _install_controlled_upstream_nodes(monkeypatch, reached_nodes, captured):
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
        def node(state):
            if node_name == "human_review":
                paths = [Path(path) for path in state["publish_package"]["rendered_image_paths"]]
                assert len(paths) == 6
                assert all(path.is_file() for path in paths)
                captured["human_review_package"] = state["publish_package"]
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


def _run_carousel_path(monkeypatch, state, storyboards, *, render_root):
    reached_nodes = []
    captured = {}
    _install_controlled_models(monkeypatch, storyboards, captured)
    _install_controlled_upstream_nodes(monkeypatch, reached_nodes, captured)
    def resolve_local_assets(_node_state):
        return {"asset_manifest": {"items": []}}

    def render_local_carousel(node_state):
        package = dict(node_state["publish_package"])
        image_dir = render_root / "20260713-beauty-skincare-integration" / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        pages = []
        for index, frame in enumerate(package["storyboards"], start=1):
            role = frame["role"].replace("_", "-")
            name = "01-cover.png" if index == 1 else f"{index:02d}-{role}.png"
            path = image_dir / name
            path.write_bytes(_png())
            paths.append(path)
            pages.append(SimpleNamespace(path=str(path), frame_id=frame["frame_id"]))
        package["rendered_image_paths"] = [str(path) for path in paths]
        return {
            "publish_package": package,
            "render_manifest": SimpleNamespace(pages=pages),
            "current_node": "EDITORIAL_CAROUSEL_RENDERER",
        }

    monkeypatch.setattr(graph_module.nodes, "asset_resolver_node", resolve_local_assets)
    monkeypatch.setattr(
        graph_module.nodes,
        "editorial_carousel_renderer_node",
        render_local_carousel,
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "render_qa_node",
        lambda _state: {"render_qa_result": {"passed": True}},
    )
    graph = graph_module.create_graph(checkpointer=InMemorySaver())

    with pytest.raises(_ReachedWorkflowNode):
        graph.invoke(state, config={"configurable": {"thread_id": "carousel-path"}})

    return reached_nodes, captured


def test_beauty_package_reaches_human_review_with_account_contract(
    beauty_account_workflow,
    monkeypatch,
    tmp_path,
):
    state = beauty_account_workflow
    contract = state["trends"][0].content_contract

    assert state["creator_profile"].profile_id == "commuting_beauty_women_v1"
    assert state["topic_signals"][0].domain == "beauty"
    assert state["topic_signals"][0].subdomain == "skincare"
    assert len(_schema_valid_storyboards(contract)) == 6

    reached_nodes, captured = _run_carousel_path(
        monkeypatch,
        state,
        _schema_valid_storyboards(contract),
        render_root=tmp_path / "renderer-repository" / "outputs" / "publish",
    )

    assert reached_nodes == ["human_review"]
    assert captured["assembler_calls"] == 1
    assert captured["storyboard_calls"] == 1
    assert captured["human_review_package"]["focus_keyword"] == "防晒搓泥"
    assert '"content_contract"' in captured["storyboard_prompt"]
    assert contract.first_screen_promise in captured["storyboard_prompt"]


def test_beauty_workflow_reaches_review_with_six_locally_rendered_carousel_pages(
    beauty_account_workflow,
    monkeypatch,
    tmp_path,
):
    reached_nodes, captured = _run_carousel_path(
        monkeypatch,
        beauty_account_workflow,
        _schema_valid_storyboards(beauty_account_workflow["trends"][0].content_contract),
        render_root=tmp_path / "renderer-repository" / "outputs" / "publish",
    )

    package = captured["human_review_package"]
    assert reached_nodes == ["human_review"]
    render_root = tmp_path / "renderer-repository" / "outputs" / "publish"
    assert Path(package["rendered_image_paths"][0]).name == "01-cover.png"
    assert all(Path(path).suffix == ".png" for path in package["rendered_image_paths"])
    assert len(list(render_root.glob("*/images/*.png"))) == 6


def test_final_guard_failure_never_writes_audit_or_export_after_human_approval(monkeypatch, tmp_path):
    import main as main_module
    from src.nodes import node_p_text_card_renderer
    from src.rendering.text_cards import output_paths

    publish_root = tmp_path / "outputs" / "publish"
    monkeypatch.setattr(node_p_text_card_renderer, "PUBLISH_ROOT", publish_root)
    image_dir = publish_root / "20260713-beauty-skincare-守门失败" / "images"
    image_dir.mkdir(parents=True)
    image_paths = output_paths(image_dir)
    for path in image_paths:
        path.write_bytes(_png())
    package = {
        "title": "守门失败",
        "domain": "beauty",
        "profile_version": "beauty-v1",
        "rendered_image_paths": [str(path) for path in image_paths],
    }

    class FailedGuardGraph:
        def stream(self, _run_input, config):
            yield {"human_review": {"review_status": "approved", "publish_package": package}}
            yield {"final_policy_guard": {"final_policy_issues": [{"rule_id": "blocked"}]}}

    main_module.stream_graph_until_stop(FailedGuardGraph(), {}, {})

    assert not list(publish_root.rglob("*.json"))
    assert sorted(image_dir.glob("*.png")) == image_paths


def test_invalid_beauty_carousel_reaches_r1_through_compiled_graph(
    beauty_account_workflow,
    monkeypatch,
    tmp_path,
):
    state = beauty_account_workflow
    storyboards = _schema_valid_storyboards(state["trends"][0].content_contract)
    storyboards[0]["visual_slots"][0]["role"] = "background_token"

    reached_nodes, captured = _run_carousel_path(
        monkeypatch,
        state,
        storyboards,
        render_root=tmp_path / "renderer-repository" / "outputs" / "publish",
    )

    assert reached_nodes == ["r1_reflector"]
    assert captured["assembler_calls"] == 1
    assert captured["storyboard_calls"] == 1


def test_semantic_storyboard_schema_error_stops_before_asset_resolution(
    beauty_account_workflow,
    monkeypatch,
    tmp_path,
):
    state = beauty_account_workflow
    storyboards = _schema_valid_storyboards(state["trends"][0].content_contract)
    storyboards[1]["wrong_items"] = ["只有一项"]

    with pytest.raises(ValidationError, match="wrong_items|extra_forbidden"):
        _run_carousel_path(
            monkeypatch,
            state,
            storyboards,
            render_root=tmp_path / "renderer-repository" / "outputs" / "publish",
        )
