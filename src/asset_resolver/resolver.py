from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Literal

from src.schemas.assets import (
    AssetManifest,
    AssetManifestItem,
    AssetRequirement,
    AssetSearchReport,
)
from src.schemas.visual_plan import VisualPlan

from .catalog import AssetCatalog, AssetEntry


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class AssetResolutionError(RuntimeError):
    """Raised when a visual-plan slot cannot be resolved locally."""


def _has_complete_provenance(entry: AssetEntry) -> bool:
    return bool(
        entry.ownership
        and entry.license
        and _SHA256_PATTERN.fullmatch(entry.sha256)
        and entry.path.is_file()
    )


def _crop_compatible(entry: AssetEntry, requirement: AssetRequirement) -> bool:
    return (
        requirement.orientation == "any"
        or entry.orientation == requirement.orientation
    )


def _base_eligible(entry: AssetEntry, requirement: AssetRequirement) -> bool:
    return (
        entry.usage == "production"
        and requirement.layout in entry.allowed_layouts
        and entry.width >= requirement.min_width
        and entry.height >= requirement.min_height
        and _crop_compatible(entry, requirement)
        and not set(requirement.context_tags).intersection(entry.disabled_contexts)
        and _has_complete_provenance(entry)
    )


def eligible(entry: AssetEntry, requirement: AssetRequirement) -> bool:
    """Return whether an entry is a production-safe exact local match."""

    return entry.role == requirement.role and _base_eligible(entry, requirement)


def _has_catalog_integrity(entry: AssetEntry, catalog: AssetCatalog) -> bool:
    try:
        path = entry.path.resolve()
        active_root = catalog.active_root.resolve()
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return False
    return path.is_relative_to(active_root) and actual_hash == entry.sha256


def _last_used_timestamp(catalog: AssetCatalog, asset_id: str) -> float:
    value = catalog.last_used_at.get(asset_id)
    if value is None:
        return float("-inf")
    if not isinstance(value, datetime):
        raise AssetResolutionError(
            f"last_used_at for {asset_id!r} must be a datetime"
        )
    return value.timestamp()


def _rank_key(
    entry: AssetEntry,
    requirement: AssetRequirement,
    catalog: AssetCatalog,
) -> tuple[int, int, int, int, float, str]:
    entry_tags = set(entry.tags)
    return (
        -int(entry.role == requirement.role),
        -len(entry_tags.intersection(requirement.context_tags)),
        -int(
            requirement.orientation != "any"
            and entry.orientation == requirement.orientation
        ),
        -len(entry_tags.intersection(requirement.palette_tags)),
        _last_used_timestamp(catalog, entry.asset_id),
        entry.asset_id,
    )


def _select_exact(
    requirement: AssetRequirement,
    catalog: AssetCatalog,
) -> AssetEntry | None:
    candidates = [
        entry
        for entry in catalog.entries
        if entry.asset_id not in catalog.recent_asset_ids
        and eligible(entry, requirement)
        and _has_catalog_integrity(entry, catalog)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda entry: _rank_key(entry, requirement, catalog))


def _select_explicit_fallback(
    requirement: AssetRequirement,
    catalog: AssetCatalog,
) -> AssetEntry | None:
    entries_by_id = {entry.asset_id: entry for entry in catalog.entries}
    for asset_id in requirement.fallback_asset_ids:
        entry = entries_by_id.get(asset_id)
        fallback_role_is_declared = entry is not None and any(
            candidate.usage == "production"
            and candidate.role == requirement.role
            and entry.role in candidate.fallback_roles
            for candidate in catalog.entries
        )
        if (
            entry is not None
            and fallback_role_is_declared
            and entry.asset_id not in catalog.recent_asset_ids
            and _base_eligible(entry, requirement)
            and _has_catalog_integrity(entry, catalog)
        ):
            return entry
    return None


def _manifest_item(
    requirement: AssetRequirement,
    entry: AssetEntry,
    *,
    status: Literal["active", "fallback"],
) -> AssetManifestItem:
    return AssetManifestItem(
        slot_id=requirement.slot_id,
        role=requirement.role,
        layout=requirement.layout,
        status=status,
        path=str(entry.path),
        asset_id=entry.asset_id,
        source_type="local",
        license=entry.license,
        width=entry.width,
        height=entry.height,
        sha256=entry.sha256,
    )


def resolve_assets(visual_plan: VisualPlan, catalog: AssetCatalog) -> AssetManifest:
    """Resolve every visual-plan slot from approved local assets or explicit fallbacks.

    External provider search and pending-asset lifecycle are intentionally deferred to
    Task 5. Providers attached to the catalog are never called by this implementation.
    """

    items: list[AssetManifestItem] = []
    selection_reasons: dict[str, str] = {}
    for requirement in visual_plan.required_assets:
        entry = _select_exact(requirement, catalog)
        if entry is not None:
            items.append(_manifest_item(requirement, entry, status="active"))
            selection_reasons[requirement.slot_id] = (
                f"selected eligible local exact match {entry.asset_id}"
            )
            continue

        fallback = _select_explicit_fallback(requirement, catalog)
        if fallback is not None:
            items.append(_manifest_item(requirement, fallback, status="fallback"))
            selection_reasons[requirement.slot_id] = (
                f"selected explicit local fallback {fallback.asset_id}"
            )
            continue

        raise AssetResolutionError(
            f"{requirement.slot_id}: no eligible asset or fallback"
        )

    return AssetManifest(
        items=items,
        search_report=AssetSearchReport(
            search_triggered=False,
            queries=[],
            provider_reports=[],
            selection_reasons=selection_reasons,
        ),
    )
