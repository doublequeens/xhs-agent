from pydantic import BaseModel, ConfigDict, Field

from .visual_plan import LayoutName


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RenderedPage(StrictModel):
    frame_id: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=48)
    layout: LayoutName
    path: str = Field(min_length=1)
    width: int = Field(ge=1)
    height: int = Field(ge=1)


class FontLoadReport(StrictModel):
    all_loaded: bool
    computed_families: list[str]


class RenderManifest(StrictModel):
    pages: list[RenderedPage]
    fonts: FontLoadReport
    contact_sheet_path: str = Field(min_length=1)
    source_asset_sha256: dict[str, str]
