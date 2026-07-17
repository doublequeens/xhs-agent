from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .editorial_templates import Density, PageArchetype, TemplateFamily


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextProbeResult(StrictModel):
    role: str = Field(min_length=1)
    text: str
    emoji_graphemes: list[str] = Field(default_factory=list)
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

    @model_validator(mode="after")
    def require_unique_asset_slots(self):
        slot_ids = [result.slot_id for result in self.asset_results]
        if len(slot_ids) != len(set(slot_ids)):
            raise ValueError("page probe asset slot IDs must be unique")
        return self


class RenderedPage(StrictModel):
    frame_id: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=48)
    page_archetype: PageArchetype
    template_family: TemplateFamily
    density: Density
    composition_variant: str
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
    contact_sheet_page_sha256: list[
        Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    ] = Field(min_length=5, max_length=7)
    source_asset_sha256: dict[str, str]

    @model_validator(mode="after")
    def require_one_template_family(self):
        families = {page.template_family for page in self.pages}
        if len(families) != 1:
            raise ValueError("all rendered pages must use one template family")
        return self
