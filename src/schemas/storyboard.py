from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .editorial_templates import DensityHint, PageArchetype
from .visual_plan import _validate_page_archetypes


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

    @field_validator("items", mode="before")
    @classmethod
    def _coerce_null_items_to_empty(cls, value):
        # Live models sometimes emit `items: null` for blocks with no items;
        # treat that as an empty list rather than failing CarouselPayload parsing.
        if value is None:
            return []
        return value


class VisualSlot(StrictModel):
    slot_id: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=64)
    semantic_tags: list[str] = Field(default_factory=list, max_length=12)
    composition: Literal["left", "right", "center", "background", "full_bleed"] | None = None
    palette_tags: list[str] = Field(default_factory=list, max_length=8)


class CarouselFrame(StrictModel):
    frame_id: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=48)
    page_archetype: PageArchetype
    content_density_hint: DensityHint = "auto"
    headline: str = Field(min_length=1, max_length=80)
    kicker: str | None = Field(default=None, max_length=48)
    content_blocks: list[ContentBlock] = Field(max_length=8)
    emphasis: list[str] = Field(default_factory=list, max_length=6)
    visual_slots: list[VisualSlot] = Field(default_factory=list, max_length=4)
    footer: str | None = Field(default=None, max_length=80)
    # soft_pink editorial layouts render an account persona footer. It is a
    # visible string, so it is locked content: set deterministically before the
    # publish package is locked (see the storyboards generator node) and it
    # enters ContentLock.canonical_sha256.
    persona: str | None = Field(default=None, max_length=48)
    # soft_pink cover hero numeral (the step-count digit), rendered as a big
    # standalone numeral beside the title. Locked visible content; the digit is
    # also removed from the title text (see primitives.cover_title_text) so it is
    # not duplicated.
    hero_numeral: str | None = Field(default=None, max_length=8)


class CarouselPayload(StrictModel):
    storyboards: list[CarouselFrame] = Field(min_length=5, max_length=7)

    @model_validator(mode="after")
    def require_editorial_frame_composition(self):
        _validate_page_archetypes(self.storyboards)
        slot_ids = [
            slot.slot_id for frame in self.storyboards for slot in frame.visual_slots
        ]
        if len(slot_ids) != len(set(slot_ids)):
            raise ValueError("storyboard visual slot IDs must be globally unique")
        return self
