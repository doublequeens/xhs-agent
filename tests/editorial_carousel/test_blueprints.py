import pytest

from src.schemas.narrative import NarrativeForm


EXPECTED_BLUEPRINTS = {
    "cognitive_correction": (
        (
            "correction-reveal",
            ("cover", "scene", "diagnostic", "explanation", "save"),
            ("comparison", "boundary"),
        ),
        (
            "correction-contrast",
            ("cover", "comparison", "explanation", "steps", "save"),
            ("scene", "boundary"),
        ),
        (
            "correction-qa",
            ("cover", "qa", "diagnostic", "explanation", "checklist"),
            ("story_beat", "boundary"),
        ),
    ),
    "step_tutorial": (
        (
            "tutorial-linear",
            ("cover", "scene", "steps", "diagnostic", "save"),
            ("explanation", "boundary"),
        ),
        (
            "tutorial-checkpoint",
            ("cover", "explanation", "steps", "qa", "checklist"),
            ("comparison", "boundary"),
        ),
        (
            "tutorial-example",
            ("cover", "story_beat", "steps", "comparison", "save"),
            ("diagnostic", "boundary"),
        ),
    ),
    "checklist_collection": (
        (
            "collection-catalog",
            ("cover", "scene", "item_collection", "checklist", "save"),
            ("comparison", "boundary"),
        ),
        (
            "collection-filter",
            ("cover", "thesis", "item_collection", "diagnostic", "checklist"),
            ("qa", "boundary"),
        ),
        (
            "collection-use",
            ("cover", "item_collection", "explanation", "steps", "save"),
            ("comparison", "boundary"),
        ),
    ),
    "comparison": (
        (
            "comparison-rule",
            ("cover", "scene", "comparison", "diagnostic", "save"),
            ("explanation", "boundary"),
        ),
        (
            "comparison-options",
            ("cover", "thesis", "comparison", "qa", "checklist"),
            ("story_beat", "boundary"),
        ),
        (
            "comparison-story",
            ("cover", "story_beat", "comparison", "explanation", "save"),
            ("diagnostic", "boundary"),
        ),
    ),
    "diagnostic_qa": (
        (
            "diagnostic-branches",
            ("cover", "scene", "diagnostic", "qa", "save"),
            ("explanation", "boundary"),
        ),
        (
            "diagnostic-checklist",
            ("cover", "qa", "diagnostic", "checklist", "boundary"),
            ("comparison", "save"),
        ),
        (
            "diagnostic-story",
            ("cover", "story_beat", "diagnostic", "explanation", "save"),
            ("qa", "boundary"),
        ),
    ),
    "scenario_story": (
        (
            "story-discovery",
            ("cover", "scene", "story_beat", "explanation", "save"),
            ("steps", "boundary"),
        ),
        (
            "story-tension",
            ("cover", "scene", "story_beat", "comparison", "checklist"),
            ("explanation", "boundary"),
        ),
        (
            "story-reflection",
            ("cover", "story_beat", "explanation", "quote", "save"),
            ("scene", "boundary"),
        ),
    ),
    "story_reversal": (
        (
            "reversal-reveal",
            ("cover", "scene", "story_beat", "explanation", "save"),
            ("comparison", "boundary"),
        ),
        (
            "reversal-diagnostic",
            ("cover", "story_beat", "diagnostic", "steps", "checklist"),
            ("explanation", "boundary"),
        ),
        (
            "reversal-contrast",
            ("cover", "comparison", "story_beat", "explanation", "save"),
            ("qa", "boundary"),
        ),
    ),
    "reflective_editorial": (
        (
            "editorial-thesis",
            ("cover", "quote", "explanation", "scene", "save"),
            ("story_beat", "boundary"),
        ),
        (
            "editorial-story",
            ("cover", "scene", "story_beat", "quote", "save"),
            ("explanation", "boundary"),
        ),
        (
            "editorial-principle",
            ("cover", "thesis", "explanation", "quote", "checklist"),
            ("scene", "boundary"),
        ),
    ),
}


def test_blueprint_catalog_matches_the_exact_authoritative_table():
    from src.editorial_carousel.blueprints import BLUEPRINTS

    actual = {
        narrative_form: tuple(
            (blueprint.blueprint_id, blueprint.required, blueprint.optional)
            for blueprint in blueprints
        )
        for narrative_form, blueprints in BLUEPRINTS.items()
    }

    assert actual == EXPECTED_BLUEPRINTS


def test_every_blueprint_materializes_to_a_strict_valid_plan_at_every_count():
    from src.editorial_carousel.blueprints import BLUEPRINTS, materialize_blueprint
    from src.schemas.visual_plan import VisualPlan

    rejected = {
        family: ["not selected"]
        for family in (
            "deep_teal",
            "soft_pink",
            "coral_impact",
            "green_catalog",
            "white_quote",
        )
    }
    for narrative_form, blueprints in BLUEPRINTS.items():
        assert len(blueprints) == 3
        for blueprint in blueprints:
            assert blueprint.narrative_form == narrative_form
            for count in (5, 6, 7):
                pages = materialize_blueprint(blueprint, count)
                plan = VisualPlan.model_validate(
                    {
                        "design_system": "beauty_editorial_v2",
                        "template_family": "pink_red",
                        "template_selection": {
                            "template_family": "pink_red",
                            "score": 0,
                            "reasons": ["catalog validation"],
                            "rejected_families": rejected,
                        },
                        "narrative_form": narrative_form,
                        "content_job": "understand_and_notice",
                        "frame_plan": [
                            {
                                "frame_id": f"frame-{index:02d}-{archetype}",
                                "role": archetype,
                                "page_archetype": archetype,
                                "purpose": "验证蓝图物化结果",
                                "allowed_density": ["standard"],
                                "asset_roles": [],
                            }
                            for index, archetype in enumerate(pages, start=1)
                        ],
                        "required_assets": [],
                    }
                )

                assert len(plan.frame_plan) == count
                assert plan.frame_plan[0].page_archetype == "cover"
                assert {
                    frame.page_archetype for frame in plan.frame_plan
                } & {"save", "checklist", "comparison"}


@pytest.mark.parametrize("frame_count", [4, 8])
def test_materialize_blueprint_rejects_counts_outside_five_to_seven(
    frame_count: int,
):
    from src.editorial_carousel.blueprints import BLUEPRINTS, materialize_blueprint

    blueprint = BLUEPRINTS[
        NarrativeForm.__args__[0]  # type: ignore[attr-defined]
    ][0]

    with pytest.raises(ValueError, match="frame_count must be 5, 6, or 7"):
        materialize_blueprint(blueprint, frame_count)
