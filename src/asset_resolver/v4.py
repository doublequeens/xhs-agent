"""v4 asset-directive adapter and explicit revision transaction boundary."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from src.schemas.assets import AssetResolutionResult
from src.schemas.v4.direction import AssetDirectiveV4
from src.schemas.visual_director import AssetDirective
from src.visual_runtime.artifact_identity import (
    ArtifactIdentityError,
    ArtifactPaths,
    revalidate_artifact_paths,
)

from .resolver import AssetResolutionError, resolve_asset_directives


DEFAULT_V4_ASSET_ROOT = Path(__file__).resolve().parents[2] / "data" / "asset_transactions"

_SOURCE_MAP = {
    "search": "search",
    "licensed_search": "search",
    "generate": "generate",
    "llm_generation": "generate",
    "either": "either",
    "none": "none",
}
_COMPOSITE_SOURCE_MAP = {
    "search_then_generate": ("search", "generate"),
    "generate_then_search": ("generate", "search"),
}


def _provider_source(value: str, *, fallback: bool = False) -> str:
    if value in _SOURCE_MAP:
        return _SOURCE_MAP[value]
    if value in _COMPOSITE_SOURCE_MAP:
        return _COMPOSITE_SOURCE_MAP[value][1 if fallback else 0]
    raise ValueError(f"unsupported v4 asset source: {value}")


def adapt_asset_directive_v4(value: AssetDirectiveV4 | dict[str, Any]) -> AssetDirective:
    """Map one revalidated v4 directive into the approved v3 provider shape.

    Only fields consumed by the shared provider/safety contract cross this
    boundary.  ``purpose`` and ``supports_fragment_refs`` remain authoring
    semantics and never enter a provider request.
    """

    try:
        raw = value.model_dump(mode="python") if isinstance(value, AssetDirectiveV4) else value
        directive = AssetDirectiveV4.model_validate(raw)
    except Exception as error:
        raise ValueError("v4 asset directive is invalid") from error

    if directive.preferred_source in _COMPOSITE_SOURCE_MAP:
        preferred, composite_fallback = _COMPOSITE_SOURCE_MAP[directive.preferred_source]
        if directive.fallback_source == "none":
            fallback = composite_fallback
        else:
            explicit_fallback = _provider_source(directive.fallback_source, fallback=True)
            if explicit_fallback != composite_fallback:
                raise ValueError(
                    "ambiguous fallback for composite v4 asset source"
                )
            fallback = composite_fallback
    else:
        preferred = _provider_source(directive.preferred_source)
        if directive.fallback_source in _COMPOSITE_SOURCE_MAP:
            raise ValueError("ambiguous composite fallback for v4 asset source")
        fallback = _provider_source(directive.fallback_source, fallback=True)
    return AssetDirective(
        directive_id=directive.directive_id,
        page_id=directive.page_id,
        role=directive.role,
        required=directive.required,
        preferred_source=preferred,
        fallback_source=fallback,
        query_or_prompt=directive.query_or_prompt,
        negative_constraints=tuple(directive.negative_constraints),
        orientation=directive.orientation,
        min_width=directive.min_width,
        min_height=directive.min_height,
    )


def adapt_asset_directives_v4(
    directives: Iterable[AssetDirectiveV4 | dict[str, Any]],
) -> tuple[AssetDirective, ...]:
    return tuple(adapt_asset_directive_v4(directive) for directive in directives)


def resolve_v4_asset_directives(
    *,
    directives: Iterable[AssetDirectiveV4 | dict[str, Any]],
    run_id: str,
    transaction_id: str,
    transaction_directory: Path | None = None,
    artifact_paths: ArtifactPaths | None = None,
    search_provider: object | None = None,
    generation_provider: object | None = None,
    safety_checker: object | None = None,
) -> AssetResolutionResult:
    """Resolve v4 directives in an already identity-bound asset directory."""

    if transaction_directory is not None:
        raise AssetResolutionError(
            "bare transaction_directory is not accepted; provide artifact_paths"
        )
    if artifact_paths is None:
        raise AssetResolutionError("v4 resolution requires complete artifact_paths identity")
    if not isinstance(artifact_paths, ArtifactPaths):
        raise AssetResolutionError("artifact_paths must be ArtifactPaths")
    try:
        checked_paths = revalidate_artifact_paths(artifact_paths)
    except (ArtifactIdentityError, OSError) as error:
        raise AssetResolutionError("artifact_paths are not identity-bound") from error
    identity = checked_paths.identity
    if run_id != identity.run_id:
        raise AssetResolutionError("run_id does not match artifact identity")
    if transaction_id != identity.revision_id:
        raise AssetResolutionError("transaction_id does not match revision identity")
    repo_root = Path(__file__).resolve().parents[2]
    try:
        if checked_paths.base_root.absolute().is_relative_to(
            (repo_root / "outputs").absolute()
        ):
            raise AssetResolutionError("v4 asset resolver cannot write under outputs")
    except (OSError, RuntimeError) as error:
        raise AssetResolutionError("v4 artifact base is unresolvable") from error

    adapted = adapt_asset_directives_v4(directives)
    return resolve_asset_directives(
        directives=adapted,
        run_id=run_id,
        transaction_id=transaction_id,
        artifact_paths=checked_paths,
        search_provider=search_provider,
        generation_provider=generation_provider,
        safety_checker=safety_checker,
    )


# Discoverable aliases for callers that spell the adapter as a conversion.
to_approved_asset_directive = adapt_asset_directive_v4
convert_asset_directive_v4 = adapt_asset_directive_v4
resolve_asset_directives_v4 = resolve_v4_asset_directives


__all__ = [
    "DEFAULT_V4_ASSET_ROOT",
    "adapt_asset_directive_v4",
    "adapt_asset_directives_v4",
    "convert_asset_directive_v4",
    "resolve_asset_directives_v4",
    "resolve_v4_asset_directives",
    "to_approved_asset_directive",
]
