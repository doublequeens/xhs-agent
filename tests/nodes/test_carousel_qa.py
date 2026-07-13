from copy import deepcopy

import pytest
from pydantic import ValidationError

from src.editorial_carousel.strategy import ASSET_ADAPTER, build_visual_plan
from src.schemas.carousel_qa import CarouselQAIssue
from src.schemas.content_contract import ContentContract


def _contract() -> ContentContract:
    return ContentContract.model_validate(
        {
            "audience": "通勤女性",
            "trigger_situation": "早高峰上班前",
            "decision_problem": "防晒和底妆如何不打架",
            "first_screen_promise": "通勤前3步避开防晒搓泥",
            "screenshot_asset": "防晒与底妆搭配清单",
            "proof_asset": "产品质地实拍",
            "visual_mode": "text_plus_real_proof",
            "content_job": "diagnose_and_adjust",
            "primary_visual_family": "face_zone_map",
            "primary_visual_subject": "face_map",
            "proof_mode": "product_texture",
            "recommended_frame_count": 6,
        }
    )


def _plan():
    return build_visual_plan(_contract(), recent_signatures=[])


def _storyboards(plan=None):
    plan = plan or _plan()
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
                    _contract().first_screen_promise
                    if index == 0
                    else planned.purpose
                ),
                "kicker": "分区护肤",
                "content_blocks": [
                    {
                        "block_type": "text",
                        "body": planned.purpose,
                    }
                ],
                "emphasis": ["分区"],
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


def _package(plan=None):
    return {
        "draft_id": "draft_001",
        "topic_id": "tp_001",
        "topic": "通勤底妆",
        "angle_id": "ag_001",
        "angle": "防晒打底顺序",
        "target_group": "通勤女性",
        "core_pain": "防晒后底妆搓泥",
        "title": "通勤底妆不搓泥",
        "content": "先给防晒成膜时间，再上底妆。",
        "cover_copy": "通勤底妆不搓泥",
        "content_contract": _contract().model_dump(mode="json"),
        "storyboards": _storyboards(plan),
    }


def _state(plan=None, package=None):
    plan = plan or _plan()
    return {
        "visual_plan": plan,
        "publish_package": package or _package(plan),
        "trends": [
            {
                "topic_id": "tp_001",
                "content_contract": _contract().model_dump(mode="json"),
            }
        ],
    }


def _rule_ids(issues):
    return [issue.rule_id for issue in issues]


def test_carousel_qa_issue_rejects_unstable_rule_id():
    with pytest.raises(ValidationError):
        CarouselQAIssue(
            rule_id="Missing Saveable Frame",
            message="unstable identifier",
            location_hint="storyboards",
        )


def test_carousel_qa_accepts_editorial_invariants_and_semantic_role_adapter():
    from src.nodes.node_p_carousel_qa import validate_carousel

    plan = _plan()
    issues = validate_carousel(_package(plan), _contract(), plan)

    assert issues == []
    first_slot = _storyboards(plan)[0]["visual_slots"][0]
    first_requirement = plan.required_assets[0]
    assert first_slot["role"] == "beauty_subject"
    assert first_requirement.role == "background_token"


def test_carousel_qa_rejects_missing_saveable_frame():
    from src.nodes.node_p_carousel_qa import validate_carousel

    plan = _plan()
    plan_data = plan.model_dump(mode="python")
    package = _package(plan)
    plan_data["frame_plan"] = plan_data["frame_plan"][:-1]
    plan_data["required_assets"] = plan_data["required_assets"][:-1]
    package["storyboards"] = package["storyboards"][:-1]

    issues = validate_carousel(package, _contract(), plan_data)

    assert _rule_ids(issues) == ["missing_saveable_frame"]


def test_carousel_qa_rejects_frame_count_outside_five_to_seven():
    from src.nodes.node_p_carousel_qa import validate_carousel

    plan = _plan().model_dump(mode="python")
    package = _package()
    keep = [0, 1, 2, 5]
    plan["frame_plan"] = [plan["frame_plan"][index] for index in keep]
    package["storyboards"] = [package["storyboards"][index] for index in keep]

    issues = validate_carousel(package, _contract(), plan)

    assert _rule_ids(issues) == ["frame_count_out_of_range"]


def test_carousel_qa_rejects_cover_promise_mismatch():
    from src.nodes.node_p_carousel_qa import validate_carousel

    package = _package()
    package["storyboards"][0]["headline"] = "另一句封面承诺"

    issues = validate_carousel(package, _contract(), _plan())

    assert _rule_ids(issues) == ["first_screen_promise_mismatch"]
    assert issues[0].frame_id == "cover"
    assert issues[0].location_hint == "storyboards[0].headline"


