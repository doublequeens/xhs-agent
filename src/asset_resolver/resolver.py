from __future__ import annotations

import hashlib
import json
import os
import re
import stat
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
from src.visual_runtime.artifact_identity import (
    ArtifactBindingError,
    ArtifactIdentityError,
    ArtifactPaths,
    _DirectoryLease,
    _atomic_write_at,
    _create_staging_directory,
    _open_absolute_directory,
    _pin_artifact_paths,
    _read_file_at,
    _remove_tree_at,
    _validate_component,
    revalidate_artifact_paths,
)

from .providers import ExternalAssetCandidate, candidate_urls_are_allowed


MAX_IMAGE_PIXELS = 40_000_000


class AssetResolutionError(RuntimeError):
    """Raised when a visual asset directive cannot be resolved."""


def _safe_component(value: str) -> str:
    """Make a deterministic leaf name without using it as an identity."""

    sanitized = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value)).strip("-.")
    return sanitized or "asset"


def _path_relative_to(path: Path, root: Path) -> tuple[str, ...]:
    """Return safe lexical parts; actual access is performed with a dirfd."""

    try:
        relative = Path(os.path.abspath(os.fspath(path))).relative_to(
            Path(os.path.abspath(os.fspath(root)))
        )
    except (TypeError, ValueError) as error:
        raise AssetResolutionError("asset path escapes its pinned transaction directory") from error
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise AssetResolutionError("asset path contains an unsafe component")
    try:
        return tuple(_validate_component(part, "asset path component") for part in relative.parts)
    except ArtifactIdentityError as error:
        raise AssetResolutionError(str(error)) from error


def _close_owned(fd: int | None, primary: BaseException | None = None) -> OSError | None:
    """Transfer descriptor ownership before one close; never retry the number."""

    if fd is None:
        return None
    try:
        os.close(fd)
    except OSError as error:
        if primary is not None:
            primary.add_note(f"descriptor cleanup failed: {error}")
        return error
    return None


def _assert_lease(lease: _DirectoryLease) -> None:
    try:
        lease.assert_intact()
    except (ArtifactIdentityError, OSError) as error:
        raise AssetResolutionError("pinned asset transaction changed") from error


def _publish_bytes(
    lease: _DirectoryLease,
    relative_parts: tuple[str, ...],
    content: bytes,
) -> None:
    try:
        _atomic_write_at(lease.fd, relative_parts, content)
    except (ArtifactIdentityError, ArtifactBindingError, OSError) as error:
        raise AssetResolutionError("asset publication failed") from error
    _assert_lease(lease)


@dataclass(frozen=True, slots=True)
class AssetSafetyDecision:
    """Deterministic safety outcome for one resolved image candidate."""

    approved: bool
    unwanted_text: bool = False
    reason: str | None = None


class DefaultAssetSafetyChecker:
    """Raster/MIME checks over an identity-pinned descriptor."""

    def check(self, path: Path, directive: AssetDirective) -> AssetSafetyDecision:
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        descriptor: int | None = None
        decision: AssetSafetyDecision | None = None
        close_error: OSError | None = None
        try:
            before = path.lstat()
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
                decision = AssetSafetyDecision(
                    approved=False,
                    unwanted_text=False,
                    reason="image is not a regular non-symlink file",
                )
            else:
                descriptor = os.open(path, os.O_RDONLY | nofollow)
                opened = os.fstat(descriptor)
                if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                    decision = AssetSafetyDecision(
                        approved=False,
                        unwanted_text=False,
                        reason="image identity changed during safety check",
                    )
                else:
                    try:
                        with os.fdopen(os.dup(descriptor), "rb") as stream:
                            with Image.open(stream) as image:
                                image.verify()
                    except (OSError, ValueError) as error:
                        decision = AssetSafetyDecision(
                            approved=False,
                            unwanted_text=False,
                            reason=f"image raster decode failed: {error}",
                        )
                    else:
                        decision = AssetSafetyDecision(approved=True, unwanted_text=False)
        except OSError as error:
            decision = AssetSafetyDecision(
                approved=False,
                unwanted_text=False,
                reason=f"image safety check failed: {error}",
            )
        finally:
            owned = descriptor
            descriptor = None
            close_error = _close_owned(owned)
        if close_error is not None:
            return AssetSafetyDecision(
                approved=False,
                unwanted_text=False,
                reason=f"image descriptor close failed: {close_error}",
            )
        return decision or AssetSafetyDecision(
            approved=False,
            unwanted_text=False,
            reason="image safety check failed",
        )


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
    if directive.orientation != "any" and candidate.orientation != directive.orientation:
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
    return "landscape" if width > height else "portrait"


