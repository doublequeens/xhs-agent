from copy import deepcopy

import pytest
from pydantic import ValidationError

from src.schemas.content_contract import ContentContract
from src.schemas.narrative import NarrativePlan


FAMILY_BY_JOB = {
    "diagnose_and_adjust": "face_zone_map",
    "follow_steps": "step_flow",
    "compare_and_choose": "comparison_decision",
    "save_and_check": "saveable_reference",
    "understand_and_notice": "beauty_editorial",
}

SUBJECT_BY_JOB = {
    "diagnose_and_adjust": "face_map",
    "follow_steps": "process",
    "compare_and_choose": "product_cutout",
    "save_and_check": "checklist",
    "understand_and_notice": "serum_texture",
}

BEATS_BY_FORM = {
    "cognitive_correction": (
        ("hook", "hook"),
        ("mistake", "misconception"),
        ("reveal", "reveal"),
        ("action", "action"),
    ),
    "step_tutorial": (
        ("hook", "hook"),
        ("scene", "scene"),
        ("steps", "steps"),
        ("diagnostic", "diagnostic"),
        ("explanation", "explanation"),
        ("action", "action"),
    ),
    "checklist_collection": (
        ("hook", "hook"),
        ("principle", "principle"),
        ("checklist", "checklist"),
        ("example", "example"),
        ("action", "action"),
    ),
    "comparison": (
        ("hook", "hook"),
        ("left-right", "comparison"),
        ("diagnostic", "diagnostic"),
        ("boundary", "boundary"),
        ("action", "action"),
    ),
    "diagnostic_qa": (
        ("hook", "hook"),
        ("diagnostic", "diagnostic"),
        ("question", "qa"),
        ("explanation", "explanation"),
        ("action", "action"),
    ),
    "scenario_story": (
        ("hook", "hook"),
        ("scene", "scene"),
        ("tension", "tension"),
        ("example", "example"),
        ("action", "action"),
    ),
    "story_reversal": (
        ("hook", "hook"),
        ("scene", "scene"),
        ("tension", "tension"),
        ("reveal", "reveal"),
        ("action", "action"),
    ),
    "reflective_editorial": (
        ("hook", "hook"),
        ("quote", "quote"),
        ("principle", "principle"),
        ("reflection", "explanation"),
        ("action", "action"),
    ),
}


def contract_for(
    job: str,
    *,
    proof_mode: str = "diagram",
    recommended_frame_count: int = 6,
    primary_visual_family: str | None = None,
) -> ContentContract:
    return ContentContract(
        audience="通勤护肤人群",
        trigger_situation="早上需要快速完成护肤",
        decision_problem="根据当前任务选择合适的执行方式",
        first_screen_promise="用一套清晰方法完成今天的护肤判断",
        screenshot_asset="可保存的执行参考卡",
        proof_asset="结构化对照证据",
        visual_mode="text_plus_real_proof",
        content_job=job,
        primary_visual_family=(
            primary_visual_family or FAMILY_BY_JOB[job]
        ),
        primary_visual_subject=SUBJECT_BY_JOB[job],
        proof_mode=proof_mode,
        recommended_frame_count=recommended_frame_count,
    )


def narrative_plan_for(form: str, *, beat_count: int | None = None) -> NarrativePlan:
    beat_values = list(BEATS_BY_FORM[form])
    if beat_count is not None:
        if beat_count > len(beat_values):
            beat_values.extend(
                (f"extra-{index}", "explanation")
                for index in range(len(beat_values) + 1, beat_count + 1)
            )
        beat_values = beat_values[:beat_count]
    beats = [
        {
            "beat_id": beat_id,
            "kind": kind,
            "purpose": f"完成{beat_id}的叙事任务",
        }
        for beat_id, kind in beat_values
    ]
    return NarrativePlan.model_validate(
        {
            "narrative_form": form,
            "beats": beats,
            "saveable_beat": beats[-1],
            "closing_mode": "action_prompt",
        }
    )


def publish_package_for(
    contract: ContentContract,
    narrative_plan: NarrativePlan,
    *,
    content: str = "正文",
) -> dict:
    return {
        "topic_id": "topic-001",
        "angle_id": "angle-001",
        "title": "分区护肤指南",
        "content": content,
        "content_contract": contract.model_dump(mode="json"),
        "narrative_plan": narrative_plan.model_dump(mode="json"),
    }


