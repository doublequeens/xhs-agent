from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
import pytest

import main as main_module
import src.graph as graph_module
from src.editorial_carousel.legacy import (
    LEGACY_EDITORIAL_V1,
    MODERN_EDITORIAL_V2,
)
from src.schemas import AgentState, DecisionOutput, NormalizedInput


def _old_checkpoint(checkpointer, config, *, predecessor, successor, values):
    builder = StateGraph(AgentState)
    builder.add_node(predecessor, lambda _state: {})
    builder.add_node(successor, lambda _state: {})
    builder.add_edge(predecessor, successor)
    builder.add_edge(successor, END)
    builder.set_entry_point(predecessor)
    graph = builder.compile(checkpointer=checkpointer)
    graph.update_state(config, values, as_node=predecessor)
    assert graph.get_state(config).next == (successor,)


def _legacy_package(*, with_storyboards=True, with_render=False):
    package = {
        "topic_id": "tp-legacy",
        "topic": "旧版清单",
        "angle_id": "ag-legacy",
        "angle": "旧版角度",
        "target_group": "通勤人群",
        "core_pain": "时间有限",
        "title": "旧版卡片",
        "content": "逐步记录。",
        "cover_copy": "旧版封面",
        "hashtags": ["#旧版"],
        "domain": "beauty",
        "subdomain": "skincare",
        "profile_version": "beauty-v1",
        "content_contract": {
            "audience": "通勤人群",
            "trigger_situation": "早上",
            "decision_problem": "如何快速安排",
            "first_screen_promise": "通勤前快速完成三步",
            "screenshot_asset": "清单",
            "proof_asset": "对照",
            "visual_mode": "text_card",
        },
    }
    if with_storyboards:
        package["storyboards"] = [
            {
                "frame_id": f"frame-{index}",
                "template": "cover_statement",
                "theme": "warm_neutral",
                "headline": f"旧版 {index}",
            }
            for index in range(1, 6)
        ]
    if with_render:
        package["rendered_image_paths"] = [f"legacy-{index}.png" for index in range(5)]
    return package


@pytest.mark.parametrize(
    "predecessor,successor,package",
    [
        ("text_card_renderer", "render_qa", _legacy_package(with_render=True)),
        ("assembler", "storyboard_generator", _legacy_package(with_storyboards=False)),
        ("storyboard_generator", "carousel_qa", _legacy_package()),
    ],
)
def test_pre_task8_exact_successor_resumes_only_legacy_lane(
    monkeypatch,
    predecessor,
    successor,
    package,
):
    checkpointer = InMemorySaver()
    config = {"configurable": {"thread_id": f"legacy-{successor}"}}
    _old_checkpoint(
        checkpointer,
        config,
        predecessor=predecessor,
        successor=successor,
        values={"domain_context": {}, "publish_package": package},
    )
    reached = []

    def legacy_storyboard(state):
        reached.append("storyboard_generator")
        assert state["editorial_workflow_version"] == LEGACY_EDITORIAL_V1
        return {"publish_package": _legacy_package()}

    def legacy_carousel(state):
        reached.append("carousel_qa")
        assert state["visual_plan"] is None
        return {"carousel_qa_result": {"passed": True}}

    def legacy_renderer(state):
        reached.append("editorial_carousel_renderer")
        updated = dict(state["publish_package"])
        updated["rendered_image_paths"] = [f"legacy-{index}.png" for index in range(5)]
        return {"publish_package": updated}

    monkeypatch.setattr(graph_module.nodes, "storyboards_generator_node", legacy_storyboard)
    monkeypatch.setattr(graph_module.nodes, "carousel_qa_node", legacy_carousel)
    monkeypatch.setattr(graph_module.nodes, "editorial_carousel_renderer_node", legacy_renderer)
    monkeypatch.setattr(
        graph_module.nodes,
        "asset_resolver_node",
        lambda _state: pytest.fail("legacy exact resume must not enter asset resolver"),
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "render_qa_node",
        lambda state: reached.append("render_qa")
        or {"render_qa_result": {"passed": True}},
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "human_review_node",
        lambda state: reached.append("human_review")
        or {"review_status": "approved", "review_route": "final_policy_guard"},
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "final_policy_guard_node",
        lambda state: reached.append("final_policy_guard")
        or {"final_policy_issues": []},
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "content_writer_node",
        lambda state: reached.append("content_writer") or {"data_writed": True},
    )
    graph = graph_module.create_graph(checkpointer=checkpointer)
    current, run_input = main_module.load_run_state(graph, config, {})
    assert run_input is None
    assert current.values["editorial_workflow_version"] == LEGACY_EDITORIAL_V1

    completed = graph.invoke(None, config=config)

    assert completed["data_writed"] is True
    assert "content_writer" in reached
    assert "asset_resolver" not in reached


