from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
import re
import fcntl
import stat
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.rendering.editorial.design_system import (
    ExternalAssetProvenance,
    load_catalog as load_design_system_catalog,
    load_catalog_bytes as load_design_system_catalog_bytes,
)

if TYPE_CHECKING:
    from .providers import AssetProvider


class CatalogError(ValueError):
    """Raised when a local production catalog is invalid or unsafe."""


def approved_manifest_item(
    pending,
    destination: Path,
    *,
    safety_review_decisions: Mapping[str, bool],
    safety_reviewed_at: str,
    review_disposition: str,
    catalog_root: Path,
) -> dict[str, object]:
    """Build the canonical catalog record shared by batch and standalone writers."""

    return {
        "asset_id": f"{pending.provider}-{pending.provider_asset_id}",
        "role": pending.role,
        "path": destination.relative_to(catalog_root).as_posix(),
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
            "unresolved_safety_checks": list(pending.unresolved_safety_checks),
            "safety_review_decisions": dict(safety_review_decisions),
            "safety_reviewed_at": safety_reviewed_at,
            "review_disposition": review_disposition,
        },
    }


@contextmanager
def catalog_review_lock(root: Path):
    """Serialize every catalog lifecycle writer before narrower locks."""

    parent_descriptor: int | None = None
    try:
        root_path = root.resolve(strict=True)
        root_metadata = root_path.stat()
        root_identity = (root_metadata.st_dev, root_metadata.st_ino)
        if root_metadata.st_uid != os.getuid() or stat.S_IMODE(root_metadata.st_mode) & 0o022:
            raise CatalogError("catalog review lock parent is unsafe")
        parent_descriptor = os.open(
            root_path,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
        lock_name = ".asset-review.lock"
        for attempt in range(3):
            try:
                descriptor = os.open(
                    lock_name,
                    os.O_RDWR
                    | os.O_CREAT
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=parent_descriptor,
                )
                break
            except FileNotFoundError:
                if attempt == 2:
                    raise
    except (OSError, CatalogError) as error:
        if parent_descriptor is not None:
            os.close(parent_descriptor)
        if isinstance(error, CatalogError):
            raise
        raise CatalogError("catalog review lock is unsafe") from error
    locked = False
    body_error: BaseException | None = None

    def validate_binding(expected: tuple[int, int] | None = None) -> tuple[int, int]:
        opened = os.fstat(descriptor)
        current_root = root_path.stat(follow_symlinks=False)
        current = os.stat(
            lock_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        identity = (opened.st_dev, opened.st_ino)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISDIR(current_root.st_mode)
            or (current_root.st_dev, current_root.st_ino) != root_identity
            or opened.st_nlink != 1
            or opened.st_uid != os.getuid()
            or stat.S_IMODE(opened.st_mode) != 0o600
            or stat.S_ISLNK(current.st_mode)
            or identity != (current.st_dev, current.st_ino)
            or (expected is not None and identity != expected)
        ):
            raise CatalogError("catalog review lock is unsafe")
        return identity

    try:
        try:
            identity = validate_binding()
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            locked = True
            validate_binding(identity)
        except OSError as error:
            raise CatalogError("catalog review lock is unsafe") from error
        try:
            yield lambda: validate_binding(identity)
        except BaseException as error:
            body_error = error
            raise
    finally:
        cleanup_error: BaseException | None = None
        try:
            if locked:
                validate_binding(identity)
        except BaseException as error:
            cleanup_error = error
        if locked:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except BaseException as error:
                cleanup_error = cleanup_error or error
        os.close(descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)
        if cleanup_error is not None:
            if body_error is not None:
                body_error.add_note(f"catalog review lock cleanup failed: {cleanup_error}")
            else:
                if isinstance(cleanup_error, CatalogError):
                    raise cleanup_error
                raise CatalogError("catalog review lock cleanup failed") from cleanup_error


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

def _from_validated_catalog(validated, manifest_path: Path) -> AssetCatalog:
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


def load_catalog(path: str | Path) -> AssetCatalog:
    """Load a repository-local catalog through the design-system validator."""

    manifest_path = Path(path).resolve()
    try:
        validated = load_design_system_catalog(manifest_path)
    except (OSError, ValueError, ET.ParseError) as error:
        raise CatalogError(str(error)) from error
    return _from_validated_catalog(validated, manifest_path)


def load_catalog_bytes(
    payload: bytes,
    *,
    catalog_root: str | Path,
    manifest_path: str | Path | None = None,
) -> AssetCatalog:
    """Load a catalog from one caller-owned secure byte snapshot."""

    root = Path(catalog_root).resolve()
    bound_manifest = Path(manifest_path).resolve() if manifest_path else root / "manifest.json"
    try:
        validated = load_design_system_catalog_bytes(payload, root)
    except (OSError, ValueError, ET.ParseError) as error:
        raise CatalogError(str(error)) from error
    return _from_validated_catalog(validated, bound_manifest)