@pytest.mark.parametrize(
    "form",
    [
        "cognitive_correction",
        "step_tutorial",
        "checklist_collection",
        "comparison",
        "diagnostic_qa",
        "scenario_story",
        "story_reversal",
        "reflective_editorial",
    ],
)
def test_public_planner_builds_a_strict_v2_plan_for_every_narrative_form(form):
    from src.editorial_carousel import build_visual_plan

    contract = contract_for("understand_and_notice", proof_mode="none")
    narrative_plan = narrative_plan_for(form)
    plan = build_visual_plan(
        contract,
        narrative_plan,
        publish_package_for(contract, narrative_plan),
        recent_signatures=[],
    )

    assert plan.design_system == "beauty_editorial_v2"
    assert plan.narrative_form == form
    assert plan.template_family == plan.template_selection.template_family
    assert len(plan.frame_plan) == 6
    assert plan.frame_plan[0].page_archetype == "cover"
    assert any(
        frame.page_archetype in {"save", "checklist", "comparison"}
        for frame in plan.frame_plan
    )
    assert plan.required_assets == []


@pytest.mark.parametrize(
    ("recommended_count", "beat_count", "expected_count"),
    [(5, 4, 5), (5, 7, 7), (7, 4, 7)],
)
def test_page_count_comes_only_from_contract_and_narrative_beats(
    recommended_count: int,
    beat_count: int,
    expected_count: int,
):
    from src.editorial_carousel.planner import build_visual_plan

    narrative_plan = narrative_plan_for("step_tutorial", beat_count=beat_count)
    contract = contract_for(
        "follow_steps",
        proof_mode="none",
        recommended_frame_count=recommended_count,
    )
    package = publish_package_for(contract, narrative_plan)

    plan = build_visual_plan(contract, narrative_plan, package, [])

    assert len(plan.frame_plan) == expected_count


def test_primary_visual_family_does_not_change_page_count_or_archetypes():
    from src.editorial_carousel.planner import build_visual_plan

    narrative_plan = narrative_plan_for("comparison")
    first_contract = contract_for(
        "compare_and_choose",
        proof_mode="none",
        primary_visual_family="comparison_decision",
    )
    second_contract = contract_for(
        "compare_and_choose",
        proof_mode="none",
        primary_visual_family="beauty_editorial",
    )
    package = publish_package_for(first_contract, narrative_plan)

    first = build_visual_plan(first_contract, narrative_plan, package, [])
    second = build_visual_plan(second_contract, narrative_plan, package, [])

    assert [frame.page_archetype for frame in first.frame_plan] == [
        frame.page_archetype for frame in second.frame_plan
    ]


def test_exact_recent_blueprint_signature_changes_an_equal_ranked_blueprint():
    from src.editorial_carousel.planner import build_visual_plan

    narrative_plan = narrative_plan_for("cognitive_correction")
    contract = contract_for(
        "understand_and_notice",
        proof_mode="none",
        recommended_frame_count=5,
    )
    package = publish_package_for(contract, narrative_plan)
    original = build_visual_plan(contract, narrative_plan, package, [])
    original_archetypes = [
        frame.page_archetype for frame in original.frame_plan
    ]
    signature = {
        "narrative_form": narrative_plan.narrative_form,
        "frame_plan_signature": original_archetypes,
        "frame_count": len(original_archetypes),
    }

    repeated = build_visual_plan(
        contract,
        narrative_plan,
        package,
        [signature],
    )

    assert [frame.page_archetype for frame in repeated.frame_plan] != (
        original_archetypes
    )
    assert len(repeated.frame_plan) == len(original.frame_plan) == 5


def test_required_assets_are_empty_for_none_and_only_bind_matching_proof_pages():
    from src.editorial_carousel.planner import build_visual_plan

    narrative_plan = narrative_plan_for("comparison")
    no_proof = contract_for("compare_and_choose", proof_mode="none")
    comparison_proof = contract_for(
        "compare_and_choose",
        proof_mode="comparison",
    )
    package = publish_package_for(comparison_proof, narrative_plan)

    pure_text_plan = build_visual_plan(no_proof, narrative_plan, package, [])
    proof_plan = build_visual_plan(
        comparison_proof,
        narrative_plan,
        package,
        [],
    )

    assert pure_text_plan.required_assets == []
    assert proof_plan.required_assets
    proof_frames = {
        frame.frame_id: frame
        for frame in proof_plan.frame_plan
        if "comparison" in frame.asset_roles
    }
    assert {
        requirement.slot_id.removesuffix("-comparison")
        for requirement in proof_plan.required_assets
    } == set(proof_frames)
    assert all(
        requirement.page_archetype
        == proof_frames[
            requirement.slot_id.removesuffix("-comparison")
        ].page_archetype
        for requirement in proof_plan.required_assets
    )


def test_public_planner_does_not_hydrate_incomplete_new_contracts():
    from src.editorial_carousel.planner import build_visual_plan

    narrative_plan = narrative_plan_for("checklist_collection")
    contract = contract_for("save_and_check")
    incomplete = deepcopy(contract.model_dump(mode="json"))
    incomplete.pop("content_job")

    with pytest.raises(ValidationError):
        build_visual_plan(
            incomplete,
            narrative_plan,
            publish_package_for(contract, narrative_plan),
            [],
        )
