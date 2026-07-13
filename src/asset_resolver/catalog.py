from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.rendering.editorial.design_system import (
    load_catalog as load_design_system_catalog,
)


class CatalogError(ValueError):
    """Raised when a local production catalog is invalid or unsafe."""


@dataclass(frozen=True, slots=True)
class AssetEntry:
    asset_id: str
    role: str
    path: Path
    width: int
    height: int
    allowed_layouts: tuple[str, ...]
    tags: tuple[str, ...]
    disabled_contexts: tuple[str, ...]
    ownership: str
    license: str
    sha256: str
    usage: str

    @property
    def orientation(self) -> str:
        if self.width == self.height:
            return "square"
        if self.width > self.height:
            return "landscape"
        return "portrait"


@dataclass(frozen=True, slots=True)
class AssetCatalog:
    catalog_id: str
    root: Path
    entries: tuple[AssetEntry, ...]
    providers: tuple[object, ...] = ()
    recent_asset_ids: frozenset[str] = frozenset()
    last_used_at: Mapping[str, datetime] = field(default_factory=dict)

    @property
    def active_root(self) -> Path:
        return self.root / "active"


def load_catalog(path: str | Path) -> AssetCatalog:
    """Load a repository-local catalog through the design-system validator."""

    manifest_path = Path(path).resolve()
    try:
        validated = load_design_system_catalog(manifest_path)
    except (OSError, ValueError, ET.ParseError) as error:
        raise CatalogError(str(error)) from error

    entries = tuple(
        AssetEntry(
            asset_id=entry.asset_id,
            role=entry.role,
            path=entry.file_path,
            width=entry.dimensions[0],
            height=entry.dimensions[1],
            allowed_layouts=entry.allowed_layouts,
            tags=entry.tags,
            disabled_contexts=entry.disabled_contexts,
            ownership=entry.ownership,
            license=entry.license,
            sha256=entry.sha256,
            usage=entry.usage,
        )
        for entry in validated.entries
    )
    return AssetCatalog(
        catalog_id=validated.catalog_id,
        root=manifest_path.parent,
        entries=entries,
    )
