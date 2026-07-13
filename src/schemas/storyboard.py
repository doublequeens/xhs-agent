from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .text_card import TextCardFrame, TextCardPayload
from .visual_plan import LayoutName, _validate_editorial_frame_layouts


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContentBlock(StrictModel):
    block_type: Literal[
        "text",
        "bullets",
        "steps",
        "comparison",
        "checklist",
        "decision_tree",
        "labels",
    ]
    heading: str | None = Field(default=None, max_length=80)
    body: str | None = Field(default=None, max_length=240)
    items: list[str] = Field(default_factory=list, max_length=8)


class VisualSlot(StrictModel):
    slot_id: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=64)
    semantic_tags: list[str] = Field(default_factory=list, max_length=12)
    composition: Literal["left", "right", "center", "background", "full_bleed"] | None = None
    palette_tags: list[str] = Field(default_factory=list, max_length=8)


class CarouselFrame(StrictModel):
    frame_id: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=48)
    layout: LayoutName
    headline: str = Field(min_length=1, max_length=80)
    kicker: str | None = Field(default=None, max_length=48)
    content_blocks: list[ContentBlock] = Field(max_length=8)
    emphasis: list[str] = Field(default_factory=list, max_length=6)
    visual_slots: list[VisualSlot] = Field(default_factory=list, max_length=4)
    footer: str | None = Field(default=None, max_length=80)


class CarouselPayload(StrictModel):
    storyboards: list[CarouselFrame] = Field(min_length=5, max_length=7)

    @model_validator(mode="after")
    def require_editorial_frame_composition(self):
        _validate_editorial_frame_layouts(self.storyboards)
        return self


# Compatibility names remain on the legacy contract until the graph migration.
StoryboardFrame = TextCardFrame
StoryboardPayload = TextCardPayload
