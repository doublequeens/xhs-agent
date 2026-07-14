from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Literal

from src.schemas.assets import AssetRequirement

from .catalog import AssetEntry


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
EligibilityMode = Literal["base", "exact", "fallback"]


def _has_complete_provenance(entry: AssetEntry) -> bool:
    return bool(
        entry.ownership
        and entry.license
        and _SHA256_PATTERN.fullmatch(entry.sha256)
    )


def entry_satisfies_requirement(
    entry: AssetEntry,
    requirement: AssetRequirement,
    *,
    mode: EligibilityMode,
    catalog_entries: Iterable[AssetEntry] = (),
    authorizer_integrity: Callable[[AssetEntry], bool] | None = None,
) -> bool:
    """Apply the resolver's canonical exact or explicit-fallback contract."""

    base_eligible = (
        entry.usage == "production"
        and requirement.layout in entry.allowed_layouts
        and entry.width >= requirement.min_width
        and entry.height >= requirement.min_height
        and (
            requirement.orientation == "any"
            or entry.orientation == requirement.orientation
        )
        and not set(requirement.context_tags).intersection(
            entry.disabled_contexts
        )
        and _has_complete_provenance(entry)
    )
    if not base_eligible or mode == "base":
        return base_eligible
    if mode == "exact":
        return entry.role == requirement.role
    if entry.asset_id not in requirement.fallback_asset_ids:
        return False
    integrity = authorizer_integrity or (lambda _entry: True)
    return any(
        candidate.usage == "production"
        and candidate.role == requirement.role
        and entry.role in candidate.fallback_roles
        and _has_complete_provenance(candidate)
        and integrity(candidate)
        for candidate in catalog_entries
    )
