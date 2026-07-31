from __future__ import annotations

import hashlib
import fcntl
import json
import os
import re
import stat
import tempfile
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Literal

from PIL import Image

from src.schemas.assets import (
    AssetManifest,
    AssetManifestItem,
    AssetRequirement,
    AssetResolutionResult,
    AssetSearchReport,
    AssetTransactionEvidence,
    ProviderSearchReport,
    UnresolvedOptionalAsset,
)
from src.schemas.visual_director import AssetDirective
from src.schemas.visual_plan import VisualPlan
from src.visual_ai.protocols import (
    GeneratedImage,
    ImageGenerationProvider,
    ImageGenerationRequest,
)
from src.visual_design.model_retry import VisualProductionInterrupted

from .catalog import AssetCatalog, AssetEntry
from .eligibility import entry_satisfies_requirement
from .lifecycle import (
    PendingAsset,
    list_pending_assets,
    write_pending_audit,
)
from .providers import (
    ExternalAssetCandidate,
    candidate_urls_are_allowed,
    structured_query,
)


MAX_IMAGE_PIXELS = 40_000_000
MAX_DOWNLOAD_ATTEMPTS = 3


class AssetResolutionError(RuntimeError):
    """Raised when a visual-plan slot cannot be resolved locally."""

    def __init__(
        self, message: str, *, search_report: AssetSearchReport | None = None
    ) -> None:
        super().__init__(message)
        self.search_report = search_report


def requirement_fingerprint(requirement: AssetRequirement) -> str:
    """Return a stable identity for every resolution-relevant requirement field."""

    payload = requirement.model_dump(mode="json")
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def eligible(entry: AssetEntry, requirement: AssetRequirement) -> bool:
    """Return whether an entry is a production-safe exact local match."""

    return entry_satisfies_requirement(entry, requirement, mode="exact")


def _has_catalog_integrity(entry: AssetEntry, catalog: AssetCatalog) -> bool:
    try:
        path = entry.path.resolve()
        active_root = catalog.active_root.resolve()
        if not path.is_relative_to(active_root):
            return False
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return False
    return actual_hash == entry.sha256


def _last_used_timestamp(catalog: AssetCatalog, asset_id: str) -> float:
    value = catalog.last_used_at.get(asset_id)
    if value is None:
        return float("-inf")
    if not isinstance(value, datetime):
        raise AssetResolutionError(
            f"last_used_at for {asset_id!r} must be a datetime"
        )
    return value.timestamp()


def _rank_key(
    entry: AssetEntry,
    requirement: AssetRequirement,
    catalog: AssetCatalog,
) -> tuple[int, int, int, int, float, str]:
    entry_tags = set(entry.tags)
    return (
        -int(entry.role == requirement.role),
        -len(entry_tags.intersection(requirement.context_tags)),
        -int(
            requirement.orientation != "any"
            and entry.orientation == requirement.orientation
        ),
        -len(entry_tags.intersection(requirement.palette_tags)),
        _last_used_timestamp(catalog, entry.asset_id),
        entry.asset_id,
    )


def _select_exact(
    requirement: AssetRequirement,
    catalog: AssetCatalog,
) -> AssetEntry | None:
    candidates = [
        entry
        for entry in catalog.entries
        if entry.asset_id not in catalog.recent_asset_ids
        and eligible(entry, requirement)
        and _has_catalog_integrity(entry, catalog)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda entry: _rank_key(entry, requirement, catalog))


def _select_explicit_fallback(
    requirement: AssetRequirement,
    catalog: AssetCatalog,
) -> AssetEntry | None:
    entries_by_id = {entry.asset_id: entry for entry in catalog.entries}
    for asset_id in requirement.fallback_asset_ids:
        entry = entries_by_id.get(asset_id)
        if (
            entry is not None
            and entry.asset_id not in catalog.recent_asset_ids
            and entry_satisfies_requirement(
                entry,
                requirement,
                mode="fallback",
                catalog_entries=catalog.entries,
                authorizer_integrity=lambda candidate: _has_catalog_integrity(
                    candidate,
                    catalog,
                ),
            )
            and _has_catalog_integrity(entry, catalog)
        ):
            return entry
    return None


def _manifest_item(
    requirement: AssetRequirement,
    entry: AssetEntry,
    *,
    status: Literal["active", "fallback"],
) -> AssetManifestItem:
    provenance = entry.provenance
    return AssetManifestItem(
        slot_id=requirement.slot_id,
        role=requirement.role,
        page_archetype=requirement.page_archetype,
        status=status,
        path=str(entry.path),
        asset_id=entry.asset_id,
        source_type=provenance.source_type if provenance else "local",
        provider=provenance.provider if provenance else None,
        provider_asset_id=provenance.provider_asset_id if provenance else None,
        source_url=provenance.source_url if provenance else None,
        source_file_url=provenance.source_file_url if provenance else None,
        author=provenance.author if provenance else None,
        provider_attribution=(
            dict(provenance.provider_attribution) if provenance else {}
        ),
        license=entry.license,
        license_snapshot=provenance.license_snapshot if provenance else None,
        license_snapshot_sha256=(
            provenance.license_snapshot_sha256 if provenance else None
        ),
        license_terms_url=provenance.license_terms_url if provenance else None,
        width=entry.width,
        height=entry.height,
        sha256=entry.sha256,
        run_id=provenance.run_id if provenance else None,
        acquired_at=provenance.acquired_at if provenance else None,
        average_hash=provenance.average_hash if provenance else None,
        requirement_fingerprint=(
            provenance.requirement_fingerprint if provenance else None
        ),
        unresolved_safety_checks=(
            list(provenance.unresolved_safety_checks) if provenance else []
        ),
        safety_review_decisions=(
            dict(provenance.safety_review_decisions) if provenance else {}
        ),
        safety_reviewed_at=(
            provenance.safety_reviewed_at if provenance else None
        ),
        review_status="approved" if provenance else None,
        review_disposition=(provenance.review_disposition if provenance else None),
    )


