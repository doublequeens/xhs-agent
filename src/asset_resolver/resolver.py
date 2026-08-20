from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from PIL import Image

from src.schemas.assets import (
    AssetManifest,
    AssetManifestItem,
    AssetResolutionResult,
    AssetTransactionEvidence,
    UnresolvedOptionalAsset,
)
from src.schemas.visual_director import AssetDirective
from src.visual_ai.protocols import (
    GeneratedImage,
    ImageGenerationProvider,
    ImageGenerationRequest,
)
from src.visual_design.model_retry import VisualProductionInterrupted

from .providers import ExternalAssetCandidate, candidate_urls_are_allowed


MAX_IMAGE_PIXELS = 40_000_000


class AssetResolutionError(RuntimeError):
    """Raised when a visual asset directive cannot be resolved."""


def _check_no_follow_chain(path: Path) -> None:
    """Reject symlinks in every existing component of a transaction path."""

    current = path
    while True:
        try:
            info = current.lstat()
        except FileNotFoundError:
            if current.parent == current:
                break
            current = current.parent
            continue
        except OSError as error:
            raise AssetResolutionError(f"cannot inspect transaction path: {current}") from error
        trusted_darwin_var = (
            current == Path("/var")
            and Path("/private/var").is_dir()
            and current.resolve(strict=False) == Path("/private/var")
        )
        if stat.S_ISLNK(info.st_mode) and not trusted_darwin_var:
            raise AssetResolutionError(f"transaction path contains symlink: {current}")
        if current.parent == current:
            break
        current = current.parent


