from copy import deepcopy

import pytest
from pydantic import ValidationError

from src.editorial_carousel import build_visual_plan
from src.schemas.carousel_qa import CarouselQAIssue
from src.schemas.content_contract import ContentContract
from src.schemas.narrative import NarrativePlan


def _contract(*, proof_mode: str = "none") -> ContentContract:
    return ContentContract.model_validate(
        {
            "audience": "通勤女性",
            "trigger_situation": "早高峰上班前",
            "decision_problem": "防晒和底妆如何不打架",
            "first_screen_promise": "通勤前3步避开防晒搓泥",
            "screenshot_asset": "防晒与底妆搭配清单",
            "proof_asset": "产品质地实拍",
            "visual_mode": (
                "text_card" if proof_mode == "none" else "text_plus_real_proof"
            ),
            "content_job": "diagnose_and_adjust",
            "primary_visual_family": "face_zone_map",
            "primary_visual_subject": "face_map",
            "proof_mode": proof_mode,
            "recommended_frame_count": 5,
        }
    )


def _narrative_plan() -> NarrativePlan:
    return NarrativePlan.model_validate(
        {
            "narrative_form": "scenario_story",
            "beats": [
                {"beat_id": "hook", "kind": "hook", "purpose": "建立阅读承诺"},
                {"beat_id": "scene", "kind": "scene", "purpose": "呈现通勤场景"},
                {"beat_id": "reveal", "kind": "reveal", "purpose": "解释搓泥原因"},
                {"beat_id": "save", "kind": "summary", "purpose": "保存调整清单"},
            ],
            "saveable_beat": {
                "beat_id": "save",
                "kind": "summary",
                "purpose": "保存调整清单",
            },
            "closing_mode": "none",
        }
    )


def _base_package() -> dict:
    narrative_plan = _narrative_plan().model_dump(mode="json")
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
        "hashtags": ["#防晒", "#底妆"],
        "narrative_plan": narrative_plan,
        "narrative_form": narrative_plan["narrative_form"],
    }


def _plan(*, proof_mode: str = "none"):
    package = _base_package()
    return build_visual_plan(
        _contract(proof_mode=proof_mode),
        _narrative_plan(),
        package,
        [],
    )


def _storyboards(plan=None):
    plan = plan or _plan()
    requirements_by_frame = {
        requirement.slot_id.rsplit("-", 1)[0]: requirement
        for requirement in plan.required_assets
    }
    frames = []
    for index, planned in enumerate(plan.frame_plan):
        requirement = requirements_by_frame.get(planned.frame_id)
        frames.append(
            {
                "frame_id": planned.frame_id,
                "role": planned.role,
                "page_archetype": planned.page_archetype,
                "content_density_hint": planned.allowed_density[0],
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
                "visual_slots": (
                    [
                        {
                            "slot_id": requirement.slot_id,
                            "role": requirement.role,
                            "semantic_tags": ["skincare"],
                        }
                    ]
                    if requirement is not None
                    else []
                ),
                "footer": "按肤感微调",
            }
        )
    return frames