def _external_eligible(
    candidate: ExternalAssetCandidate, requirement: AssetRequirement
) -> bool:
    role_evidence = set(candidate.score_tags)
    role_terms = set(requirement.role.replace("_", " ").split())
    role_compatible = candidate.role == requirement.role or bool(
        role_evidence.intersection(role_terms | set(requirement.context_tags))
    )
    return (
        role_compatible
        and candidate.width >= requirement.min_width
        and candidate.height >= requirement.min_height
        and (
            requirement.orientation == "any"
            or candidate.orientation == requirement.orientation
        )
        and bool(candidate.provider)
        and bool(candidate.provider_asset_id)
        and bool(candidate.author)
        and candidate.source_url.startswith("https://")
        and candidate.source_file_url.startswith("https://")
        and bool(candidate.license)
        and bool(candidate.license_snapshot)
        and bool(candidate.license_terms_url)
        and not candidate.has_watermark
        and not candidate.has_logo
        and not candidate.has_text
        and not candidate.recognizable_face
        and candidate.allowed_for_publishing is not False
    )


def _external_rank_key(
    candidate: ExternalAssetCandidate, requirement: AssetRequirement
) -> tuple[int, int, int, int, str, str]:
    score_tags = set(candidate.score_tags)
    palette_tags = set(candidate.palette_tags)
    return (
        -len(score_tags.intersection(requirement.context_tags)),
        -int(
            requirement.orientation != "any"
            and candidate.orientation == requirement.orientation
        ),
        -len(palette_tags.intersection(requirement.palette_tags)),
        -(candidate.width * candidate.height),
        candidate.provider_asset_id,
        candidate.source_url,
    )


def _deduplicate_candidates(
    candidates: list[ExternalAssetCandidate],
) -> list[ExternalAssetCandidate]:
    result: list[ExternalAssetCandidate] = []
    seen_provider_ids: set[tuple[str, str]] = set()
    seen_source_urls: set[str] = set()
    for candidate in candidates:
        provider_id = (candidate.provider, candidate.provider_asset_id)
        if provider_id in seen_provider_ids or candidate.source_url in seen_source_urls:
            continue
        seen_provider_ids.add(provider_id)
        seen_source_urls.add(candidate.source_url)
        result.append(candidate)
    return result


def _normalize_image(raw: bytes) -> tuple[bytes, str, int, int, str]:
    try:
        with Image.open(BytesIO(raw)) as source:
            width, height = source.size
            if width * height > MAX_IMAGE_PIXELS:
                raise AssetResolutionError("provider image exceeds pixel limit")
            source.load()
            has_alpha = "A" in source.getbands() or "transparency" in source.info
            normalized = source.convert("RGBA" if has_alpha else "RGB")
    except (OSError, ValueError) as error:
        raise AssetResolutionError("provider returned an invalid image") from error
    output = BytesIO()
    if has_alpha:
        normalized.save(output, format="PNG", optimize=True)
        extension = ".png"
    else:
        normalized.save(output, format="WEBP", lossless=True, method=6)
        extension = ".webp"
    return output.getvalue(), extension, width, height, _average_hash(normalized)


def _average_hash(image: Image.Image) -> str:
    grayscale = image.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
    pixels = list(grayscale.tobytes())
    average = sum(pixels) / len(pixels)
    bits = "".join("1" if pixel >= average else "0" for pixel in pixels)
    return f"{int(bits, 2):016x}"


def _hash_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def _has_near_duplicate(average_hash: str, known_hashes: set[str]) -> bool:
    return any(_hash_distance(average_hash, known) <= 5 for known in known_hashes)


def _pixel_orientation(width: int, height: int) -> str:
    if width == height:
        return "square"
    if width > height:
        return "landscape"
    return "portrait"


def _existing_audit_keys(root: Path) -> tuple[set[tuple[str, str]], set[str], set[str], set[str]]:
    provider_ids: set[tuple[str, str]] = set()
    source_urls: set[str] = set()
    sha256_values: set[str] = set()
    average_hashes: set[str] = set()
    audit_root = root / "incoming" / "external"
    if not audit_root.exists():
        return provider_ids, source_urls, sha256_values, average_hashes
    for audit_path in audit_root.glob("*/*.json"):
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            provider = audit.get("provider")
            asset_id = audit.get("provider_asset_id")
            source_url = audit.get("source_url")
            sha256 = audit.get("sha256")
            average_hash = audit.get("average_hash")
            if isinstance(provider, str) and isinstance(asset_id, str):
                provider_ids.add((provider, asset_id))
            if isinstance(source_url, str):
                source_urls.add(source_url)
            if isinstance(sha256, str):
                sha256_values.add(sha256)
            if isinstance(average_hash, str):
                average_hashes.add(average_hash)
        except (OSError, ValueError, TypeError):
            continue
    return provider_ids, source_urls, sha256_values, average_hashes


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    content = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _atomic_write_bytes(path, content)


def _persist_license_snapshot(
    catalog: AssetCatalog, candidate: ExternalAssetCandidate
) -> tuple[str, str]:
    if not candidate.license_terms_url or not candidate.license_snapshot.strip():
        raise AssetResolutionError("provider candidate has no license terms summary")
    relative_path = Path("licenses") / (
        f"{_safe_component(candidate.provider)}-terms-summary-v1.txt"
    )
    path = (catalog.root / relative_path).resolve()
    root = catalog.root.resolve()
    if not path.is_relative_to(root):
        raise AssetResolutionError("license snapshot path escapes catalog")
    content = candidate.license_snapshot.encode("utf-8")
    if path.exists():
        if path.read_bytes() != content:
            raise AssetResolutionError("license terms summary version changed")
    else:
        _atomic_write_bytes(path, content)
    return relative_path.as_posix(), hashlib.sha256(content).hexdigest()