def _decode_raster(raw: bytes) -> tuple[bytes, str, int, int]:
    """Return canonical bytes, extension, width and height."""

    try:
        with Image.open(BytesIO(raw)) as source:
            width, height = source.size
            if width * height > MAX_IMAGE_PIXELS:
                raise AssetResolutionError("provider image exceeds pixel limit")
            source.load()
            has_alpha = "A" in source.getbands() or "transparency" in source.info
            normalized = source.convert("RGBA" if has_alpha else "RGB")
    except AssetResolutionError:
        raise
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


def _transaction_dir(transaction_root: Path, transaction_id: str) -> Path:
    """Create one legacy transaction using only a trusted root dirfd."""

    lease, result = _legacy_transaction_lease(transaction_root, transaction_id)
    close_error = lease.close()
    if close_error is not None:
        raise AssetResolutionError("transaction directory descriptor close failed") from close_error
    return result


def _close_owned_lease(lease: _DirectoryLease, primary: BaseException | None = None) -> None:
    error = lease.close()
    if error is not None and primary is not None:
        primary.add_note(f"descriptor cleanup failed: {error}")


def _legacy_transaction_lease(transaction_root: Path, transaction_id: str) -> tuple[_DirectoryLease, Path]:
    """Establish and keep the root and transaction descriptors pinned."""

    try:
        _validate_component(transaction_id, "transaction_id")
    except ArtifactIdentityError as error:
        raise AssetResolutionError(str(error)) from error
    try:
        lease = _open_absolute_directory(Path(transaction_root), create=True)
        lease.add_child(transaction_id, create=True)
        lease.assert_intact()
        return lease, lease.paths[-1]
    except (ArtifactIdentityError, OSError) as error:
        if "lease" in locals():
            _close_owned_lease(lease, error)
        raise AssetResolutionError("transaction directory could not be established") from error


def _explicit_transaction_lease(paths: ArtifactPaths) -> tuple[_DirectoryLease, Path, ArtifactPaths]:
    try:
        lease = _pin_artifact_paths(paths, create=False)
        lease.assert_intact()
        return lease, paths.asset_root, paths
    except (ArtifactIdentityError, ArtifactBindingError, OSError) as error:
        raise AssetResolutionError("artifact paths are not a valid pinned revision") from error


