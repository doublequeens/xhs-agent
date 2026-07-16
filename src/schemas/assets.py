from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .editorial_templates import PageArchetype


LayoutName = Literal[
    "editorial_cover",
    "texture_baseline",
    "front_face_zone",
    "three_quarter_face_zone",
    "step_timeline",
    "morning_evening_flow",
    "left_right_comparison",
    "three_state_diagnostic",
    "decision_tree",
    "saveable_checklist",
    "saveable_reference",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssetRequirement(StrictModel):
    slot_id: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=64)
    page_archetype: PageArchetype
    min_width: int = Field(ge=1)
    min_height: int = Field(ge=1)
    context_tags: list[str] = Field(default_factory=list, max_length=12)
    orientation: Literal["portrait", "landscape", "square", "any"] = "any"
    palette_tags: list[str] = Field(default_factory=list, max_length=8)
    fallback_asset_ids: list[str] = Field(default_factory=list, max_length=4)


class ProviderSearchReport(StrictModel):
    provider: str = Field(min_length=1, max_length=32)
    status: Literal["not_configured", "skipped", "success", "failed"]
    query: str | None = None
    result_ids: list[str] = Field(default_factory=list)
    error: str | None = None
    elapsed_ms: float | None = Field(default=None, ge=0)
    download_errors: list[str] = Field(default_factory=list)


class AssetSearchReport(StrictModel):
    search_triggered: bool
    queries: list[str]
    provider_reports: list[ProviderSearchReport]
    selection_reasons: dict[str, str]


class AssetManifestItem(StrictModel):
    slot_id: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=64)
    page_archetype: PageArchetype
    status: Literal["active", "pending_external", "fallback"]
    path: str = Field(min_length=1)
    asset_id: str | None = None
    source_type: str = Field(min_length=1)
    provider: str | None = None
    provider_asset_id: str | None = None
    source_url: str | None = None
    source_file_url: str | None = None
    author: str | None = None
    provider_attribution: dict[str, str] = Field(default_factory=dict)
    license: str = Field(min_length=1)
    license_snapshot: str | None = None
    license_snapshot_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    license_terms_url: str | None = None
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pending_id: str | None = None
    metadata_path: str | None = None
    run_id: str | None = None
    acquired_at: str | None = None
    average_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")
    candidate_rank: int | None = Field(default=None, ge=1)
    requirement_fingerprint: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    attempt_number: int | None = Field(default=None, ge=1, le=3)
    unresolved_safety_checks: list[str] = Field(default_factory=list)
    safety_review_decisions: dict[str, bool] = Field(default_factory=dict)
    safety_reviewed_at: str | None = None
    review_status: Literal["approved"] | None = None
    review_disposition: Literal["approved_for_publishing"] | None = None


class AssetManifest(StrictModel):
    items: list[AssetManifestItem]
    search_report: AssetSearchReport