def _safe_component(value: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-.")
    return sanitized or "asset"


def _attempt_ledger_path(
    catalog: AssetCatalog, requirement: AssetRequirement, fingerprint: str
) -> Path:
    incoming_root = catalog.incoming_root.resolve()
    ledger_root = (incoming_root / ".attempt-ledgers").resolve()
    if not ledger_root.is_relative_to(incoming_root):
        raise AssetResolutionError("attempt ledger directory escapes incoming root")
    ledger_root.mkdir(parents=True, exist_ok=True)
    ledger_root = ledger_root.resolve()
    if not ledger_root.is_relative_to(incoming_root):
        raise AssetResolutionError("attempt ledger directory escapes incoming root")
    ledger_path = ledger_root / (
        f"attempts-{_safe_component(requirement.slot_id)}-{fingerprint}.json"
    )
    if (
        not ledger_path.resolve().is_relative_to(ledger_root)
        or ledger_path.resolve().parent != ledger_root
    ):
        raise AssetResolutionError("attempt ledger path escapes incoming root")
    return ledger_path


@contextmanager
def _resolution_lock(
    catalog: AssetCatalog,
    requirement: AssetRequirement,
    fingerprint: str,
    held_inodes: set[tuple[int, int]],
):
    incoming_root = catalog.incoming_root.resolve()
    lock_root = (incoming_root / ".resolution-locks").resolve()
    if not lock_root.is_relative_to(incoming_root):
        raise AssetResolutionError("resolution lock directory escapes incoming root")
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_root = lock_root.resolve()
    if not lock_root.is_relative_to(incoming_root):
        raise AssetResolutionError("resolution lock directory escapes incoming root")
    identity = f"{requirement.slot_id}\0{fingerprint}"
    lock_name = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    lock_path = lock_root / f"{lock_name}.lock"
    if not lock_path.resolve().is_relative_to(lock_root):
        raise AssetResolutionError("resolution lock path escapes incoming root")
    if lock_path.is_symlink() or lock_path.resolve() != lock_path:
        raise AssetResolutionError("resolution lock symlink is not allowed")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(lock_path, flags, 0o600)
        descriptor_stat = os.fstat(descriptor)
        path_stat = os.lstat(lock_path)
        if (
            stat.S_ISLNK(path_stat.st_mode)
            or (descriptor_stat.st_dev, descriptor_stat.st_ino)
            != (path_stat.st_dev, path_stat.st_ino)
        ):
            raise AssetResolutionError(
                "resolution lock symlink is not allowed"
            )
        if descriptor_stat.st_nlink != 1 or path_stat.st_nlink != 1:
            raise AssetResolutionError(
                "resolution lock hard-link alias is not allowed"
            )
        inode_identity = (descriptor_stat.st_dev, descriptor_stat.st_ino)
        if inode_identity in held_inodes:
            raise AssetResolutionError(
                "resolution lock inode alias is not allowed"
            )
        lock_handle = os.fdopen(descriptor, "a+b")
        descriptor = None
    except OSError as error:
        raise AssetResolutionError(
            "resolution lock symlink or unsafe path is not allowed"
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    with lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            try:
                locked_descriptor_stat = os.fstat(lock_handle.fileno())
                locked_path_stat = os.lstat(lock_path)
            except OSError as error:
                raise AssetResolutionError(
                    "resolution lock path changed while waiting"
                ) from error
            if (
                stat.S_ISLNK(locked_path_stat.st_mode)
                or lock_path.resolve() != lock_path
                or locked_descriptor_stat.st_nlink != 1
                or locked_path_stat.st_nlink != 1
                or (locked_descriptor_stat.st_dev, locked_descriptor_stat.st_ino)
                != (locked_path_stat.st_dev, locked_path_stat.st_ino)
                or (locked_descriptor_stat.st_dev, locked_descriptor_stat.st_ino)
                != inode_identity
            ):
                raise AssetResolutionError(
                    "resolution lock path changed while waiting"
                )
            held_inodes.add(inode_identity)
            try:
                yield
            finally:
                held_inodes.discard(inode_identity)
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _reserve_download_attempt(
    catalog: AssetCatalog,
    requirement: AssetRequirement,
    fingerprint: str,
    candidate: ExternalAssetCandidate,
) -> tuple[Literal["reserved", "duplicate", "exhausted"], int | None]:
    ledger_path = _attempt_ledger_path(catalog, requirement, fingerprint)
    lock_path = ledger_path.with_suffix(f"{ledger_path.suffix}.lock")
    ledger_root = ledger_path.parent.resolve()
    if (
        not ledger_root.is_relative_to(catalog.incoming_root.resolve())
        or not lock_path.resolve().is_relative_to(ledger_root)
    ):
        raise AssetResolutionError("attempt ledger path escapes incoming root")
    with lock_path.open("a+b") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            if ledger_path.exists():
                try:
                    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError) as error:
                    raise AssetResolutionError("download attempt ledger is invalid") from error
                if (
                    not isinstance(ledger, dict)
                    or set(ledger) != {"slot_id", "requirement_fingerprint", "attempts"}
                    or ledger.get("slot_id") != requirement.slot_id
                    or ledger.get("requirement_fingerprint") != fingerprint
                    or not isinstance(ledger.get("attempts"), list)
                ):
                    raise AssetResolutionError("download attempt ledger is invalid")
            else:
                ledger = {
                    "slot_id": requirement.slot_id,
                    "requirement_fingerprint": fingerprint,
                    "attempts": [],
                }
            attempts = ledger["attempts"]
            if any(
                (
                    item.get("provider") == candidate.provider
                    and item.get("provider_asset_id")
                    == candidate.provider_asset_id
                )
                or item.get("source_url") == candidate.source_url
                for item in attempts
                if isinstance(item, dict)
            ):
                return "duplicate", None
            if len(attempts) >= MAX_DOWNLOAD_ATTEMPTS:
                return "exhausted", None
            attempt_number = len(attempts) + 1
            attempts.append(
                {
                    "attempt_number": attempt_number,
                    "provider": candidate.provider,
                    "provider_asset_id": candidate.provider_asset_id,
                    "source_url": candidate.source_url,
                    "attempted_at": datetime.now(UTC).isoformat(),
                }
            )
            _atomic_write_json(ledger_path, ledger)
            return "reserved", attempt_number
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _download_pending_candidates(
    requirement: AssetRequirement,
    catalog: AssetCatalog,
    ranked: list[ExternalAssetCandidate],
    providers_by_candidate: dict[int, object],
) -> tuple[list[PendingAsset], dict[str, list[str]]]:
    fingerprint = requirement_fingerprint(requirement)
    existing_ids, existing_urls, existing_sha256, existing_hashes = _existing_audit_keys(
        catalog.root
    )
    pending_assets: list[PendingAsset] = []
    download_errors: dict[str, list[str]] = {}
    available = [
        (candidate_rank, candidate)
        for candidate_rank, candidate in enumerate(ranked, start=1)
        if (candidate.provider, candidate.provider_asset_id) not in existing_ids
        and candidate.source_url not in existing_urls
    ]
    for candidate_rank, candidate in available:
        if not candidate_urls_are_allowed(
            candidate.provider,
            source_url=candidate.source_url,
            source_file_url=candidate.source_file_url,
            license_terms_url=candidate.license_terms_url,
        ):
            download_errors.setdefault(candidate.provider, []).append(
                f"{candidate.provider_asset_id}: provider URLs are not allowlisted"
            )
            continue
        reservation, attempt_number = _reserve_download_attempt(
            catalog, requirement, fingerprint, candidate
        )
        if reservation == "duplicate":
            continue
        if reservation == "exhausted":
            break
        assert attempt_number is not None
        candidate_key = (candidate.provider, candidate.provider_asset_id)
        provider = providers_by_candidate[id(candidate)]
        try:
            provider.record_download(candidate)
            normalized, extension, width, height, average_hash = _normalize_image(
                provider.download(candidate)
            )
        except Exception as error:
            download_errors.setdefault(candidate.provider, []).append(
                f"{candidate.provider_asset_id}: {error}"
            )
            continue
        if (
            width < requirement.min_width
            or height < requirement.min_height
            or (
                requirement.orientation != "any"
                and _pixel_orientation(width, height) != requirement.orientation
            )
        ):
            download_errors.setdefault(candidate.provider, []).append(
                f"{candidate.provider_asset_id}: downloaded pixels fail dimensions/orientation"
            )
            continue
        sha256 = hashlib.sha256(normalized).hexdigest()
        if sha256 in existing_sha256 or _has_near_duplicate(
            average_hash, existing_hashes
        ):
            continue
        basename = "-".join(
            (
                _safe_component(requirement.slot_id),
                _safe_component(candidate.provider),
                _safe_component(candidate.provider_asset_id),
            )
        )
        path = catalog.incoming_root / f"{basename}{extension}"
        metadata_path = catalog.incoming_root / f"{basename}.json"
        tags = tuple(
            dict.fromkeys(
                (*candidate.score_tags, *candidate.palette_tags)
            )
        ) or ("unclassified",)
        license_snapshot, license_snapshot_sha256 = _persist_license_snapshot(
            catalog, candidate
        )
        pending = PendingAsset(
            pending_id=f"{catalog.run_id}-{basename}",
            slot_id=requirement.slot_id,
            candidate_rank=candidate_rank,
            path=path,
            metadata_path=metadata_path,
            provider=candidate.provider,
            provider_asset_id=candidate.provider_asset_id,
            author=candidate.author,
            source_url=candidate.source_url,
            source_file_url=candidate.source_file_url,
            role=requirement.role,
            page_archetype=requirement.page_archetype,
            width=width,
            height=height,
            license=candidate.license,
            license_snapshot=license_snapshot,
            license_snapshot_sha256=license_snapshot_sha256,
            license_terms_url=candidate.license_terms_url,
            sha256=sha256,
            average_hash=average_hash,
            run_id=catalog.run_id,
            production_relative_path=Path("stock")
            / f"{_safe_component(candidate.provider)}-{_safe_component(candidate.provider_asset_id)}{extension}",
            tags=tags,
            fallback_roles=(requirement.role,),
            unresolved_safety_checks=tuple(
                field_name
                for field_name in (
                    "has_watermark",
                    "has_logo",
                    "has_text",
                    "recognizable_face",
                    "allowed_for_publishing",
                )
                if getattr(candidate, field_name) is None
            ),
            requirement_fingerprint=fingerprint,
            attempt_number=attempt_number,
            provider_attribution=candidate.provider_attribution,
        )
        _atomic_write_bytes(path, normalized)
        try:
            write_pending_audit(pending)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        pending_assets.append(pending)
        existing_ids.add(candidate_key)
        existing_urls.add(candidate.source_url)
        existing_sha256.add(sha256)
        existing_hashes.add(average_hash)
    return pending_assets, download_errors


def _pending_manifest_item(
    requirement: AssetRequirement, pending: PendingAsset
) -> AssetManifestItem:
    return AssetManifestItem(
        slot_id=requirement.slot_id,
        role=requirement.role,
        page_archetype=requirement.page_archetype,
        status="pending_external",
        path=str(pending.path),
        source_type="external",
        provider=pending.provider,
        provider_asset_id=pending.provider_asset_id,
        source_url=pending.source_url,
        source_file_url=pending.source_file_url,
        author=pending.author,
        license=pending.license,
        license_snapshot=pending.license_snapshot,
        license_snapshot_sha256=pending.license_snapshot_sha256,
        license_terms_url=pending.license_terms_url,
        width=pending.width,
        height=pending.height,
        sha256=pending.sha256,
        pending_id=pending.pending_id,
        metadata_path=str(pending.metadata_path),
        run_id=pending.run_id,
        candidate_rank=pending.candidate_rank,
        requirement_fingerprint=pending.requirement_fingerprint,
        attempt_number=pending.attempt_number,
        unresolved_safety_checks=list(pending.unresolved_safety_checks),
    )


def _search_provider(
    provider: object,
    requirement: AssetRequirement,
    query: str,
) -> tuple[ProviderSearchReport, list[ExternalAssetCandidate]]:
    started_at = time.perf_counter()
    if getattr(provider, "enabled", True) is False:
        return (
            ProviderSearchReport(
                provider=provider.name,
                status="not_configured",
                query=query,
                elapsed_ms=(time.perf_counter() - started_at) * 1000,
            ),
            [],
        )
    try:
        results = provider.search(requirement)
    except Exception as error:
        return (
            ProviderSearchReport(
                provider=provider.name,
                status="failed",
                query=query,
                error=str(error),
                elapsed_ms=(time.perf_counter() - started_at) * 1000,
            ),
            [],
        )
    normalized_results = [
        result for result in results if isinstance(result, ExternalAssetCandidate)
    ]
    mismatched = [
        result
        for result in normalized_results
        if result.provider != provider.name
    ]
    if mismatched:
        return (
            ProviderSearchReport(
                provider=provider.name,
                status="failed",
                query=query,
                result_ids=[result.provider_asset_id for result in normalized_results],
                error="provider identity mismatch in normalized candidate",
                elapsed_ms=(time.perf_counter() - started_at) * 1000,
            ),
            [],
        )
    return (
        ProviderSearchReport(
            provider=provider.name,
            status="success",
            query=query,
            result_ids=[result.provider_asset_id for result in normalized_results],
            elapsed_ms=(time.perf_counter() - started_at) * 1000,
        ),
        normalized_results,
    )


def resolve_assets(visual_plan: VisualPlan, catalog: AssetCatalog) -> AssetManifest:
    """Serialize external resolution by run, slot, and requirement contract."""

    if not visual_plan.required_assets:
        return AssetManifest(
            items=[],
            search_report=AssetSearchReport(
                search_triggered=False,
                queries=[],
                provider_reports=[],
                selection_reasons={},
            ),
        )

    has_external_provider = any(
        isinstance(getattr(provider, "name", None), str)
        and callable(getattr(provider, "search", None))
        and callable(getattr(provider, "record_download", None))
        and callable(getattr(provider, "download", None))
        for provider in catalog.providers
    )
    requirements_needing_external = [
        requirement
        for requirement in visual_plan.required_assets
        if has_external_provider and _select_exact(requirement, catalog) is None
    ]
    lock_requirements = sorted(
        {
            (requirement.slot_id, requirement_fingerprint(requirement)): requirement
            for requirement in requirements_needing_external
        }.values(),
        key=lambda requirement: (
            requirement.slot_id,
            requirement_fingerprint(requirement),
        ),
    )
    with ExitStack() as stack:
        held_resolution_inodes: set[tuple[int, int]] = set()
        for requirement in lock_requirements:
            stack.enter_context(
                _resolution_lock(
                    catalog,
                    requirement,
                    requirement_fingerprint(requirement),
                    held_resolution_inodes,
                )
            )
        return _resolve_assets_unlocked(visual_plan, catalog)


def _resolve_assets_unlocked(
    visual_plan: VisualPlan, catalog: AssetCatalog
) -> AssetManifest:
    """Resolve local assets first, then audited external gaps, then fallbacks."""

    items: list[AssetManifestItem] = []
    selection_reasons: dict[str, str] = {}
    queries: list[str] = []
    provider_reports: list[ProviderSearchReport] = []
    search_triggered = False
    for requirement in visual_plan.required_assets:
        fingerprint = requirement_fingerprint(requirement)
        entry = _select_exact(requirement, catalog)
        if entry is not None:
            items.append(_manifest_item(requirement, entry, status="active"))
            selection_reasons[requirement.slot_id] = (
                f"selected eligible local exact match {entry.asset_id}"
            )
            continue

        resumed_pending = list_pending_assets(
            catalog,
            slot_id=requirement.slot_id,
            requirement_fingerprint=fingerprint,
        )
        if resumed_pending:
            items.append(_pending_manifest_item(requirement, resumed_pending[0]))
            selection_reasons[requirement.slot_id] = (
                f"resumed pending external candidate {resumed_pending[0].pending_id}"
            )
            continue

        valid_providers = [
            provider
            for provider in catalog.providers
            if isinstance(getattr(provider, "name", None), str)
            and callable(getattr(provider, "search", None))
            and callable(getattr(provider, "record_download", None))
            and callable(getattr(provider, "download", None))
        ]
        external_candidates: list[ExternalAssetCandidate] = []
        report_start = len(provider_reports)
        providers_by_candidate: dict[int, object] = {}
        if valid_providers:
            search_triggered = True
            query = structured_query(requirement)
            queries.append(query)
            with ThreadPoolExecutor(max_workers=len(valid_providers)) as executor:
                search_results = executor.map(
                    lambda provider: _search_provider(
                        provider, requirement, query
                    ),
                    valid_providers,
                )
                for provider, (report, normalized_results) in zip(
                    valid_providers, search_results
                ):
                    provider_reports.append(report)
                    external_candidates.extend(normalized_results)
                    providers_by_candidate.update(
                        {id(candidate): provider for candidate in normalized_results}
                    )
        ranked = sorted(
            (
                candidate
                for candidate in _deduplicate_candidates(external_candidates)
                if _external_eligible(candidate, requirement)
            ),
            key=lambda candidate: _external_rank_key(candidate, requirement),
        )
        pending, download_errors = _download_pending_candidates(
            requirement, catalog, ranked, providers_by_candidate
        )
        for index in range(report_start, len(provider_reports)):
            report = provider_reports[index]
            errors = download_errors.get(report.provider, [])
            if errors:
                provider_reports[index] = report.model_copy(
                    update={"download_errors": errors}
                )
        if pending:
            items.append(_pending_manifest_item(requirement, pending[0]))
            selection_reasons[requirement.slot_id] = (
                f"selected pending external candidate {pending[0].provider}:"
                f"{pending[0].provider_asset_id}"
            )
            continue

        fallback = _select_explicit_fallback(requirement, catalog)
        if fallback is not None:
            items.append(_manifest_item(requirement, fallback, status="fallback"))
            selection_reasons[requirement.slot_id] = (
                f"selected explicit local fallback {fallback.asset_id}"
            )
            continue

        search_report = AssetSearchReport(
            search_triggered=search_triggered,
            queries=queries,
            provider_reports=provider_reports,
            selection_reasons=selection_reasons,
        )
        raise AssetResolutionError(
            f"{requirement.slot_id}: no eligible asset or fallback",
            search_report=search_report,
        )

    return AssetManifest(
        items=items,
        search_report=AssetSearchReport(
            search_triggered=search_triggered,
            queries=queries,
            provider_reports=provider_reports,
            selection_reasons=selection_reasons,
        ),
    )


# ---------------------------------------------------------------------------
# Directive-first resolver (Task 7). The slot-based `resolve_assets` path
# above is retained only for import compatibility; it is non-functional under
# the directive-based `AssetManifestItem` contract and slated for deletion.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssetSafetyDecision:
    """Deterministic safety outcome for one resolved image candidate."""

    approved: bool
    unwanted_text: bool = False
    reason: str | None = None


class DefaultAssetSafetyChecker:
    """Deterministic raster/MIME/containment safety checks.

    Unwanted-visible-text detection is delegated to the injected checker in
    production; the default only fails closed on unreadable or non-regular
    images so generated/searched bytes cannot be marked approved unless they
    decode as a real raster.
    """

    def check(self, path: Path, directive: AssetDirective) -> AssetSafetyDecision:
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        descriptor: int | None = None
        try:
            before = path.lstat()
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
                return AssetSafetyDecision(
                    approved=False,
                    unwanted_text=False,
                    reason="image is not a regular non-symlink file",
                )
            descriptor = os.open(path, os.O_RDONLY | nofollow)
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                return AssetSafetyDecision(
                    approved=False,
                    unwanted_text=False,
                    reason="image identity changed during safety check",
                )
            try:
                with Image.open(path) as image:
                    image.verify()
            except (OSError, ValueError) as error:
                return AssetSafetyDecision(
                    approved=False,
                    unwanted_text=False,
                    reason=f"image raster decode failed: {error}",
                )
        except OSError as error:
            return AssetSafetyDecision(
                approved=False,
                unwanted_text=False,
                reason=f"image safety check failed: {error}",
            )
        finally:
            if descriptor is not None:
                os.close(descriptor)
        return AssetSafetyDecision(approved=True, unwanted_text=False)


def _directive_rejection_message(field_name: str) -> str:
    return f"candidate rejected: {field_name}"


def _candidate_meets_directive(
    candidate: ExternalAssetCandidate, directive: AssetDirective
) -> tuple[bool, str | None]:
    """Deterministic eligibility gate mirroring the legacy external contract."""

    if not candidate.provider or not candidate.provider_asset_id:
        return False, _directive_rejection_message("provider identity missing")
    if not isinstance(candidate.source_url, str) or not candidate.source_url.startswith("https://"):
        return False, _directive_rejection_message("source_url must be https")
    if not isinstance(candidate.source_file_url, str) or not candidate.source_file_url.startswith(
        "https://"
    ):
        return False, _directive_rejection_message("source_file_url must be https")
    if not candidate.license or not candidate.license.strip():
        return False, _directive_rejection_message("license is empty")
    if not candidate.license_snapshot or not candidate.license_snapshot.strip():
        return False, _directive_rejection_message("license_snapshot is empty")
    if not candidate.license_terms_url:
        return False, _directive_rejection_message("license_terms_url is missing")
    if candidate.width < directive.min_width or candidate.height < directive.min_height:
        return False, _directive_rejection_message("dimensions below directive minimum")
    if (
        directive.orientation != "any"
        and candidate.orientation != directive.orientation
    ):
        return False, _directive_rejection_message("orientation mismatch")
    if candidate.has_watermark is True:
        return False, _directive_rejection_message("watermark present")
    if candidate.has_logo is True:
        return False, _directive_rejection_message("logo present")
    if candidate.has_text is True:
        return False, _directive_rejection_message("text present")
    if candidate.recognizable_face is True:
        return False, _directive_rejection_message("recognizable face present")
    if candidate.allowed_for_publishing is False:
        return False, _directive_rejection_message("candidate disallowed for publishing")
    if not candidate_urls_are_allowed(
        candidate.provider,
        source_url=candidate.source_url,
        source_file_url=candidate.source_file_url,
        license_terms_url=candidate.license_terms_url,
    ):
        return False, _directive_rejection_message("provider URLs are not allowlisted")
    return True, None


def _pixel_orientation_local(width: int, height: int) -> str:
    if width == height:
        return "square"
    if width > height:
        return "landscape"
    return "portrait"


def _decode_raster(raw: bytes) -> tuple[bytes, str, int, int]:
    """Return (bytes, extension, width, height); raise on invalid rasters."""

    try:
        with Image.open(BytesIO(raw)) as source:
            width, height = source.size
            if width * height > MAX_IMAGE_PIXELS:
                raise AssetResolutionError("provider image exceeds pixel limit")
            source.load()
            has_alpha = "A" in source.getbands() or "transparency" in source.info
            normalized = source.convert("RGBA" if has_alpha else "RGB")
    except (OSError, ValueError) as error:
        raise AssetResolutionError("provider returned an invalid image") from error
    output = BytesIO()
    if has_alpha:
        normalized.save(output, format="PNG", optimize=True)
        extension = ".png"
    else:
        normalized.save(output, format="WEBP", lossless=True, method=6)
        extension = ".webp"
    return output.getvalue(), extension, width, height


def _nofollow_read(path: Path) -> tuple[bytes, tuple[int, int]]:
    """Read a regular non-symlink file via O_NOFOLLOW and return (bytes, identity)."""

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise AssetResolutionError("generated image is not a regular file")
        descriptor = os.open(path, os.O_RDONLY | nofollow)
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise AssetResolutionError("generated image identity changed during read")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks), (opened.st_dev, opened.st_ino)
    except OSError as error:
        raise AssetResolutionError("generated image is unreadable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _transaction_dir(transaction_root: Path, transaction_id: str) -> Path:
    root = Path(transaction_root).resolve()
    if not root.exists():
        root.mkdir(parents=True, exist_ok=True)
    directory = root / transaction_id
    if directory.exists() or directory.is_symlink():
        if not directory.is_dir() or directory.is_symlink():
            raise AssetResolutionError("transaction id collides with a non-directory")
    else:
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def _persist_recovery_journal(
    transaction_dir: Path,
    *,
    transaction_id: str,
    run_id: str,
    errors: tuple[str, ...],
) -> None:
    payload = {
        "status": "interrupted",
        "transaction_id": transaction_id,
        "run_id": run_id,
        "stage": "asset_resolver",
        "errors": list(errors),
        "written_at": datetime.now(UTC).isoformat(),
    }
    journal_path = transaction_dir / "recovery.json"
    content = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    ).encode("utf-8")
    _atomic_write_bytes(journal_path, content)


