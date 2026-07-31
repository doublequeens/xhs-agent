from typing import Annotated, Literal

from pydantic import Field, model_validator

from .assets import AssetManifest
from .content_atoms import ContentAtomSet, canonical_sha256
from .visual_director import VisualDirectionPlan
from .visual_style import HexColor, Sha256, StrictModel


class Box(StrictModel):
    x: float = Field(ge=0, le=1080)
    y: float = Field(ge=0, le=1440)
    width: float = Field(gt=0, le=1080)
    height: float = Field(gt=0, le=1440)


class ElementBase(StrictModel):
    element_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    layer: int = Field(ge=0, le=100)
    intentional_overlap_with: tuple[str, ...] = ()


class TextStyle(StrictModel):
    font_role: Literal["display", "heading", "body", "caption"]
    font_size: float = Field(ge=12, le=180)
    line_height: float = Field(ge=1.0, le=2.0)
    color: HexColor
    align: Literal["left", "center", "right"]
    weight: Literal[400, 500, 600, 700, 800, 900]
    emphasis_ranges: tuple[tuple[int, int], ...] = ()

    @model_validator(mode="after")
    def validate_emphasis_ranges(self):
        if any(start < 0 or end <= start for start, end in self.emphasis_ranges):
            raise ValueError("text emphasis ranges must be non-empty and ordered")
        return self


class TextElement(ElementBase):
    kind: Literal["text"] = "text"
    box: Box
    content_ref: str = Field(min_length=1)
    style: TextStyle


class ImageElement(ElementBase):
    kind: Literal["image"] = "image"
    box: Box
    asset_ref: str = Field(min_length=1)
    fit: Literal["cover", "contain"]
    focal_point: tuple[float, float]
    corner_radius: float = Field(ge=0, le=240)

    @model_validator(mode="after")
    def validate_focal_point(self):
        if any(value < 0 or value > 1 for value in self.focal_point):
            raise ValueError("image focal point must be within 0..1")
        return self


class ShapeElement(ElementBase):
    kind: Literal["shape"] = "shape"
    box: Box
    shape: Literal["rectangle", "rounded_rectangle", "circle", "ellipse"]
    fill: HexColor
    stroke: HexColor | None = None


class LineElement(ElementBase):
    kind: Literal["line"] = "line"
    start: tuple[float, float]
    end: tuple[float, float]
    color: HexColor
    width: float = Field(gt=0, le=24)


class IconElement(ElementBase):
    kind: Literal["icon"] = "icon"
    box: Box
    icon: Literal["arrow", "check", "cross", "sparkle", "dot", "bracket"]
    color: HexColor


SceneElement = Annotated[
    TextElement | ImageElement | ShapeElement | LineElement | IconElement,
    Field(discriminator="kind"),
]


class PageScene(StrictModel):
    page_id: str
    sequence: int = Field(ge=1)
    background: HexColor
    elements: tuple[SceneElement, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_element_ids(self):
        element_ids = [element.element_id for element in self.elements]
        if len(element_ids) != len(set(element_ids)):
            raise ValueError("page scene element IDs must be unique")
        return self


class CarouselDesignPlan(StrictModel):
    direction_plan_sha256: Sha256
    content_atom_set_sha256: Sha256
    asset_manifest_sha256: Sha256
    revision: int = Field(ge=0)
    pages: tuple[PageScene, ...] = Field(min_length=5, max_length=18)

    @model_validator(mode="after")
    def require_contiguous_unique_pages(self):
        page_ids = [page.page_id for page in self.pages]
        if len(page_ids) != len(set(page_ids)):
            raise ValueError("design plan page IDs must be unique")
        if [page.sequence for page in self.pages] != list(
            range(1, len(self.pages) + 1)
        ):
            raise ValueError("design plan page sequences must be contiguous from 1")
        return self

    def validate_bindings(
        self,
        direction_plan: VisualDirectionPlan,
        content_atom_set: ContentAtomSet,
        asset_manifest: AssetManifest,
    ) -> None:
        if self.direction_plan_sha256 != canonical_sha256(direction_plan):
            raise ValueError("design plan direction hash does not match source")
        if self.content_atom_set_sha256 != content_atom_set.canonical_sha256:
            raise ValueError("design plan content atom set hash does not match source")
        if self.asset_manifest_sha256 != canonical_sha256(asset_manifest):
            raise ValueError("design plan asset manifest hash does not match source")

