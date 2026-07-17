from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.schemas.content_contract import ContentContract
from src.schemas.narrative import NarrativePlan
from tests.editorial_carousel.test_strategy import (
    contract_for,
    narrative_plan_for,
    publish_package_for,
)


def _state(
    contract: ContentContract | dict | None = None,
    narrative_plan: NarrativePlan | dict | None = None,
) -> dict:
    resolved_contract = contract or contract_for(
        "diagnose_and_adjust",
        proof_mode="none",
    )
    resolved_narrative = narrative_plan or narrative_plan_for("diagnostic_qa")
    validated_contract = ContentContract.model_validate(resolved_contract)
    validated_narrative = NarrativePlan.model_validate(resolved_narrative)
    return {
        "publish_package": publish_package_for(
            validated_contract,
            validated_narrative,
        ),
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

    assert set(result) == {
        "visual_plan",
        "editorial_workflow_version",
        "legacy_editorial_checkpoint",
        "asset_manifest",
        "render_manifest",
        "carousel_qa_result",
        "render_qa_result",
    }
    assert result["editorial_workflow_version"] == "modern_v2"
    assert result["legacy_editorial_checkpoint"] is False
    assert result["visual_plan"].content_job == "diagnose_and_adjust"
    assert result["visual_plan"].narrative_form == "diagnostic_qa"
    assert result["visual_plan"].design_system == "beauty_editorial_v2"


def test_visual_strategy_planner_uses_recent_visual_signatures():
    from src.nodes.node_p_visual_strategy_planner import (
        visual_strategy_planner_node,
    )

    state = _state(
        contract_for(
            "understand_and_notice",
            proof_mode="none",
            recommended_frame_count=5,
        ),
        narrative_plan_for("cognitive_correction"),
    )
    first = visual_strategy_planner_node(state)["visual_plan"]
    state["memory_context"]["recent_content"] = [
        {
            "visual_plan": first.model_dump(mode="json"),
        }
    ]

    repeated = visual_strategy_planner_node(state)["visual_plan"]

    assert (
        repeated.template_family != first.template_family
        or repeated.frame_plan != first.frame_plan
    )
    assert len(repeated.frame_plan) == len(first.frame_plan) == 5


def test_visual_strategy_planner_ignores_noncanonical_signature_aliases():
    from src.nodes.node_p_visual_strategy_planner import (
        visual_strategy_planner_node,
    )

    state = _state(
        contract_for(
            "understand_and_notice",
            proof_mode="none",
            recommended_frame_count=5,
        ),
        narrative_plan_for("cognitive_correction"),
    )
    baseline = visual_strategy_planner_node(state)["visual_plan"]
    signature = {
        "narrative_form": baseline.narrative_form,
        "template_family": baseline.template_family,
        "frame_plan_signature": [
            frame.page_archetype for frame in baseline.frame_plan
        ],
        "frame_count": len(baseline.frame_plan),
    }
    state["memory_context"] = {
        "recent_frame_plan_signatures": [signature],
        "frame_plan_signatures": [signature],
        "recent_content": [
            signature,
            {"visual_signature": signature},
            {"frame_plan_signature": signature},
        ],
    }

    result = visual_strategy_planner_node(state)["visual_plan"]

    assert result == baseline


def test_visual_strategy_planner_honors_canonical_recent_visual_signatures():
    from src.nodes.node_p_visual_strategy_planner import (
        visual_strategy_planner_node,
    )

    state = _state(
        contract_for(
            "understand_and_notice",
            proof_mode="none",
            recommended_frame_count=5,
        ),
        narrative_plan_for("cognitive_correction"),
    )
    first = visual_strategy_planner_node(state)["visual_plan"]
    # The canonical v2 key is honored directly (no visual_plan fallback needed),
    # including the full persisted 5-key shape (with density_profile).
    state["memory_context"]["recent_visual_signatures"] = [
        {
            "narrative_form": first.narrative_form,
            "template_family": first.template_family,
            "frame_plan_signature": [
                frame.page_archetype for frame in first.frame_plan
            ],
            "frame_count": len(first.frame_plan),
            "density_profile": ["standard"] * len(first.frame_plan),
        }
    ]

    repeated = visual_strategy_planner_node(state)["visual_plan"]

    assert (
        repeated.template_family != first.template_family
        or repeated.frame_plan != first.frame_plan
    )
    assert len(repeated.frame_plan) == len(first.frame_plan) == 5


def test_visual_strategy_planner_ignores_non_strict_embedded_visual_plan():
    from src.nodes.node_p_visual_strategy_planner import (
        visual_strategy_planner_node,
    )

    state = _state(
        contract_for(
            "understand_and_notice",
            proof_mode="none",
            recommended_frame_count=5,
        ),
        narrative_plan_for("cognitive_correction"),
    )
    baseline = visual_strategy_planner_node(state)["visual_plan"]
    invalid_plan = baseline.model_dump(mode="json")
    invalid_plan["design_system"] = "beauty_editorial_v1"
    state["memory_context"]["recent_content"] = [
        {"visual_plan": invalid_plan}
    ]

    result = visual_strategy_planner_node(state)["visual_plan"]

    assert result == baseline


@pytest.mark.parametrize(
    ("missing_key", "message"),
    [
        (
            "content_contract",
            "visual_strategy_planner_node requires publish_package.content_contract",
        ),
        (
            "narrative_plan",
            "visual_strategy_planner_node requires publish_package.narrative_plan",
        ),
    ],
)
def test_visual_strategy_planner_requires_final_planning_contracts(
    missing_key: str,
    message: str,
):
    from src.nodes.node_p_visual_strategy_planner import (
        visual_strategy_planner_node,
    )

    state = _state()
    state["publish_package"].pop(missing_key)

    with pytest.raises(ValueError, match=message):
        visual_strategy_planner_node(state)


def test_visual_strategy_planner_does_not_apply_legacy_hydration():
    from src.nodes.node_p_visual_strategy_planner import (
        visual_strategy_planner_node,
    )

    state = _state()
    state["publish_package"]["content_contract"].pop("content_job")

    with pytest.raises(ValidationError):
        visual_strategy_planner_node(state)
