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

    issue = next(item for item in issues if item.rule_id == "frame_role_mismatch")
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
    assert route_after_carousel_qa(passed) == "editorial_carousel_renderer"

    broken = deepcopy(_package())
    broken["storyboards"][0]["headline"] = "错误承诺"
    failed = carousel_qa_node(_state(package=broken))
    assert failed["carousel_qa_result"].passed is False
    assert route_after_carousel_qa(failed) == "r1_reflector"


def test_carousel_qa_rejects_plan_storyboard_length_mismatch_before_traversal():
    from src.nodes.node_p_carousel_qa import validate_carousel

    package = _package()
    extra = deepcopy(package["storyboards"][1])
    extra.update(
        frame_id="extra-frame",
        role="extra-task",
        layout="step_timeline",
        visual_slots=[],
    )
    package["storyboards"].append(extra)

    issues = validate_carousel(package, _contract(), _plan())

    assert [(issue.rule_id, issue.location_hint) for issue in issues] == [
        ("frame_plan_count_mismatch", "visual_plan.frame_plan")
    ]


@pytest.mark.parametrize(
    ("target", "rule_id", "location"),
    [
        ("plan_frame", "duplicate_plan_frame_id", "visual_plan.frame_plan[1].frame_id"),
        ("storyboard_frame", "duplicate_storyboard_frame_id", "storyboards[1].frame_id"),
        (
            "storyboard_slot",
            "duplicate_storyboard_slot_id",
            "storyboards[0].visual_slots[1].slot_id",
        ),
        (
            "requirement_slot",
            "duplicate_asset_requirement_slot_id",
            "visual_plan.required_assets[1].slot_id",
        ),
    ],
)
def test_carousel_qa_rejects_duplicate_identity_before_mapping(
    target, rule_id, location
):
    from src.nodes.node_p_carousel_qa import validate_carousel

    plan = _plan().model_dump(mode="python")
    package = _package()
    if target == "plan_frame":
        plan["frame_plan"][1]["frame_id"] = plan["frame_plan"][0]["frame_id"]
    elif target == "storyboard_frame":
        package["storyboards"][1]["frame_id"] = package["storyboards"][0]["frame_id"]
    elif target == "storyboard_slot":
        package["storyboards"][0]["visual_slots"].append(
            deepcopy(package["storyboards"][0]["visual_slots"][0])
        )
    else:
        plan["required_assets"][1]["slot_id"] = plan["required_assets"][0]["slot_id"]

    issues = validate_carousel(package, _contract(), plan)

    issue = next(item for item in issues if item.rule_id == rule_id)
    assert issue.location_hint == location


def test_schema_invalid_frame_does_not_cascade_into_dependent_rules():
    from src.nodes.node_p_carousel_qa import validate_carousel

    package = _package()
    package["storyboards"][2]["free_css"] = "position:absolute"
    package["storyboards"][2]["role"] = "also-wrong"
    package["storyboards"][2]["layout"] = "decision_tree"

    issues = validate_carousel(package, _contract(), _plan())
    frame_issues = [issue for issue in issues if issue.frame_id == "applicable-case"]

    assert [issue.rule_id for issue in frame_issues] == ["storyboard_schema_invalid"]


def test_role_and_layout_drift_are_separate_atomic_issues():
    from src.nodes.node_p_carousel_qa import validate_carousel

    package = _package()
    package["storyboards"][2]["role"] = "wrong-role"
    package["storyboards"][2]["layout"] = "decision_tree"

    issues = validate_carousel(package, _contract(), _plan())
    drift = [
        (issue.rule_id, issue.location_hint)
        for issue in issues
        if issue.frame_id == "applicable-case"
        and issue.rule_id in {"frame_role_mismatch", "frame_layout_mismatch"}
    ]

    assert drift == [
        ("frame_role_mismatch", "storyboards[2].role"),
        ("frame_layout_mismatch", "storyboards[2].layout"),
    ]


def test_r1_task_identity_does_not_depend_on_issue_order():
    from src.nodes.node_p_carousel_qa import _build_r1_tasks

    cover = CarouselQAIssue(
        rule_id="first_screen_promise_mismatch",
        message="cover mismatch",
        location_hint="storyboards[0].headline",
        frame_id="cover",
    )
    unrelated = CarouselQAIssue(
        rule_id="missing_saveable_frame",
        message="saveable missing",
        location_hint="storyboards",
    )

    alone = _build_r1_tasks([cover]).mandatory[0].task_id
    reordered = _build_r1_tasks([unrelated, cover]).mandatory[1].task_id

    assert alone == reordered


def test_semantic_state_missing_visual_plan_is_not_legacy_fixed_six():
    from src.nodes.node_p_carousel_qa import carousel_qa_node

    state = _state()
    state.pop("visual_plan")

    result = carousel_qa_node(state)

    assert [issue.rule_id for issue in result["carousel_qa_result"].issues] == [
        "visual_plan_missing"
    ]


