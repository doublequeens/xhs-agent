from __future__ import annotations

import hashlib
import json
import re
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from PIL import Image


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FONT_ROOT = REPOSITORY_ROOT / "assets/fonts/beauty-editorial-v1"
ASSET_ROOT = REPOSITORY_ROOT / "assets/visual/beauty-editorial-v1"

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ENTRY_FIELDS = frozenset(
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
        "fallback_roles",
        "usage",
    }
)
_EXTERNAL_PROVENANCE_FIELDS = frozenset(
    {
        "source_type",
        "acquired_at",
        "run_id",
        "provider",
        "provider_asset_id",
        "source_url",
        "source_file_url",
        "author",
        "provider_attribution",
        "license_snapshot",
        "license_snapshot_sha256",
        "license_terms_url",
        "average_hash",
        "requirement_fingerprint",
        "safety_review_decisions",
        "safety_reviewed_at",
        "review_disposition",
    }
)
_AVERAGE_HASH_PATTERN = re.compile(r"^[0-9a-f]{16}$")


@dataclass(frozen=True)
class DesignSystem:
    name: str
    canvas: tuple[int, int]
    colors: Mapping[str, str]
    font_paths: Mapping[str, Path]


@dataclass(frozen=True)
class CatalogEntry:
    asset_id: str
    role: str
    path: str
    ownership: str
    license: str
    dimensions: tuple[int, int]
    sha256: str
    allowed_layouts: tuple[str, ...]
    tags: tuple[str, ...]
    disabled_contexts: tuple[str, ...]
    fallback_roles: tuple[str, ...]
    usage: str
    provenance: "ExternalAssetProvenance | None"
    _catalog_root: Path

    @property
    def file_path(self) -> Path:
        return self._catalog_root / self.path


@dataclass(frozen=True)
class AssetCatalog:
    catalog_id: str
    entries: tuple[CatalogEntry, ...]


@dataclass(frozen=True)
class ExternalAssetProvenance:
    source_type: str
    acquired_at: str
    run_id: str
    provider: str
    provider_asset_id: str
    source_url: str
    source_file_url: str
    author: str
    provider_attribution: Mapping[str, str]
    license_snapshot: str
    license_snapshot_sha256: str
    license_terms_url: str
    average_hash: str
    requirement_fingerprint: str
    safety_review_decisions: Mapping[str, bool]
    safety_reviewed_at: str
    review_disposition: str


def _require_timezone_timestamp(value: Any, field: str, asset_id: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{asset_id}: provenance {field} must be non-empty")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{asset_id}: provenance {field} is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{asset_id}: provenance {field} needs timezone")
    return value


