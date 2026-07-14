from __future__ import annotations

import hashlib
import fcntl
import json
import os
import re
import stat
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Literal

from PIL import Image

from src.schemas.assets import (
    AssetManifest,
    AssetManifestItem,
    AssetRequirement,
    AssetSearchReport,
    ProviderSearchReport,
)
from src.schemas.visual_plan import VisualPlan

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
        layout=requirement.layout,
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
            layout=requirement.layout,
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
        layout=requirement.layout,
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
