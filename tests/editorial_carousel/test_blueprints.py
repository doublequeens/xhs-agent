import pytest

from src.schemas.narrative import NarrativeForm


def test_every_narrative_form_has_three_blueprints_supporting_five_six_and_seven_pages():
    from src.editorial_carousel.blueprints import BLUEPRINTS, materialize_blueprint

    assert set(BLUEPRINTS) == {
        "cognitive_correction",
        "step_tutorial",
        "checklist_collection",
        "comparison",
        "diagnostic_qa",
        "scenario_story",
        "story_reversal",
        "reflective_editorial",
    }
    for narrative_form, blueprints in BLUEPRINTS.items():
        assert len(blueprints) == 3
        assert all(
            blueprint.narrative_form == narrative_form
            for blueprint in blueprints
        )
        for blueprint in blueprints:
            assert [
                len(materialize_blueprint(blueprint, count))
                for count in (5, 6, 7)
            ] == [5, 6, 7]


def test_materialized_blueprint_always_starts_with_cover_and_contains_saveable_page():
    from src.editorial_carousel.blueprints import BLUEPRINTS, materialize_blueprint

    for blueprints in BLUEPRINTS.values():
        for blueprint in blueprints:
            pages = materialize_blueprint(blueprint, 7)
            assert pages[0] == "cover"
            assert set(pages) & {"save", "checklist", "comparison"}


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
