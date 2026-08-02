from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    model_validator,
)


class StrictModel(BaseModel):
    # NOTE: ``strict=True`` is intentionally omitted. Real structured-output
    # providers (Gemini) return JSON, where every sequence is a JSON array
    # (Python list). Pydantic's strict mode rejects list -> tuple coercion,
    # which made every tuple-typed field (palette, page_sequence, asset_directives,
    # ...) fail validation against real model output. ``extra="forbid"`` still
    # rejects unknown fields and ``frozen=True`` keeps instances immutable, which
    # are the invariants that actually matter.
    model_config = ConfigDict(extra="forbid", frozen=True)


def deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, list | tuple):
        return tuple(deep_freeze(item) for item in value)
    return value


def deep_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [deep_thaw(item) for item in value]
    return value


Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
HexColor = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]

TemplateFamily = Literal[
    "pink_red",
    "deep_teal",
    "soft_pink",
    "coral_impact",
    "green_catalog",
    "white_quote",
]

FontRole = Literal["display", "heading", "body", "caption"]


class FamilyStyleProfile(StrictModel):
    family: TemplateFamily
    reference_image_paths: tuple[str, ...] = Field(min_length=1)
    palette: tuple[str, ...] = Field(min_length=3)
    font_roles: dict[FontRole, str]
    composition_principles: tuple[str, ...] = Field(min_length=2)
    whitespace_range: tuple[float, float]
    density_range: tuple[float, float]
    allowed_motifs: tuple[str, ...]
    prohibited_patterns: tuple[str, ...]

    @model_validator(mode="after")
    def validate_profile_ranges_and_roles(self):
        expected_roles = {"display", "heading", "body", "caption"}
        if set(self.font_roles) != expected_roles:
            raise ValueError("family font roles must define display, heading, body, caption")
        for label, value_range in (
            ("whitespace", self.whitespace_range),
            ("density", self.density_range),
        ):
            low, high = value_range
            if not 0 <= low <= high <= 1:
                raise ValueError(f"family {label} range must be ordered within 0..1")
        object.__setattr__(self, "font_roles", deep_freeze(self.font_roles))
        return self

    @field_serializer("font_roles")
    def serialize_font_roles(self, value):
        return deep_thaw(value)
