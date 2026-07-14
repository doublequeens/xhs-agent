from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
import pytest

import main as main_module
import src.graph as graph_module
from src.editorial_carousel.legacy import MODERN_EDITORIAL_V2
from src.schemas import AgentState


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
        package["rendered_image_paths"] = [
            f"legacy-{index}.png" for index in range(5)
        ]
    return package


@pytest.mark.parametrize(
    "predecessor,successor,package",
    [
        ("carousel_qa", "text_card_renderer", _legacy_package()),
        ("text_card_renderer", "render_qa", _legacy_package(with_render=True)),
        ("assembler", "storyboard_generator", _legacy_package(with_storyboards=False)),
        ("storyboard_generator", "carousel_qa", _legacy_package()),
        ("render_qa", "human_review", _legacy_package(with_render=True)),
        ("human_review", "final_policy_guard", _legacy_package(with_render=True)),
        ("final_policy_guard", "content_writer", _legacy_package(with_render=True)),
    ],
)
def test_pre_task8_exact_successor_migrates_to_modern_storyboard_seam(
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

    def modern_storyboard(state):
        reached.append("storyboard_generator")
        assert state["editorial_workflow_version"] == MODERN_EDITORIAL_V2
        assert state["legacy_editorial_checkpoint"] is False
        assert state["visual_plan"] is not None
        return {"publish_package": state["publish_package"]}

    monkeypatch.setattr(
        graph_module.nodes,
        "storyboards_generator_node",
        modern_storyboard,
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "asset_resolver_node",
        lambda _state: reached.append("asset_resolver")
        or {"asset_manifest": {"items": []}},
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "carousel_qa_node",
        lambda _state: reached.append("carousel_qa")
        or {"carousel_qa_result": {"passed": True}},
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "editorial_carousel_renderer_node",
        lambda state: reached.append("editorial_carousel_renderer")
        or {
            "publish_package": state["publish_package"],
            "render_manifest": {"pages": []},
        },
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "render_qa_node",
        lambda _state: reached.append("render_qa")
        or {"render_qa_result": {"passed": True}},
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "human_review_node",
        lambda _state: reached.append("human_review")
        or {"review_status": "approved", "review_route": "final_policy_guard"},
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "final_policy_guard_node",
        lambda _state: reached.append("final_policy_guard")
        or {"final_policy_issues": []},
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "content_writer_node",
        lambda _state: reached.append("content_writer") or {"data_writed": True},
    )

    graph = graph_module.create_graph(checkpointer=checkpointer)
    current, run_input = main_module.load_run_state(graph, config, {})

    assert run_input is None
    assert current.next == ("storyboard_generator",)
    assert current.values["editorial_workflow_version"] == MODERN_EDITORIAL_V2
    assert current.values["legacy_editorial_checkpoint"] is False
    assert current.values["visual_plan"] is not None
    assert current.values["asset_manifest"] is None
    assert current.values["render_manifest"] is None
    assert "storyboards" not in current.values["publish_package"]
    assert "rendered_image_paths" not in current.values["publish_package"]

    completed = graph.invoke(None, config=config)

    assert completed["data_writed"] is True
    assert reached == [
        "storyboard_generator",
        "asset_resolver",
        "carousel_qa",
        "editorial_carousel_renderer",
        "render_qa",
        "human_review",
        "final_policy_guard",
        "content_writer",
    ]
