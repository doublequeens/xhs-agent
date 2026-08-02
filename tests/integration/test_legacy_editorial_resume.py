from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
import pytest

import main as main_module
import src.graph as graph_module
from src.editorial_carousel.legacy import (
    DYNAMIC_REENTRY_PREDECESSOR,
    DYNAMIC_VISUAL_V3,
    dynamic_visual_transition_updates,
)
from src.schemas import AgentState
from src.schemas.visual_critique import VisualCritique


_LEGACY_VISUAL_SUCCESSORS = (
    "content_atomizer",
    "visual_director",
    "asset_resolver",
    "page_designer",
    "design_plan_qa",
    "design_reviser",
    "generic_scene_renderer",
    "render_qa",
    "visual_critic",
    "human_review",
    "final_policy_guard",
    "content_writer",
)


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


def _legacy_package(*, with_storyboards=True, with_render=False, with_visual_plan=True):
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
    if with_visual_plan:
        package["visual_plan"] = {
            "design_system": "beauty_editorial_v1",
            "template_family": "pink_red",
            "frame_plan": [
                {"frame_id": f"frame-{i}", "layout": "editorial_cover"}
                for i in range(1, 6)
            ],
        }
    return package


def _preserved_state_payload(package):
    """Content/R1/R2/title/hashtags/assembler package fields that must survive."""

    return {
        "domain_context": {"domain": "beauty", "subdomain": "skincare"},
        "r1_output": {"draft_id": "draft-legacy", "scores": {"clarity": 8}},
        "r2_output": {"compliance_audit": {"block_publish": False}},
        "hashtags": {"tags": ["#旧版"]},
        "title_winner": {"title": "旧版卡片"},
        "publish_package": package,
    }


@pytest.mark.parametrize(
    "successor",
    _LEGACY_VISUAL_SUCCESSORS,
)
def test_legacy_visual_successor_migrates_to_dynamic_v3_and_reenters_atomizer(
    monkeypatch, successor
):
    checkpointer = InMemorySaver()
    config = {"configurable": {"thread_id": f"legacy-{successor}"}}
    package = _legacy_package()
    _old_checkpoint(
        checkpointer,
        config,
        predecessor="assembler",
        successor=successor,
        values=_preserved_state_payload(package),
    )
    calls = {"as_node": None}

    class FakeGraph:
        def __init__(self, real_graph):
            self._real = real_graph

        def __getattr__(self, name):
            return getattr(self._real, name)

        def update_state(self, cfg, updates, *, as_node=None):
            calls["as_node"] = as_node
            return self._real.update_state(cfg, updates, as_node=as_node)

    real_graph = graph_module.create_graph(checkpointer=checkpointer)
    current, run_input = main_module.load_run_state(
        FakeGraph(real_graph), config, {}
    )

    # Resume always re-enters at the assembler -> content_atomizer seam.
    assert run_input is None
    assert current.next == ("content_atomizer",)
    assert calls["as_node"] == DYNAMIC_REENTRY_PREDECESSOR == "assembler"
    # Version is stamped; legacy flag cleared.
    assert current.values["editorial_workflow_version"] == DYNAMIC_VISUAL_V3
    assert current.values["legacy_editorial_checkpoint"] is False
    # Old visual artifacts are gone from the package.
    assert "storyboards" not in current.values["publish_package"]
    assert "rendered_image_paths" not in current.values["publish_package"]
    # Preserved content/R1/R2/title/hashtags survive untouched.
    assert current.values["r1_output"] == {"draft_id": "draft-legacy", "scores": {"clarity": 8}}
    assert current.values["r2_output"] == {"compliance_audit": {"block_publish": False}}
    assert current.values["hashtags"] == {"tags": ["#旧版"]}
    assert current.values["publish_package"]["title"] == "旧版卡片"
    # New visual state slots are wiped so content_atomizer re-derives them.
    assert current.values["content_atom_set"] is None
    assert current.values["visual_direction_plan"] is None
    assert current.values["asset_manifest"] is None
    assert current.values["render_manifest"] is None
    assert current.values["render_qa_result"] is None
    assert current.values["visual_critique"] is None


def test_dynamic_visual_transition_updates_preserves_package_and_drops_storyboards():
    package = _legacy_package()
    values = {"publish_package": package}

    updates = dynamic_visual_transition_updates(values)

    assert updates["editorial_workflow_version"] == DYNAMIC_VISUAL_V3
    assert updates["legacy_editorial_checkpoint"] is False
    # Content package is preserved (title/hashtags/contract survive) but the
    # obsolete storyboard frames are stripped.
    assert updates["publish_package"]["title"] == "旧版卡片"
    assert updates["publish_package"]["hashtags"] == ["#旧版"]
    assert "storyboards" not in updates["publish_package"]
    # Every dynamic visual slot is reset so the new pipeline rebuilds it.
    for cleared in (
        "content_atom_set",
        "visual_direction_plan",
        "asset_manifest",
        "carousel_design_plan",
        "design_plan_qa_result",
        "render_manifest",
        "render_qa_result",
        "visual_critique",
    ):
        assert updates[cleared] is None
    assert updates["review_status"] is None
    assert updates["review_route"] is None


