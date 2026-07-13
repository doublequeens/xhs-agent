from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .catalog import AssetCatalog, AssetEntry
from .providers import candidate_urls_are_allowed


class AssetLifecycleError(RuntimeError):
    """Raised when a pending external asset cannot be safely reviewed."""


@dataclass(frozen=True, slots=True)
class PendingAsset:
    pending_id: str
    slot_id: str
    candidate_rank: int
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
    license_snapshot_sha256: str
    license_terms_url: str
    sha256: str
    average_hash: str
    run_id: str
    production_relative_path: Path
    tags: tuple[str, ...]
    fallback_roles: tuple[str, ...]
    unresolved_safety_checks: tuple[str, ...]
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
        record["unresolved_safety_checks"] = list(self.unresolved_safety_checks)
        return record


_PENDING_FIELDS = frozenset(item.name for item in fields(PendingAsset))
_AUDIT_EXTRA_FIELDS = frozenset(
    {"rejection_reason", "approved_path", "approved_sha256"}
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_AVERAGE_HASH = re.compile(r"^[0-9a-f]{16}$")
_SAFETY_CHECKS = frozenset(
    {
        "has_watermark",
        "has_logo",
        "has_text",
        "recognizable_face",
        "allowed_for_publishing",
    }
)


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


def load_pending_asset(
    metadata_path: str | Path, catalog: AssetCatalog | None = None
) -> PendingAsset:
    path = Path(metadata_path).resolve()
    try:
        audit = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as error:
        raise AssetLifecycleError("pending asset audit is missing or invalid") from error
    if not isinstance(audit, dict):
        raise AssetLifecycleError("pending asset audit schema must be an object")
    keys = frozenset(audit)
    if not _PENDING_FIELDS.issubset(keys) or keys - _PENDING_FIELDS - _AUDIT_EXTRA_FIELDS:
        raise AssetLifecycleError("pending asset audit schema is invalid")
    try:
        candidate = PendingAsset(
            **{
                **{name: audit[name] for name in _PENDING_FIELDS},
                "path": Path(audit["path"]).resolve(),
                "metadata_path": Path(audit["metadata_path"]).resolve(),
                "production_relative_path": Path(audit["production_relative_path"]),
                "tags": tuple(audit["tags"]),
                "fallback_roles": tuple(audit["fallback_roles"]),
                "unresolved_safety_checks": tuple(
                    audit["unresolved_safety_checks"]
                ),
                "provider_attribution": tuple(
                    sorted(dict(audit["provider_attribution"]).items())
                ),
            }
        )
    except (KeyError, TypeError, ValueError) as error:
        raise AssetLifecycleError("pending asset audit schema is invalid") from error
    if candidate.metadata_path != path:
        raise AssetLifecycleError("pending asset audit metadata path is not canonical")
    if (
        isinstance(candidate.candidate_rank, bool)
        or candidate.candidate_rank < 1
        or not candidate.slot_id
        or candidate.review_status not in {"pending", "approved", "rejected"}
        or candidate.source_type != "stock_photo"
        or candidate.width < 1
        or candidate.height < 1
        or _HEX64.fullmatch(candidate.sha256) is None
        or _HEX64.fullmatch(candidate.license_snapshot_sha256) is None
        or _AVERAGE_HASH.fullmatch(candidate.average_hash) is None
        or not set(candidate.unresolved_safety_checks).issubset(_SAFETY_CHECKS)
        or not candidate_urls_are_allowed(
            candidate.provider,
            source_url=candidate.source_url,
            source_file_url=candidate.source_file_url,
            license_terms_url=candidate.license_terms_url,
        )
    ):
        raise AssetLifecycleError("pending asset audit schema is invalid")
    try:
        acquired_at = datetime.fromisoformat(candidate.acquired_at)
    except ValueError as error:
        raise AssetLifecycleError("pending asset audit schema is invalid") from error
    if acquired_at.tzinfo is None:
        raise AssetLifecycleError("pending asset audit schema is invalid")
    production_path = candidate.production_relative_path
    if (
        production_path.is_absolute()
        or ".." in production_path.parts
        or production_path.suffix.lower() not in {".png", ".webp"}
    ):
        raise AssetLifecycleError("pending asset canonical production path is invalid")
    if catalog is not None:
        _validate_run_scope(candidate, catalog)
        catalog_root = catalog.root.resolve()
    else:
        expected_parent = (
            candidate.path.parents[2] / "external" / candidate.run_id
            if len(candidate.path.parents) >= 3
            else Path("/__invalid__")
        )
        if candidate.path.parent != expected_parent or candidate.metadata_path.parent != expected_parent:
            raise AssetLifecycleError(
                "pending asset must stay in its run-scoped incoming directory"
            )
        catalog_root = candidate.path.parents[3].resolve()
    snapshot_path = (catalog_root / candidate.license_snapshot).resolve()
    license_root = (catalog_root / "licenses").resolve()
    if not snapshot_path.is_relative_to(license_root) or not snapshot_path.is_file():
        raise AssetLifecycleError("pending asset canonical license snapshot is invalid")
    if sha256_file(snapshot_path) != candidate.license_snapshot_sha256:
        raise AssetLifecycleError("pending asset canonical license snapshot hash changed")
    return candidate


def list_pending_assets(
    catalog: AssetCatalog,
    *,
    slot_id: str,
    review_statuses: tuple[str, ...] = ("pending",),
) -> list[PendingAsset]:
    if not catalog.incoming_root.exists():
        return []
    candidates = [
        load_pending_asset(path, catalog)
        for path in catalog.incoming_root.glob("*.json")
    ]
    return sorted(
        (
            candidate
            for candidate in candidates
            if candidate.slot_id == slot_id
            and candidate.review_status in review_statuses
        ),
        key=lambda candidate: (
            candidate.candidate_rank,
            candidate.provider,
            candidate.provider_asset_id,
            candidate.pending_id,
        ),
    )


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
    canonical = load_pending_asset(candidate.metadata_path, catalog)
    if canonical.review_status != "pending":
        raise AssetLifecycleError("only pending assets can be approved")
    if canonical != candidate:
        raise AssetLifecycleError("caller does not match canonical pending audit")
    candidate = canonical
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
    moved = False
    try:
        _atomic_write_json(candidate.metadata_path, approved_audit)
        candidate.path.replace(destination)
        moved = True
        entry = catalog.append_approved(candidate, destination)
    except Exception:
        if moved and destination.exists():
            destination.replace(candidate.path)
        _atomic_write_json(candidate.metadata_path, original_audit)
        raise
    return entry


def reject_external_asset(
    candidate: PendingAsset,
    *,
    reason: str,
    catalog: AssetCatalog | None = None,
) -> PendingAsset | None:
    canonical = load_pending_asset(candidate.metadata_path, catalog)
    if canonical.review_status != "pending":
        raise AssetLifecycleError("only pending assets can be rejected")
    if canonical != candidate:
        raise AssetLifecycleError("caller does not match canonical pending audit")
    candidate = canonical
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
    if catalog is None:
        return None
    remaining = list_pending_assets(catalog, slot_id=candidate.slot_id)
    return next(
        (
            item
            for item in remaining
            if item.candidate_rank > candidate.candidate_rank
        ),
        None,
    )
