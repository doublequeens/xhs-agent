from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator


TemplateFamily = Literal[
    "pink_red",
    "deep_teal",
    "soft_pink",
    "coral_impact",
    "green_catalog",
    "white_quote",
]
PageArchetype = Literal[
    "cover",
    "thesis",
    "scene",
    "story_beat",
    "explanation",
    "steps",
    "checklist",
    "comparison",
    "diagnostic",
    "qa",
    "item_collection",
    "quote",
    "boundary",
    "save",
    "closing",
]
Density = Literal["sparse", "standard", "dense"]
DensityHint = Literal["auto", "sparse", "standard", "dense"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TemplateSelection(StrictModel):
    template_family: TemplateFamily
    score: int
    reasons: list[str] = Field(min_length=1)
    rejected_families: dict[TemplateFamily, list[str]]

    @model_validator(mode="after")
    def require_all_other_families(self):
        expected = set(get_args(TemplateFamily)) - {self.template_family}
        if set(self.rejected_families) != expected:
            raise ValueError(
                "rejected_families must contain every unselected family"
            )
        return self


class CopyMetrics(StrictModel):
    grapheme_count: int = Field(ge=0)
    cjk_count: int = Field(ge=0)
    latin_word_count: int = Field(ge=0)
    emoji_count: int = Field(ge=0)
    block_count: int = Field(ge=0)
    item_count: int = Field(ge=0)
    max_item_graphemes: int = Field(ge=0)
    estimated_lines: int = Field(ge=0)


class ResolvedVariant(StrictModel):
    density: Density
    composition_variant: str = Field(min_length=1, max_length=64)
    metrics: CopyMetrics
