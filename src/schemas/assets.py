from typing import Literal

from pydantic import Field, field_serializer, model_validator

from .visual_style import Sha256, StrictModel, deep_freeze, deep_thaw


class AssetManifestItem(StrictModel):
    asset_id: str = Field(min_length=1)
    directive_id: str = Field(min_length=1)
    page_id: str = Field(min_length=1)
    source_kind: Literal["catalog", "search", "generated"]
    provider: str = Field(min_length=1)
    license: str = Field(min_length=1)
    local_path: str = Field(min_length=1)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    sha256: Sha256
    subject_focal_point: tuple[float, float]
    crop_guidance: str
    security_status: Literal["approved", "rejected"]
    human_decision: Literal["pending", "approved", "rejected"]
    run_id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    internal_provenance: dict[str, str]

    @model_validator(mode="after")
    def validate_focal_point(self):
        if any(value < 0 or value > 1 for value in self.subject_focal_point):
            raise ValueError("asset subject focal point must be within 0..1")
        object.__setattr__(
            self,
            "internal_provenance",
            deep_freeze(self.internal_provenance),
        )
        return self

    @field_serializer("internal_provenance")
    def serialize_internal_provenance(self, value):
        return deep_thaw(value)


class AssetManifest(StrictModel):
    items: tuple[AssetManifestItem, ...]

    @model_validator(mode="after")
    def require_unique_bindings(self):
        asset_ids = [item.asset_id for item in self.items]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("asset manifest asset IDs must be unique")
        directive_ids = [item.directive_id for item in self.items]
        if len(directive_ids) != len(set(directive_ids)):
            raise ValueError("asset manifest directive IDs must be unique")
        return self
