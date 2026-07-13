from copy import deepcopy

import pytest

from src.schemas.content_contract import ContentContract


FAMILY_BY_JOB = {
    "diagnose_and_adjust": "face_zone_map",
    "follow_steps": "step_flow",
    "compare_and_choose": "comparison_decision",
    "save_and_check": "saveable_reference",
    "understand_and_notice": "beauty_editorial",
}


def contract_for(job: str) -> ContentContract:
    subject_by_job = {
        "diagnose_and_adjust": "face_map",
        "follow_steps": "process",
        "compare_and_choose": "product_cutout",
        "save_and_check": "checklist",
        "understand_and_notice": "serum_texture",
    }
    return ContentContract(
        audience="通勤护肤人群",
        trigger_situation="早上需要快速完成护肤",
        decision_problem="根据当前任务选择合适的执行方式",
        first_screen_promise="用一套清晰方法完成今天的护肤判断",
        screenshot_asset="可保存的执行参考卡",
        proof_asset="结构化对照证据",
        visual_mode="text_plus_real_proof",
        content_job=job,
        primary_visual_family=FAMILY_BY_JOB[job],
        primary_visual_subject=subject_by_job[job],
        proof_mode="diagram",
        recommended_frame_count=6,
    )


@pytest.mark.parametrize("job,family", FAMILY_BY_JOB.items())
def test_strategy_maps_content_job_to_family(job, family):
    from src.editorial_carousel.strategy import build_visual_plan

    plan = build_visual_plan(contract_for(job), recent_signatures=[])

    assert plan.content_job == job
    assert plan.primary_visual_family == family
    assert plan.frame_plan[0].layout == "editorial_cover"
    assert 5 <= len(plan.frame_plan) <= 7
    assert len({frame.layout for frame in plan.frame_plan}) >= 3
    assert any(
        frame.layout in {"saveable_checklist", "saveable_reference"}
        for frame in plan.frame_plan
    )
    assert [
        (requirement.role, requirement.layout)
        for requirement in plan.required_assets
    ] == [
        (frame.asset_roles[0], frame.layout)
        for frame in plan.frame_plan
        if frame.asset_roles
    ]


def test_zone_strategy_produces_the_six_spec_semantic_roles():
    from src.editorial_carousel.strategy import build_visual_plan

    plan = build_visual_plan(
        contract_for("diagnose_and_adjust"), recent_signatures=[]
    )

    assert [
        (frame.role, frame.layout, frame.asset_roles)
        for frame in plan.frame_plan
    ] == [
        ("cover", "editorial_cover", ["beauty_subject"]),
        ("baseline", "texture_baseline", ["product_texture"]),
        ("applicable_case", "front_face_zone", ["face_map"]),
        ("zone_adjustment", "three_quarter_face_zone", ["face_map"]),
        ("feedback_diagnosis", "three_state_diagnostic", ["comparison"]),
        ("save", "saveable_reference", ["reference"]),
    ]


@pytest.mark.parametrize(
    "job",
    [
        "follow_steps",
        "compare_and_choose",
        "save_and_check",
        "understand_and_notice",
    ],
)
def test_non_zone_recipes_use_the_smallest_schema_valid_frame_count(job):
    from src.editorial_carousel.strategy import build_visual_plan

    plan = build_visual_plan(contract_for(job), recent_signatures=[])

    assert len(plan.frame_plan) == 5


def test_recent_identical_signature_selects_deterministic_auxiliary_layout():
    from src.editorial_carousel.strategy import build_visual_plan

    contract = contract_for("diagnose_and_adjust")
    original = build_visual_plan(contract, recent_signatures=[])
    signature = tuple(
        (frame.role, frame.layout) for frame in original.frame_plan
    )

    alternative = build_visual_plan(contract, recent_signatures=[signature])
    repeated = build_visual_plan(contract, recent_signatures=[signature])

    assert alternative.content_job == original.content_job
    assert alternative.primary_visual_family == original.primary_visual_family
    assert alternative.frame_plan != original.frame_plan
    assert alternative.frame_plan == repeated.frame_plan
    assert alternative.frame_plan[4].layout == "decision_tree"


def test_legacy_hydration_is_explicit_and_preserves_supplied_values():
    from src.editorial_carousel.legacy import hydrate_legacy_content_contract

    raw = {
        "visual_mode": "comparison_table",
        "primary_visual_subject": "process",
    }

    hydrated = hydrate_legacy_content_contract(raw)

    assert hydrated == {
        "visual_mode": "comparison_table",
        "content_job": "save_and_check",
        "primary_visual_family": "saveable_reference",
        "primary_visual_subject": "process",
        "proof_mode": "comparison",
        "recommended_frame_count": 6,
    }
    assert raw == {
        "visual_mode": "comparison_table",
        "primary_visual_subject": "process",
    }


def test_strategy_does_not_hydrate_incomplete_new_contracts():
    from pydantic import ValidationError

    from src.editorial_carousel.strategy import build_visual_plan

    raw = contract_for("save_and_check").model_dump(mode="json")
    incomplete = deepcopy(raw)
    incomplete.pop("content_job")

    with pytest.raises(ValidationError):
        build_visual_plan(incomplete, recent_signatures=[])