def _load_external_provenance(
    raw: Any, catalog_root: Path, asset_id: str
) -> ExternalAssetProvenance:
    if not isinstance(raw, dict) or set(raw) != _EXTERNAL_PROVENANCE_FIELDS:
        raise ValueError(f"{asset_id}: external provenance schema is invalid")
    text_fields = {
        field: raw.get(field)
        for field in _EXTERNAL_PROVENANCE_FIELDS
        if field
        not in {
            "provider_attribution",
            "safety_review_decisions",
            "acquired_at",
            "safety_reviewed_at",
        }
    }
    if any(not isinstance(value, str) or not value for value in text_fields.values()):
        raise ValueError(f"{asset_id}: external provenance text is invalid")
    if raw["source_type"] != "stock_photo":
        raise ValueError(f"{asset_id}: external provenance source_type is invalid")
    attribution = raw["provider_attribution"]
    if (
        not isinstance(attribution, dict)
        or not attribution
        or any(
            not isinstance(key, str)
            or not key
            or not isinstance(value, str)
            or not value
            for key, value in attribution.items()
        )
    ):
        raise ValueError(f"{asset_id}: external provenance attribution is invalid")
    decisions = raw["safety_review_decisions"]
    if not isinstance(decisions, dict) or any(
        not isinstance(key, str)
        or not key
        or type(value) is not bool
        for key, value in decisions.items()
    ):
        raise ValueError(f"{asset_id}: external provenance safety review is invalid")
    if raw["review_disposition"] != "approved_for_publishing":
        raise ValueError(f"{asset_id}: external provenance disposition is invalid")
    if not _SHA256_PATTERN.fullmatch(raw["license_snapshot_sha256"]):
        raise ValueError(f"{asset_id}: external provenance snapshot hash is invalid")
    if not _SHA256_PATTERN.fullmatch(raw["requirement_fingerprint"]):
        raise ValueError(f"{asset_id}: external provenance fingerprint is invalid")
    if not _AVERAGE_HASH_PATTERN.fullmatch(raw["average_hash"]):
        raise ValueError(f"{asset_id}: external provenance average hash is invalid")
    from src.asset_resolver.providers import candidate_urls_are_allowed

    if not candidate_urls_are_allowed(
        raw["provider"],
        source_url=raw["source_url"],
        source_file_url=raw["source_file_url"],
        license_terms_url=raw["license_terms_url"],
    ):
        raise ValueError(f"{asset_id}: external provenance URLs are invalid")
    snapshot_relative = Path(raw["license_snapshot"])
    snapshot_path = (catalog_root / snapshot_relative).resolve()
    license_root = (catalog_root / "licenses").resolve()
    if (
        snapshot_relative.is_absolute()
        or not snapshot_path.is_relative_to(license_root)
        or not snapshot_path.is_file()
        or hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
        != raw["license_snapshot_sha256"]
    ):
        raise ValueError(f"{asset_id}: external provenance license snapshot is invalid")
    return ExternalAssetProvenance(
        source_type=raw["source_type"],
        acquired_at=_require_timezone_timestamp(
            raw["acquired_at"], "acquired_at", asset_id
        ),
        run_id=raw["run_id"],
        provider=raw["provider"],
        provider_asset_id=raw["provider_asset_id"],
        source_url=raw["source_url"],
        source_file_url=raw["source_file_url"],
        author=raw["author"],
        provider_attribution=MappingProxyType(dict(attribution)),
        license_snapshot=raw["license_snapshot"],
        license_snapshot_sha256=raw["license_snapshot_sha256"],
        license_terms_url=raw["license_terms_url"],
        average_hash=raw["average_hash"],
        requirement_fingerprint=raw["requirement_fingerprint"],
        safety_review_decisions=MappingProxyType(dict(decisions)),
        safety_reviewed_at=_require_timezone_timestamp(
            raw["safety_reviewed_at"], "safety_reviewed_at", asset_id
        ),
        review_disposition=raw["review_disposition"],
    )


def _require_text(item: Mapping[str, Any], field: str, asset_id: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{asset_id}: {field} must be a non-empty string")
    return value


def _require_text_list(
    item: Mapping[str, Any], field: str, asset_id: str, *, allow_empty: bool
) -> tuple[str, ...]:
    value = item.get(field)
    if not isinstance(value, list) or any(
        not isinstance(element, str) or not element for element in value
    ):
        raise ValueError(f"{asset_id}: {field} must contain only non-empty strings")
    if not allow_empty and not value:
        raise ValueError(f"{asset_id}: {field} cannot be empty")
    return tuple(value)


def _read_dimensions(path: Path) -> tuple[int, int]:
    suffix = path.suffix.lower()
    if suffix == ".svg":
        root = ET.parse(path).getroot()
        try:
            return int(float(root.attrib["width"])), int(float(root.attrib["height"]))
        except (KeyError, ValueError) as error:
            raise ValueError(f"{path}: SVG must declare numeric width and height") from error
    if suffix == ".png":
        header = path.read_bytes()[:24]
        if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"{path}: invalid PNG header")
        return struct.unpack(">II", header[16:24])
    if suffix == ".webp":
        try:
            with Image.open(path) as image:
                return image.size
        except (OSError, ValueError) as error:
            raise ValueError(f"{path}: invalid WebP image") from error
    raise ValueError(f"{path}: unsupported catalog file type")


