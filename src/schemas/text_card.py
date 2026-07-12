from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


REQUIRED_TEXT_CARD_TEMPLATES = (
    "cover_statement",
    "wrong_vs_right",
    "step_timeline",
    "saveable_checklist",
    "decision_rule",
    "question_closer",
)

TextCardTheme = Literal["warm_neutral", "cool_sage"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TimelineStep(_StrictModel):
    name: str = Field(min_length=1, max_length=12)
    hint: str = Field(min_length=1, max_length=16)


class _TextCardFrame(_StrictModel):
    frame_id: str = Field(min_length=1, max_length=64)
    theme: TextCardTheme
    kicker: str = Field(min_length=1, max_length=10)
    headline: str = Field(min_length=1, max_length=28)
    footer: str = Field(min_length=1, max_length=18)


class CoverStatementFrame(_TextCardFrame):
    template: Literal["cover_statement"]


class WrongVsRightFrame(_TextCardFrame):
    template: Literal["wrong_vs_right"]
    wrong_items: list[str] = Field(min_length=2, max_length=3)
    right_items: list[str] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def require_short_items(self):
        if any(not item or len(item) > 16 for item in self.wrong_items + self.right_items):
            raise ValueError("wrong_items and right_items entries must be 1-16 characters")
        return self


class StepTimelineFrame(_TextCardFrame):
    template: Literal["step_timeline"]
    steps: list[TimelineStep] = Field(min_length=3, max_length=5)


class SaveableChecklistFrame(_TextCardFrame):
    template: Literal["saveable_checklist"]
    checklist_items: list[str] = Field(min_length=3, max_length=5)

    @model_validator(mode="after")
    def require_short_items(self):
        if any(not item or len(item) > 16 for item in self.checklist_items):
            raise ValueError("checklist_items entries must be 1-16 characters")
        return self


class DecisionRuleFrame(_TextCardFrame):
    template: Literal["decision_rule"]
    condition: str = Field(min_length=1, max_length=16)
    recommendation: str = Field(min_length=1, max_length=16)


class QuestionCloserFrame(_TextCardFrame):
    template: Literal["question_closer"]
    question: str = Field(min_length=1, max_length=22)


TextCardFrame = Annotated[
    Union[
        CoverStatementFrame,
        WrongVsRightFrame,
        StepTimelineFrame,
        SaveableChecklistFrame,
        DecisionRuleFrame,
        QuestionCloserFrame,
    ],
    Field(discriminator="template"),
]


class TextCardPayload(_StrictModel):
    storyboards: list[TextCardFrame] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def require_template_order(self):
        if [frame.template for frame in self.storyboards] != list(REQUIRED_TEXT_CARD_TEMPLATES):
            raise ValueError("storyboards must use the six required templates in order")
        if len({frame.theme for frame in self.storyboards}) != 1:
            raise ValueError("all storyboards must use one theme")
        return self
