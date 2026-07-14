from __future__ import annotations

import hashlib
import base64
import fcntl
import json
import os
import stat
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from src.schemas.assets import LayoutName

from .catalog import (
    AssetCatalog,
    AssetEntry,
    approved_manifest_item,
    catalog_review_lock,
)
from .providers import candidate_urls_are_allowed


class AssetLifecycleError(RuntimeError):
    """Raised when a pending external asset cannot be safely reviewed."""


@dataclass(frozen=True, slots=True)
class BatchAssetReviewResult:
    any_rejected: bool
    finalized_value: Any = None


RECOVERY_JOURNAL_DIR = ".asset-review-recovery"
RECOVERY_JOURNAL_VERSION = 1


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
    requirement_fingerprint: str
    attempt_number: int
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
_SAFETY_CHECKS = frozenset(
    {
        "has_watermark",
        "has_logo",
        "has_text",
        "recognizable_face",
        "allowed_for_publishing",
    }
)

NonEmptyStrictString = Annotated[StrictStr, Field(min_length=1)]
Hash64 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
AverageHash = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{16}$")]


class PendingAuditRecord(BaseModel):
    """Strict on-disk contract for a reviewed external candidate."""

    model_config = ConfigDict(extra="forbid", strict=True)

    pending_id: NonEmptyStrictString
    slot_id: NonEmptyStrictString
    candidate_rank: Annotated[StrictInt, Field(ge=1)]
    path: NonEmptyStrictString
    metadata_path: NonEmptyStrictString
    provider: NonEmptyStrictString
    provider_asset_id: NonEmptyStrictString
    author: NonEmptyStrictString
    source_url: NonEmptyStrictString
    source_file_url: NonEmptyStrictString
    role: NonEmptyStrictString
    layout: LayoutName
    width: Annotated[StrictInt, Field(ge=1)]
    height: Annotated[StrictInt, Field(ge=1)]
    license: NonEmptyStrictString
    license_snapshot: NonEmptyStrictString
    license_snapshot_sha256: Hash64
    license_terms_url: NonEmptyStrictString
    sha256: Hash64
    average_hash: AverageHash
    run_id: NonEmptyStrictString
    production_relative_path: NonEmptyStrictString
    tags: Annotated[list[NonEmptyStrictString], Field(min_length=1)]
    fallback_roles: Annotated[list[NonEmptyStrictString], Field(min_length=1)]
    unresolved_safety_checks: list[NonEmptyStrictString]
    requirement_fingerprint: Hash64
    attempt_number: Annotated[StrictInt, Field(ge=1, le=3)]
    source_type: Literal["stock_photo"]
    acquired_at: NonEmptyStrictString
    provider_attribution: Annotated[
        dict[NonEmptyStrictString, NonEmptyStrictString], Field(min_length=1)
    ]
    review_status: Literal["pending", "approved", "rejected"]
    rejection_reason: NonEmptyStrictString | None = None
    approved_path: NonEmptyStrictString | None = None
    approved_sha256: Hash64 | None = None
    safety_review_decisions: dict[NonEmptyStrictString, StrictBool] | None = None
    safety_reviewed_at: NonEmptyStrictString | None = None
    review_disposition: Literal[
        "approved_for_publishing", "rejected"
    ] | None = None

    @field_validator("pending_id", "slot_id", "provider", "provider_asset_id", "author", "role", "license", "run_id")
    @classmethod
    def reject_whitespace_only(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("unresolved_safety_checks")
    @classmethod
    def validate_safety_checks(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or not set(value).issubset(_SAFETY_CHECKS):
            raise ValueError("invalid unresolved safety checks")
        return value

    @field_validator("acquired_at", "safety_reviewed_at")
    @classmethod
    def validate_timestamp(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("timestamp must include timezone")
        return value

    @model_validator(mode="after")
    def validate_review_state(self) -> "PendingAuditRecord":
        if self.review_status == "pending" and any(
            value is not None
            for value in (
                self.rejection_reason,
                self.approved_path,
                self.approved_sha256,
                self.safety_review_decisions,
                self.safety_reviewed_at,
                self.review_disposition,
            )
        ):
            raise ValueError("pending audit contains completed review fields")
        if self.review_status == "approved" and (
            self.approved_path is None
            or self.approved_sha256 is None
            or self.safety_review_decisions is None
            or self.safety_reviewed_at is None
            or self.review_disposition != "approved_for_publishing"
            or self.rejection_reason is not None
        ):
            raise ValueError("approved audit is incomplete")
        if self.review_status == "approved" and self.safety_review_decisions is not None:
            decisions = self.safety_review_decisions
            unresolved = set(self.unresolved_safety_checks)
            if set(decisions) != unresolved or any(
                decisions[name] is not False
                for name in unresolved - {"allowed_for_publishing"}
            ) or (
                "allowed_for_publishing" in unresolved
                and decisions["allowed_for_publishing"] is not True
            ):
                raise ValueError("approved safety review is invalid")
        if self.review_status == "rejected" and (
            self.rejection_reason is None
            or self.safety_reviewed_at is None
            or self.review_disposition != "rejected"
            or self.approved_path is not None
            or self.approved_sha256 is not None
        ):
            raise ValueError("rejected audit is incomplete")
        return self


RecoveryPhase = Literal["pending", "intent", "done"]


class RecoveryAssetRecord(BaseModel):
    """Strict write-ahead record for one newly reviewed candidate."""

    model_config = ConfigDict(extra="forbid", strict=True)

    pending_id: NonEmptyStrictString
    disposition: Literal["approved", "rejected"]
    pending_path: NonEmptyStrictString
    destination: NonEmptyStrictString
    metadata_path: NonEmptyStrictString
    asset_sha256: Hash64
    source_device: Annotated[StrictInt, Field(ge=0)]
    source_inode: Annotated[StrictInt, Field(ge=1)]
    metadata_device: Annotated[StrictInt, Field(ge=0)]
    metadata_inode: Annotated[StrictInt, Field(ge=1)]
    original_audit_bytes_b64: NonEmptyStrictString
    original_audit_sha256: Hash64
    target_audit_bytes_b64: NonEmptyStrictString
    target_audit_sha256: Hash64
    audit_phase: RecoveryPhase = "pending"
    move_phase: RecoveryPhase = "pending"
    rollback_audit_phase: RecoveryPhase = "pending"
    rollback_move_phase: RecoveryPhase = "pending"


class AssetReviewRecoveryJournal(BaseModel):
    """Versioned, catalog-bound recovery record; unknown fields fail closed."""

    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[RECOVERY_JOURNAL_VERSION]
    transaction_id: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{32}$")]
    catalog_id: NonEmptyStrictString
    catalog_root: NonEmptyStrictString
    run_id: NonEmptyStrictString
    manifest_path: NonEmptyStrictString
    state: Literal[
        "prepared",
        "applying",
        "finalizing",
        "committed",
        "rolling_back",
        "needs_recovery",
    ]
    original_manifest_bytes_b64: NonEmptyStrictString
    original_manifest_sha256: Hash64
    target_manifest_bytes_b64: NonEmptyStrictString
    target_manifest_sha256: Hash64
    manifest_phase: RecoveryPhase = "pending"
    rollback_manifest_phase: RecoveryPhase = "pending"
    assets: list[RecoveryAssetRecord]
    rollback_errors: list[StrictStr] = Field(default_factory=list)


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
        _fsync_directory(path.parent)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        _fsync_directory(path.parent)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def write_pending_audit(candidate: PendingAsset) -> None:
    try:
        audit = PendingAuditRecord.model_validate(candidate.audit_record(), strict=True)
    except (ValidationError, TypeError, ValueError) as error:
        raise AssetLifecycleError("pending asset audit schema is invalid") from error
    _atomic_write_json(candidate.metadata_path, audit.model_dump(mode="json"))


def load_pending_asset(
    metadata_path: str | Path, catalog: AssetCatalog
) -> PendingAsset:
    try:
        path = Path(metadata_path).resolve()
    except (TypeError, ValueError, OSError) as error:
        raise AssetLifecycleError("pending asset audit path is invalid") from error
    incoming_root = catalog.incoming_root
    if not path.is_relative_to(incoming_root) or path.parent != incoming_root:
        raise AssetLifecycleError(
            "pending asset must stay in the catalog run-scoped incoming directory"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        audit = PendingAuditRecord.model_validate(raw, strict=True)
    except OSError as error:
        raise AssetLifecycleError("pending asset audit is missing or invalid") from error
    except (ValidationError, ValueError, TypeError) as error:
        raise AssetLifecycleError("pending asset audit schema is invalid") from error
    try:
        candidate = PendingAsset(
            **{
                **{
                    name: getattr(audit, name)
                    for name in _PENDING_FIELDS
                },
                "path": Path(audit.path).resolve(),
                "metadata_path": Path(audit.metadata_path).resolve(),
                "production_relative_path": Path(audit.production_relative_path),
                "tags": tuple(audit.tags),
                "fallback_roles": tuple(audit.fallback_roles),
                "unresolved_safety_checks": tuple(
                    audit.unresolved_safety_checks
                ),
                "provider_attribution": tuple(
                    sorted(audit.provider_attribution.items())
                ),
            }
        )
    except (TypeError, ValueError, OSError) as error:
        raise AssetLifecycleError("pending asset audit schema is invalid") from error
    if candidate.metadata_path != path:
        raise AssetLifecycleError("pending asset audit metadata path is not canonical")
    if not candidate_urls_are_allowed(
            candidate.provider,
            source_url=candidate.source_url,
            source_file_url=candidate.source_file_url,
            license_terms_url=candidate.license_terms_url,
        ):
        raise AssetLifecycleError("pending asset audit schema is invalid")
    production_path = candidate.production_relative_path
    if (
        production_path.is_absolute()
        or ".." in production_path.parts
        or production_path.suffix.lower() not in {".png", ".webp"}
    ):
        raise AssetLifecycleError("pending asset canonical production path is invalid")
    _validate_run_scope(candidate, catalog)
    catalog_root = catalog.root.resolve()
    snapshot_path = (catalog_root / candidate.license_snapshot).resolve()
    license_root = (catalog_root / "licenses").resolve()
    if not snapshot_path.is_relative_to(license_root) or not snapshot_path.is_file():
        raise AssetLifecycleError("pending asset canonical license snapshot is invalid")
    if sha256_file(snapshot_path) != candidate.license_snapshot_sha256:
        raise AssetLifecycleError("pending asset canonical license snapshot hash changed")
    if audit.review_status in {"pending", "rejected"}:
        if not candidate.path.is_file() or sha256_file(candidate.path) != candidate.sha256:
            raise AssetLifecycleError("pending asset bytes are missing or changed")
    elif audit.review_status == "approved":
        approved_path = Path(str(audit.approved_path)).resolve()
        expected_approved_path = (
            catalog.active_root / candidate.production_relative_path
        ).resolve()
        if (
            approved_path != expected_approved_path
            or audit.approved_sha256 != candidate.sha256
            or not approved_path.is_relative_to(catalog.active_root.resolve())
            or not approved_path.is_file()
            or sha256_file(approved_path) != audit.approved_sha256
        ):
            raise AssetLifecycleError("approved asset bytes are missing or changed")
    return candidate


def list_pending_assets(
    catalog: AssetCatalog,
    *,
    slot_id: str,
    requirement_fingerprint: str,
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
            and candidate.requirement_fingerprint == requirement_fingerprint
            and candidate.review_status in review_statuses
        ),
        key=lambda candidate: (
            candidate.candidate_rank,
            candidate.provider,
            candidate.provider_asset_id,
            candidate.pending_id,
        ),
    )


@contextmanager
def _candidate_lifecycle_lock(metadata_path: Path, catalog: AssetCatalog):
    resolved = metadata_path.resolve()
    incoming_root = catalog.incoming_root
    if not resolved.is_relative_to(incoming_root) or resolved.parent != incoming_root:
        raise AssetLifecycleError(
            "pending asset must stay in the catalog run-scoped incoming directory"
        )
    lock_path = metadata_path.with_suffix(f"{metadata_path.suffix}.lock")
    with lock_path.open("a+b") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _catalog_asset_lock(catalog: AssetCatalog, asset_id: str):
    lock_root = (catalog.root.resolve() / ".asset-locks").resolve()
    if not lock_root.is_relative_to(catalog.root.resolve()):
        raise AssetLifecycleError("catalog asset lock escapes catalog root")
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_name = hashlib.sha256(asset_id.encode("utf-8")).hexdigest()
    with (lock_root / f"{lock_name}.lock").open("a+b") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _complete_approval(
    candidate: PendingAsset,
    catalog: AssetCatalog,
    destination: Path,
    actual: str,
    decisions: dict[str, bool],
) -> AssetEntry:
    if destination.exists():
        raise AssetLifecycleError("approved destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    original_audit = json.loads(
        candidate.metadata_path.read_text(encoding="utf-8")
    )
    reviewed_at = datetime.now(UTC).isoformat()
    approved_audit = candidate.audit_record()
    approved_audit.update(
        {
            "review_status": "approved",
            "approved_path": str(destination),
            "approved_sha256": actual,
            "safety_review_decisions": decisions,
            "safety_reviewed_at": reviewed_at,
            "review_disposition": "approved_for_publishing",
        }
    )
    try:
        validated_audit = PendingAuditRecord.model_validate(
            approved_audit, strict=True
        ).model_dump(mode="json")
    except (ValidationError, TypeError, ValueError) as error:
        raise AssetLifecycleError("pending asset audit schema is invalid") from error
    moved = False
    try:
        _atomic_write_json(candidate.metadata_path, validated_audit)
        candidate.path.replace(destination)
        moved = True
        entry = catalog.append_approved(
            candidate,
            destination,
            safety_review_decisions=decisions,
            safety_reviewed_at=reviewed_at,
            review_disposition="approved_for_publishing",
            _review_lock_held=True,
        )
    except Exception:
        if moved and destination.exists():
            destination.replace(candidate.path)
        _atomic_write_json(candidate.metadata_path, original_audit)
        raise
    return entry


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


def _approve_external_asset_locked(
    candidate: PendingAsset,
    catalog: AssetCatalog,
    *,
    safety_decisions: Mapping[str, bool] | None = None,
) -> AssetEntry:
    with _candidate_lifecycle_lock(candidate.metadata_path, catalog):
        canonical = load_pending_asset(candidate.metadata_path, catalog)
        if canonical.review_status != "pending":
            raise AssetLifecycleError("only pending assets can be approved")
        if canonical != candidate:
            raise AssetLifecycleError("caller does not match canonical pending audit")
        candidate = canonical
        decisions = dict(safety_decisions or {})
        unresolved = set(candidate.unresolved_safety_checks)
        if set(decisions) != unresolved:
            raise AssetLifecycleError(
                "safety review must resolve every unresolved safety check"
            )
        if any(
            decisions[name] is not False
            for name in unresolved - {"allowed_for_publishing"}
        ) or (
            "allowed_for_publishing" in unresolved
            and decisions["allowed_for_publishing"] is not True
        ):
            raise AssetLifecycleError("safety review did not approve safe publishing")
        if any(type(value) is not bool for value in decisions.values()):
            raise AssetLifecycleError("safety review decisions must be booleans")
        actual = sha256_file(candidate.path)
        if actual != candidate.sha256:
            raise AssetLifecycleError("pending asset hash changed before approval")
        destination = (
            catalog.active_root / candidate.production_relative_path
        ).resolve()
        active_root = catalog.active_root.resolve()
        if not destination.is_relative_to(active_root):
            raise AssetLifecycleError("production path escapes active catalog")
        asset_id = f"{candidate.provider}-{candidate.provider_asset_id}"
        with _catalog_asset_lock(catalog, asset_id):
            return _complete_approval(
                candidate, catalog, destination, actual, decisions
            )


def approve_external_asset(
    candidate: PendingAsset,
    catalog: AssetCatalog,
    *,
    safety_decisions: Mapping[str, bool] | None = None,
) -> AssetEntry:
    with catalog_review_lock(catalog.root):
        return _approve_external_asset_locked(
            candidate,
            catalog,
            safety_decisions=safety_decisions,
        )


def _reject_external_asset_locked(
    candidate: PendingAsset,
    *,
    reason: str,
    catalog: AssetCatalog,
) -> PendingAsset | None:
    with _candidate_lifecycle_lock(candidate.metadata_path, catalog):
        canonical = load_pending_asset(candidate.metadata_path, catalog)
        if canonical.review_status != "pending":
            raise AssetLifecycleError("only pending assets can be rejected")
        if canonical != candidate:
            raise AssetLifecycleError("caller does not match canonical pending audit")
        candidate = canonical
        if not reason.strip():
            raise AssetLifecycleError("rejection reason is required")
        if sha256_file(candidate.path) != candidate.sha256:
            raise AssetLifecycleError("pending asset hash changed before rejection")
        audit = candidate.audit_record()
        audit.update(
            {
                "review_status": "rejected",
                "rejection_reason": reason.strip(),
                "safety_reviewed_at": datetime.now(UTC).isoformat(),
                "review_disposition": "rejected",
            }
        )
        try:
            validated_audit = PendingAuditRecord.model_validate(
                audit, strict=True
            ).model_dump(mode="json")
        except (ValidationError, TypeError, ValueError) as error:
            raise AssetLifecycleError("pending asset audit schema is invalid") from error
        _atomic_write_json(candidate.metadata_path, validated_audit)
    remaining = list_pending_assets(
        catalog,
        slot_id=candidate.slot_id,
        requirement_fingerprint=candidate.requirement_fingerprint,
    )
    return next(
        (
            item
            for item in remaining
            if item.candidate_rank > candidate.candidate_rank
        ),
        None,
    )


def reject_external_asset(
    candidate: PendingAsset,
    *,
    reason: str,
    catalog: AssetCatalog,
) -> PendingAsset | None:
    with catalog_review_lock(catalog.root):
        return _reject_external_asset_locked(
            candidate,
            reason=reason,
            catalog=catalog,
        )


_DECISION_BINDING_FIELDS = (
    "pending_id",
    "slot_id",
    "provider",
    "provider_asset_id",
    "requirement_fingerprint",
    "sha256",
    "metadata_path",
)


def _payload_value(payload, key: str):
    if isinstance(payload, dict):
        return payload.get(key)
    return getattr(payload, key, None)


def pending_asset_decision_binding(candidate: PendingAsset) -> dict[str, str]:
    return {
        "pending_id": candidate.pending_id,
        "slot_id": candidate.slot_id,
        "provider": candidate.provider,
        "provider_asset_id": candidate.provider_asset_id,
        "requirement_fingerprint": candidate.requirement_fingerprint,
        "sha256": candidate.sha256,
        "metadata_path": str(candidate.metadata_path.resolve()),
    }


def _validate_explicit_safety_review(
    candidate: PendingAsset,
    decisions: Mapping[str, bool] | None,
) -> dict[str, bool]:
    reviewed = dict(decisions or {})
    unresolved = set(candidate.unresolved_safety_checks)
    if set(reviewed) != unresolved or any(type(value) is not bool for value in reviewed.values()):
        raise AssetLifecycleError(
            "safety review must explicitly resolve every unresolved safety check"
        )
    if any(
        reviewed[name] is not False
        for name in unresolved - {"allowed_for_publishing"}
    ) or (
        "allowed_for_publishing" in unresolved
        and reviewed["allowed_for_publishing"] is not True
    ):
        raise AssetLifecycleError("safety review did not approve safe publishing")
    return reviewed


@contextmanager
def _batch_lifecycle_lock(catalog: AssetCatalog):
    with catalog_review_lock(catalog.root):
        yield


def _bytes_digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _require_directory_without_symlinks(path: Path, *, label: str) -> Path:
    lexical = Path(os.path.abspath(path))
    current = Path(lexical.anchor)
    try:
        for component in lexical.parts[1:]:
            current /= component
            metadata = current.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise AssetLifecycleError(f"{label} is not a trusted directory")
    except OSError as error:
        raise AssetLifecycleError(f"{label} is not a trusted directory") from error
    return lexical


def _recovery_root(catalog: AssetCatalog, *, create: bool) -> Path:
    catalog_root = _require_directory_without_symlinks(
        catalog.root,
        label="catalog root",
    )
    recovery_root = catalog_root / RECOVERY_JOURNAL_DIR
    if create and not recovery_root.exists():
        try:
            recovery_root.mkdir(mode=0o700)
            _fsync_directory(catalog_root)
        except OSError as error:
            raise AssetLifecycleError(
                "recovery journal directory could not be created"
            ) from error
    if recovery_root.exists() or recovery_root.is_symlink():
        return _require_directory_without_symlinks(
            recovery_root,
            label="recovery journal directory",
        )
    return recovery_root


def _decode_bound_bytes(encoded: str, expected_sha256: str, *, label: str) -> bytes:
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as error:
        raise AssetLifecycleError(f"recovery journal {label} is invalid") from error
    if _bytes_digest(payload) != expected_sha256:
        raise AssetLifecycleError(f"recovery journal {label} hash is invalid")
    return payload


def _regular_file_metadata(path: Path, *, label: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise AssetLifecycleError(f"recovery journal {label} is missing") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise AssetLifecycleError(
            f"recovery journal {label} must be a regular non-symlink file"
        )
    return metadata


def _lexical_path_inside(path_value: str, root: Path, *, label: str) -> Path:
    path = Path(os.path.abspath(path_value))
    root = Path(os.path.abspath(root))
    if not path.is_relative_to(root):
        raise AssetLifecycleError(f"recovery journal {label} escapes its trusted root")
    _require_directory_without_symlinks(path.parent, label=f"{label} parent")
    return path


def _durable_replace(source: Path, destination: Path) -> None:
    source_parent = source.parent
    destination_parent = destination.parent
    source.replace(destination)
    _fsync_directory(destination_parent)
    if source_parent != destination_parent:
        _fsync_directory(source_parent)


def _durable_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    _fsync_directory(path.parent)


def _durable_mkdir(path: Path, *, root: Path) -> None:
    root = Path(os.path.abspath(root))
    path = Path(os.path.abspath(path))
    if not path.is_relative_to(root):
        raise AssetLifecycleError("directory creation escapes trusted root")
    current = root
    for component in path.relative_to(root).parts:
        child = current / component
        if not child.exists():
            child.mkdir(mode=0o755)
            _fsync_directory(current)
        current = _require_directory_without_symlinks(
            child,
            label="created directory",
        )


def _journal_path(catalog: AssetCatalog, transaction_id: str) -> Path:
    root = _recovery_root(catalog, create=True)
    return root / f"{transaction_id}.json"


def _write_recovery_journal(
    path: Path,
    journal: AssetReviewRecoveryJournal,
) -> None:
    _atomic_write_json(path, journal.model_dump(mode="json"))


def _crash_point(_event: str) -> None:
    """Test seam for simulating process death after durable WAL transitions."""


def _set_journal_phase(
    journal_path: Path,
    journal: AssetReviewRecoveryJournal,
    record: RecoveryAssetRecord | None,
    field_name: str,
    phase: RecoveryPhase,
    event: str,
) -> None:
    target = record if record is not None else journal
    setattr(target, field_name, phase)
    _write_recovery_journal(journal_path, journal)
    _crash_point(event)


def _manifest_cas_write(
    catalog: AssetCatalog,
    *,
    expected_sha256: str,
    target_bytes: bytes,
) -> None:
    manifest_path = catalog.manifest_path
    if manifest_path is None:
        raise AssetLifecycleError("recovery requires a persistent catalog manifest")
    lock_path = manifest_path.with_suffix(f"{manifest_path.suffix}.lock")
    with lock_path.open("a+b") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            current = manifest_path.read_bytes()
            target_sha256 = _bytes_digest(target_bytes)
            if _bytes_digest(current) == target_sha256:
                return
            if _bytes_digest(current) != expected_sha256:
                raise AssetLifecycleError(
                    "catalog manifest changed after batch snapshot; recovery refused to overwrite it"
                )
            _atomic_write_bytes(manifest_path, target_bytes)
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _quarantine_journal(path: Path) -> None:
    quarantine = path.with_name(f"{path.name}.invalid-{uuid.uuid4().hex}")
    try:
        os.replace(path, quarantine)
        _fsync_directory(path.parent)
    except OSError:
        # Failure to quarantine still fails closed; no journal-directed mutation follows.
        pass


def _read_journal_file(path: Path) -> dict[str, object]:
    descriptor: int | None = None
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        before = _regular_file_metadata(path, label="file")
        if before.st_nlink != 1:
            raise AssetLifecycleError("recovery journal file has unsafe links")
        descriptor = os.open(path, os.O_RDONLY | nofollow)
        opened = os.fstat(descriptor)
        after = path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            or (opened.st_dev, opened.st_ino) != (after.st_dev, after.st_ino)
        ):
            raise AssetLifecycleError("recovery journal file identity changed")
        chunks = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return json.loads(b"".join(chunks).decode("utf-8"))
    except (OSError, ValueError, TypeError) as error:
        if isinstance(error, AssetLifecycleError):
            raise
        raise AssetLifecycleError("asset review recovery journal is unreadable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _validated_recovery_journal(
    catalog: AssetCatalog,
    path: Path,
) -> AssetReviewRecoveryJournal:
    try:
        journal = AssetReviewRecoveryJournal.model_validate(
            _read_journal_file(path),
            strict=True,
        )
    except (ValidationError, AssetLifecycleError, TypeError, ValueError) as error:
        _quarantine_journal(path)
        raise AssetLifecycleError("asset review recovery journal schema is invalid") from error

    try:
        catalog_root = _require_directory_without_symlinks(
            catalog.root,
            label="catalog root",
        )
        if catalog.manifest_path is None:
            raise AssetLifecycleError("recovery journal manifest binding is invalid")
        manifest_path = Path(os.path.abspath(catalog.manifest_path))
        if (
            path.stem != journal.transaction_id
            or journal.catalog_id != catalog.catalog_id
            or journal.catalog_root != str(catalog_root)
            or journal.run_id != catalog.run_id
            or journal.manifest_path != str(manifest_path)
            or manifest_path.parent != catalog_root
        ):
            raise AssetLifecycleError("recovery journal transaction binding is invalid")
        _regular_file_metadata(manifest_path, label="catalog manifest")

        original_manifest = _decode_bound_bytes(
            journal.original_manifest_bytes_b64,
            journal.original_manifest_sha256,
            label="original manifest snapshot",
        )
        target_manifest = _decode_bound_bytes(
            journal.target_manifest_bytes_b64,
            journal.target_manifest_sha256,
            label="target manifest snapshot",
        )
        for payload in (original_manifest, target_manifest):
            manifest = json.loads(payload.decode("utf-8"))
            if manifest.get("catalog_id") != catalog.catalog_id:
                raise AssetLifecycleError("recovery journal catalog binding is invalid")

        incoming_root = _require_directory_without_symlinks(
            catalog.incoming_root,
            label="incoming root",
        )
        active_root = _require_directory_without_symlinks(
            catalog.active_root,
            label="active root",
        )
        seen: set[tuple[str, str]] = set()
        for record in journal.assets:
            original_audit_bytes = _decode_bound_bytes(
                record.original_audit_bytes_b64,
                record.original_audit_sha256,
                label="audit snapshot",
            )
            target_audit_bytes = _decode_bound_bytes(
                record.target_audit_bytes_b64,
                record.target_audit_sha256,
                label="target audit snapshot",
            )
            original_audit = PendingAuditRecord.model_validate_json(
                original_audit_bytes,
                strict=True,
            )
            target_audit = PendingAuditRecord.model_validate_json(
                target_audit_bytes,
                strict=True,
            )
            pending_path = _lexical_path_inside(
                record.pending_path,
                incoming_root,
                label="pending path",
            )
            metadata_path = _lexical_path_inside(
                record.metadata_path,
                incoming_root,
                label="metadata path",
            )
            destination = _lexical_path_inside(
                record.destination,
                active_root,
                label="destination path",
            )
            if (
                pending_path.parent != incoming_root
                or metadata_path.parent != incoming_root
                or original_audit.review_status != "pending"
                or original_audit.pending_id != record.pending_id
                or target_audit.pending_id != record.pending_id
                or original_audit.run_id != catalog.run_id
                or target_audit.run_id != catalog.run_id
                or Path(original_audit.path) != pending_path
                or Path(target_audit.path) != pending_path
                or Path(original_audit.metadata_path) != metadata_path
                or Path(target_audit.metadata_path) != metadata_path
                or original_audit.sha256 != record.asset_sha256
                or target_audit.sha256 != record.asset_sha256
                or destination
                != (active_root / original_audit.production_relative_path)
                or target_audit.review_status != record.disposition
                or (
                    record.disposition == "approved"
                    and Path(str(target_audit.approved_path)) != destination
                )
            ):
                raise AssetLifecycleError("recovery journal audit snapshot binding is invalid")
            identity_key = (record.pending_id, str(metadata_path))
            if identity_key in seen:
                raise AssetLifecycleError("recovery journal contains duplicate assets")
            seen.add(identity_key)

            metadata = _regular_file_metadata(metadata_path, label="metadata path")
            current_audit_sha256 = _bytes_digest(metadata_path.read_bytes())
            if current_audit_sha256 not in {
                record.original_audit_sha256,
                record.target_audit_sha256,
            }:
                raise AssetLifecycleError("recovery journal audit bytes are unbound")
            if (
                current_audit_sha256 == record.original_audit_sha256
                and record.audit_phase == "pending"
                and record.rollback_audit_phase == "pending"
                and (metadata.st_dev, metadata.st_ino)
                != (record.metadata_device, record.metadata_inode)
            ):
                raise AssetLifecycleError("recovery journal audit identity is unbound")

            pending_exists = pending_path.exists()
            destination_exists = destination.exists()
            if record.disposition == "approved" and pending_exists == destination_exists:
                raise AssetLifecycleError("recovery journal asset paths are ambiguous")
            if record.disposition == "rejected" and (
                not pending_exists or destination_exists
            ):
                raise AssetLifecycleError("recovery journal rejected asset path is invalid")
            existing_path = pending_path if pending_exists else destination
            file_metadata = _regular_file_metadata(existing_path, label="asset path")
            if (
                _bytes_digest(existing_path.read_bytes()) != record.asset_sha256
                or (file_metadata.st_dev, file_metadata.st_ino)
                != (record.source_device, record.source_inode)
            ):
                raise AssetLifecycleError("recovery journal asset identity is unbound")
            if record.disposition == "rejected" and existing_path != pending_path:
                raise AssetLifecycleError("recovery journal rejected asset moved unexpectedly")
    except (ValidationError, OSError, ValueError, TypeError, AssetLifecycleError) as error:
        _quarantine_journal(path)
        if isinstance(error, AssetLifecycleError):
            raise
        raise AssetLifecycleError("asset review recovery journal binding is invalid") from error
    return journal


def _rollback_from_journal(
    catalog: AssetCatalog,
    journal_path: Path,
    journal: AssetReviewRecoveryJournal,
) -> list[str]:
    errors: list[str] = []
    journal.state = "rolling_back"
    _write_recovery_journal(journal_path, journal)

    try:
        _set_journal_phase(
            journal_path,
            journal,
            None,
            "rollback_manifest_phase",
            "intent",
            "rollback_manifest.intent",
        )
        original_manifest = _decode_bound_bytes(
            journal.original_manifest_bytes_b64,
            journal.original_manifest_sha256,
            label="original manifest snapshot",
        )
        _manifest_cas_write(
            catalog,
            expected_sha256=journal.target_manifest_sha256,
            target_bytes=original_manifest,
        )
        _crash_point("rollback_manifest.applied")
        _set_journal_phase(
            journal_path,
            journal,
            None,
            "rollback_manifest_phase",
            "done",
            "rollback_manifest.done",
        )
    except Exception as error:
        errors.append(f"restore catalog manifest: {error}")

    for record in reversed(journal.assets):
        pending_path = Path(record.pending_path)
        destination = Path(record.destination)
        if record.disposition == "approved":
            try:
                _set_journal_phase(
                    journal_path,
                    journal,
                    record,
                    "rollback_move_phase",
                    "intent",
                    f"{record.pending_id}.rollback_move.intent",
                )
                if destination.exists() and not pending_path.exists():
                    _durable_replace(destination, pending_path)
                elif not pending_path.exists() or destination.exists():
                    raise AssetLifecycleError("asset rollback paths are inconsistent")
                _crash_point(f"{record.pending_id}.rollback_move.applied")
                _set_journal_phase(
                    journal_path,
                    journal,
                    record,
                    "rollback_move_phase",
                    "done",
                    f"{record.pending_id}.rollback_move.done",
                )
            except Exception as error:
                errors.append(f"restore asset {pending_path}: {error}")
        try:
            _set_journal_phase(
                journal_path,
                journal,
                record,
                "rollback_audit_phase",
                "intent",
                f"{record.pending_id}.rollback_audit.intent",
            )
            original_audit = _decode_bound_bytes(
                record.original_audit_bytes_b64,
                record.original_audit_sha256,
                label="audit snapshot",
            )
            metadata_path = Path(record.metadata_path)
            current_sha256 = _bytes_digest(metadata_path.read_bytes())
            if current_sha256 == record.target_audit_sha256:
                _atomic_write_bytes(metadata_path, original_audit)
            elif current_sha256 != record.original_audit_sha256:
                raise AssetLifecycleError("audit rollback compare-and-swap failed")
            _crash_point(f"{record.pending_id}.rollback_audit.applied")
            _set_journal_phase(
                journal_path,
                journal,
                record,
                "rollback_audit_phase",
                "done",
                f"{record.pending_id}.rollback_audit.done",
            )
        except Exception as error:
            errors.append(f"restore audit {record.metadata_path}: {error}")
    return errors


def _recover_asset_review_journals_locked(catalog: AssetCatalog) -> None:
    recovery_root = _recovery_root(catalog, create=False)
    if not recovery_root.exists():
        return
    for path in sorted(recovery_root.glob("*.json")):
        journal = _validated_recovery_journal(catalog, path)
        if journal.state == "committed":
            _durable_unlink(path)
            continue
        errors = _rollback_from_journal(catalog, path, journal)
        if errors:
            journal.state = "needs_recovery"
            journal.rollback_errors = errors
            _write_recovery_journal(path, journal)
            raise AssetLifecycleError(
                "asset review recovery remains incomplete: " + "; ".join(errors)
            )
        _durable_unlink(path)


def _json_bytes(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _reviewed_audit_bytes(
    candidate: PendingAsset,
    *,
    disposition: str,
    destination: Path,
    safety: dict[str, bool],
    rejection_reason: str,
    reviewed_at: str,
) -> bytes:
    payload = candidate.audit_record()
    if disposition == "approved":
        payload.update(
            {
                "review_status": "approved",
                "approved_path": str(destination),
                "approved_sha256": candidate.sha256,
                "safety_review_decisions": safety,
                "safety_reviewed_at": reviewed_at,
                "review_disposition": "approved_for_publishing",
            }
        )
    else:
        payload.update(
            {
                "review_status": "rejected",
                "rejection_reason": rejection_reason.strip(),
                "safety_reviewed_at": reviewed_at,
                "review_disposition": "rejected",
            }
        )
    try:
        validated = PendingAuditRecord.model_validate(
            payload,
            strict=True,
        ).model_dump(mode="json")
    except (ValidationError, TypeError, ValueError) as error:
        raise AssetLifecycleError("pending asset audit schema is invalid") from error
    return _json_bytes(validated)


def _prepare_batch_journal(
    catalog: AssetCatalog,
    canonical_by_id: dict[str, PendingAsset],
    normalized: dict[str, tuple[str, dict[str, bool]]],
    *,
    rejection_reason: str,
) -> tuple[Path, AssetReviewRecoveryJournal]:
    if catalog.manifest_path is None:
        raise AssetLifecycleError("asset review requires a persistent catalog manifest")
    catalog_root = _require_directory_without_symlinks(
        catalog.root,
        label="catalog root",
    )
    incoming_root = _require_directory_without_symlinks(
        catalog.incoming_root,
        label="incoming root",
    )
    active_root = catalog_root / "active"
    if not active_root.exists():
        _durable_mkdir(active_root, root=catalog_root)
    active_root = _require_directory_without_symlinks(
        active_root,
        label="active root",
    )
    original_manifest = catalog.manifest_path.read_bytes()
    try:
        target_manifest_payload = json.loads(original_manifest.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError) as error:
        raise AssetLifecycleError("catalog manifest is invalid") from error
    target_assets = target_manifest_payload.setdefault("assets", [])
    records: list[RecoveryAssetRecord] = []

    for pending_id, (disposition, safety) in normalized.items():
        candidate = canonical_by_id[pending_id]
        if candidate.review_status == disposition:
            # A prior committed review is not owned by this transaction.
            continue
        if candidate.review_status != "pending":
            raise AssetLifecycleError("canonical audit conflicts with requested decision")
        pending_path = _lexical_path_inside(
            str(candidate.path),
            incoming_root,
            label="pending path",
        )
        metadata_path = _lexical_path_inside(
            str(candidate.metadata_path),
            incoming_root,
            label="metadata path",
        )
        destination = Path(
            os.path.abspath(active_root / candidate.production_relative_path)
        )
        if not destination.is_relative_to(active_root):
            raise AssetLifecycleError("approved destination escapes active catalog")
        _durable_mkdir(destination.parent, root=active_root)
        _require_directory_without_symlinks(
            destination.parent,
            label="destination parent",
        )
        _fsync_directory(destination.parent)
        source_metadata = _regular_file_metadata(pending_path, label="pending path")
        audit_metadata = _regular_file_metadata(metadata_path, label="metadata path")
        original_audit = metadata_path.read_bytes()
        reviewed_at = datetime.now(UTC).isoformat()
        target_audit = _reviewed_audit_bytes(
            candidate,
            disposition=disposition,
            destination=destination,
            safety=safety,
            rejection_reason=rejection_reason,
            reviewed_at=reviewed_at,
        )
        if disposition == "approved":
            asset_id = f"{candidate.provider}-{candidate.provider_asset_id}"
            if any(item.get("asset_id") == asset_id for item in target_assets):
                raise AssetLifecycleError(f"duplicate approved asset_id: {asset_id}")
            target_assets.append(
                approved_manifest_item(
                    candidate,
                    destination,
                    safety_review_decisions=safety,
                    safety_reviewed_at=reviewed_at,
                    review_disposition="approved_for_publishing",
                    catalog_root=catalog_root,
                )
            )
        records.append(
            RecoveryAssetRecord(
                pending_id=pending_id,
                disposition=disposition,
                pending_path=str(pending_path),
                destination=str(destination),
                metadata_path=str(metadata_path),
                asset_sha256=candidate.sha256,
                source_device=source_metadata.st_dev,
                source_inode=source_metadata.st_ino,
                metadata_device=audit_metadata.st_dev,
                metadata_inode=audit_metadata.st_ino,
                original_audit_bytes_b64=base64.b64encode(original_audit).decode(
                    "ascii"
                ),
                original_audit_sha256=_bytes_digest(original_audit),
                target_audit_bytes_b64=base64.b64encode(target_audit).decode(
                    "ascii"
                ),
                target_audit_sha256=_bytes_digest(target_audit),
            )
        )

    target_manifest = _json_bytes(target_manifest_payload)
    transaction_id = uuid.uuid4().hex
    journal = AssetReviewRecoveryJournal(
        version=RECOVERY_JOURNAL_VERSION,
        transaction_id=transaction_id,
        catalog_id=catalog.catalog_id,
        catalog_root=str(catalog_root),
        run_id=catalog.run_id,
        manifest_path=str(Path(os.path.abspath(catalog.manifest_path))),
        state="prepared",
        original_manifest_bytes_b64=base64.b64encode(original_manifest).decode(
            "ascii"
        ),
        original_manifest_sha256=_bytes_digest(original_manifest),
        target_manifest_bytes_b64=base64.b64encode(target_manifest).decode("ascii"),
        target_manifest_sha256=_bytes_digest(target_manifest),
        assets=records,
    )
    journal_path = _journal_path(catalog, transaction_id)
    _write_recovery_journal(journal_path, journal)
    _crash_point("transaction.prepared")
    return journal_path, journal


def _apply_batch_journal(
    catalog: AssetCatalog,
    journal_path: Path,
    journal: AssetReviewRecoveryJournal,
) -> None:
    journal.state = "applying"
    _write_recovery_journal(journal_path, journal)
    _crash_point("transaction.applying")
    for record in journal.assets:
        with _candidate_lifecycle_lock(Path(record.metadata_path), catalog):
            _set_journal_phase(
                journal_path,
                journal,
                record,
                "audit_phase",
                "intent",
                f"{record.pending_id}.audit.intent",
            )
            metadata_path = Path(record.metadata_path)
            current_audit_sha256 = _bytes_digest(metadata_path.read_bytes())
            if current_audit_sha256 == record.original_audit_sha256:
                _atomic_write_bytes(
                    metadata_path,
                    _decode_bound_bytes(
                        record.target_audit_bytes_b64,
                        record.target_audit_sha256,
                        label="target audit snapshot",
                    ),
                )
            elif current_audit_sha256 != record.target_audit_sha256:
                raise AssetLifecycleError("audit apply compare-and-swap failed")
            _crash_point(f"{record.pending_id}.audit.applied")
            _set_journal_phase(
                journal_path,
                journal,
                record,
                "audit_phase",
                "done",
                f"{record.pending_id}.audit.done",
            )
            if record.disposition == "approved":
                _set_journal_phase(
                    journal_path,
                    journal,
                    record,
                    "move_phase",
                    "intent",
                    f"{record.pending_id}.move.intent",
                )
                pending_path = Path(record.pending_path)
                destination = Path(record.destination)
                if pending_path.exists() and not destination.exists():
                    _durable_replace(pending_path, destination)
                elif not destination.exists() or pending_path.exists():
                    raise AssetLifecycleError("asset apply paths are inconsistent")
                _crash_point(f"{record.pending_id}.move.applied")
                _set_journal_phase(
                    journal_path,
                    journal,
                    record,
                    "move_phase",
                    "done",
                    f"{record.pending_id}.move.done",
                )

    _set_journal_phase(
        journal_path,
        journal,
        None,
        "manifest_phase",
        "intent",
        "manifest.intent",
    )
    target_manifest = _decode_bound_bytes(
        journal.target_manifest_bytes_b64,
        journal.target_manifest_sha256,
        label="target manifest snapshot",
    )
    _manifest_cas_write(
        catalog,
        expected_sha256=journal.original_manifest_sha256,
        target_bytes=target_manifest,
    )
    _crash_point("manifest.applied")
    _set_journal_phase(
        journal_path,
        journal,
        None,
        "manifest_phase",
        "done",
        "manifest.done",
    )


def review_pending_asset_batch(
    catalog: AssetCatalog,
    manifest_items: list[object],
    decisions: Mapping[str, object],
    *,
    rejection_reason: str,
    finalize: Callable[[], Any] | None = None,
) -> BatchAssetReviewResult:
    """Atomically review a complete pending-asset batch.

    Every decision carries the exact provenance binding shown to the human.
    Audit files, incoming bytes, promoted bytes, and the catalog manifest are
    restored together if any review operation or the caller's final resolver
    refresh fails.
    """
    pending_items = [
        item for item in manifest_items
        if _payload_value(item, "status") == "pending_external"
    ]
    if not pending_items:
        if decisions:
            raise AssetLifecycleError("asset decisions contain no pending assets")
        return BatchAssetReviewResult(False, finalize() if finalize else None)
    if not isinstance(decisions, Mapping):
        raise AssetLifecycleError("asset decisions must be a mapping")

    with _batch_lifecycle_lock(catalog):
        _recover_asset_review_journals_locked(catalog)
        canonical_by_id: dict[str, PendingAsset] = {}
        for item in pending_items:
            metadata_path = _payload_value(item, "metadata_path")
            if not metadata_path:
                raise AssetLifecycleError("pending asset is missing metadata_path")
            candidate = load_pending_asset(metadata_path, catalog)
            if candidate.pending_id in canonical_by_id:
                raise AssetLifecycleError(
                    f"duplicate pending asset in manifest: {candidate.pending_id}"
                )
            binding = pending_asset_decision_binding(candidate)
            for field_name in _DECISION_BINDING_FIELDS:
                manifest_value = _payload_value(item, field_name)
                expected = binding[field_name]
                if field_name == "metadata_path" and manifest_value:
                    manifest_value = str(Path(str(manifest_value)).resolve())
                if str(manifest_value or "") != expected:
                    raise AssetLifecycleError(
                        f"manifest does not match canonical pending asset: {field_name}"
                    )
            canonical_by_id[candidate.pending_id] = candidate

        normalized: dict[str, tuple[str, dict[str, bool]]] = {}
        for raw_pending_id, raw_decision in decisions.items():
            pending_id = str(raw_pending_id)
            if pending_id not in canonical_by_id:
                raise AssetLifecycleError(
                    f"unknown canonical pending asset decision ID: {raw_pending_id}"
                )
            if pending_id in normalized:
                raise AssetLifecycleError(f"duplicate decision for pending asset: {pending_id}")
            if not isinstance(raw_decision, Mapping):
                raise AssetLifecycleError("asset decision must include binding and safety review")
            disposition = raw_decision.get("decision")
            if disposition not in {"approved", "rejected"}:
                raise AssetLifecycleError("asset decision must be approved or rejected")
            candidate = canonical_by_id[pending_id]
            if dict(raw_decision.get("binding") or {}) != pending_asset_decision_binding(candidate):
                raise AssetLifecycleError("asset decision binding does not match canonical audit")
            safety = dict(raw_decision.get("safety_decisions") or {})
            if disposition == "approved":
                safety = _validate_explicit_safety_review(candidate, safety)
            elif safety:
                raise AssetLifecycleError("rejected asset must not carry approval safety decisions")
            normalized[pending_id] = (str(disposition), safety)
        if set(normalized) != set(canonical_by_id):
            raise AssetLifecycleError("every pending asset requires one explicit decision")
        if any(value[0] == "rejected" for value in normalized.values()) and not rejection_reason.strip():
            raise AssetLifecycleError("rejection reason is required")

        if catalog.manifest_path is None or not catalog.manifest_path.is_file():
            raise AssetLifecycleError("asset review requires a persistent catalog manifest")
        approved_destinations: set[Path] = set()
        for pending_id, (disposition, _safety) in normalized.items():
            candidate = canonical_by_id[pending_id]
            if candidate.review_status not in {"pending", disposition}:
                raise AssetLifecycleError("canonical audit conflicts with requested decision")
            if candidate.review_status == "approved":
                completed_audit = PendingAuditRecord.model_validate_json(
                    candidate.metadata_path.read_text(encoding="utf-8"),
                    strict=True,
                )
                if completed_audit.safety_review_decisions != _safety:
                    raise AssetLifecycleError(
                        "completed approval safety review conflicts with retry"
                    )
            if disposition == "approved" and candidate.review_status == "pending":
                destination = (catalog.active_root / candidate.production_relative_path).resolve()
                if destination in approved_destinations or destination.exists():
                    raise AssetLifecycleError("approved destination is not available")
                approved_destinations.add(destination)

        any_rejected = any(value[0] == "rejected" for value in normalized.values())
        journal_path, journal = _prepare_batch_journal(
            catalog,
            canonical_by_id,
            normalized,
            rejection_reason=rejection_reason,
        )
        try:
            _apply_batch_journal(catalog, journal_path, journal)
            journal.state = "finalizing"
            _write_recovery_journal(journal_path, journal)
            _crash_point("transaction.finalizing")
            finalized = finalize() if finalize else None
        except Exception as original_error:
            try:
                rollback_errors = _rollback_from_journal(
                    catalog,
                    journal_path,
                    journal,
                )
            except Exception as rollback_error:
                rollback_errors = [f"start rollback: {rollback_error}"]
            if rollback_errors:
                journal.state = "needs_recovery"
                journal.rollback_errors = rollback_errors
                try:
                    _write_recovery_journal(journal_path, journal)
                except Exception as journal_error:
                    rollback_errors.append(
                        f"persist recovery journal: {journal_error}"
                    )
                original_error.add_note(
                    "asset review rollback incomplete: "
                    + "; ".join(rollback_errors)
                )
            else:
                _durable_unlink(journal_path)
            raise
        journal.state = "committed"
        _write_recovery_journal(journal_path, journal)
        _crash_point("transaction.committed")
        _durable_unlink(journal_path)
        return BatchAssetReviewResult(any_rejected, finalized)