def _directive_search_query(directive: AssetDirective) -> str:
    raw_terms: list[str] = []
    if directive.query_or_prompt:
        raw_terms.extend(directive.query_or_prompt.replace("_", " ").split())
    terms: list[str] = []
    seen: set[str] = set()
    for raw in raw_terms:
        for term in re.findall(r"[a-z0-9-]+", str(raw).lower()):
            if term not in seen:
                seen.add(term)
                terms.append(term)
    return " ".join(terms) or directive.role.replace("_", " ")


def _generation_request(
    directive: AssetDirective, *, width: int, height: int
) -> ImageGenerationRequest:
    prompt = directive.query_or_prompt or directive.role.replace("_", " ")
    encoded = prompt.encode("utf-8")
    return ImageGenerationRequest(
        prompt=prompt,
        negative_constraints=tuple(directive.negative_constraints),
        width=width,
        height=height,
        prompt_sha256=hashlib.sha256(encoded).hexdigest(),
    )


def _resolve_via_search(
    directive: AssetDirective,
    *,
    search_provider: object,
    transaction_dir: Path,
    safety_checker: object,
    run_id: str,
    transaction_id: str,
) -> AssetManifestItem:
    name = getattr(search_provider, "name", "search")
    try:
        results = search_provider.search(directive)
    except Exception as error:
        raise AssetResolutionError(str(error) or "search provider failed") from error

    candidates = [result for result in results if isinstance(result, ExternalAssetCandidate)]
    rejection_reasons: list[str] = []
    selected: ExternalAssetCandidate | None = None
    for candidate in candidates:
        eligible, reason = _candidate_meets_directive(candidate, directive)
        if not eligible:
            if reason is not None:
                rejection_reasons.append(reason)
            continue
        selected = candidate
        break
    if selected is None:
        if rejection_reasons:
            raise AssetResolutionError("; ".join(rejection_reasons))
        raise AssetResolutionError("search provider returned no candidates")

    try:
        search_provider.record_download(selected)
        raw = search_provider.download(selected)
    except Exception as error:
        raise AssetResolutionError(
            f"search provider {name} download failed: {error}"
        ) from error

    normalized, extension, raster_width, raster_height = _decode_raster(raw)
    if (
        raster_width < directive.min_width
        or raster_height < directive.min_height
        or (
            directive.orientation != "any"
            and _pixel_orientation_local(raster_width, raster_height) != directive.orientation
        )
    ):
        raise AssetResolutionError("downloaded raster fails directive dimensions/orientation")

    sha256 = hashlib.sha256(normalized).hexdigest()
    asset_id = f"{selected.provider}-{selected.provider_asset_id}"
    relative_path = Path("search") / f"{_safe_component(directive.directive_id)}-{_safe_component(asset_id)}{extension}"
    destination = transaction_dir / relative_path
    if not destination.resolve().is_relative_to(transaction_dir.resolve()):
        raise AssetResolutionError("search asset destination escapes the transaction dir")
    _atomic_write_bytes(destination, normalized)

    decision = safety_checker.check(destination, directive)
    if not decision.approved:
        message = (
            "rejected: unwanted visible text"
            if decision.unwanted_text
            else f"rejected: {decision.reason or 'safety check failed'}"
        )
        raise AssetResolutionError(message)

    return AssetManifestItem(
        asset_id=asset_id,
        directive_id=directive.directive_id,
        page_id=directive.page_id,
        source_kind="search",
        provider=selected.provider,
        license=selected.license,
        local_path=str(destination),
        width=raster_width,
        height=raster_height,
        sha256=sha256,
        subject_focal_point=(0.5, 0.5),
        crop_guidance=directive.orientation,
        security_status="approved",
        human_decision="pending",
        run_id=run_id,
        transaction_id=transaction_id,
        internal_provenance={
            "provider": selected.provider,
            "source_url": selected.source_url,
            "author": selected.author,
        },
    )


