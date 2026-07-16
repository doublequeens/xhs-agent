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


def test_reflective_five_page_story_blueprint_is_strict_valid():
    from src.editorial_carousel import build_visual_plan

    contract = contract_for(
        "understand_and_notice",
        proof_mode="none",
        recommended_frame_count=5,
    )
    narrative_plan = NarrativePlan.model_validate(
        {
            "narrative_form": "reflective_editorial",
            "beats": [
                {
                    "beat_id": "hook",
                    "kind": "hook",
                    "purpose": "提出值得停下来思考的问题",
                },
                {
                    "beat_id": "scene",
                    "kind": "scene",
                    "purpose": "落到一个具体护肤场景",
                },
                {
                    "beat_id": "tension",
                    "kind": "tension",
                    "purpose": "呈现习惯与真实需要之间的张力",
                },
                {
                    "beat_id": "quote",
                    "kind": "quote",
                    "purpose": "给出可独立保存的反思句",
                },
            ],
            "saveable_beat": {
                "beat_id": "quote",
                "kind": "quote",
                "purpose": "给出可独立保存的反思句",
            },
            "closing_mode": "reflection",
        }
    )

    plan = build_visual_plan(
        contract,
        narrative_plan,
        publish_package_for(contract, narrative_plan),
        recent_signatures=[],
    )

    assert [frame.page_archetype for frame in plan.frame_plan] == [
        "cover",
        "scene",
        "story_beat",
        "quote",
        "save",
    ]


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
    first_package = publish_package_for(first_contract, narrative_plan)
    second_package = publish_package_for(second_contract, narrative_plan)

    first = build_visual_plan(
        first_contract,
        narrative_plan,
        first_package,
        [],
    )
    second = build_visual_plan(
        second_contract,
        narrative_plan,
        second_package,
        [],
    )

    assert [frame.page_archetype for frame in first.frame_plan] == [
        frame.page_archetype for frame in second.frame_plan
    ]


def test_required_beat_fit_selects_the_best_matching_blueprint():
    from src.editorial_carousel.planner import build_visual_plan

    contract = contract_for(
        "diagnose_and_adjust",
        proof_mode="none",
        recommended_frame_count=5,
    )
    narrative_plan = NarrativePlan.model_validate(
        {
            "narrative_form": "cognitive_correction",
            "beats": [
                {"beat_id": "hook", "kind": "hook", "purpose": "提出问题"},
                {"beat_id": "qa", "kind": "qa", "purpose": "回答疑问"},
                {
                    "beat_id": "diagnostic",
                    "kind": "diagnostic",
                    "purpose": "给出判断标准",
                },
                {
                    "beat_id": "explanation",
                    "kind": "explanation",
                    "purpose": "解释原因",
                },
            ],
            "saveable_beat": {
                "beat_id": "explanation",
                "kind": "explanation",
                "purpose": "解释原因",
            },
            "closing_mode": "reflection",
        }
    )

    plan = build_visual_plan(
        contract,
        narrative_plan,
        publish_package_for(contract, narrative_plan),
        [],
    )

    assert [frame.page_archetype for frame in plan.frame_plan] == [
        "cover",
        "qa",
        "diagnostic",
        "explanation",
        "checklist",
    ]


def test_saveable_beat_fit_breaks_an_equal_required_beat_tie():
    from src.editorial_carousel.planner import build_visual_plan

    contract = contract_for(
        "follow_steps",
        proof_mode="none",
        recommended_frame_count=5,
    )
    narrative_plan = NarrativePlan.model_validate(
        {
            "narrative_form": "cognitive_correction",
            "beats": [
                {
                    "beat_id": "hook-one",
                    "kind": "hook",
                    "purpose": "提出问题",
                },
                {
                    "beat_id": "hook-two",
                    "kind": "hook",
                    "purpose": "强化问题",
                },
                {
                    "beat_id": "scene",
                    "kind": "scene",
                    "purpose": "进入具体场景",
                },
                {
                    "beat_id": "steps",
                    "kind": "steps",
                    "purpose": "给出可保存的步骤",
                },
            ],
            "saveable_beat": {
                "beat_id": "steps",
                "kind": "steps",
                "purpose": "给出可保存的步骤",
            },
            "closing_mode": "action_prompt",
        }
    )

    plan = build_visual_plan(
        contract,
        narrative_plan,
        publish_package_for(contract, narrative_plan),
        [],
    )

    assert [frame.page_archetype for frame in plan.frame_plan] == [
        "cover",
        "comparison",
        "explanation",
        "steps",
        "save",
    ]


