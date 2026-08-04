from typing import Annotated, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

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
    # Scene elements are creative LLM output; tolerate extra fields (e.g. the
    # model sometimes adds corner_radius to shapes) by ignoring unknown keys.
    model_config = ConfigDict(extra="ignore", frozen=True)

    element_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    layer: int = Field(ge=0, le=100)
    intentional_overlap_with: tuple[str, ...] = ()


# CSS weight names → integer (LLMs sometimes emit string weights).
_WEIGHT_NAMES = {
    "thin": 400, "hairline": 400, "light": 400, "regular": 400, "normal": 400,
    "medium": 500,
    "semibold": 600, "semi-bold": 600, "demibold": 600,
    "bold": 700,
    "extrabold": 800, "extra-bold": 800, "heavy": 800,
    "black": 900,
}


class TextStyle(StrictModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    font_role: Literal["display", "heading", "body", "caption"]
    font_size: float = Field(ge=12, le=180)
    line_height: float = Field(ge=1.0, le=2.0)
    color: HexColor
    align: Literal["left", "center", "right"]
    weight: Literal[400, 500, 600, 700, 800, 900]
    emphasis_ranges: tuple[tuple[int, int], ...] = ()

    @field_validator("weight", mode="before")
    @classmethod
    def _coerce_weight(cls, value):
        if isinstance(value, str):
            return _WEIGHT_NAMES.get(value.lower().strip(), value)
        return value

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
    corner_radius: float = Field(default=0, ge=0, le=240)

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

        content_atom_set.validate_complete_fragments(
            direction_plan.content_fragments
        )
        direction_pages = tuple(
            (page.page_id, page.sequence) for page in direction_plan.page_sequence
        )
        design_pages = tuple((page.page_id, page.sequence) for page in self.pages)
        if design_pages != direction_pages:
            raise ValueError(
                "design plan pages must exactly match direction page IDs and sequences"
            )

        fragment_by_id = {
            fragment.fragment_id: fragment
            for fragment in direction_plan.content_fragments
        }
        direction_page_by_id = {
            page.page_id: page for page in direction_plan.page_sequence
        }
        asset_by_id = {item.asset_id: item for item in asset_manifest.items}
        directive_by_id = {
            directive.directive_id: directive
            for directive in direction_plan.asset_directives
        }

        for page in self.pages:
            direction_page = direction_page_by_id[page.page_id]
            owned_fragments = set(direction_page.fragment_ids)
            owned_directives = set(direction_page.asset_directive_ids)
            for element in page.elements:
                if isinstance(element, TextElement):
                    if element.content_ref not in fragment_by_id:
                        raise ValueError(
                            "text element content reference is unknown: "
                            f"{element.content_ref}"
                        )
                    if element.content_ref not in owned_fragments:
                        raise ValueError(
                            "text element content reference belongs to a different "
                            f"page: {element.content_ref}"
                        )
                elif isinstance(element, ImageElement):
                    asset = asset_by_id.get(element.asset_ref)
                    if asset is None:
                        raise ValueError(
                            "image element asset reference is unknown: "
                            f"{element.asset_ref}"
                        )
                    if asset.security_status != "approved":
                        raise ValueError(
                            "image element asset is not security-approved: "
                            f"{element.asset_ref}"
                        )
                    if asset.page_id != page.page_id:
                        raise ValueError(
                            "image element asset belongs to a different page: "
                            f"{element.asset_ref}"
                        )
                    directive = directive_by_id.get(asset.directive_id)
                    if (
                        asset.directive_id not in owned_directives
                        or directive is None
                        or directive.page_id != page.page_id
                    ):
                        raise ValueError(
                            "image element asset directive is not owned by page: "
                            f"{asset.directive_id}"
                        )
