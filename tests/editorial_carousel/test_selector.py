from src.schemas.editorial_templates import TemplateFamily


def selector_input(**overrides):
    from src.editorial_carousel.selector import SelectorInput

    values = {
        "topic_id": "topic-001",
        "angle_id": "angle-001",
        "narrative_form": "scenario_story",
        "content_job": "understand_and_notice",
        "page_archetypes": (
            "cover",
            "scene",
            "story_beat",
            "explanation",
            "save",
        ),
        "estimated_density": "sparse",
        "proof_mode": "none",
    }
    values.update(overrides)
    return SelectorInput(**values)


def test_selector_returns_only_approved_family_and_is_deterministic():
    from src.editorial_carousel.selector import select_template

    first = select_template(selector_input(), recent_signatures=[])
    second = select_template(selector_input(), recent_signatures=[])

    assert first == second
    assert first.template_family in TemplateFamily.__args__  # type: ignore[attr-defined]
    assert set(first.rejected_families) == (
        set(TemplateFamily.__args__) - {first.template_family}  # type: ignore[attr-defined]
    )
    assert all(first.rejected_families.values())


def test_recent_family_penalty_changes_equal_fit_tie_without_changing_page_count():
    from src.editorial_carousel.selector import select_template

    selector_value = selector_input(
        narrative_form="diagnostic_qa",
        content_job="understand_and_notice",
        page_archetypes=(
            "cover",
            "scene",
            "diagnostic",
            "qa",
            "save",
        ),
        estimated_density="standard",
        proof_mode="none",
    )
    original_pages = selector_value.page_archetypes
    baseline = select_template(selector_value, recent_signatures=[])
    repeated = select_template(
        selector_value,
        recent_signatures=[{"template_family": baseline.template_family}],
    )

    assert repeated.template_family != baseline.template_family
    assert selector_value.page_archetypes == original_pages
    assert selector_value.frame_count == 5


def test_exact_combination_penalty_is_additional_and_deterministic():
    from src.editorial_carousel.selector import select_template

    selector_value = selector_input()
    baseline = select_template(selector_value, recent_signatures=[])
    signature = {
        "narrative_form": selector_value.narrative_form,
        "template_family": baseline.template_family,
        "frame_plan_signature": list(selector_value.page_archetypes),
        "frame_count": selector_value.frame_count,
    }

    first = select_template(selector_value, recent_signatures=[signature])
    second = select_template(selector_value, recent_signatures=[signature])

    assert first == second
    assert first.template_family != baseline.template_family
    assert selector_value.page_archetypes == tuple(
        signature["frame_plan_signature"]
    )


def test_selector_estimates_density_from_final_publish_copy():
    from src.editorial_carousel.selector import SelectorInput
    from src.schemas.visual_plan import FramePlanItem

    from tests.editorial_carousel.test_strategy import (
        contract_for,
        narrative_plan_for,
    )

    contract = contract_for("understand_and_notice", proof_mode="none")
    narrative_plan = narrative_plan_for("scenario_story")
    frame_plan = [
        FramePlanItem(
            frame_id=f"frame-{index:02d}-{archetype}",
            role=archetype,
            page_archetype=archetype,
            purpose="承载叙事任务",
            allowed_density=["sparse", "standard", "dense"],
            asset_roles=[],
        )
        for index, archetype in enumerate(
            ("cover", "scene", "story_beat", "explanation", "save"),
            start=1,
        )
    ]

    sparse = SelectorInput.from_content(
        contract,
        narrative_plan,
        {"topic_id": "t", "angle_id": "a", "title": "短标题", "content": "短正文"},
        frame_plan,
    )
    standard = SelectorInput.from_content(
        contract,
        narrative_plan,
        {"title": "题", "content": "中" * 400},
        frame_plan,
    )
    dense = SelectorInput.from_content(
        contract,
        narrative_plan,
        {"title": "题", "content": "长" * 901},
        frame_plan,
    )

    assert (sparse.estimated_density, standard.estimated_density, dense.estimated_density) == (
        "sparse",
        "standard",
        "dense",
    )