def test_equal_blueprint_scores_use_the_stable_sha256_order():
    from src.editorial_carousel.planner import build_visual_plan

    narrative_plan = narrative_plan_for("cognitive_correction")
    contract = contract_for(
        "understand_and_notice",
        proof_mode="none",
        recommended_frame_count=5,
    )

    plan = build_visual_plan(
        contract,
        narrative_plan,
        publish_package_for(contract, narrative_plan),
        [],
    )

    assert [frame.page_archetype for frame in plan.frame_plan] == [
        "cover",
        "qa",
        "diagnostic",
        "explanation",
        "checklist",
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
        "template_family": original.template_family,
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


def test_template_history_and_mockup_metadata_cannot_rematerialize_frames():
    from src.editorial_carousel.planner import build_visual_plan

    narrative_plan = narrative_plan_for("diagnostic_qa")
    contract = contract_for(
        "understand_and_notice",
        proof_mode="none",
        recommended_frame_count=5,
    )
    package = publish_package_for(contract, narrative_plan)
    baseline = build_visual_plan(contract, narrative_plan, package, [])
    misleading_package = {
        **package,
        "template_family": "coral_impact",
        "selected_family": "green_catalog",
        "primary_visual_family": "step_flow",
        "mockup_page_count": 12,
        "mockup_count": 12,
        "page_count": 12,
    }
    history = [
        {
            "narrative_form": "comparison",
            "template_family": baseline.template_family,
            "frame_plan_signature": [
                "cover",
                "scene",
                "comparison",
                "diagnostic",
                "save",
            ],
            "frame_count": 5,
        }
    ]

    repeated = build_visual_plan(
        contract,
        narrative_plan,
        misleading_package,
        history,
    )

    assert repeated.template_family != baseline.template_family
    assert [frame.page_archetype for frame in repeated.frame_plan] == [
        frame.page_archetype for frame in baseline.frame_plan
    ]
    assert len(repeated.frame_plan) == len(baseline.frame_plan) == 5


@pytest.mark.parametrize(
    ("proof_mode", "matching_archetypes"),
    [
        ("diagram", {"diagnostic", "explanation", "steps"}),
        ("real_photo", {"scene", "story_beat"}),
        ("product_texture", {"scene", "explanation"}),
        ("comparison", {"comparison", "diagnostic"}),
        ("none", set()),
    ],
)
def test_required_assets_cover_every_proof_mode(
    proof_mode,
    matching_archetypes,
):
    from src.editorial_carousel.planner import build_visual_plan

    narrative_plan = narrative_plan_for("step_tutorial")
    contract = contract_for(
        "follow_steps",
        proof_mode=proof_mode,
    )
    plan = build_visual_plan(
        contract,
        narrative_plan,
        publish_package_for(contract, narrative_plan),
        [],
    )

    if proof_mode == "none":
        assert plan.required_assets == []
        return

    proof_frames = {
        frame.frame_id: frame
        for frame in plan.frame_plan
        if proof_mode in frame.asset_roles
    }
    assert proof_frames
    assert {
        requirement.slot_id.removesuffix(f"-{proof_mode}")
        for requirement in plan.required_assets
    } == set(proof_frames)
    assert all(
        requirement.role == proof_mode
        and requirement.page_archetype in matching_archetypes
        and requirement.page_archetype
        == proof_frames[
            requirement.slot_id.removesuffix(f"-{proof_mode}")
        ].page_archetype
        for requirement in plan.required_assets
    )


def test_required_assets_reject_mismatched_role_and_page_archetype_bindings():
    from src.editorial_carousel.planner import required_assets_for
    from src.schemas.visual_plan import FramePlanItem

    contract = contract_for(
        "compare_and_choose",
        proof_mode="comparison",
    )
    frames = [
        FramePlanItem(
            frame_id="frame-01-scene",
            role="scene",
            page_archetype="scene",
            purpose="错误地声明 comparison role",
            allowed_density=["standard"],
            asset_roles=["comparison"],
        ),
        FramePlanItem(
            frame_id="frame-02-comparison",
            role="comparison",
            page_archetype="comparison",
            purpose="缺少 matching role",
            allowed_density=["standard"],
            asset_roles=[],
        ),
        FramePlanItem(
            frame_id="frame-03-diagnostic",
            role="diagnostic",
            page_archetype="diagnostic",
            purpose="正确绑定 comparison role",
            allowed_density=["standard"],
            asset_roles=["comparison"],
        ),
    ]

    requirements = required_assets_for(frames, contract)

    assert [
        (
            requirement.slot_id,
            requirement.role,
            requirement.page_archetype,
        )
        for requirement in requirements
    ] == [
        (
            "frame-03-diagnostic-comparison",
            "comparison",
            "diagnostic",
        )
    ]


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
