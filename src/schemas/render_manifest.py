from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .visual_plan import LayoutName


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextProbeResult(StrictModel):
    role: str = Field(min_length=1)
    text: str
    visible: bool
    overflow: bool
    ink_clipped: bool
    layout_clipped: bool
    font_family: str = Field(min_length=1)
    font_size: float = Field(gt=0)
    line_height: float = Field(gt=0)
    line_count: int = Field(ge=1)
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class AssetProbeResult(StrictModel):
    slot_id: str = Field(min_length=1, max_length=64)
    natural_width: int = Field(ge=1)
    natural_height: int = Field(ge=1)
    rendered_width: float = Field(gt=0)
    rendered_height: float = Field(gt=0)
    object_fit: Literal["contain", "cover", "fill", "none", "scale-down"]
    cropped: bool
    aspect_ratio_error: float = Field(ge=0)


class PageProbeAttestation(StrictModel):
    canvas_width: Literal[1080]
    canvas_height: Literal[1440]
    safe_margin: float = Field(ge=0)
    text_results: list[TextProbeResult] = Field(min_length=1)
    asset_results: list[AssetProbeResult]
    issues: list[str]


class RenderedPage(StrictModel):
    frame_id: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=48)
    layout: LayoutName
    path: str = Field(min_length=1)
    width: Literal[1080]
    height: Literal[1440]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe: PageProbeAttestation


class FontLoadReport(StrictModel):
    all_loaded: bool
    computed_families: list[str]


class RenderManifest(StrictModel):
    pages: list[RenderedPage] = Field(min_length=5, max_length=7)
    fonts: FontLoadReport
    contact_sheet_path: str = Field(min_length=1)
    contact_sheet_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    contact_sheet_page_sha256: list[str] = Field(min_length=5, max_length=7)
    source_asset_sha256: dict[str, str]