def test_authoritative_topic_contract_cannot_be_overridden_by_package_contract():
    from src.nodes.node_p_carousel_qa import carousel_qa_node

    authoritative = _contract()
    tampered = authoritative.model_copy(
        update={"first_screen_promise": "这是被篡改后的另一句首屏承诺"}
    )
    package = _package()
    package["content_contract"] = tampered.model_dump(mode="json")
    package["storyboards"][0]["headline"] = tampered.first_screen_promise
    state = _state(package=package)

    result = carousel_qa_node(state)

    assert [issue.rule_id for issue in result["carousel_qa_result"].issues[:2]] == [
        "content_contract_mismatch",
        "first_screen_promise_mismatch",
    ]


def test_storyboard_slot_ids_are_unique_across_the_entire_carousel():
    from src.nodes.node_p_carousel_qa import validate_carousel

    package = _package()
    package["storyboards"][1]["visual_slots"][0]["slot_id"] = package[
        "storyboards"
    ][0]["visual_slots"][0]["slot_id"]
    package["storyboards"][0]["headline"] = "independent cover failure"

    issues = validate_carousel(package, _contract(), _plan())

    assert (
        "duplicate_storyboard_slot_id",
        "storyboards[1].visual_slots[0].slot_id",
    ) in [(issue.rule_id, issue.location_hint) for issue in issues]
    assert "first_screen_promise_mismatch" in _rule_ids(issues)
    assert not any(
        issue.rule_id.startswith("asset_requirement_")
        and issue.frame_id in {"cover", "baseline"}
        for issue in issues
    )


def test_length_mismatch_does_not_hide_independent_cover_failure():
    from src.nodes.node_p_carousel_qa import validate_carousel

    package = _package()
    package["storyboards"].append(deepcopy(package["storyboards"][-1]))
    package["storyboards"][-1]["frame_id"] = "extra"
    package["storyboards"][0]["headline"] = "independent cover failure"

    issues = validate_carousel(package, _contract(), _plan())

    assert "frame_plan_count_mismatch" in _rule_ids(issues)
    assert "first_screen_promise_mismatch" in _rule_ids(issues)


def test_duplicate_identity_does_not_hide_unrelated_frame_failure():
    from src.nodes.node_p_carousel_qa import validate_carousel

    plan = _plan().model_dump(mode="python")
    plan["frame_plan"][1]["frame_id"] = plan["frame_plan"][0]["frame_id"]
    package = _package()
    package["storyboards"][4]["role"] = "unrelated-wrong-role"

    issues = validate_carousel(package, _contract(), plan)

    assert "duplicate_plan_frame_id" in _rule_ids(issues)
    assert any(
        issue.rule_id == "frame_role_mismatch"
        and issue.frame_id == "feedback-diagnosis"
        for issue in issues
    )


def test_invalid_frame_does_not_hide_independent_valid_frame_composition_issue():
    from src.nodes.node_p_carousel_qa import validate_carousel

    package = _package()
    package["storyboards"][2]["free_css"] = "position:absolute"
    package["storyboards"][5]["layout"] = package["storyboards"][4]["layout"]

    issues = validate_carousel(package, _contract(), _plan())

    invalid_frame_rules = [
        issue.rule_id for issue in issues if issue.frame_id == "applicable-case"
    ]
    assert invalid_frame_rules == ["storyboard_schema_invalid"]
    assert any(
        issue.rule_id == "consecutive_layout_repeat" and issue.frame_id == "save"
        for issue in issues
    )


def test_asset_requirement_role_and_layout_drift_are_atomic():
    from src.nodes.node_p_carousel_qa import validate_carousel

    plan = _plan().model_dump(mode="python")
    plan["required_assets"][0]["role"] = "wrong-role"
    plan["required_assets"][0]["layout"] = "texture_baseline"

    issues = validate_carousel(_package(), _contract(), plan)
    drift = [
        (issue.rule_id, issue.location_hint)
        for issue in issues
        if issue.rule_id
        in {"asset_requirement_role_mismatch", "asset_requirement_layout_mismatch"}
    ]

    assert drift == [
        ("asset_requirement_role_mismatch", "visual_plan.required_assets[0].role"),
        (
            "asset_requirement_layout_mismatch",
            "visual_plan.required_assets[0].layout",
        ),
    ]


def test_each_missing_semantic_slot_gets_a_unique_stable_task_id():
    from src.nodes.node_p_carousel_qa import _build_r1_tasks, validate_carousel

    plan = _plan().model_dump(mode="python")
    plan["frame_plan"][0]["asset_roles"] = [
        "beauty_subject",
        "beauty_subject",
        "beauty_subject",
    ]
    package = _package()
    package["storyboards"][0]["visual_slots"] = []

    missing = [
        issue
        for issue in validate_carousel(package, _contract(), plan)
        if issue.rule_id == "semantic_slot_role_mismatch"
        and ".missing_role[" in issue.location_hint
    ]
    task_ids = [task.task_id for task in _build_r1_tasks(missing).mandatory]

    assert len(missing) == 3
    assert len(task_ids) == len(set(task_ids)) == 3