def _load_entry(raw: Any, catalog_root: Path) -> CatalogEntry:
    if not isinstance(raw, dict):
        raise ValueError("catalog entries must be objects")
    missing = _ENTRY_FIELDS - raw.keys()
    if missing:
        raise ValueError(f"catalog entry missing fields: {sorted(missing)}")

    asset_id = _require_text(raw, "asset_id", "catalog entry")
    relative_path = Path(_require_text(raw, "path", asset_id))
    if relative_path.is_absolute():
        raise ValueError(f"{asset_id}: path escapes catalog root")
    file_path = (catalog_root / relative_path).resolve()
    if not file_path.is_relative_to(catalog_root):
        raise ValueError(f"{asset_id}: path escapes catalog root")

    usage = _require_text(raw, "usage", asset_id)
    if usage != "production":
        raise ValueError(f"{asset_id}: production catalog cannot include {usage!r} usage")
    if not file_path.is_relative_to(catalog_root / "active"):
        raise ValueError(f"{asset_id}: production assets must live under active/")
    if not file_path.is_file():
        raise ValueError(f"{asset_id}: asset file does not exist")

    dimensions = raw.get("dimensions")
    if not isinstance(dimensions, dict):
        raise ValueError(f"{asset_id}: dimensions must be an object")
    width = dimensions.get("width")
    height = dimensions.get("height")
    if not isinstance(width, int) or width < 1 or not isinstance(height, int) or height < 1:
        raise ValueError(f"{asset_id}: dimensions must contain positive integers")
    if _read_dimensions(file_path) != (width, height):
        raise ValueError(f"{asset_id}: dimensions do not match asset file")

    expected_hash = _require_text(raw, "sha256", asset_id)
    if not _SHA256_PATTERN.fullmatch(expected_hash):
        raise ValueError(f"{asset_id}: invalid sha256")
    actual_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError(f"{asset_id}: sha256 does not match asset file")

    ownership = _require_text(raw, "ownership", asset_id)
    provenance_raw = raw.get("provenance")
    if ownership == "licensed_stock":
        provenance = _load_external_provenance(
            provenance_raw, catalog_root, asset_id
        )
    elif provenance_raw is not None:
        raise ValueError(f"{asset_id}: only licensed stock may have provenance")
    else:
        provenance = None

    return CatalogEntry(
        asset_id=asset_id,
        role=_require_text(raw, "role", asset_id),
        path=relative_path.as_posix(),
        ownership=ownership,
        license=_require_text(raw, "license", asset_id),
        dimensions=(width, height),
        sha256=expected_hash,
        allowed_layouts=_require_text_list(
            raw, "allowed_layouts", asset_id, allow_empty=False
        ),
        tags=_require_text_list(raw, "tags", asset_id, allow_empty=False),
        disabled_contexts=_require_text_list(
            raw, "disabled_contexts", asset_id, allow_empty=True
        ),
        fallback_roles=_require_text_list(
            raw, "fallback_roles", asset_id, allow_empty=False
        ),
        usage=usage,
        provenance=provenance,
        _catalog_root=catalog_root,
    )


def load_catalog(manifest_path: Path) -> AssetCatalog:
    """Load and integrity-check a production-only local asset catalog."""
    manifest_path = manifest_path.resolve()
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("catalog manifest must be an object")
    catalog_id = raw.get("catalog_id")
    if not isinstance(catalog_id, str) or not catalog_id:
        raise ValueError("catalog_id must be a non-empty string")
    assets = raw.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("catalog assets must be a non-empty list")

    catalog_root = manifest_path.parent.resolve()
    entries = tuple(_load_entry(item, catalog_root) for item in assets)
    asset_ids = [entry.asset_id for entry in entries]
    paths = [entry.path for entry in entries]
    if len(set(asset_ids)) != len(asset_ids):
        raise ValueError("catalog asset_id values must be unique")
    if len(set(paths)) != len(paths):
        raise ValueError("catalog paths must be unique")
    return AssetCatalog(catalog_id=catalog_id, entries=entries)


BEAUTY_EDITORIAL_V1 = DesignSystem(
    name="beauty_editorial_v1",
    canvas=(1080, 1440),
    colors=MappingProxyType(
        {
            "background": "#F7F2EA",
            "ink": "#292625",
            "mauve": "#9A707B",
            "coral": "#D45D4C",
            "sage": "#78805E",
        }
    ),
    font_paths=MappingProxyType(
        {
            "display": FONT_ROOT / "SourceHanSerifSC-SemiBold.otf",
            "body_regular": FONT_ROOT / "SourceHanSansSC-Regular.otf",
            "body_medium": FONT_ROOT / "SourceHanSansSC-Medium.otf",
            "numeral": FONT_ROOT / "BodoniModa-Regular.ttf",
        }
    ),
)
