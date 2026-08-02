"""Domain workflow integration for the ``llm_scene_v3`` pipeline.

Replaces the pre-v3 ``storyboard``-based domain workflow test (deleted with the
fixed-card renderer) with its v3 successors:

* The old ``test_semantic_storyboard_schema_error_stops_before_asset_resolution``
  intent -> a forbidden visible-copy finding (the v3 content-atomizer gate) MUST
  route to R2 compliance and stop the visual chain BEFORE ``asset_resolver`` or
  the structured visual nodes ever run. Under v3 the atomizer is the gate that
  predecessor's ``carousel_qa``/storyboard-validator used to be.
* Multi-domain context propagation: a non-beauty ``domain_context`` (wellness,
  healthy_lifestyle) is carried through the dynamic visual chain unchanged.
"""

from __future__ import annotations

from typing import Any

from tests.dynamic_visual.golden_fixtures import CaseSpec, GoldenHarness

FORBIDDEN_TOKEN = "仅供参考"


class _R2ComplianceReached(Exception):
    def __init__(self, state) -> None:
        self.state = state


class _AssetResolverReached(Exception):
    """Raised if asset_resolver runs -- it must NOT on a forbidden-copy stop."""


def _forbidden_copy_spec() -> CaseSpec:
    return CaseSpec(
        case_id="domain-forbidden-copy",
        family="deep_teal",
        page_count=5,
        density="standard",
        copy_shape="narrative",
        asset_mode="text-only",
        note="forbidden visible copy gate",
        publish_package={
            "topic_id": "tp_forbidden",
            "angle_id": "ag_forbidden",
            "topic": "测试禁止可见文案",
            "angle": "内容原子门禁",
            "target_group": "测试人群",
            "core_pain": "测试",
            "focus_keyword": "测试",
            "title": "测试禁止可见文案",
            "cover_copy": "封面文案",
            # A disclaimer line the content atomizer must catch.
            "content": f"第一段正文内容\n第二段正文内容\n{FORBIDDEN_TOKEN}不能进入视觉链",
            "hashtags": ["#测试"],
            "domain": "beauty",
            "subdomain": "skincare",
            "content_contract": {"first_screen_promise": "首屏承诺"},
        },
        human_review_payload={"approved": True},
    )


def _wellness_spec() -> CaseSpec:
    return CaseSpec(
        case_id="domain-wellness",
        family="green_catalog",
        page_count=6,
        density="standard",
        copy_shape="checklist",
        asset_mode="text-only",
        note="wellness domain context propagation",
        publish_package={
            "topic_id": "tp_wellness_sleep",
            "angle_id": "ag_wellness_sleep",
            "topic": "睡前放松清单",
            "angle": "可保存的睡前习惯",
            "target_group": "失眠人群",
            "core_pain": "入睡困难",
            "focus_keyword": "睡前放松",
            "title": "睡前放松清单",
            "cover_copy": "五个可保存的睡前习惯",
            "content": "\n".join(
                [
                    "- 睡前一小时调暗灯光",
                    "- 放下手机做几次深呼吸",
                    "- 用温水泡脚十分钟",
                    "- 记录三件今天值得开心的事",
                ]
            ),
            "hashtags": ["#睡前放松", "#失眠"],
            "domain": "wellness",
            "subdomain": "sleep",
            "content_contract": {"first_screen_promise": "五个可保存的睡前习惯"},
        },
        human_review_payload={"approved": True},
    )


def test_forbidden_visible_copy_stops_before_asset_resolution(
    tmp_path, monkeypatch
):
    """A forbidden visible-copy finding routes to R2 compliance at the content
    atomizer; the visual chain (asset_resolver + structured visual nodes) MUST
    NEVER run. This is the v3 successor of the old storyboard-schema-error
    'stops before asset resolution' guarantee."""
    spec = _forbidden_copy_spec()
    harness = GoldenHarness(spec=spec, tmp_path=tmp_path)

    def r2_sentinel(state):
        raise _R2ComplianceReached(state)

    def asset_resolver_sentinel(state, **_kwargs):
        raise _AssetResolverReached(state)

    harness.overrides = {
        "r2_compliance_node": r2_sentinel,
        "asset_resolver_node": asset_resolver_sentinel,
    }
    monkeypatch.chdir(tmp_path)
    harness.install(monkeypatch)
    # content_atomizer is REAL and runs before any visual node.
    # The graph will pause/return at the r2 sentinel; no human_review involved.
    import pytest
    from langgraph.checkpoint.memory import InMemorySaver
    from src import graph as graph_module

    graph = graph_module.create_graph(checkpointer=InMemorySaver())
    config = {
        "configurable": {"thread_id": "domain-forbidden"},
        "recursion_limit": 80,
    }
    with pytest.raises(_R2ComplianceReached) as excinfo:
        graph.invoke(harness.initial_state(), config=config)
    state = excinfo.value.state
    assert state.get("content_atomization_route") == "r2_compliance"
    issues = state.get("content_atomization_issues") or []
    assert any(FORBIDDEN_TOKEN in issue for issue in issues)
    # The visual chain never produced any artifacts.
    assert state.get("visual_direction_plan") is None
    assert state.get("asset_manifest") is None
    assert state.get("carousel_design_plan") is None


def test_wellness_domain_context_propagates_through_visual_chain(
    tmp_path, monkeypatch
):
    """A non-beauty (wellness) domain_context is carried unchanged through the
    dynamic visual chain to the terminal state."""
    spec = _wellness_spec()
    harness = GoldenHarness(spec=spec, tmp_path=tmp_path)
    state = harness.run(monkeypatch)

    assert state.get("review_status") == "approved"
    assert state.get("final_policy_issues") == []
    assert state["domain_context"]["domain"] == "wellness"
    assert state["publish_package"]["focus_keyword"] == "睡前放松"
    # The visual plan still binds to the atoms produced from wellness copy.
    atom_set = state["content_atom_set"]
    assert state["visual_direction_plan"].content_atom_set_sha256 == (
        atom_set.canonical_sha256
    )
