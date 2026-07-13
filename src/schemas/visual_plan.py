from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
