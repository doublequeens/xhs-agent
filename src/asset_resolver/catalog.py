from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_FIELDS = frozenset(
    {
        "asset_id",
        "role",
        "path",
        "ownership",
        "license",
        "dimensions",
        "sha256",
        "allowed_layouts",
        "tags",
        "disabled_contexts",
        "usage",
    }
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


def _require_text(raw: Mapping[str, Any], field_name: str, asset_id: str) -> str:
    value = raw.get(field_name)
    if not isinstance(value, str) or not value:
        raise CatalogError(f"{asset_id}: {field_name} must be a non-empty string")
    return value


def _require_text_list(
    raw: Mapping[str, Any],
    field_name: str,
    asset_id: str,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    value = raw.get(field_name)
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise CatalogError(
            f"{asset_id}: {field_name} must contain only non-empty strings"
        )
    if not allow_empty and not value:
        raise CatalogError(f"{asset_id}: {field_name} cannot be empty")
    return tuple(value)


def _load_entry(raw: Any, root: Path, active_root: Path) -> AssetEntry:
    if not isinstance(raw, dict):
        raise CatalogError("catalog entries must be objects")
    missing = _REQUIRED_FIELDS - raw.keys()
    if missing:
        raise CatalogError(f"catalog entry missing fields: {sorted(missing)}")

    asset_id = _require_text(raw, "asset_id", "catalog entry")
    relative_path = Path(_require_text(raw, "path", asset_id))
    if relative_path.is_absolute():
        raise CatalogError(f"{asset_id}: path must be relative to the catalog root")
    path = (root / relative_path).resolve()
    if not path.is_relative_to(active_root):
        raise CatalogError(f"{asset_id}: production asset must live under active/")
    if not path.is_file():
        raise CatalogError(f"{asset_id}: asset file does not exist")

    usage = _require_text(raw, "usage", asset_id)
    if usage != "production":
        raise CatalogError(
            f"{asset_id}: production catalog cannot include {usage!r} usage"
        )

    dimensions = raw.get("dimensions")
    if not isinstance(dimensions, dict):
        raise CatalogError(f"{asset_id}: dimensions must be an object")
    width = dimensions.get("width")
    height = dimensions.get("height")
    if (
        not isinstance(width, int)
        or isinstance(width, bool)
        or width < 1
        or not isinstance(height, int)
        or isinstance(height, bool)
        or height < 1
    ):
        raise CatalogError(f"{asset_id}: dimensions must contain positive integers")

    expected_hash = _require_text(raw, "sha256", asset_id)
    if not _SHA256_PATTERN.fullmatch(expected_hash):
        raise CatalogError(f"{asset_id}: invalid sha256")
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise CatalogError(f"{asset_id}: sha256 does not match asset file")

    return AssetEntry(
        asset_id=asset_id,
        role=_require_text(raw, "role", asset_id),
        path=path,
        width=width,
        height=height,
        allowed_layouts=_require_text_list(
            raw, "allowed_layouts", asset_id, allow_empty=False
        ),
        tags=_require_text_list(raw, "tags", asset_id, allow_empty=False),
        disabled_contexts=_require_text_list(
            raw, "disabled_contexts", asset_id, allow_empty=True
        ),
        ownership=_require_text(raw, "ownership", asset_id),
        license=_require_text(raw, "license", asset_id),
        sha256=expected_hash,
        usage=usage,
    )


def load_catalog(path: str | Path) -> AssetCatalog:
    """Load a repository-local, production-only visual asset catalog."""

    manifest_path = Path(path).resolve()
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CatalogError(
            f"could not load catalog {manifest_path}: {error}"
        ) from error

    if not isinstance(raw, dict):
        raise CatalogError("catalog manifest must be an object")
    catalog_id = raw.get("catalog_id")
    if not isinstance(catalog_id, str) or not catalog_id:
        raise CatalogError("catalog_id must be a non-empty string")
    assets = raw.get("assets")
    if not isinstance(assets, list):
        raise CatalogError("catalog assets must be a list")

    root = manifest_path.parent
    active_root = (root / "active").resolve()
    entries = tuple(_load_entry(item, root, active_root) for item in assets)
    asset_ids = [entry.asset_id for entry in entries]
    paths = [entry.path for entry in entries]
    if len(set(asset_ids)) != len(asset_ids):
        raise CatalogError("catalog asset_id values must be unique")
    if len(set(paths)) != len(paths):
        raise CatalogError("catalog paths must be unique")

    return AssetCatalog(catalog_id=catalog_id, root=root, entries=entries)
