from dataclasses import dataclass

from src.schemas.editorial_templates import PageArchetype
from src.schemas.narrative import NarrativeForm


@dataclass(frozen=True)
class FrameBlueprint:
    blueprint_id: str
    narrative_form: NarrativeForm
    required: tuple[PageArchetype, ...]
    optional: tuple[PageArchetype, PageArchetype]


def materialize_blueprint(
    blueprint: FrameBlueprint,
    frame_count: int,
) -> tuple[PageArchetype, ...]:
    if frame_count not in {5, 6, 7}:
        raise ValueError("frame_count must be 5, 6, or 7")
    return blueprint.required + blueprint.optional[: frame_count - 5]


BLUEPRINTS: dict[NarrativeForm, tuple[FrameBlueprint, ...]] = {
    "cognitive_correction": (
        FrameBlueprint(
            "correction-reveal",
            "cognitive_correction",
            ("cover", "scene", "diagnostic", "explanation", "save"),
            ("comparison", "boundary"),
        ),
        FrameBlueprint(
            "correction-contrast",
            "cognitive_correction",
            ("cover", "comparison", "explanation", "steps", "save"),
            ("scene", "boundary"),
        ),
        FrameBlueprint(
            "correction-qa",
            "cognitive_correction",
            ("cover", "qa", "diagnostic", "explanation", "checklist"),
            ("story_beat", "boundary"),
        ),
    ),
    "step_tutorial": (
        FrameBlueprint(
            "tutorial-linear",
            "step_tutorial",
            ("cover", "scene", "steps", "diagnostic", "save"),
            ("explanation", "boundary"),
        ),
        FrameBlueprint(
            "tutorial-checkpoint",
            "step_tutorial",
            ("cover", "explanation", "steps", "qa", "checklist"),
            ("comparison", "boundary"),
        ),
        FrameBlueprint(
            "tutorial-example",
            "step_tutorial",
            ("cover", "story_beat", "steps", "comparison", "save"),
            ("diagnostic", "boundary"),
        ),
    ),
    "checklist_collection": (
        FrameBlueprint(
            "collection-catalog",
            "checklist_collection",
            ("cover", "scene", "item_collection", "checklist", "save"),
            ("comparison", "boundary"),
        ),
        FrameBlueprint(
            "collection-filter",
            "checklist_collection",
            ("cover", "thesis", "item_collection", "diagnostic", "checklist"),
            ("qa", "boundary"),
        ),
        FrameBlueprint(
            "collection-use",
            "checklist_collection",
            ("cover", "item_collection", "explanation", "steps", "save"),
            ("comparison", "boundary"),
        ),
    ),
    "comparison": (
        FrameBlueprint(
            "comparison-rule",
            "comparison",
            ("cover", "scene", "comparison", "diagnostic", "save"),
            ("explanation", "boundary"),
        ),
        FrameBlueprint(
            "comparison-options",
            "comparison",
            ("cover", "thesis", "comparison", "qa", "checklist"),
            ("story_beat", "boundary"),
        ),
        FrameBlueprint(
            "comparison-story",
            "comparison",
            ("cover", "story_beat", "comparison", "explanation", "save"),
            ("diagnostic", "boundary"),
        ),
    ),
    "diagnostic_qa": (
        FrameBlueprint(
            "diagnostic-branches",
            "diagnostic_qa",
            ("cover", "scene", "diagnostic", "qa", "save"),
            ("explanation", "boundary"),
        ),
        FrameBlueprint(
            "diagnostic-checklist",
            "diagnostic_qa",
            ("cover", "qa", "diagnostic", "checklist", "boundary"),
            ("comparison", "save"),
        ),
        FrameBlueprint(
            "diagnostic-story",
            "diagnostic_qa",
            ("cover", "story_beat", "diagnostic", "explanation", "save"),
            ("qa", "boundary"),
        ),
    ),
    "scenario_story": (
        FrameBlueprint(
            "story-discovery",
            "scenario_story",
            ("cover", "scene", "story_beat", "explanation", "save"),
            ("steps", "boundary"),
        ),
        FrameBlueprint(
            "story-tension",
            "scenario_story",
            ("cover", "scene", "story_beat", "comparison", "checklist"),
            ("explanation", "boundary"),
        ),
        FrameBlueprint(
            "story-reflection",
            "scenario_story",
            ("cover", "story_beat", "explanation", "quote", "save"),
            ("scene", "boundary"),
        ),
    ),
    "story_reversal": (
        FrameBlueprint(
            "reversal-reveal",
            "story_reversal",
            ("cover", "scene", "story_beat", "explanation", "save"),
            ("comparison", "boundary"),
        ),
        FrameBlueprint(
            "reversal-diagnostic",
            "story_reversal",
            ("cover", "story_beat", "diagnostic", "steps", "checklist"),
            ("explanation", "boundary"),
        ),
        FrameBlueprint(
            "reversal-contrast",
            "story_reversal",
            ("cover", "comparison", "story_beat", "explanation", "save"),
            ("qa", "boundary"),
        ),
    ),
    "reflective_editorial": (
        FrameBlueprint(
            "editorial-thesis",
            "reflective_editorial",
            ("cover", "quote", "explanation", "scene", "save"),
            ("story_beat", "boundary"),
        ),
        FrameBlueprint(
            "editorial-story",
            "reflective_editorial",
            ("cover", "scene", "story_beat", "quote", "save"),
            ("explanation", "boundary"),
        ),
        FrameBlueprint(
            "editorial-principle",
            "reflective_editorial",
            ("cover", "thesis", "explanation", "quote", "checklist"),
            ("scene", "boundary"),
        ),
    ),
}
