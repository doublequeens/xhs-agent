from __future__ import annotations

from pathlib import Path

from src.asset_resolver import resolve_asset_directives
from src.schemas import AgentState, VisualDirectionPlan
from src.utils import _value


def asset_resolver_node(
    state: AgentState,
    *,
    search_provider,
    generation_provider,
    safety_checker=None,
    transaction_root: Path,
    transaction_id: str,
) -> dict:
    """Resolve a VisualDirectionPlan's asset directives into a manifest.

    Reads ``state["visual_direction_plan"]`` and
    ``state["topic_generation_trace"]["run_id"]`` and returns the manifest,
    optional unresolved directives, and transaction evidence. The node does
    not pause for asset-specific Human Review; rendered/approved assets stay
    ``human_decision="pending"`` until the unified Final Review.
    """

    raw_plan = state.get("visual_direction_plan")
    if raw_plan is None:
        raise ValueError("asset_resolver_node requires visual_direction_plan in state.")
    plan = VisualDirectionPlan.model_validate(raw_plan)
    trace_run_id = _value(state.get("topic_generation_trace"), "run_id")
    if not isinstance(trace_run_id, str) or not trace_run_id:
        raise ValueError("asset_resolver_node requires topic_generation_trace.run_id")
    result = resolve_asset_directives(
        directives=plan.asset_directives,
        transaction_root=Path(transaction_root),
        run_id=trace_run_id,
        transaction_id=transaction_id,
        search_provider=search_provider,
        generation_provider=generation_provider,
        safety_checker=safety_checker,
    )
    return {
        "asset_manifest": result.manifest,
        "unresolved_optional_assets": result.unresolved_optional_assets,
        "asset_transaction_evidence": result.transaction_evidence,
        "current_node": "ASSET_RESOLVER",
    }
