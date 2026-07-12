import re
from typing import Annotated, Literal, Union

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


REQUIRED_TEXT_CARD_TEMPLATES = (
    "cover_statement",
    "wrong_vs_right",
    "step_timeline",
    "saveable_checklist",
    "decision_rule",
    "question_closer",
)

TextCardTheme = Literal["warm_neutral", "cool_sage"]

# Emoji are prohibited in every atom the renderer can place on a card.  This
# deliberately lives at the leaf-string boundary so nested/list atoms cannot
# bypass the rule.
_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\U0001FC00-\U0001FFFD\u2600-\u27BF]")


def _reject_emoji(value: str) -> str:
    if _EMOJI_RE.search(value):
        raise ValueError("visible card copy must not contain emoji")
    return value


VisibleCopy = Annotated[str, AfterValidator(_reject_emoji)]
ShortItem = Annotated[VisibleCopy, Field(min_length=1, max_length=16)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TimelineStep(_StrictModel):
    name: VisibleCopy = Field(min_length=1, max_length=12)
    hint: ShortItem


class DecisionCondition(_StrictModel):
    situation: ShortItem
    recommendation: ShortItem


class _TextCardFrame(_StrictModel):
    frame_id: str = Field(min_length=1, max_length=64)
    theme: TextCardTheme
    kicker: VisibleCopy | None = Field(default=None, max_length=10)
    headline: VisibleCopy = Field(min_length=1, max_length=28)
    footer: VisibleCopy | None = Field(default=None, max_length=18)


class CoverStatementFrame(_TextCardFrame):
    template: Literal["cover_statement"]


class WrongVsRightFrame(_TextCardFrame):
    template: Literal["wrong_vs_right"]
    wrong_items: list[ShortItem] = Field(min_length=2, max_length=3)
    right_items: list[ShortItem] = Field(min_length=2, max_length=4)


class StepTimelineFrame(_TextCardFrame):
    template: Literal["step_timeline"]
    steps: list[TimelineStep] = Field(min_length=3, max_length=5)


class SaveableChecklistFrame(_TextCardFrame):
    template: Literal["saveable_checklist"]
    checklist_items: list[ShortItem] = Field(min_length=3, max_length=5)


class DecisionRuleFrame(_TextCardFrame):
    template: Literal["decision_rule"]
    conditions: list[DecisionCondition] = Field(min_length=2, max_length=3)


class QuestionCloserFrame(_TextCardFrame):
    template: Literal["question_closer"]
    question: VisibleCopy = Field(min_length=1, max_length=22)


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