def test_dynamic_visual_transition_updates_handles_missing_package():
    updates = dynamic_visual_transition_updates({})

    assert updates["editorial_workflow_version"] == DYNAMIC_VISUAL_V3
    assert updates["publish_package"] == {}
    assert updates["content_atom_set"] is None


def test_resuming_migrated_checkpoint_runs_content_atomizer_not_old_renderer(
    monkeypatch,
):
    """The migrated run must execute content_atomizer first; never an old renderer."""

    checkpointer = InMemorySaver()
    config = {"configurable": {"thread_id": "legacy-resume"}}
    package = _legacy_package()
    _old_checkpoint(
        checkpointer,
        config,
        predecessor="assembler",
        successor="human_review",
        values=_preserved_state_payload(package),
    )
    invoked: list[str] = []

    monkeypatch.setattr(
        graph_module.nodes,
        "content_atomizer_node",
        lambda state: invoked.append("content_atomizer")
        or {
            "content_atom_set": {"atoms": []},
            "content_atomization_route": "visual_director",
            "content_atomization_issues": [],
        },
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "visual_director_node",
        lambda _state, **kwargs: invoked.append("visual_director")
        or {"visual_direction_plan": {"page_sequence": []}},
    )
    # Asset resolver must not be re-run on a migrated, asset-free checkpoint.
    monkeypatch.setattr(
        "src.asset_resolver.resolver.resolve_asset_directives",
        lambda *_args, **_kwargs: pytest.fail("resume must not resolve old assets"),
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "asset_resolver_node",
        lambda _state, **kwargs: invoked.append("asset_resolver")
        or {"asset_manifest": {"items": []}, "unresolved_optional_assets": []},
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "page_designer_node",
        lambda _state, **kwargs: invoked.append("page_designer") or {"carousel_design_plan": {"pages": []}},
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "design_plan_qa_node",
        lambda _state: invoked.append("design_plan_qa")
        or {"design_plan_qa_result": {"passed": True}},
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "generic_scene_renderer_node",
        lambda _state: invoked.append("generic_scene_renderer") or {"render_manifest": {"pages": []}},
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "render_qa_node",
        lambda _state: invoked.append("render_qa") or {"render_qa_result": {"passed": True}},
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "visual_critic_node",
        lambda _state, **kwargs: invoked.append("visual_critic")
        or {"visual_critique": VisualCritique.model_construct(passed=True, revision_round=0)},
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "human_review_node",
        lambda _state: invoked.append("human_review")
        or {"review_status": "approved", "review_route": "final_policy_guard"},
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "final_policy_guard_node",
        lambda _state: invoked.append("final_policy_guard") or {"final_policy_issues": []},
    )
    monkeypatch.setattr(
        graph_module.nodes,
        "content_writer_node",
        lambda _state: invoked.append("content_writer") or {"data_writed": True},
    )

    graph = graph_module.create_graph(checkpointer=checkpointer)
    main_module.load_run_state(graph, config, {})

    completed = graph.invoke(None, config=config)

    assert completed["data_writed"] is True
    # The dynamic visual chain runs in order; no retired renderer executes.
    assert invoked[0] == "content_atomizer"
    assert "editorial_carousel_renderer" not in invoked
    assert "carousel_qa" not in invoked
    assert "storyboards_generator" not in invoked
    assert "visual_strategy_planner" not in invoked
    assert invoked == [
        "content_atomizer",
        "visual_director",
        "asset_resolver",
        "page_designer",
        "design_plan_qa",
        "generic_scene_renderer",
        "render_qa",
        "visual_critic",
        "human_review",
        "final_policy_guard",
        "content_writer",
    ]


def test_unknown_future_editorial_version_fails_closed(monkeypatch):
    main = main_module
    from types import SimpleNamespace

    state = SimpleNamespace(
        values={
            "domain_context": {"domain": "beauty"},
            "editorial_workflow_version": "attacker_v9",
            "publish_package": {"title": "x"},
        },
        next=("content_atomizer",),
    )

    class FakeGraph:
        def get_state(self, _config):
            return state

        def update_state(self, *_args, **_kwargs):
            raise AssertionError("unknown versions must not be rewritten")

    with pytest.raises(ValueError, match="unsupported editorial workflow version"):
        main.load_run_state(
            FakeGraph(), {"configurable": {"thread_id": "unknown-version"}}, {}
        )


def test_modern_v3_checkpoint_is_not_re_migrated(monkeypatch):
    main = main_module
    from types import SimpleNamespace

    state = SimpleNamespace(
        values={
            "domain_context": {"domain": "beauty"},
            "editorial_workflow_version": DYNAMIC_VISUAL_V3,
            "publish_package": {"title": "v3"},
            "content_atom_set": {"atoms": [{"atom_id": "title-001"}]},
            "visual_direction_plan": {"page_sequence": [{"page_id": "p-1"}]},
        },
        next=("visual_director",),
    )

    class FakeGraph:
        def get_state(self, _config):
            return state

        def update_state(self, *_args, **_kwargs):
            raise AssertionError("v3 checkpoint must not be re-migrated")

    current, run_input = main.load_run_state(
        FakeGraph(), {"configurable": {"thread_id": "v3"}}, {}
    )

    assert run_input is None
    assert current.values["content_atom_set"] == {"atoms": [{"atom_id": "title-001"}]}
    assert current.next == ("visual_director",)
