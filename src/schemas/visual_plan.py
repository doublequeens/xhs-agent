from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .assets import AssetRequirement, LayoutName


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
_SAVEABLE_LAYOUTS = frozenset({"saveable_checklist", "saveable_reference"})


def _validate_editorial_frame_layouts(frames) -> None:
    layouts = [frame.layout for frame in frames]
    if layouts[0] != "editorial_cover":
        raise ValueError("first frame layout must be editorial_cover")
    if len(set(layouts)) < 3:
        raise ValueError("frame plan must use at least three distinct layouts")
    if not _SAVEABLE_LAYOUTS.intersection(layouts):
        raise ValueError("frame plan must include a saveable layout")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FramePlanItem(StrictModel):
    frame_id: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=48)
    layout: LayoutName
    purpose: str = Field(min_length=1, max_length=160)
    asset_roles: list[str] = Field(default_factory=list, max_length=4)


class VisualPlan(StrictModel):
    design_system: Literal["beauty_editorial_v1"]
    content_job: ContentJob
    primary_visual_family: VisualFamily
    supporting_families: list[VisualFamily] = Field(max_length=4)
    frame_plan: list[FramePlanItem] = Field(min_length=5, max_length=7)
    required_assets: list[AssetRequirement]

    @model_validator(mode="after")
    def require_editorial_frame_composition(self):
        _validate_editorial_frame_layouts(self.frame_plan)
        return self