def test_carousel_qa_rejects_layout_outside_declared_families():
    from src.nodes.node_p_carousel_qa import validate_carousel

    plan = _plan().model_dump(mode="python")
    plan["supporting_families"].remove("beauty_editorial")

    issues = validate_carousel(_package(), _contract(), plan)

    issue = next(item for item in issues if item.rule_id == "layout_family_mismatch")
    assert issue.frame_id == "cover"
    assert issue.location_hint == "visual_plan.frame_plan[0].layout"


def test_carousel_qa_rejects_less_than_three_layouts_and_consecutive_repeat():
    from src.nodes.node_p_carousel_qa import validate_carousel

    plan = _plan().model_dump(mode="python")
    package = _package()
    for index in range(1, 5):
        plan["frame_plan"][index]["layout"] = "saveable_reference"
        package["storyboards"][index]["layout"] = "saveable_reference"

    issues = validate_carousel(package, _contract(), plan)

    assert "insufficient_layout_variety" in _rule_ids(issues)
    repeated = [item for item in issues if item.rule_id == "consecutive_layout_repeat"]
    assert [item.frame_id for item in repeated] == [
        plan["frame_plan"][2]["frame_id"],
        plan["frame_plan"][3]["frame_id"],
        plan["frame_plan"][4]["frame_id"],
        plan["frame_plan"][5]["frame_id"],
    ]


def test_carousel_qa_rejects_frame_that_changes_its_single_planned_task():
    from src.nodes.node_p_carousel_qa import validate_carousel

    package = _package()
    package["storyboards"][2]["role"] = "unplanned_second_task"

    issues = validate_carousel(package, _contract(), _plan())

    issue = next(item for item in issues if item.rule_id == "frame_task_mismatch")
    assert issue.frame_id == "applicable-case"
    assert issue.location_hint == "storyboards[2].role"


def test_carousel_qa_rejects_semantic_slot_that_uses_concrete_catalog_role():
    from src.nodes.node_p_carousel_qa import validate_carousel

    plan = _plan()
    package = _package(plan)
    package["storyboards"][0]["visual_slots"][0]["role"] = "background_token"

    issues = validate_carousel(package, _contract(), plan)

    issue = next(
        item for item in issues if item.rule_id == "semantic_slot_role_mismatch"
    )
    assert issue.frame_id == "cover"
    assert issue.location_hint == "storyboards[0].visual_slots[0].role"


def test_carousel_qa_rejects_adapter_requirement_role_mismatch():
    from src.nodes.node_p_carousel_qa import validate_carousel

    plan = _plan().model_dump(mode="python")
    plan["required_assets"][0]["role"] = "beauty_subject"

    issues = validate_carousel(_package(), _contract(), plan)

    issue = next(
        item for item in issues if item.rule_id == "asset_requirement_role_mismatch"
    )
    assert issue.frame_id == "cover"
    assert issue.location_hint == "visual_plan.required_assets[0].role"


def test_carousel_qa_turns_schema_failure_into_atomic_r1_task():
    from src.nodes.node_p_carousel_qa import carousel_qa_node

    package = _package()
    package["storyboards"][0]["free_css"] = "position:absolute"

    result = carousel_qa_node(_state(package=package))

    schema_issue = next(
        issue
        for issue in result["carousel_qa_result"].issues
        if issue.rule_id == "storyboard_schema_invalid"
    )
    task = next(
        task
        for task in result[
            "decision_output"
        ].normalized_input.r1_input.editorial_tasks.mandatory
        if task.location_hint == schema_issue.location_hint
    )
    assert schema_issue.frame_id == "cover"
    assert task.source == "carousel_qa"
    assert task.severity == "high"
    assert result["decision_output"].next_node == "R1_REFLECTOR"


def test_carousel_qa_node_preserves_success_and_failure_routes():
    from src.nodes.node_p_carousel_qa import (
        carousel_qa_node,
        route_after_carousel_qa,
    )

    passed = carousel_qa_node(_state())
    assert passed["carousel_qa_result"].passed is True
    assert route_after_carousel_qa(passed) == "text_card_renderer"

    broken = deepcopy(_package())
    broken["storyboards"][0]["headline"] = "错误承诺"
    failed = carousel_qa_node(_state(package=broken))
    assert failed["carousel_qa_result"].passed is False
    assert route_after_carousel_qa(failed) == "r1_reflector"