def _resolve_via_generation(
    directive: AssetDirective,
    *,
    generation_provider: ImageGenerationProvider,
    transaction_dir: Path,
    safety_checker: object,
    run_id: str,
    transaction_id: str,
) -> AssetManifestItem:
    generation_dir = transaction_dir / "generated"
    generation_dir.mkdir(parents=True, exist_ok=True)
    request = _generation_request(
        directive,
        width=directive.min_width,
        height=directive.min_height,
    )
    try:
        generated = generation_provider.generate(request, generation_dir)
    except Exception as error:
        raise AssetResolutionError(f"generation provider failed: {error}") from error

    if not isinstance(generated, GeneratedImage):
        raise AssetResolutionError("generation provider returned a non-GeneratedImage result")

    generated_path = Path(generated.path)
    # Containment + no-follow: read actual bytes from the regular file only.
    raw, _identity = _nofollow_read(generated_path)
    try:
        resolved = generated_path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise AssetResolutionError("generated image path is unresolvable") from error
    transaction_resolved = transaction_dir.resolve()
    if not resolved.is_relative_to(transaction_resolved):
        raise AssetResolutionError("generated image escapes the transaction directory")

    # Re-decode to validate the raster and obtain authoritative dimensions.
    # The manifest hash is computed from the actual on-disk bytes (raw), not
    # from a re-encoded copy or the provider-reported digest, so the manifest
    # matches the bytes a downstream renderer will read.
    _validated, _extension, raster_width, raster_height = _decode_raster(raw)
    if (
        raster_width < directive.min_width
        or raster_height < directive.min_height
        or (
            directive.orientation != "any"
            and _pixel_orientation_local(raster_width, raster_height) != directive.orientation
        )
    ):
        raise AssetResolutionError("generated raster fails directive dimensions/orientation")

    sha256 = hashlib.sha256(raw).hexdigest()

    decision = safety_checker.check(generated_path, directive)
    if not decision.approved:
        message = (
            "rejected: unwanted visible text"
            if decision.unwanted_text
            else f"rejected: {decision.reason or 'safety check failed'}"
        )
        raise AssetResolutionError(message)

    provenance = dict(generated.internal_provenance)
    return AssetManifestItem(
        asset_id=f"generated-{directive.directive_id}",
        directive_id=directive.directive_id,
        page_id=directive.page_id,
        source_kind="generated",
        provider=generated.provider,
        license="internal-generated",
        local_path=str(generated_path),
        width=raster_width,
        height=raster_height,
        sha256=sha256,
        subject_focal_point=(0.5, 0.5),
        crop_guidance=directive.orientation,
        security_status="approved",
        human_decision="pending",
        run_id=run_id,
        transaction_id=transaction_id,
        internal_provenance=provenance,
    )


