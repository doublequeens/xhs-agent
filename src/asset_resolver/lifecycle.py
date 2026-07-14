from __future__ import annotations

import hashlib
import base64
import fcntl
import json
import os
import stat
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields, replace
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
    CatalogError,
    approved_manifest_item,
    catalog_review_lock,
    load_catalog,
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
TRANSACTION_REGISTRY_FILENAME = "transactions.registry"
TRANSACTION_REGISTRY_VERSION = 1
MAX_RECOVERY_FILE_BYTES = 2 * 1024 * 1024
MAX_RECOVERY_SNAPSHOT_BYTES = 1024 * 1024
MAX_RECOVERY_TOTAL_SNAPSHOT_BYTES = 4 * 1024 * 1024
MAX_TRANSACTION_AGE_SECONDS = 30 * 24 * 60 * 60


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
    created_at: NonEmptyStrictString
    plan_sha256: Hash64
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

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("timestamp must include timezone")
        return value


class TransactionRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    plan_sha256: Hash64
    state: Literal["prepared", "committed", "aborted"]
    created_at: NonEmptyStrictString

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("timestamp must include timezone")
        return value


class TransactionRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[TRANSACTION_REGISTRY_VERSION]
    catalog_id: NonEmptyStrictString
    catalog_root: NonEmptyStrictString
    run_id: NonEmptyStrictString
    transactions: dict[
        Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{32}$")],
        TransactionRegistryEntry,
    ] = Field(default_factory=dict)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def _held_parent_directory(path: Path):
    """Open an absolute parent component-by-component and hold its binding."""

    lexical = Path(os.path.abspath(path))
    descriptors: list[int] = []
    bindings: list[tuple[int, str, tuple[int, int]]] = []
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    flags = os.O_RDONLY | os.O_DIRECTORY | nofollow
    try:
        descriptors.append(os.open(lexical.anchor, flags))
        for component in lexical.parent.parts[1:]:
            parent = descriptors[-1]
            child = os.open(component, flags, dir_fd=parent)
            opened = os.fstat(child)
            named = os.stat(component, dir_fd=parent, follow_symlinks=False)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            ):
                os.close(child)
                raise AssetLifecycleError("trusted parent directory identity changed")
            bindings.append(
                (parent, component, (opened.st_dev, opened.st_ino))
            )
            descriptors.append(child)
        yield descriptors[-1], lexical.name
        for parent, component, identity in bindings:
            current = os.stat(component, dir_fd=parent, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != identity:
                raise AssetLifecycleError("trusted parent directory identity changed")
    except OSError as error:
        raise AssetLifecycleError("trusted parent directory is unsafe") from error
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short write")
        view = view[written:]


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    _atomic_write_bytes(path, _json_bytes(payload))


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    temporary_name = f".{path.name}.{uuid.uuid4().hex}.tmp"
    descriptor: int | None = None
    with _held_parent_directory(path) as (parent_descriptor, name):
        try:
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=parent_descriptor,
            )
            _write_all(descriptor, payload)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            os.rename(
                temporary_name,
                name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            os.fsync(parent_descriptor)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
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
    if catalog.manifest_path is None:
        raise CatalogError("approval requires a persistent catalog manifest")
    reviewed = _validate_explicit_safety_review(candidate, safety_decisions)
    try:
        review_pending_asset_batch(
            catalog,
            [{
                **_standalone_manifest_item(candidate),
                "_require_pending": True,
                "_caller_audit_record": candidate.audit_record(),
            }],
            {
                candidate.pending_id: {
                    "decision": "approved",
                    "binding": pending_asset_decision_binding(candidate),
                    "safety_decisions": reviewed,
                }
            },
            rejection_reason="not selected",
        )
    except AssetLifecycleError as error:
        if str(error) == "only pending assets can be reviewed":
            raise AssetLifecycleError("only pending assets can be approved") from error
        raise
    asset_id = f"{candidate.provider}-{candidate.provider_asset_id}"
    reloaded = load_catalog(catalog.manifest_path)
    return next(entry for entry in reloaded.entries if entry.asset_id == asset_id)


def reject_external_asset(
    candidate: PendingAsset,
    *,
    reason: str,
    catalog: AssetCatalog,
) -> PendingAsset | None:
    review_catalog = catalog
    if catalog.manifest_path is None:
        anchor = catalog.root.resolve() / ".asset-review-rejection-anchor.json"
        expected = _json_bytes({"catalog_id": catalog.catalog_id, "assets": []})
        with catalog_review_lock(catalog.root):
            if anchor.exists():
                if anchor.read_bytes() != expected:
                    raise AssetLifecycleError(
                        "asset review rejection anchor is invalid"
                    )
            else:
                _atomic_write_bytes(anchor, expected)
        review_catalog = replace(catalog, manifest_path=anchor)
    try:
        review_pending_asset_batch(
            review_catalog,
            [{
                **_standalone_manifest_item(candidate),
                "_require_pending": True,
                "_caller_audit_record": candidate.audit_record(),
            }],
            {
                candidate.pending_id: {
                    "decision": "rejected",
                    "binding": pending_asset_decision_binding(candidate),
                    "safety_decisions": {},
                }
            },
            rejection_reason=reason,
        )
    except AssetLifecycleError as error:
        if str(error) == "only pending assets can be reviewed":
            raise AssetLifecycleError("only pending assets can be rejected") from error
        raise
    remaining = list_pending_assets(
        review_catalog,
        slot_id=candidate.slot_id,
        requirement_fingerprint=candidate.requirement_fingerprint,
    )
    return next(
        (item for item in remaining if item.candidate_rank > candidate.candidate_rank),
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


def _standalone_manifest_item(candidate: PendingAsset) -> dict[str, str]:
    return {
        "status": "pending_external",
        **pending_asset_decision_binding(candidate),
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
        trusted = _require_directory_without_symlinks(
            recovery_root,
            label="recovery journal directory",
        )
        metadata = trusted.stat()
        if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise AssetLifecycleError(
                "recovery journal directory owner or mode is unsafe"
            )
        return trusted
    return recovery_root


def _decode_bound_bytes(
    encoded: str,
    expected_sha256: str,
    *,
    label: str,
    max_bytes: int = MAX_RECOVERY_SNAPSHOT_BYTES,
) -> bytes:
    if len(encoded) > ((max_bytes + 2) // 3) * 4:
        raise AssetLifecycleError(f"recovery journal {label} is too large")
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as error:
        raise AssetLifecycleError(f"recovery journal {label} is invalid") from error
    if len(payload) > max_bytes:
        raise AssetLifecycleError(f"recovery journal {label} is too large")
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
    with _held_parent_directory(source) as (source_parent, source_name):
        source_metadata = os.stat(
            source_name,
            dir_fd=source_parent,
            follow_symlinks=False,
        )
        if not stat.S_ISREG(source_metadata.st_mode) or source_metadata.st_nlink != 1:
            raise AssetLifecycleError("asset move source is unsafe")
        with _held_parent_directory(destination) as (
            destination_parent,
            destination_name,
        ):
            os.rename(
                source_name,
                destination_name,
                src_dir_fd=source_parent,
                dst_dir_fd=destination_parent,
            )
            os.fsync(destination_parent)
            if source_parent != destination_parent:
                os.fsync(source_parent)


def _durable_unlink(path: Path) -> None:
    with _held_parent_directory(path) as (parent_descriptor, name):
        try:
            metadata = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise AssetLifecycleError("durable unlink target is unsafe")
            os.unlink(name, dir_fd=parent_descriptor)
        except FileNotFoundError:
            return
        os.fsync(parent_descriptor)


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


def _registry_path(catalog: AssetCatalog) -> Path:
    return _recovery_root(catalog, create=True) / TRANSACTION_REGISTRY_FILENAME


def _journal_plan_payload(journal: AssetReviewRecoveryJournal) -> dict[str, object]:
    phase_fields = {
        "audit_phase",
        "move_phase",
        "rollback_audit_phase",
        "rollback_move_phase",
    }
    return {
        "version": journal.version,
        "transaction_id": journal.transaction_id,
        "created_at": journal.created_at,
        "catalog_id": journal.catalog_id,
        "catalog_root": journal.catalog_root,
        "run_id": journal.run_id,
        "manifest_path": journal.manifest_path,
        "original_manifest_bytes_b64": journal.original_manifest_bytes_b64,
        "original_manifest_sha256": journal.original_manifest_sha256,
        "target_manifest_bytes_b64": journal.target_manifest_bytes_b64,
        "target_manifest_sha256": journal.target_manifest_sha256,
        "assets": [
            {
                key: value
                for key, value in record.model_dump(mode="json").items()
                if key not in phase_fields
            }
            for record in journal.assets
        ],
    }


def _journal_plan_sha256(journal: AssetReviewRecoveryJournal) -> str:
    payload = json.dumps(
        _journal_plan_payload(journal),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _bytes_digest(payload)


def _new_registry(catalog: AssetCatalog) -> TransactionRegistry:
    return TransactionRegistry(
        version=TRANSACTION_REGISTRY_VERSION,
        catalog_id=catalog.catalog_id,
        catalog_root=str(_require_directory_without_symlinks(catalog.root, label="catalog root")),
        run_id=catalog.run_id,
    )


def _load_registry(catalog: AssetCatalog, *, create: bool) -> TransactionRegistry:
    path = _registry_path(catalog)
    if not path.exists():
        registry = _new_registry(catalog)
        if create:
            _atomic_write_json(path, registry.model_dump(mode="json"))
        return registry
    try:
        registry = TransactionRegistry.model_validate(
            _read_journal_file(path), strict=True
        )
    except (ValidationError, AssetLifecycleError, TypeError, ValueError) as error:
        raise AssetLifecycleError("asset review transaction registry is invalid") from error
    expected_root = str(_require_directory_without_symlinks(catalog.root, label="catalog root"))
    if (
        registry.catalog_id != catalog.catalog_id
        or registry.catalog_root != expected_root
        or registry.run_id != catalog.run_id
    ):
        raise AssetLifecycleError("asset review transaction registry binding is invalid")
    return registry


def _write_registry(catalog: AssetCatalog, registry: TransactionRegistry) -> None:
    _atomic_write_json(_registry_path(catalog), registry.model_dump(mode="json"))


def _registry_prepare(
    catalog: AssetCatalog,
    journal: AssetReviewRecoveryJournal,
) -> None:
    registry = _load_registry(catalog, create=True)
    if journal.transaction_id in registry.transactions:
        raise AssetLifecycleError("asset review transaction ID was already used")
    registry.transactions[journal.transaction_id] = TransactionRegistryEntry(
        plan_sha256=journal.plan_sha256,
        state="prepared",
        created_at=journal.created_at,
    )
    _write_registry(catalog, registry)


def _registry_entry(
    catalog: AssetCatalog,
    journal: AssetReviewRecoveryJournal,
) -> TransactionRegistryEntry:
    registry = _load_registry(catalog, create=False)
    entry = registry.transactions.get(journal.transaction_id)
    if entry is None or entry.plan_sha256 != journal.plan_sha256:
        raise AssetLifecycleError("recovery journal transaction registry binding is invalid")
    try:
        created_at = datetime.fromisoformat(entry.created_at)
        journal_created_at = datetime.fromisoformat(journal.created_at)
    except ValueError as error:
        raise AssetLifecycleError("recovery journal transaction timestamp is invalid") from error
    now = datetime.now(UTC)
    if (
        entry.created_at != journal.created_at
        or created_at > now
        or journal_created_at > now
        or (now - created_at).total_seconds() > MAX_TRANSACTION_AGE_SECONDS
    ):
        raise AssetLifecycleError("recovery journal transaction is stale or invalid")
    return entry


def _registry_set_state(
    catalog: AssetCatalog,
    journal: AssetReviewRecoveryJournal,
    state: Literal["committed", "aborted"],
) -> None:
    registry = _load_registry(catalog, create=False)
    entry = registry.transactions.get(journal.transaction_id)
    if entry is None or entry.plan_sha256 != journal.plan_sha256:
        raise AssetLifecycleError("asset review transaction registry binding is invalid")
    if entry.state == state:
        return
    if entry.state != "prepared":
        raise AssetLifecycleError("asset review transaction state transition is invalid")
    entry.state = state
    _write_registry(catalog, registry)


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
    # Every caller holds catalog_review_lock; this CAS is the only manifest writer.
    current = manifest_path.read_bytes()
    target_sha256 = _bytes_digest(target_bytes)
    if _bytes_digest(current) == target_sha256:
        return
    if _bytes_digest(current) != expected_sha256:
        raise AssetLifecycleError(
            "catalog manifest changed after batch snapshot; recovery refused to overwrite it"
        )
    _atomic_write_bytes(manifest_path, target_bytes)


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
        if (
            before.st_nlink != 1
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size > MAX_RECOVERY_FILE_BYTES
        ):
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
        total = 0
        while chunk := os.read(descriptor, min(64 * 1024, MAX_RECOVERY_FILE_BYTES + 1 - total)):
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_RECOVERY_FILE_BYTES:
                raise AssetLifecycleError("recovery journal file is too large")
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
        decoded_total = len(original_manifest) + len(target_manifest)
        original_manifest_payload = json.loads(original_manifest.decode("utf-8"))
        target_manifest_payload = json.loads(target_manifest.decode("utf-8"))
        for manifest in (original_manifest_payload, target_manifest_payload):
            if not isinstance(manifest, dict) or manifest.get("catalog_id") != catalog.catalog_id:
                raise AssetLifecycleError("recovery journal catalog binding is invalid")
        original_assets = original_manifest_payload.get("assets")
        target_assets = target_manifest_payload.get("assets")
        if not isinstance(original_assets, list) or not isinstance(target_assets, list):
            raise AssetLifecycleError("recovery journal manifest assets are invalid")
        original_without_assets = {**original_manifest_payload, "assets": []}
        target_without_assets = {**target_manifest_payload, "assets": []}
        if original_without_assets != target_without_assets:
            raise AssetLifecycleError("recovery journal manifest plan is invalid")

        incoming_root = _require_directory_without_symlinks(
            catalog.incoming_root,
            label="incoming root",
        )
        active_root = Path(os.path.abspath(catalog.active_root))
        if active_root.exists() or active_root.is_symlink():
            active_root = _require_directory_without_symlinks(
                active_root,
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
            decoded_total += len(original_audit_bytes) + len(target_audit_bytes)
            if decoded_total > MAX_RECOVERY_TOTAL_SNAPSHOT_BYTES:
                raise AssetLifecycleError("recovery journal snapshots are too large")
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
            destination = Path(os.path.abspath(record.destination))
            if not destination.is_relative_to(active_root):
                raise AssetLifecycleError(
                    "recovery journal destination path escapes its trusted root"
                )
            if record.disposition == "approved" or destination.parent.exists():
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
        expected_additions = []
        for record in journal.assets:
            if record.disposition != "approved":
                continue
            target_audit = PendingAuditRecord.model_validate_json(
                _decode_bound_bytes(
                    record.target_audit_bytes_b64,
                    record.target_audit_sha256,
                    label="target audit snapshot",
                ),
                strict=True,
            )
            expected_additions.append(
                approved_manifest_item(
                    target_audit,
                    Path(record.destination),
                    safety_review_decisions=target_audit.safety_review_decisions or {},
                    safety_reviewed_at=str(target_audit.safety_reviewed_at),
                    review_disposition=str(target_audit.review_disposition),
                    catalog_root=catalog_root,
                )
            )
        if (
            target_assets[: len(original_assets)] != original_assets
            or target_assets[len(original_assets) :] != expected_additions
        ):
            raise AssetLifecycleError("recovery journal manifest operations are invalid")
        if _journal_plan_sha256(journal) != journal.plan_sha256:
            raise AssetLifecycleError("recovery journal plan hash is invalid")
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
        registry_entry = _registry_entry(catalog, journal)
        if registry_entry.state in {"committed", "aborted"}:
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
        _registry_set_state(catalog, journal, "aborted")
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
    has_new_approval = any(
        disposition == "approved"
        and canonical_by_id[pending_id].review_status == "pending"
        for pending_id, (disposition, _safety) in normalized.items()
    )
    if has_new_approval and not active_root.exists():
        _durable_mkdir(active_root, root=catalog_root)
    if active_root.exists() or active_root.is_symlink():
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
        if disposition == "approved":
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
    created_at = datetime.now(UTC).isoformat()
    journal = AssetReviewRecoveryJournal(
        version=RECOVERY_JOURNAL_VERSION,
        transaction_id=transaction_id,
        created_at=created_at,
        plan_sha256="0" * 64,
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
    journal.plan_sha256 = _journal_plan_sha256(journal)
    journal_path = _journal_path(catalog, transaction_id)
    _registry_prepare(catalog, journal)
    _crash_point("transaction.registered")
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
            if _payload_value(item, "_require_pending") is True and candidate.review_status != "pending":
                raise AssetLifecycleError("only pending assets can be reviewed")
            caller_audit = _payload_value(item, "_caller_audit_record")
            if caller_audit is not None and caller_audit != candidate.audit_record():
                raise AssetLifecycleError("caller does not match canonical pending audit")
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
                try:
                    _registry_set_state(catalog, journal, "aborted")
                    _durable_unlink(journal_path)
                except Exception as cleanup_error:
                    journal.state = "needs_recovery"
                    journal.rollback_errors = [f"complete rollback cleanup: {cleanup_error}"]
                    try:
                        _write_recovery_journal(journal_path, journal)
                    except Exception as journal_error:
                        original_error.add_note(
                            f"asset review cleanup journal failed: {journal_error}"
                        )
                    original_error.add_note(
                        f"asset review rollback cleanup incomplete: {cleanup_error}"
                    )
            raise
        _registry_set_state(catalog, journal, "committed")
        _crash_point("transaction.commit_registered")
        journal.state = "committed"
        _write_recovery_journal(journal_path, journal)
        _crash_point("transaction.committed")
        _durable_unlink(journal_path)
        return BatchAssetReviewResult(any_rejected, finalized)
