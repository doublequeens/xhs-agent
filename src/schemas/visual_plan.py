from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .assets import AssetRequirement
from .editorial_templates import (
    Density,
    PageArchetype,
    TemplateFamily,
    TemplateSelection,
)
from .narrative import NarrativeForm


ContentJob = Literal[
    "diagnose_and_adjust",
    "follow_steps",
    "compare_and_choose",
    "save_and_check",
    "understand_and_notice",
]
VisualFamily = Literal[
    "beauty_editorial",
    "face_zone_map",
    "step_flow",
    "comparison_decision",
    "saveable_reference",
]
_SAVEABLE_ARCHETYPES = frozenset({"save", "checklist", "comparison"})


def _validate_page_archetypes(frames) -> None:
    if frames[0].page_archetype != "cover":
        raise ValueError("first frame page_archetype must be cover")
    if not any(
        frame.page_archetype in _SAVEABLE_ARCHETYPES for frame in frames
    ):
        raise ValueError(
            "frame plan must include a standalone saveable archetype"
        )


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FramePlanItem(StrictModel):
    frame_id: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=48)
    page_archetype: PageArchetype
    purpose: str = Field(min_length=1, max_length=160)
    allowed_density: list[Density] = Field(min_length=1, max_length=3)
    asset_roles: list[str] = Field(default_factory=list, max_length=4)


class VisualPlan(StrictModel):
    design_system: Literal["beauty_editorial_v2"]
    template_family: TemplateFamily
    template_selection: TemplateSelection
    narrative_form: NarrativeForm
    content_job: ContentJob
    frame_plan: list[FramePlanItem] = Field(min_length=5, max_length=7)
    required_assets: list[AssetRequirement]

    @model_validator(mode="after")
    def require_editorial_frame_composition(self):
        _validate_page_archetypes(self.frame_plan)
        return self