def test_legacy_r1_regeneration_transitions_to_modern_lane_in_same_run(monkeypatch):
    checkpointer = InMemorySaver()
    config = {"configurable": {"thread_id": "legacy-r1-modern"}}
    _old_checkpoint(
        checkpointer,
        config,
        predecessor="storyboard_generator",
        successor="carousel_qa",
        values={"domain_context": {}, "publish_package": _legacy_package()},
    )
    reached = []

    def carousel(state):
        if state.get("visual_plan") is None:
            reached.append("legacy_carousel_failed")
            return {
                "carousel_qa_result": {"passed": False},
                "decision_output": DecisionOutput(
                    next_node="R1_REFLECTOR",
                    normalized_input=NormalizedInput(),
                ),
            }
        reached.append("modern_carousel_passed")
        return {"carousel_qa_result": {"passed": True}}

    monkeypatch.setattr(graph_module.nodes, "carousel_qa_node", carousel)
    monkeypatch.setattr(
        graph_module.nodes,
        "r1_reflector_node",
        lambda state: reached.append("r1_reflector")
        or {"current_node": "R1_REFLECTOR"},
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "decision_engine_node",
        lambda state: {
            "decision_output": DecisionOutput(
                next_node="HASHTAG_SEO",
                normalized_input=NormalizedInput(),
            )
        },
    )
    monkeypatch.setattr(graph_module.nodes, "hashtag_node", lambda _state: {})
    modern_contract = {
        "audience": "通勤人群",
        "trigger_situation": "早上",
        "decision_problem": "如何快速安排",
        "first_screen_promise": "通勤前快速完成三步",
        "screenshot_asset": "清单",
        "proof_asset": "对照",
        "visual_mode": "text_card",
        "content_job": "save_and_check",
        "primary_visual_family": "saveable_reference",
        "primary_visual_subject": "checklist",
        "proof_mode": "diagram",
        "recommended_frame_count": 5,
    }
    monkeypatch.setattr(
        graph_module.nodes,
        "assembler_node",
        lambda state: {"publish_package": {**_legacy_package(), "content_contract": modern_contract}},
    )

    def modern_storyboard(state):
        reached.append("modern_storyboard")
        assert state["editorial_workflow_version"] == MODERN_EDITORIAL_V2
        assert state["legacy_editorial_checkpoint"] is False
        plan = state["visual_plan"]
        return {
            "publish_package": {
                **state["publish_package"],
                "storyboards": [
                    {
                        "frame_id": frame.frame_id,
                        "role": frame.role,
                        "layout": frame.layout,
                        "headline": modern_contract["first_screen_promise"] if index == 0 else frame.purpose,
                        "content_blocks": [],
                        "visual_slots": [],
                    }
                    for index, frame in enumerate(plan.frame_plan)
                ],
            }
        }

    monkeypatch.setattr(graph_module.nodes, "storyboards_generator_node", modern_storyboard)
    monkeypatch.setattr(
        graph_module.nodes,
        "asset_resolver_node",
        lambda state: reached.append("asset_resolver") or {"asset_manifest": {"items": []}},
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "editorial_carousel_renderer_node",
        lambda state: {"publish_package": state["publish_package"], "render_manifest": {"pages": []}},
    )
    monkeypatch.setattr(graph_module.nodes, "render_qa_node", lambda _state: {"render_qa_result": {"passed": True}})
    monkeypatch.setattr(graph_module.nodes, "human_review_node", lambda _state: {"review_status": "approved", "review_route": "final_policy_guard"})
    monkeypatch.setattr(
        graph_module.nodes,
        "final_policy_guard_node",
        lambda state: reached.append("modern_guard")
        or ({"final_policy_issues": []} if state["editorial_workflow_version"] == MODERN_EDITORIAL_V2 else pytest.fail("guard stayed legacy")),
    )
    monkeypatch.setattr(graph_module.nodes, "content_writer_node", lambda _state: {"data_writed": True})
    graph = graph_module.create_graph(checkpointer=checkpointer)
    main_module.load_run_state(graph, config, {})

    completed = graph.invoke(None, config=config)

    assert completed["data_writed"] is True
    assert reached == [
        "legacy_carousel_failed",
        "r1_reflector",
        "modern_storyboard",
        "asset_resolver",
        "modern_carousel_passed",
        "modern_guard",
    ]