def _package(plan=None):
    plan = plan or _plan()
    return {
        **_base_package(),
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


def test_carousel_qa_accepts_v2_archetypes_and_empty_visual_slots():
    from src.nodes.node_p_carousel_qa import validate_carousel

    plan = _plan()
    package = _package(plan)

    assert validate_carousel(package, _contract(), plan) == []
    assert all(frame["visual_slots"] == [] for frame in package["storyboards"])


def test_carousel_qa_requires_narrative_plan_and_matching_narrative_form():
    from src.nodes.node_p_carousel_qa import validate_carousel

    missing = _package()
    missing.pop("narrative_plan")
    mismatched_plan = _plan().model_dump(mode="python")
    mismatched_plan["narrative_form"] = "comparison"

    assert "narrative_plan_missing" in _rule_ids(
        validate_carousel(missing, _contract(), _plan())
    )
    assert "narrative_form_mismatch" in _rule_ids(
        validate_carousel(_package(), _contract(), mismatched_plan)
    )


def test_carousel_qa_requires_every_beat_and_exact_saveable_purpose_coverage():
    from src.nodes.node_p_carousel_qa import validate_carousel

    plan = _plan().model_dump(mode="python")
    saveable_purpose = _narrative_plan().saveable_beat.purpose
    for frame in plan["frame_plan"]:
        frame["purpose"] = frame["purpose"].replace(
            saveable_purpose,
            "另一项不相关任务",
        )

    issues = validate_carousel(_package(), _contract(), plan)

    assert "narrative_beat_missing" in _rule_ids(issues)
    assert "saveable_beat_missing" in _rule_ids(issues)


def test_carousel_qa_rejects_non_cover_first_archetype():
    from src.nodes.node_p_carousel_qa import validate_carousel

    plan = _plan().model_dump(mode="python")
    package = _package()
    plan["frame_plan"][0]["page_archetype"] = "scene"
    package["storyboards"][0]["page_archetype"] = "scene"

    issues = validate_carousel(package, _contract(), plan)

    assert "first_archetype_not_cover" in _rule_ids(issues)


def test_carousel_qa_rejects_unknown_template_family():
    from src.nodes.node_p_carousel_qa import validate_carousel

    plan = _plan().model_dump(mode="python")
    plan["template_family"] = "unapproved_family"

    issues = validate_carousel(_package(), _contract(), plan)

    assert "template_family_invalid" in _rule_ids(issues)


def test_carousel_qa_rejects_exact_recent_combination_signature():
    from src.nodes.node_p_carousel_qa import validate_carousel

    plan = _plan()
    signature = {
        "narrative_form": plan.narrative_form,
        "template_family": plan.template_family,
        "frame_plan_signature": [
            frame.page_archetype for frame in plan.frame_plan
        ],
        "frame_count": len(plan.frame_plan),
    }

    issues = validate_carousel(
        _package(plan),
        _contract(),
        plan,
        recent_signatures=[signature],
    )

    assert "recent_combination_exact_repeat" in _rule_ids(issues)


def test_carousel_qa_rejects_fixed_three_item_filler_only_for_three_adjacent_pages():
    from src.nodes.node_p_carousel_qa import validate_carousel

    plan = _plan().model_dump(mode="python")
    package = _package()
    for index in (1, 2, 3):
        plan["frame_plan"][index]["page_archetype"] = "steps"
        package["storyboards"][index]["page_archetype"] = "steps"
        package["storyboards"][index]["content_blocks"] = [
            {
                "block_type": "steps",
                "items": ["第一项", "第二项", "第三项"],
            }
        ]

    issues = validate_carousel(package, _contract(), plan)

    filler = [
        issue for issue in issues if issue.rule_id == "fixed_cardinality_filler"
    ]
    assert len(filler) == 1
    assert filler[0].location_hint == "storyboards[3].content_blocks"

    package["storyboards"][2]["content_blocks"][0]["items"].append("第四项")
    issues = validate_carousel(package, _contract(), plan)
    assert "fixed_cardinality_filler" not in _rule_ids(issues)


def test_carousel_qa_allows_one_legitimate_three_item_page():
    from src.nodes.node_p_carousel_qa import validate_carousel

    package = _package()
    package["storyboards"][2]["content_blocks"] = [
        {
            "block_type": "steps",
            "items": ["第一项", "第二项", "第三项"],
        }
    ]

    assert "fixed_cardinality_filler" not in _rule_ids(
        validate_carousel(package, _contract(), _plan())
    )


def test_carousel_qa_rejects_frame_count_outside_five_to_seven():
    from src.nodes.node_p_carousel_qa import validate_carousel

    plan = _plan().model_dump(mode="python")
    package = _package()
    plan["frame_plan"] = plan["frame_plan"][:4]
    package["storyboards"] = package["storyboards"][:4]

    issues = validate_carousel(package, _contract(), plan)

    assert "frame_count_out_of_range" in _rule_ids(issues)


def test_carousel_qa_rejects_cover_promise_mismatch():
    from src.nodes.node_p_carousel_qa import validate_carousel

    package = _package()
    package["storyboards"][0]["headline"] = "另一句封面承诺"

    issues = validate_carousel(package, _contract(), _plan())

    assert "first_screen_promise_mismatch" in _rule_ids(issues)
    issue = next(
        item for item in issues if item.rule_id == "first_screen_promise_mismatch"
    )
    assert issue.location_hint == "storyboards[0].headline"


def test_carousel_qa_rejects_role_and_page_archetype_drift_atomically():
    from src.nodes.node_p_carousel_qa import validate_carousel

    package = _package()
    target = package["storyboards"][2]
    target["role"] = "unplanned-task"
    target["page_archetype"] = "qa"

    issues = validate_carousel(package, _contract(), _plan())

    assert (
        "frame_role_mismatch",
        "storyboards[2].role",
    ) in [(issue.rule_id, issue.location_hint) for issue in issues]
    assert (
        "frame_page_archetype_mismatch",
        "storyboards[2].page_archetype",
    ) in [(issue.rule_id, issue.location_hint) for issue in issues]


def test_carousel_qa_requires_exact_slot_requirement_bindings():
    from src.nodes.node_p_carousel_qa import validate_carousel

    contract = _contract(proof_mode="product_texture")
    package_base = _base_package()
    plan = build_visual_plan(contract, _narrative_plan(), package_base, [])
    package = {
        **package_base,
        "content_contract": contract.model_dump(mode="json"),
        "storyboards": _storyboards(plan),
    }

    assert validate_carousel(package, contract, plan) == []

    missing_slot = deepcopy(package)
    planned_index = next(
        index
        for index, frame in enumerate(missing_slot["storyboards"])
        if frame["visual_slots"]
    )
    missing_slot["storyboards"][planned_index]["visual_slots"] = []
    assert "asset_slot_binding_mismatch" in _rule_ids(
        validate_carousel(missing_slot, contract, plan)
    )

    wrong_requirement = plan.model_dump(mode="python")
    wrong_requirement["required_assets"][0]["page_archetype"] = "qa"
    assert "asset_requirement_page_archetype_mismatch" in _rule_ids(
        validate_carousel(package, contract, wrong_requirement)
    )


def test_carousel_qa_binds_slots_by_exact_frame_identity_not_prefix():
    from src.nodes.node_p_carousel_qa import validate_carousel

    contract = _contract(proof_mode="diagram")
    plan_model = build_visual_plan(
        contract,
        _narrative_plan(),
        _base_package(),
        [],
    )
    plan = plan_model.model_dump(mode="python")
    package = {
        **_base_package(),
        "content_contract": contract.model_dump(mode="json"),
        "storyboards": _storyboards(plan_model),
    }
    asset_frame_index = next(
        index
        for index, frame in enumerate(plan["frame_plan"])
        if frame["asset_roles"]
    )
    plan["frame_plan"][0]["frame_id"] = "frame"
    package["storyboards"][0]["frame_id"] = "frame"
    plan["frame_plan"][asset_frame_index]["frame_id"] = "frame-one"
    package["storyboards"][asset_frame_index]["frame_id"] = "frame-one"
    plan["required_assets"][0]["slot_id"] = "frame-one-diagram"
    package["storyboards"][asset_frame_index]["visual_slots"][0][
        "slot_id"
    ] = "frame-one-diagram"

    assert validate_carousel(package, contract, plan) == []


def test_invalid_asset_frame_does_not_emit_dependent_slot_cascade():
    from src.nodes.node_p_carousel_qa import validate_carousel

    contract = _contract(proof_mode="diagram")
    plan = build_visual_plan(
        contract,
        _narrative_plan(),
        _base_package(),
        [],
    )
    package = {
        **_base_package(),
        "content_contract": contract.model_dump(mode="json"),
        "storyboards": _storyboards(plan),
    }
    asset_frame = next(
        frame for frame in package["storyboards"] if frame["visual_slots"]
    )
    asset_frame["free_css"] = "position:absolute"

    issues = validate_carousel(package, contract, plan)

    assert [
        issue.rule_id
        for issue in issues
        if issue.frame_id == asset_frame["frame_id"]
    ] == ["storyboard_schema_invalid"]
    assert not any(
        issue.rule_id == "asset_slot_binding_mismatch"
        and issue.location_hint == "visual_plan.required_assets"
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
        and issue.frame_id == package["storyboards"][4]["frame_id"]
        for issue in issues
    )


def test_asset_requirement_role_and_archetype_drift_are_atomic():
    from src.nodes.node_p_carousel_qa import validate_carousel

    contract = _contract(proof_mode="diagram")
    plan_model = build_visual_plan(
        contract,
        _narrative_plan(),
        _base_package(),
        [],
    )
    plan = plan_model.model_dump(mode="python")
    package = {
        **_base_package(),
        "content_contract": contract.model_dump(mode="json"),
        "storyboards": _storyboards(plan_model),
    }
    plan["required_assets"][0]["role"] = "wrong-role"
    plan["required_assets"][0]["page_archetype"] = "qa"

    issues = validate_carousel(package, contract, plan)
    drift = [
        (issue.rule_id, issue.location_hint)
        for issue in issues
        if issue.rule_id
        in {
            "asset_requirement_role_mismatch",
            "asset_requirement_page_archetype_mismatch",
        }
    ]

    assert drift == [
        (
            "asset_requirement_role_mismatch",
            "visual_plan.required_assets[0].role",
        ),
        (
            "asset_requirement_page_archetype_mismatch",
            "visual_plan.required_assets[0].page_archetype",
        ),
    ]


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
    assert task.source == "carousel_qa"
    assert task.severity == "high"
    assert result["decision_output"].next_node == "R1_REFLECTOR"
    assert (
        result[
            "decision_output"
        ].normalized_input.r1_input.content_candidate.narrative_plan
        == _narrative_plan()
    )


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


def test_carousel_qa_node_reports_invalid_narrative_without_crashing():
    from src.nodes.node_p_carousel_qa import (
        carousel_qa_node,
        route_after_carousel_qa,
    )

    package = _package()
    package["narrative_plan"] = {"narrative_form": "scenario_story"}

    result = carousel_qa_node(_state(package=package))

    assert "narrative_plan_missing" in _rule_ids(
        result["carousel_qa_result"].issues
    )
    assert "decision_output" not in result
    assert route_after_carousel_qa(result) == "r1_reflector"


@pytest.mark.parametrize(
    ("target", "rule_id"),
    [
        ("plan_frame", "duplicate_plan_frame_id"),
        ("storyboard_frame", "duplicate_storyboard_frame_id"),
        ("storyboard_slot", "duplicate_storyboard_slot_id"),
        ("requirement_slot", "duplicate_asset_requirement_slot_id"),
    ],
)
def test_carousel_qa_rejects_duplicate_identity_before_mapping(target, rule_id):
    from src.nodes.node_p_carousel_qa import validate_carousel

    contract = _contract(proof_mode="product_texture")
    plan_model = build_visual_plan(
        contract,
        _narrative_plan(),
        _base_package(),
        [],
    )
    plan = plan_model.model_dump(mode="python")
    package = {
        **_base_package(),
        "content_contract": contract.model_dump(mode="json"),
        "storyboards": _storyboards(plan_model),
    }
    if target == "plan_frame":
        plan["frame_plan"][1]["frame_id"] = plan["frame_plan"][0]["frame_id"]
    elif target == "storyboard_frame":
        package["storyboards"][1]["frame_id"] = package["storyboards"][0][
            "frame_id"
        ]
    elif target == "storyboard_slot":
        frame = next(
            frame for frame in package["storyboards"] if frame["visual_slots"]
        )
        frame["visual_slots"].append(deepcopy(frame["visual_slots"][0]))
    else:
        plan["required_assets"].append(deepcopy(plan["required_assets"][0]))

    assert rule_id in _rule_ids(validate_carousel(package, contract, plan))


def test_r1_task_identity_does_not_depend_on_issue_order():
    from src.nodes.node_p_carousel_qa import _build_r1_tasks

    cover = CarouselQAIssue(
        rule_id="first_screen_promise_mismatch",
        message="cover mismatch",
        location_hint="storyboards[0].headline",
        frame_id="frame-01-cover",
    )
    unrelated = CarouselQAIssue(
        rule_id="saveable_beat_missing",
        message="saveable missing",
        location_hint="visual_plan.frame_plan",
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

    result = carousel_qa_node(_state(package=package))

    rule_ids = _rule_ids(result["carousel_qa_result"].issues)
    assert "content_contract_mismatch" in rule_ids
    assert "first_screen_promise_mismatch" in rule_ids