def _secure_mkdir(path: Path) -> None:
    """Create a directory without following an existing symlink."""

    _check_no_follow_chain(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            _check_no_follow_chain(path)
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise AssetResolutionError(f"transaction directory collision: {path}")
        except OSError as error:
            raise AssetResolutionError(f"cannot create transaction directory: {path}") from error
        return
    except OSError as error:
        raise AssetResolutionError(f"cannot inspect transaction directory: {path}") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise AssetResolutionError(f"transaction directory collision: {path}")


def _secure_mkdirs(path: Path) -> None:
    """Create missing directory components one at a time."""

    missing: list[Path] = []
    current = path
    while True:
        try:
            current.lstat()
            break
        except FileNotFoundError:
            missing.append(current)
            if current.parent == current:
                break
            current = current.parent
    for item in reversed(missing):
        _secure_mkdir(item)


def _validate_transaction_directory(path: Path, *, create: bool) -> Path:
    """Validate an explicit v4 asset root and optionally establish it."""

    directory = Path(path).absolute()
    _check_no_follow_chain(directory)
    if create and not directory.exists():
        _secure_mkdirs(directory)
    _check_no_follow_chain(directory)
    try:
        info = directory.lstat()
    except OSError as error:
        raise AssetResolutionError("explicit transaction directory is unavailable") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise AssetResolutionError("explicit transaction directory must be a regular directory")
    try:
        directory.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise AssetResolutionError("explicit transaction directory containment failed") from error
    return directory


def _path_contained(path: Path, root: Path) -> bool:
    try:
        path.absolute().relative_to(root.absolute())
        _check_no_follow_chain(path.absolute())
        path.absolute().resolve(strict=False).relative_to(root.absolute().resolve(strict=False))
    except (OSError, RuntimeError, ValueError, AssetResolutionError):
        return False
    return True


def _safe_component(value: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-.")
    return sanitized or "asset"


def _atomic_write_bytes(path: Path, content: bytes, *, replace_existing: bool = True) -> None:
    _secure_mkdirs(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if replace_existing:
            os.replace(temporary_name, path)
        else:
            try:
                os.link(temporary_name, path, follow_symlinks=False)
            except FileExistsError as error:
                raise AssetResolutionError("artifact destination already exists") from error
            except OSError as error:
                raise AssetResolutionError("artifact destination could not be published") from error
            os.unlink(temporary_name)
            temporary_name = None
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        try:
            if temporary_name is not None:
                os.unlink(temporary_name)
        except FileNotFoundError:
            pass


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
                # Decode through a duplicate of the already identity-checked
                # descriptor; reopening ``path`` would reintroduce a swap
                # window between no-follow validation and raster inspection.
                with os.fdopen(os.dup(descriptor), "rb") as stream:
                    with Image.open(stream) as image:
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
        after_fd = os.fstat(descriptor)
        after_path = path.lstat()
        if (after_fd.st_dev, after_fd.st_ino) != (before.st_dev, before.st_ino) or (
            after_path.st_dev,
            after_path.st_ino,
        ) != (before.st_dev, before.st_ino):
            raise AssetResolutionError("generated image identity changed during read")
        return b"".join(chunks), (opened.st_dev, opened.st_ino)
    except OSError as error:
        raise AssetResolutionError("generated image is unreadable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _transaction_dir(transaction_root: Path, transaction_id: str) -> Path:
    if type(transaction_id) is not str or not transaction_id:
        raise AssetResolutionError("transaction_id must be a non-empty string")
    root = Path(transaction_root).absolute()
    _secure_mkdirs(root)
    directory = root / transaction_id
    try:
        directory.relative_to(root)
    except ValueError as error:
        raise AssetResolutionError("transaction id escapes transaction root") from error
    _secure_mkdirs(directory)
    _check_no_follow_chain(directory)
    try:
        info = directory.lstat()
    except OSError as error:
        raise AssetResolutionError("transaction directory is unavailable") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise AssetResolutionError("transaction id collides with a non-directory")
    try:
        directory.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as error:
        raise AssetResolutionError("transaction directory escapes transaction root") from error
    return directory


def _persist_recovery_journal(
    transaction_dir: Path,
    *,
    transaction_id: str,
    run_id: str,
    errors: tuple[str, ...],
    immutable_transaction: bool = False,
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
    _atomic_write_bytes(
        journal_path,
        content,
        replace_existing=not immutable_transaction,
    )


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
    immutable_transaction: bool = False,
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
    if not _path_contained(destination, transaction_dir):
        raise AssetResolutionError("search asset destination escapes the transaction dir")
    _atomic_write_bytes(
        destination,
        normalized,
        replace_existing=not immutable_transaction,
    )

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
    immutable_transaction: bool = False,
) -> AssetManifestItem:
    generation_dir = transaction_dir / "generated"
    if immutable_transaction and generation_dir.exists():
        raise AssetResolutionError("generated asset directory already exists in immutable revision")
    _secure_mkdirs(generation_dir)
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
    # Containment is checked before reading provider output, and bytes are
    # then read through a no-follow descriptor so the provider cannot smuggle
    # a path outside the transaction into the manifest.
    if not _path_contained(generated_path, transaction_dir):
        raise AssetResolutionError("generated image escapes the transaction directory")
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
    # Generated assets come back at the provider's default aspect ratio (the
    # interactions API is called with just the prompt); the renderer's
    # fit="cover" + focal_point + crop map the asset into the page box, so the
    # generated raster's absolute dimensions and orientation need not match the
    # directive's min_width/min_height/orientation. Only require a valid raster.
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
    immutable_transaction: bool = False,
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
            immutable_transaction=immutable_transaction,
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
            immutable_transaction=immutable_transaction,
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
    immutable_transaction: bool = False,
) -> tuple[AssetManifestItem | None, tuple[str, ...]]:
    """Resolve a directive; return (item-or-None, error-tuple)."""

    errors: list[str] = []
    try:
        primary = _select_primary_source(directive)
    except AssetResolutionError as error:
        return None, (str(error),)
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
            immutable_transaction=immutable_transaction,
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
                immutable_transaction=immutable_transaction,
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
    run_id: str,
    transaction_root: Path | None = None,
    transaction_id: str | None = None,
    search_provider: object | None = None,
    generation_provider: object | None = None,
    safety_checker: object | None = None,
    transaction_directory: Path | None = None,
) -> AssetResolutionResult:
    """Resolve visual asset directives into a hash-bound manifest.

    Preferred source first; on primary failure, fall back only when the
    directive allows it. Required unresolved directives raise
    ``VisualProductionInterrupted`` with recovery evidence persisted under
    ``transaction_root / transaction_id / recovery.json``; optional unresolved
    directives become ``UnresolvedOptionalAsset`` entries.
    """

    checker = safety_checker if safety_checker is not None else DefaultAssetSafetyChecker()
    explicit_directory = transaction_directory is not None
    if explicit_directory:
        if transaction_root is not None:
            raise AssetResolutionError(
                "transaction_directory is mutually exclusive with transaction_root"
            )
        if transaction_id is None or type(transaction_id) is not str or not transaction_id:
            raise AssetResolutionError(
                "transaction_directory mode requires a non-empty transaction_id"
            )
        transaction_dir = _validate_transaction_directory(
            Path(transaction_directory), create=True
        )
    else:
        if transaction_root is None or transaction_id is None:
            raise AssetResolutionError(
                "v3 resolver mode requires transaction_root and transaction_id"
            )
        transaction_dir = _transaction_dir(transaction_root, transaction_id)
    resolved_transaction_id = transaction_id
    assert resolved_transaction_id is not None
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
            transaction_id=resolved_transaction_id,
            immutable_transaction=explicit_directory,
        )
        if item is not None:
            items.append(item)
            continue
        if directive.required:
            try:
                _persist_recovery_journal(
                    transaction_dir,
                    transaction_id=resolved_transaction_id,
                    run_id=run_id,
                    errors=errors,
                    immutable_transaction=explicit_directory,
                )
            except Exception as journal_error:
                # The persistence-and-assets contract requires recovery
                # failures to preserve the primary resolution error rather
                # than masking it; chain the journal error as the cause.
                raise VisualProductionInterrupted(
                    stage="asset_resolver",
                    errors=errors,
                    raw_outputs=(),
                ) from journal_error
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
        transaction_id=resolved_transaction_id,
        transaction_root=str(transaction_dir),
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
