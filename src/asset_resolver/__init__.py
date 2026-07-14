"""Deterministic local-first visual asset resolution."""

from .catalog import AssetCatalog, AssetEntry, CatalogError, load_catalog
from .lifecycle import (
    AssetLifecycleError,
    PendingAsset,
    BatchAssetReviewResult,
    approve_external_asset,
    list_pending_assets,
    load_pending_asset,
    reject_external_asset,
    pending_asset_decision_binding,
    review_pending_asset_batch,
)
from .providers import (
    AssetProvider,
    ExternalAssetCandidate,
    PexelsProvider,
    UnsplashProvider,
)
from .resolver import AssetResolutionError, resolve_assets

__all__ = [
    "AssetCatalog",
    "AssetEntry",
    "AssetLifecycleError",
    "AssetProvider",
    "AssetResolutionError",
    "CatalogError",
    "ExternalAssetCandidate",
    "PendingAsset",
    "BatchAssetReviewResult",
    "PexelsProvider",
    "UnsplashProvider",
    "approve_external_asset",
    "list_pending_assets",
    "load_catalog",
    "load_pending_asset",
    "reject_external_asset",
    "pending_asset_decision_binding",
    "review_pending_asset_batch",
    "resolve_assets",
]