def _attempt_source(
    source: str,
    directive: AssetDirective,
    *,
    search_provider: object | None,
    generation_provider: object | None,
    transaction_dir: Path,
    safety_checker: object,
    run_id: str,
    transaction_id: str,
) -> AssetManifestItem:
    if source == "search":
        if search_provider is None:
            raise AssetResolutionError("search source requested without a search provider")
        return _resolve_via_search(
            directive,
            search_provider=search_provider,
            transaction_dir=transaction_dir,
            safety_checker=safety_checker,
            run_id=run_id,
            transaction_id=transaction_id,
        )
    if source == "generate":
        if generation_provider is None:
            raise AssetResolutionError("generate source requested without a generation provider")
        return _resolve_via_generation(
            directive,
            generation_provider=generation_provider,
            transaction_dir=transaction_dir,
            safety_checker=safety_checker,
            run_id=run_id,
            transaction_id=transaction_id,
        )
    raise AssetResolutionError(f"unsupported source kind: {source}")


def _preferred_then_fallback(
    directive: AssetDirective,
    *,
    search_provider: object | None,
    generation_provider: object | None,
    transaction_dir: Path,
    safety_checker: object,
    run_id: str,
    transaction_id: str,
) -> tuple[AssetManifestItem | None, tuple[str, ...]]:
    """Resolve a directive; return (item-or-None, error-tuple)."""

    primary = _select_primary_source(directive)
    errors: list[str] = []
    try:
        item = _attempt_source(
            primary,
            directive,
            search_provider=search_provider,
            generation_provider=generation_provider,
            transaction_dir=transaction_dir,
            safety_checker=safety_checker,
            run_id=run_id,
            transaction_id=transaction_id,
        )
        return item, ()
    except AssetResolutionError as error:
        errors.append(str(error))

    if directive.fallback_source != "none":
        fallback = directive.fallback_source
        try:
            item = _attempt_source(
                fallback,
                directive,
                search_provider=search_provider,
                generation_provider=generation_provider,
                transaction_dir=transaction_dir,
                safety_checker=safety_checker,
                run_id=run_id,
                transaction_id=transaction_id,
            )
            return item, ()
        except AssetResolutionError as fallback_error:
            errors.append(str(fallback_error))

    return None, tuple(errors)


