from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .catalog import AssetCatalog, AssetEntry


class AssetLifecycleError(RuntimeError):
    """Raised when a pending external asset cannot be safely reviewed."""


@dataclass(frozen=True, slots=True)
class PendingAsset:
    pending_id: str
    path: Path
    metadata_path: Path
    provider: str
    provider_asset_id: str
    author: str
    source_url: str
    source_file_url: str
    role: str
    layout: str
    width: int
    height: int
    license: str
    license_snapshot: str
    sha256: str
    average_hash: str
    run_id: str
    production_relative_path: Path
    tags: tuple[str, ...]
    fallback_roles: tuple[str, ...]
    source_type: str = "stock_photo"
    acquired_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    provider_attribution: tuple[tuple[str, str], ...] = ()
    review_status: Literal["pending", "approved", "rejected"] = "pending"

    def audit_record(self) -> dict[str, object]:
        record = asdict(self)
        record["path"] = str(self.path)
        record["metadata_path"] = str(self.metadata_path)
        record["production_relative_path"] = self.production_relative_path.as_posix()
        record["tags"] = list(self.tags)
        record["fallback_roles"] = list(self.fallback_roles)
        record["provider_attribution"] = dict(self.provider_attribution)
        return record


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def write_pending_audit(candidate: PendingAsset) -> None:
    _atomic_write_json(candidate.metadata_path, candidate.audit_record())


def _current_review_status(candidate: PendingAsset) -> str:
    try:
        audit = json.loads(candidate.metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as error:
        raise AssetLifecycleError("pending asset audit is missing or invalid") from error
    status = audit.get("review_status")
    if not isinstance(status, str):
        raise AssetLifecycleError("pending asset audit has no review status")
    return status


def _validate_run_scope(candidate: PendingAsset, catalog: AssetCatalog) -> None:
    incoming_root = catalog.incoming_root.resolve()
    if (
        candidate.run_id != catalog.run_id
        or not candidate.path.resolve().is_relative_to(incoming_root)
        or not candidate.metadata_path.resolve().is_relative_to(incoming_root)
    ):
        raise AssetLifecycleError(
            "pending asset must stay in the catalog run-scoped incoming directory"
        )


def approve_external_asset(
    candidate: PendingAsset, catalog: AssetCatalog
) -> AssetEntry:
    _validate_run_scope(candidate, catalog)
    if (
        candidate.review_status != "pending"
        or _current_review_status(candidate) != "pending"
    ):
        raise AssetLifecycleError("only pending assets can be approved")
    actual = sha256_file(candidate.path)
    if actual != candidate.sha256:
        raise AssetLifecycleError("pending asset hash changed before approval")
    destination = (catalog.active_root / candidate.production_relative_path).resolve()
    active_root = catalog.active_root.resolve()
    if not destination.is_relative_to(active_root):
        raise AssetLifecycleError("production path escapes active catalog")
    if destination.exists():
        raise AssetLifecycleError("approved destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    original_audit = json.loads(candidate.metadata_path.read_text(encoding="utf-8"))
    approved_audit = candidate.audit_record()
    approved_audit.update(
        {
            "review_status": "approved",
            "approved_path": str(destination),
            "approved_sha256": actual,
        }
    )
    _atomic_write_json(candidate.metadata_path, approved_audit)
    candidate.path.replace(destination)
    try:
        entry = catalog.append_approved(candidate, destination)
    except Exception:
        destination.replace(candidate.path)
        _atomic_write_json(candidate.metadata_path, original_audit)
        raise
    return entry


def reject_external_asset(candidate: PendingAsset, *, reason: str) -> None:
    catalog_root = candidate.path.parents[3]
    expected_root = catalog_root / "incoming" / "external" / candidate.run_id
    if (
        not candidate.path.resolve().is_relative_to(expected_root.resolve())
        or not candidate.metadata_path.resolve().is_relative_to(expected_root.resolve())
    ):
        raise AssetLifecycleError(
            "pending asset must stay in its run-scoped incoming directory"
        )
    if (
        candidate.review_status != "pending"
        or _current_review_status(candidate) != "pending"
    ):
        raise AssetLifecycleError("only pending assets can be rejected")
    if not reason.strip():
        raise AssetLifecycleError("rejection reason is required")
    if sha256_file(candidate.path) != candidate.sha256:
        raise AssetLifecycleError("pending asset hash changed before rejection")
    audit = candidate.audit_record()
    audit.update({"review_status": "rejected", "rejection_reason": reason.strip()})
    _atomic_write_json(candidate.metadata_path, audit)
