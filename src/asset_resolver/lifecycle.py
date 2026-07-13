from __future__ import annotations

import hashlib
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, Mapping

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
        if not path.name.startswith("attempts-")
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
            )
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