def _select_primary_source(directive: AssetDirective) -> str:
    preferred = directive.preferred_source
    if preferred == "either":
        return "search"
    if preferred == "none":
        if directive.fallback_source != "none":
            return directive.fallback_source
        raise AssetResolutionError("directive has no usable source")
    if preferred in {"search", "generate"}:
        return preferred
    raise AssetResolutionError(f"unsupported preferred_source: {preferred}")


def resolve_asset_directives(
    *,
    directives: Iterable[AssetDirective],
    transaction_root: Path,
    run_id: str,
    transaction_id: str,
    search_provider: object | None = None,
    generation_provider: object | None = None,
    safety_checker: object | None = None,
) -> AssetResolutionResult:
    """Resolve visual asset directives into a hash-bound manifest.

    Preferred source first; on primary failure, fall back only when the
    directive allows it. Required unresolved directives raise
    ``VisualProductionInterrupted`` with recovery evidence persisted under
    ``transaction_root / transaction_id / recovery.json``; optional unresolved
    directives become ``UnresolvedOptionalAsset`` entries.
    """

    checker = safety_checker if safety_checker is not None else DefaultAssetSafetyChecker()
    transaction_dir = _transaction_dir(transaction_root, transaction_id)
    items: list[AssetManifestItem] = []
    unresolved: list[UnresolvedOptionalAsset] = []

    for directive in directives:
        item, errors = _preferred_then_fallback(
            directive,
            search_provider=search_provider,
            generation_provider=generation_provider,
            transaction_dir=transaction_dir,
            safety_checker=checker,
            run_id=run_id,
            transaction_id=transaction_id,
        )
        if item is not None:
            items.append(item)
            continue
        if directive.required:
            _persist_recovery_journal(
                transaction_dir,
                transaction_id=transaction_id,
                run_id=run_id,
                errors=errors,
            )
            raise VisualProductionInterrupted(
                stage="asset_resolver",
                errors=errors,
                raw_outputs=(),
            )
        reason = errors[0] if errors else "optional directive could not be resolved"
        unresolved.append(
            UnresolvedOptionalAsset(
                directive_id=directive.directive_id,
                page_id=directive.page_id,
                reason=reason,
            )
        )

    evidence = AssetTransactionEvidence(
        run_id=run_id,
        transaction_id=transaction_id,
        transaction_root=str(transaction_dir.resolve()),
        journal_path=str(transaction_dir / "recovery.json"),
        status="complete",
        resolved_directive_ids=tuple(item.directive_id for item in items),
        unresolved_optional_directive_ids=tuple(
            entry.directive_id for entry in unresolved
        ),
    )
    return AssetResolutionResult(
        manifest=AssetManifest(items=tuple(items)),
        unresolved_optional_assets=tuple(unresolved),
        transaction_evidence=evidence,
    )
