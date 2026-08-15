from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from .scene_graph import Box
from .visual_style import Sha256, StrictModel, deep_freeze, deep_thaw


class RenderedElementProbe(StrictModel):
    element_id: str = Field(min_length=1)
    kind: Literal["text", "image", "shape", "line", "icon"]
    actual_box: Box
    computed_font_family: str | None
    computed_font_size: float | None = Field(default=None, ge=0)
    computed_line_height: float | None = Field(default=None, ge=0)
    overflow: bool
    ink_clipped: bool
    layout_clipped: bool
    contrast_ratio: float = Field(ge=0, le=21)
    content_ref: str | None
    asset_ref: str | None
    rasterized_text_sha256: Sha256 | None
    rendered_asset_sha256: Sha256 | None = None
    actual_focal_point: tuple[float, float] | None = None
    crop_box: Box | None = None
    # Raw layout attestations collected from the DOM (Task 11 brief Step 1).
    # Optional and backward-compatible: text probes surface the measured
    # scroll/client box and per-line rectangles; image probes surface the
    # <img> intrinsic (natural) dimensions. Consumers that ignore them are
    # unaffected.
    scroll_width: float | None = Field(default=None, ge=0)
    scroll_height: float | None = Field(default=None, ge=0)
    client_width: float | None = Field(default=None, ge=0)
    client_height: float | None = Field(default=None, ge=0)
    line_boxes: tuple[Box, ...] | None = None
    natural_width: float | None = Field(default=None, ge=0)
    natural_height: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_kind_attestation(self):
        if self.kind == "text":
            required = (
                self.computed_font_family,
                self.computed_font_size,
                self.computed_line_height,
                self.content_ref,
                self.rasterized_text_sha256,
            )
            if any(value is None for value in required):
                raise ValueError("text probe requires font, content, and rasterized text hash")
            if self.asset_ref is not None:
                raise ValueError("text probe cannot carry an asset reference")
        elif self.kind == "image":
            if self.asset_ref is None or self.rendered_asset_sha256 is None:
                raise ValueError("image probe requires asset reference and rendered asset hash")
            if self.content_ref is not None or self.rasterized_text_sha256 is not None:
                raise ValueError("image probe cannot carry content attestation")
        return self


class RenderedPage(StrictModel):
    page_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    path: str = Field(min_length=1)
    width: Literal[1080]
    height: Literal[1440]
    sha256: Sha256
    element_probes: tuple[RenderedElementProbe, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_probe_ids(self):
        probe_ids = [probe.element_id for probe in self.element_probes]
        if len(probe_ids) != len(set(probe_ids)):
            raise ValueError("rendered page element probe IDs must be unique")
        return self


class FontLoadReport(StrictModel):
    all_loaded: bool
    computed_families: tuple[str, ...]


class RenderManifest(StrictModel):
    design_plan_sha256: Sha256
    content_atom_set_sha256: Sha256
    asset_manifest_sha256: Sha256
    revision: int = Field(ge=0)
    pages: tuple[RenderedPage, ...] = Field(min_length=5, max_length=18)
    fonts: FontLoadReport
    contact_sheet_path: str = Field(min_length=1)
    contact_sheet_sha256: Sha256
    source_asset_sha256: dict[str, Sha256]

    @model_validator(mode="after")
    def require_contiguous_unique_pages(self):
        page_ids = [page.page_id for page in self.pages]
        if len(page_ids) != len(set(page_ids)):
            raise ValueError("render manifest page IDs must be unique")
        if [page.sequence for page in self.pages] != list(
            range(1, len(self.pages) + 1)
        ):
            raise ValueError("render manifest page sequences must be contiguous from 1")
        object.__setattr__(
            self,
            "source_asset_sha256",
            deep_freeze(self.source_asset_sha256),
        )
        return self

    @field_serializer("source_asset_sha256")
    def serialize_source_asset_sha256(self, value):
        return deep_thaw(value)
