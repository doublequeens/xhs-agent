"""v4 asset resolver node with a hard Q1 and immutable revision boundary."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.asset_resolver.v4 import (
    DEFAULT_V4_ASSET_ROOT,
    resolve_v4_asset_directives,
)
from src.schemas.assets import AssetResolutionResult
from src.schemas.v4.direction import VisualDirectionPlanV4
from src.visual_runtime.artifact_identity import (
    ArtifactIdentity,
    ArtifactPaths,
    ensure_artifact_paths,
    resolve_artifact_paths,
)

from .authoring import route_after_authoring_qa


_CURRENT_NODE = "V4_ASSET_RESOLVER"
_NEXT_ROUTE = "composition_planning"
_FAIL_ROUTE = "visual_authoring"


def _required_identity(state: Mapping[str, Any], field_name: str) -> str:
    value = state.get(field_name)
    if type(value) is not str or not value.strip():
        raise ValueError(f"v4 asset resolver requires non-empty state.{field_name}")
    return value


def _blocked_result() -> dict[str, Any]:
    return {
        "current_node": _CURRENT_NODE,
        "route": _FAIL_ROUTE,
        "visual_route": _FAIL_ROUTE,
        "asset_resolver_route": _FAIL_ROUTE,
    }


def _coerce_plan(value: Any) -> VisualDirectionPlanV4:
    raw = value.model_dump(mode="python") if isinstance(value, VisualDirectionPlanV4) else value
    if not isinstance(raw, Mapping):
        raise ValueError("v4 asset resolver requires persisted visual_direction_plan")
    try:
        return VisualDirectionPlanV4.model_validate(raw)
    except Exception as error:
        raise ValueError("v4 asset resolver visual_direction_plan is invalid") from error


def _select_base_root(
    *,
    base_root: Path | None,
    root: Path | None,
    transaction_root: Path | None,
) -> Path:
    supplied = [value for value in (base_root, root, transaction_root) if value is not None]
    if len(supplied) > 1:
        raise ValueError("v4 asset resolver root aliases are mutually exclusive")
    selected = Path(supplied[0]) if supplied else DEFAULT_V4_ASSET_ROOT
    # The v4 node owns asset transactions only; a caller cannot redirect this
    # path into the publish surface.
    repo_root = Path(__file__).resolve().parents[3]
    try:
        if selected.absolute().resolve(strict=False).is_relative_to(
            (repo_root / "outputs").resolve(strict=False)
        ):
            raise ValueError("v4 asset resolver cannot use outputs as an artifact root")
    except (OSError, RuntimeError) as error:
        raise ValueError("v4 asset resolver root is unresolvable") from error
    return selected


def _revalidated_q1_route(state: Mapping[str, Any]) -> str:
    try:
        return route_after_authoring_qa(state)
    except Exception:
        # The Task 8 helper is intentionally fail-closed.  Keep this guard in
        # case a replacement helper raises instead of returning its fail route.
        return _FAIL_ROUTE


def _assert_manifest_security(result: AssetResolutionResult) -> None:
    for item in result.manifest.items:
        if item.security_status != "approved" or item.human_decision != "pending":
            raise ValueError(
                "v4 asset resolver refuses a manifest item without approved/pending status"
            )


def asset_resolver_node(
    state: Mapping[str, Any],
    *,
    search_provider: object | None = None,
    generation_provider: object | None = None,
    safety_checker: object | None = None,
    base_root: Path | None = None,
    root: Path | None = None,
    transaction_root: Path | None = None,
) -> dict[str, Any]:
    """Resolve all plan directives once in the current candidate revision.

    Q1 is recomputed before identity validation, directory creation, or any
    provider interaction.  A stale/missing/failed authoring result therefore
    routes back to ``visual_authoring`` with no side effects.
    """

    if not isinstance(state, Mapping):
        raise ValueError("v4 asset resolver requires state")
    if _revalidated_q1_route(state) != "asset_resolver":
        return _blocked_result()

    run_id = _required_identity(state, "run_id")
    _required_identity(state, "run_mode")
    candidate_id = _required_identity(state, "candidate_id")
    revision_id = _required_identity(state, "revision_id")
    parent_revision_id = state.get("parent_revision_id")
    if parent_revision_id is not None and (
        type(parent_revision_id) is not str or not parent_revision_id.strip()
    ):
        raise ValueError("v4 asset resolver state.parent_revision_id must be non-empty or None")

    plan = _coerce_plan(state.get("visual_direction_plan"))
    identity = ArtifactIdentity(
        run_id=run_id,
        candidate_id=candidate_id,
        revision_id=revision_id,
    )
    selected_root = _select_base_root(
        base_root=base_root,
        root=root,
        transaction_root=transaction_root,
    )
    paths = ensure_artifact_paths(resolve_artifact_paths(selected_root, identity))

    result = resolve_v4_asset_directives(
        directives=plan.asset_directives,
        run_id=identity.run_id,
        transaction_id=identity.revision_id,
        artifact_paths=paths,
        search_provider=search_provider,
        generation_provider=generation_provider,
        safety_checker=safety_checker,
    )
    _assert_manifest_security(result)
    return {
        "asset_manifest": result.manifest,
        "unresolved_optional_assets": result.unresolved_optional_assets,
        "asset_transaction_evidence": result.transaction_evidence,
        "asset_resolution_result": result,
        "artifact_paths": paths,
        "asset_transaction_paths": paths,
        "current_node": _CURRENT_NODE,
        "route": _NEXT_ROUTE,
        "visual_route": _NEXT_ROUTE,
        "asset_resolver_route": _NEXT_ROUTE,
    }


# Graph wiring can choose the explicit v4 spelling without importing a v3
# node; aliases do not change the persisted node identity above.
v4_asset_resolver_node = asset_resolver_node


__all__ = ["asset_resolver_node", "v4_asset_resolver_node"]
