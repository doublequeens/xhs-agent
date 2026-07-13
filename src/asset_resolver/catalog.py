from __future__ import annotations

import json
import os
import tempfile
import xml.etree.ElementTree as ET
import re
import hashlib
import fcntl
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.rendering.editorial.design_system import (
    ExternalAssetProvenance,
    load_catalog as load_design_system_catalog,
)

if TYPE_CHECKING:
    from .providers import AssetProvider


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
    fallback_roles: tuple[str, ...]
    ownership: str
    license: str
    sha256: str
    usage: str
    provenance: ExternalAssetProvenance | None = None

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
    providers: tuple[AssetProvider, ...] = ()
    recent_asset_ids: frozenset[str] = frozenset()
    last_used_at: Mapping[str, datetime] = field(default_factory=dict)
    run_id: str = "adhoc"
    manifest_path: Path | None = None

    def __post_init__(self) -> None:
        if (
            self.run_id in {".", ".."}
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", self.run_id)
            is None
        ):
            raise CatalogError("run_id must be exactly one safe path component")
        root = self.root.resolve()
        incoming_base = (root / "incoming" / "external").resolve()
        if not incoming_base.is_relative_to(root):
            raise CatalogError("incoming/external escapes catalog root")
        incoming_root = (incoming_base / self.run_id).resolve()
        if not incoming_root.is_relative_to(incoming_base):
            raise CatalogError("run_id escapes incoming/external")

    @property
    def active_root(self) -> Path:
        return self.root / "active"

    @property
    def incoming_root(self) -> Path:
        root = self.root.resolve()
        incoming_base = (root / "incoming" / "external").resolve()
        if not incoming_base.is_relative_to(root):
            raise CatalogError("incoming/external escapes catalog root")
        incoming_root = (incoming_base / self.run_id).resolve()
        if not incoming_root.is_relative_to(incoming_base):
            raise CatalogError("run_id escapes incoming/external")
        return incoming_root

    def append_approved(
        self,
        pending,
        destination: Path,
        *,
        safety_review_decisions: Mapping[str, bool],
        safety_reviewed_at: str,
        review_disposition: str,
    ) -> AssetEntry:
        """Atomically append a promoted pending asset to the production manifest."""

        asset_id = f"{pending.provider}-{pending.provider_asset_id}"
        entry = AssetEntry(
            asset_id=asset_id,
            role=pending.role,
            path=destination,
            width=pending.width,
            height=pending.height,
            allowed_layouts=(pending.layout,),
            tags=pending.tags,
            disabled_contexts=(),
            fallback_roles=pending.fallback_roles,
            ownership="licensed_stock",
            license=pending.license,
            sha256=pending.sha256,
            usage="production",
            provenance=ExternalAssetProvenance(
                source_type=pending.source_type,
                acquired_at=pending.acquired_at,
                run_id=pending.run_id,
                provider=pending.provider,
                provider_asset_id=pending.provider_asset_id,
                source_url=pending.source_url,
                source_file_url=pending.source_file_url,
                author=pending.author,
                provider_attribution=dict(pending.provider_attribution),
                license_snapshot=pending.license_snapshot,
                license_snapshot_sha256=pending.license_snapshot_sha256,
                license_terms_url=pending.license_terms_url,
                average_hash=pending.average_hash,
                requirement_fingerprint=pending.requirement_fingerprint,
                unresolved_safety_checks=pending.unresolved_safety_checks,
                safety_review_decisions=dict(safety_review_decisions),
                safety_reviewed_at=safety_reviewed_at,
                review_disposition=review_disposition,
            ),
        )
        if self.manifest_path is None:
            raise CatalogError("approval requires a persistent catalog manifest")
        manifest_path = self.manifest_path
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = manifest_path.with_suffix(f"{manifest_path.suffix}.lock")
        with lock_path.open("a+b") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            original_bytes = manifest_path.read_bytes()
            original_version = hashlib.sha256(original_bytes).hexdigest()
            raw = json.loads(original_bytes.decode("utf-8"))
            assets = raw.setdefault("assets", [])
            if any(item.get("asset_id") == asset_id for item in assets):
                raise CatalogError(f"duplicate approved asset_id: {asset_id}")
            assets.append(
                {
                    "asset_id": asset_id,
                    "role": pending.role,
                    "path": destination.relative_to(self.root).as_posix(),
                    "ownership": "licensed_stock",
                    "license": pending.license,
                    "dimensions": {"width": pending.width, "height": pending.height},
                    "sha256": pending.sha256,
                    "allowed_layouts": [pending.layout],
                    "tags": list(pending.tags),
                    "disabled_contexts": [],
                    "fallback_roles": list(pending.fallback_roles),
                    "usage": "production",
                    "provenance": {
                        "source_type": pending.source_type,
                        "acquired_at": pending.acquired_at,
                        "run_id": pending.run_id,
                        "provider": pending.provider,
                        "provider_asset_id": pending.provider_asset_id,
                        "source_url": pending.source_url,
                        "source_file_url": pending.source_file_url,
                        "author": pending.author,
                        "provider_attribution": dict(pending.provider_attribution),
                        "license_snapshot": pending.license_snapshot,
                        "license_snapshot_sha256": pending.license_snapshot_sha256,
                        "license_terms_url": pending.license_terms_url,
                        "average_hash": pending.average_hash,
                        "requirement_fingerprint": pending.requirement_fingerprint,
                        "unresolved_safety_checks": list(
                            pending.unresolved_safety_checks
                        ),
                        "safety_review_decisions": dict(safety_review_decisions),
                        "safety_reviewed_at": safety_reviewed_at,
                        "review_disposition": review_disposition,
                    },
                }
            )
            file_descriptor, temporary_name = tempfile.mkstemp(
                dir=manifest_path.parent,
                prefix=f".{manifest_path.name}.",
                suffix=".tmp",
            )
            try:
                with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
                    json.dump(raw, handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                load_design_system_catalog(Path(temporary_name))
                current_version = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
                if current_version != original_version:
                    raise CatalogError("catalog manifest changed during approval")
                os.replace(temporary_name, manifest_path)
            finally:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        return entry


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
            fallback_roles=entry.fallback_roles,
            ownership=entry.ownership,
            license=entry.license,
            sha256=entry.sha256,
            usage=entry.usage,
            provenance=entry.provenance,
        )
        for entry in validated.entries
    )
    return AssetCatalog(
        catalog_id=validated.catalog_id,
        root=manifest_path.parent,
        entries=entries,
        manifest_path=manifest_path,
    )