def _persist_recovery_journal(
    transaction_lease: _DirectoryLease,
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
    content = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    _publish_bytes(transaction_lease, ("recovery.json",), content)


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


def _safety_error(decision: AssetSafetyDecision) -> AssetResolutionError | None:
    if decision.approved:
        return None
    message = (
        "rejected: unwanted visible text"
        if decision.unwanted_text
        else f"rejected: {decision.reason or 'safety check failed'}"
    )
    return AssetResolutionError(message)


def _final_snapshot(
    lease: _DirectoryLease,
    transaction_dir: Path,
    relative_parts: tuple[str, ...],
    *,
    path_label: str,
) -> object:
    try:
        snapshot = _read_file_at(lease.fd, relative_parts)
    except (ArtifactIdentityError, ArtifactBindingError, OSError) as error:
        raise AssetResolutionError(f"{path_label} publication could not be read") from error
    _assert_lease(lease)
    return snapshot


def _resolve_via_search(
    directive: AssetDirective,
    *,
    search_provider: object,
    transaction_lease: _DirectoryLease,
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
        raise AssetResolutionError(f"search provider {name} download failed: {error}") from error

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
    leaf = (
        f"{_safe_component(directive.directive_id)}-"
        f"{_safe_component(asset_id)}-{sha256[:16]}{extension}"
    )
    relative_parts = ("search", leaf)
    _publish_bytes(transaction_lease, relative_parts, normalized)
    destination = transaction_dir.joinpath(*relative_parts)
    before = _final_snapshot(
        transaction_lease,
        transaction_dir,
        relative_parts,
        path_label="search asset",
    )
    try:
        decision = safety_checker.check(destination, directive)
    except Exception as error:
        raise AssetResolutionError(f"asset safety checker failed: {error}") from error
    safety_error = _safety_error(decision)
    if safety_error is not None:
        raise safety_error
    after = _final_snapshot(
        transaction_lease,
        transaction_dir,
        relative_parts,
        path_label="search asset",
    )
    if (after.sha256, after.size, after.identity) != (
        before.sha256,
        before.size,
        before.identity,
    ):
        raise AssetResolutionError("search asset changed during safety validation")

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
        sha256=after.sha256,
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


def _close_staging(
    asset_fd: int,
    staging_name: str,
    staging_fd: int | None,
    primary: BaseException | None,
) -> AssetResolutionError | None:
    owned = staging_fd
    staging_fd = None
    close_error = _close_owned(owned, primary)
    try:
        _remove_tree_at(asset_fd, staging_name)
    except (ArtifactIdentityError, OSError) as error:
        if primary is not None:
            primary.add_note(f"staging cleanup failed: {error}")
        else:
            return AssetResolutionError("staging cleanup failed")
    if close_error is not None and primary is None:
        error = AssetResolutionError("staging descriptor close failed")
        error.__cause__ = close_error
        return error
    return None


def _resolve_via_generation(
    directive: AssetDirective,
    *,
    generation_provider: ImageGenerationProvider,
    transaction_lease: _DirectoryLease,
    transaction_dir: Path,
    safety_checker: object,
    run_id: str,
    transaction_id: str,
) -> AssetManifestItem:
    # A provider receives a fresh exclusive staging subtree, never the final
    # generated directory.  Final bytes are published by the resolver.
    staging_name = f".staging-{_safe_component(directive.directive_id)}-{os.urandom(8).hex()}"
    staging_path = transaction_dir / staging_name
    try:
        staging_fd = _create_staging_directory(transaction_lease.fd, staging_name)
    except (ArtifactIdentityError, OSError) as error:
        raise AssetResolutionError("generation staging directory could not be created") from error
    primary: BaseException | None = None
    try:
        request = _generation_request(
            directive,
            width=directive.min_width,
            height=directive.min_height,
        )
        try:
            generated = generation_provider.generate(request, staging_path)
        except Exception as error:
            raise AssetResolutionError(f"generation provider failed: {error}") from error
        _assert_lease(transaction_lease)
        if not isinstance(generated, GeneratedImage):
            raise AssetResolutionError("generation provider returned a non-GeneratedImage result")
        if (
            type(generated.provider) is not str
            or not generated.provider.strip()
            or type(generated.model) is not str
            or not generated.model.strip()
            or type(generated.mime_type) is not str
            or not generated.mime_type.startswith("image/")
        ):
            raise AssetResolutionError("generated provider identity or MIME is invalid")

        generated_path = Path(generated.path)
        generated_parts = _path_relative_to(generated_path, staging_path)
        try:
            staged = _read_file_at(staging_fd, generated_parts)
        except (ArtifactIdentityError, ArtifactBindingError, OSError) as error:
            raise AssetResolutionError("generated image is not a stable regular staging file") from error
        _assert_lease(transaction_lease)
        if generated.sha256.lower() != staged.sha256:
            raise AssetResolutionError("generated provider byte hash does not match output")
        normalized, extension, raster_width, raster_height = _decode_raster(staged.raw)
        sha256 = hashlib.sha256(normalized).hexdigest()
        final_parts = (
            "generated",
            f"{_safe_component(directive.directive_id)}-{sha256[:16]}{extension}",
        )
        _publish_bytes(transaction_lease, final_parts, normalized)
        destination = transaction_dir.joinpath(*final_parts)
        before = _final_snapshot(
            transaction_lease,
            transaction_dir,
            final_parts,
            path_label="generated asset",
        )
        try:
            decision = safety_checker.check(destination, directive)
        except Exception as error:
            raise AssetResolutionError(f"asset safety checker failed: {error}") from error
        safety_error = _safety_error(decision)
        if safety_error is not None:
            raise safety_error
        after = _final_snapshot(
            transaction_lease,
            transaction_dir,
            final_parts,
            path_label="generated asset",
        )
        if (after.sha256, after.size, after.identity) != (
            before.sha256,
            before.size,
            before.identity,
        ):
            raise AssetResolutionError("generated asset changed during safety validation")
        provenance = dict(generated.internal_provenance)
        return AssetManifestItem(
            asset_id=f"generated-{directive.directive_id}",
            directive_id=directive.directive_id,
            page_id=directive.page_id,
            source_kind="generated",
            provider=generated.provider,
            license="internal-generated",
            local_path=str(destination),
            width=raster_width,
            height=raster_height,
            sha256=after.sha256,
            subject_focal_point=(0.5, 0.5),
            crop_guidance=directive.orientation,
            security_status="approved",
            human_decision="pending",
            run_id=run_id,
            transaction_id=transaction_id,
            internal_provenance=provenance,
        )
    except BaseException as error:
        primary = error
        raise
    finally:
        cleanup_error = _close_staging(
            transaction_lease.fd,
            staging_name,
            staging_fd,
            primary,
        )
        if cleanup_error is not None and primary is None:
            raise cleanup_error


def _attempt_source(
    source: str,
    directive: AssetDirective,
    *,
    search_provider: object | None,
    generation_provider: object | None,
    transaction_lease: _DirectoryLease,
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
            transaction_lease=transaction_lease,
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
            transaction_lease=transaction_lease,
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
    transaction_lease: _DirectoryLease,
    transaction_dir: Path,
    safety_checker: object,
    run_id: str,
    transaction_id: str,
) -> tuple[AssetManifestItem | None, tuple[str, ...]]:
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
            transaction_lease=transaction_lease,
            transaction_dir=transaction_dir,
            safety_checker=safety_checker,
            run_id=run_id,
            transaction_id=transaction_id,
        )
        return item, ()
    except AssetResolutionError as error:
        errors.append(str(error))

    if directive.fallback_source != "none":
        try:
            item = _attempt_source(
                directive.fallback_source,
                directive,
                search_provider=search_provider,
                generation_provider=generation_provider,
                transaction_lease=transaction_lease,
                transaction_dir=transaction_dir,
                safety_checker=safety_checker,
                run_id=run_id,
                transaction_id=transaction_id,
            )
            return item, ()
        except AssetResolutionError as error:
            errors.append(str(error))
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


def _run_resolution(
    *,
    directives: Iterable[AssetDirective],
    transaction_lease: _DirectoryLease,
    transaction_dir: Path,
    run_id: str,
    transaction_id: str,
    checker: object,
    search_provider: object | None,
    generation_provider: object | None,
) -> AssetResolutionResult:
    items: list[AssetManifestItem] = []
    unresolved: list[UnresolvedOptionalAsset] = []
    for directive in directives:
        item, errors = _preferred_then_fallback(
                directive,
                search_provider=search_provider,
                generation_provider=generation_provider,
                transaction_lease=transaction_lease,
                transaction_dir=transaction_dir,
                safety_checker=checker,
                run_id=run_id,
                transaction_id=transaction_id,
            )
        if item is not None:
            items.append(item)
            continue
        if directive.required:
            try:
                _persist_recovery_journal(
                        transaction_lease,
                        transaction_dir,
                        transaction_id=transaction_id,
                        run_id=run_id,
                        errors=errors,
                    )
            except Exception as journal_error:
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
        transaction_id=transaction_id,
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


def resolve_asset_directives(
    *,
    directives: Iterable[AssetDirective],
    run_id: str,
    transaction_root: Path | None = None,
    transaction_id: str | None = None,
    search_provider: object | None = None,
    generation_provider: object | None = None,
    safety_checker: object | None = None,
    artifact_paths: ArtifactPaths | None = None,
    transaction_directory: Path | None = None,
) -> AssetResolutionResult:
    """Resolve directives using legacy v3 root/id or a complete v4 binding.

    The old v3 API remains available.  The v4 API is intentionally typed: a
    bare directory cannot be paired with misleading run/revision evidence.
    """

    if transaction_directory is not None:
        raise AssetResolutionError(
            "bare transaction_directory mode is not supported; provide artifact_paths"
        )
    if artifact_paths is not None and (transaction_root is not None):
        raise AssetResolutionError("artifact_paths is mutually exclusive with transaction_root")
    checker = safety_checker if safety_checker is not None else DefaultAssetSafetyChecker()

    lease: _DirectoryLease
    transaction_dir: Path
    resolved_run_id = run_id
    resolved_transaction_id: str
    if artifact_paths is not None:
        if not isinstance(artifact_paths, ArtifactPaths):
            raise AssetResolutionError("artifact_paths must be ArtifactPaths")
        try:
            checked = revalidate_artifact_paths(artifact_paths)
        except (ArtifactIdentityError, ArtifactBindingError, OSError) as error:
            raise AssetResolutionError("artifact_paths are not identity-bound") from error
        if run_id != checked.identity.run_id:
            raise AssetResolutionError("run_id does not match artifact identity")
        if transaction_id is not None and transaction_id != checked.identity.revision_id:
            raise AssetResolutionError("transaction_id does not match artifact identity")
        resolved_run_id = checked.identity.run_id
        resolved_transaction_id = checked.identity.revision_id
        lease, transaction_dir, _ = _explicit_transaction_lease(checked)
    else:
        if transaction_root is None or transaction_id is None:
            raise AssetResolutionError(
                "v3 resolver mode requires transaction_root and transaction_id"
            )
        if type(transaction_id) is not str:
            raise AssetResolutionError("transaction_id must be a non-empty string")
        lease, transaction_dir = _legacy_transaction_lease(transaction_root, transaction_id)
        resolved_transaction_id = transaction_id

    primary: BaseException | None = None
    try:
        try:
            return _run_resolution(
                directives=directives,
                transaction_lease=lease,
                transaction_dir=transaction_dir,
                run_id=resolved_run_id,
                transaction_id=resolved_transaction_id,
                checker=checker,
                search_provider=search_provider,
                generation_provider=generation_provider,
            )
        except (AssetResolutionError, VisualProductionInterrupted):
            raise
        except (ArtifactIdentityError, ArtifactBindingError, OSError) as error:
            raise AssetResolutionError("asset transaction operation failed") from error
    except BaseException as error:
        primary = error
        raise
    finally:
        close_error = lease.close()
        if close_error is not None and primary is not None:
            primary.add_note(f"descriptor cleanup failed: {close_error}")
        elif close_error is not None:
            raise AssetResolutionError("asset transaction descriptor close failed") from close_error


__all__ = [
    "AssetResolutionError",
    "AssetSafetyDecision",
    "DefaultAssetSafetyChecker",
    "resolve_asset_directives",
]
