from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


NarrativeForm = Literal[
    "cognitive_correction",
    "step_tutorial",
    "checklist_collection",
    "comparison",
    "diagnostic_qa",
    "scenario_story",
    "story_reversal",
    "reflective_editorial",
]
NarrativeBeatKind = Literal[
    "hook",
    "scene",
    "tension",
    "misconception",
    "reveal",
    "principle",
    "explanation",
    "example",
    "steps",
    "checklist",
    "comparison",
    "diagnostic",
    "qa",
    "quote",
    "boundary",
    "summary",
    "action",
]
ClosingMode = Literal[
    "none",
    "boundary",
    "reflection",
    "focused_question",
    "action_prompt",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NarrativeBeat(StrictModel):
    beat_id: str = Field(min_length=1, max_length=48)
    kind: NarrativeBeatKind
    purpose: str = Field(min_length=1, max_length=160)


class NarrativePlan(StrictModel):
    narrative_form: NarrativeForm
    beats: list[NarrativeBeat] = Field(min_length=4, max_length=8)
    saveable_beat: NarrativeBeat
    closing_mode: ClosingMode

    @model_validator(mode="after")
    def validate_beats(self):
        beat_ids = [beat.beat_id for beat in self.beats]
        if len(beat_ids) != len(set(beat_ids)):
            raise ValueError("narrative beat IDs must be unique")
        if self.saveable_beat not in self.beats:
            raise ValueError("saveable_beat must exactly match one narrative beat")
        return self
