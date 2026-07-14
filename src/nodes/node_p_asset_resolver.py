from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path

from src.asset_resolver import (
    PexelsProvider,
    UnsplashProvider,
    load_catalog,
    resolve_assets,
)
from src.rendering.editorial.design_system import ASSET_ROOT
from src.schemas import AgentState, VisualPlan


CATALOG_PATH = ASSET_ROOT / "manifest.json"


def _value(payload, key, default=None):
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


def _asset_run_id(state: AgentState) -> str:
    manifest = state.get("asset_manifest")
    for item in _value(manifest, "items", []) or []:
        run_id = _value(item, "run_id")
        if isinstance(run_id, str) and run_id:
            return run_id
    trace_run_id = _value(state.get("topic_generation_trace"), "run_id")
    if isinstance(trace_run_id, str) and trace_run_id:
        return f"editorial-{trace_run_id}"
    package = state.get("publish_package") or {}
    identity = "|".join(
        str(package.get(name) or "")
        for name in ("topic_id", "draft_id", "angle_id")
    )
    return "editorial-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def load_asset_catalog_for_state(
    state: AgentState,
    *,
    run_id: str | None = None,
    allow_external: bool = True,
):
    """Load graph-scoped catalog configuration without doing resolution work."""

    catalog = load_catalog(Path(CATALOG_PATH))
    providers = ()
    if allow_external:
        providers = (
            PexelsProvider(os.getenv("PEXELS_API_KEY")),
            UnsplashProvider(os.getenv("UNSPLASH_ACCESS_KEY")),
        )
    return replace(
        catalog,
        providers=providers,
        run_id=run_id or _asset_run_id(state),
    )


def asset_resolver_node(state: AgentState) -> dict:
    raw_plan = state.get("visual_plan")
    if raw_plan is None:
        raise ValueError("asset_resolver_node requires visual_plan in state.")
    plan = VisualPlan.model_validate(raw_plan)
    catalog = load_asset_catalog_for_state(state)
    return {
        "asset_manifest": resolve_assets(plan, catalog),
        "current_node": "ASSET_RESOLVER",
    }
