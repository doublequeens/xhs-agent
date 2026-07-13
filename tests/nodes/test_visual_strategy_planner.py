from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.schemas.content_contract import ContentContract
from tests.editorial_carousel.test_strategy import contract_for


def _state(contract: ContentContract | dict | None = None) -> dict:
    return {
        "publish_package": {
            "topic_id": "topic-001",
            "title": "分区护肤指南",
            "content_contract": contract or contract_for("diagnose_and_adjust"),
        },
        "evidence_briefs": {
            "topic-001": SimpleNamespace(items=[], unsupported_claims=[])
        },
        "memory_context": {"recent_content": []},
    }


def test_visual_strategy_planner_builds_plan_from_final_publish_package():
    from src.nodes.node_p_visual_strategy_planner import (
        visual_strategy_planner_node,
    )

    result = visual_strategy_planner_node(_state())

    assert set(result) == {"visual_plan"}
    assert result["visual_plan"].content_job == "diagnose_and_adjust"
    assert result["visual_plan"].primary_visual_family == "face_zone_map"


def test_visual_strategy_planner_uses_recent_published_frame_plan_signatures():
    from src.editorial_carousel.strategy import build_visual_plan
    from src.nodes.node_p_visual_strategy_planner import (
        visual_strategy_planner_node,
    )

    contract = contract_for("diagnose_and_adjust")
    original = build_visual_plan(contract, recent_signatures=[])
    signature = [
        [frame.role, frame.layout]
        for frame in original.frame_plan
    ]
    state = _state(contract)
    state["memory_context"]["recent_content"] = [
        {"frame_plan_signature": signature}
    ]

    result = visual_strategy_planner_node(state)

    assert result["visual_plan"].frame_plan[4].layout == "decision_tree"


def test_visual_strategy_planner_requires_publish_package_contract():
    from src.nodes.node_p_visual_strategy_planner import (
        visual_strategy_planner_node,
    )

    state = _state()
    state["publish_package"].pop("content_contract")

    with pytest.raises(
        ValueError,
        match="visual_strategy_planner_node requires publish_package.content_contract",
    ):
        visual_strategy_planner_node(state)


def test_visual_strategy_planner_does_not_apply_legacy_hydration():
    from src.nodes.node_p_visual_strategy_planner import (
        visual_strategy_planner_node,
    )

    incomplete = contract_for("save_and_check").model_dump(mode="json")
    incomplete.pop("content_job")

    with pytest.raises(ValidationError):
        visual_strategy_planner_node(_state(incomplete))
