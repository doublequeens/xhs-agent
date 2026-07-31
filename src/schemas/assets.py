from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from .editorial_templates import PageArchetype
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


class LegacyAssetModel(BaseModel):
    """Temporary import compatibility for the v2 visual path pending removal."""

    model_config = ConfigDict(extra="forbid")


class AssetRequirement(LegacyAssetModel):
    slot_id: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=64)
    page_archetype: PageArchetype
    min_width: int = Field(ge=1)
    min_height: int = Field(ge=1)
    context_tags: list[str] = Field(default_factory=list, max_length=12)
    orientation: Literal["portrait", "landscape", "square", "any"] = "any"
    palette_tags: list[str] = Field(default_factory=list, max_length=8)
    fallback_asset_ids: list[str] = Field(default_factory=list, max_length=4)


class ProviderSearchReport(LegacyAssetModel):
    provider: str = Field(min_length=1, max_length=32)
    status: Literal["not_configured", "skipped", "success", "failed"]
    query: str | None = None
    result_ids: list[str] = Field(default_factory=list)
    error: str | None = None
    elapsed_ms: float | None = Field(default=None, ge=0)
    download_errors: list[str] = Field(default_factory=list)


class AssetSearchReport(LegacyAssetModel):
    search_triggered: bool
    queries: list[str]
    provider_reports: list[ProviderSearchReport]
    selection_reasons: dict[str, str]
