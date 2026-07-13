"""Deterministic local-first visual asset resolution."""

from .catalog import AssetCatalog, AssetEntry, CatalogError, load_catalog
from .lifecycle import (
    AssetLifecycleError,
    PendingAsset,
    approve_external_asset,
    reject_external_asset,
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
    "PexelsProvider",
    "UnsplashProvider",
    "approve_external_asset",
    "load_catalog",
    "reject_external_asset",
    "resolve_assets",
]
