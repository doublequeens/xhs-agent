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

from .catalog import AssetCatalog, AssetEntry
from .providers import candidate_urls_are_allowed


class AssetLifecycleError(RuntimeError):
    """Raised when a pending external asset cannot be safely reviewed."""


@dataclass(frozen=True, slots=True)
class BatchAssetReviewResult:
    any_rejected: bool
    finalized_value: Any = None


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
        asset_id = f"{candidate.provider}-{candidate.provider_asset_id}"
        with _catalog_asset_lock(catalog, asset_id):
            return _complete_approval(
                candidate, catalog, destination, actual, decisions
            )


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
    lock_path = catalog.root.resolve() / ".asset-review-batch.lock"
    with lock_path.open("a+b") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


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
        canonical_by_id: dict[str, PendingAsset] = {}
        aliases: dict[str, set[str]] = {}
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
            for alias in {
                candidate.pending_id,
                candidate.provider_asset_id,
                f"{candidate.provider}:{candidate.provider_asset_id}",
            }:
                aliases.setdefault(alias, set()).add(candidate.pending_id)

        normalized: dict[str, tuple[str, dict[str, bool]]] = {}
        for raw_alias, raw_decision in decisions.items():
            matching = aliases.get(str(raw_alias), set())
            if len(matching) != 1:
                raise AssetLifecycleError(
                    f"unknown or ambiguous pending asset decision ID: {raw_alias}"
                )
            pending_id = next(iter(matching))
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

        manifest_bytes = catalog.manifest_path.read_bytes()
        audit_bytes = {
            item.pending_id: item.metadata_path.read_bytes()
            for item in canonical_by_id.values()
        }
        any_rejected = any(value[0] == "rejected" for value in normalized.values())
        try:
            for pending_id, (disposition, safety) in normalized.items():
                candidate = canonical_by_id[pending_id]
                if candidate.review_status == disposition:
                    continue
                if disposition == "approved":
                    approve_external_asset(
                        candidate,
                        catalog,
                        safety_decisions=safety,
                    )
                else:
                    reject_external_asset(
                        candidate,
                        reason=rejection_reason,
                        catalog=catalog,
                    )
            finalized = finalize() if finalize else None
        except Exception:
            for candidate in canonical_by_id.values():
                destination = (
                    catalog.active_root / candidate.production_relative_path
                ).resolve()
                if destination.exists() and not candidate.path.exists():
                    candidate.path.parent.mkdir(parents=True, exist_ok=True)
                    destination.replace(candidate.path)
                _atomic_write_bytes(
                    candidate.metadata_path,
                    audit_bytes[candidate.pending_id],
                )
            _atomic_write_bytes(catalog.manifest_path, manifest_bytes)
            raise
        return BatchAssetReviewResult(any_rejected, finalized)
