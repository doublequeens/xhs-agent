"""Strict graph boundary for deterministic v4 visual repair routing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.schemas.v4.direction import AuthoringQAResultV4
from src.schemas.v4.quality import DesignPlanQAResultV4
from src.schemas.v4.rendering import RenderQAResultV4
from src.schemas.v4.revision import FailureFingerprintV4, NormalizedFailureV4, RevisionEventV4
from src.schemas.v4.semantic import SemanticQAResultV4
from src.visual_design.v4.revisions import append_revision_event, layer_for_failure_code, route_revision


_ROUTE_FOR_LAYER = {
    "SEMANTIC": "semantic_reviser", "AUTHORING": "authoring_reviser", "ASSET": "asset_resolver",
    "COMPOSITION": "composition_reviser", "LAYOUT": "layout_reviser", "RENDER": "render", "AESTHETIC": "visual_critic",
}


def _issue_failure(*, node: str, code: str, page_id: str | None, fragment_id: str | None, region: str | None) -> NormalizedFailureV4:
    fingerprint = FailureFingerprintV4.create(
        node=node, page_id=page_id or "all", failure_code=code,
        affected_fragment_ids=() if fragment_id is None else (fragment_id,), geometry_region=region,
    )
    return NormalizedFailureV4.from_fingerprint(fingerprint)


def _failures_from_result(result: object) -> tuple[NormalizedFailureV4, ...]:
    """Accept only exact current Q0-Q3 contracts, never structural lookalikes."""
    if type(result) is SemanticQAResultV4:
        result.validate_integrity()
        if result.passed:
            raise ValueError("Q0 passed result cannot request revision")
        return tuple(_issue_failure(node="V4_SEMANTIC_QA", code=issue.code, page_id=None, fragment_id=issue.fragment_id or issue.atom_id, region=issue.group_id) for issue in result.issues)
    if type(result) is AuthoringQAResultV4:
        result.validate_integrity()
        if result.passed:
            raise ValueError("Q1 passed result cannot request revision")
        return tuple(_issue_failure(node="V4_AUTHORING_QA", code=issue.code, page_id=issue.page_id, fragment_id=issue.fragment_id, region=issue.directive_id) for issue in result.issues)
    if type(result) is DesignPlanQAResultV4:
        result.validate_integrity()
        if result.passed:
            raise ValueError("Q2 passed result cannot request revision")
        return tuple(_issue_failure(node="V4_DESIGN_QA", code=issue.code, page_id=issue.page_id, fragment_id=issue.fragment_ref, region=issue.region_id or issue.element_id) for page in result.page_metrics for issue in page.issues)
    if type(result) is RenderQAResultV4:
        result.validate_integrity()
        if result.passed:
            raise ValueError("Q3 passed result cannot request revision")
        return tuple(_issue_failure(node="V4_RENDER_QA", code=issue.code, page_id=issue.page_id, fragment_id=issue.fragment_ref, region=issue.element_id) for issue in result.issues)
    raise ValueError("v4 revision node requires an exact failed Q0-Q3 result")


def _result_from_state(state: Mapping[str, Any]) -> object:
    values = tuple(value for key in ("render_qa_result_v4", "design_plan_qa_result_v4", "authoring_qa_result_v4", "semantic_qa_result_v4") if (value := state.get(key)) is not None)
    if len(values) != 1:
        raise ValueError("v4 revision node requires exactly one failed Q0-Q3 state result")
    return values[0]


def _normalized_failures_from_state(state: Mapping[str, Any]) -> tuple[NormalizedFailureV4, ...]:
    if "normalized_failures_v4" not in state:
        return _failures_from_result(_result_from_state(state))
    if any(state.get(key) is not None for key in ("render_qa_result_v4", "design_plan_qa_result_v4", "authoring_qa_result_v4", "semantic_qa_result_v4")):
        raise ValueError("v4 revision node cannot mix normalized and Q0-Q3 inputs")
    values = state["normalized_failures_v4"]
    if type(values) is not tuple or not values or any(type(item) is not NormalizedFailureV4 for item in values):
        raise ValueError("v4 revision node requires exact normalized failure tuple")
    for value in values:
        value.validate_contract()
    return values


def _select_upstream_failures(failures: tuple[NormalizedFailureV4, ...]) -> tuple[NormalizedFailureV4, ...]:
    """Repair the earliest layer; its exact failures invalidate later symptoms."""
    ordered_layers = ("SEMANTIC", "AUTHORING", "ASSET", "COMPOSITION", "LAYOUT", "RENDER", "AESTHETIC")
    layer_by_failure = {
        item.fingerprint.canonical_sha256: layer_for_failure_code(item.failure_code, node=item.fingerprint.node)
        for item in failures
    }
    target = next(layer for layer in ordered_layers if layer in layer_by_failure.values())
    selected = tuple(sorted((item for item in failures if layer_by_failure[item.fingerprint.canonical_sha256] == target), key=lambda item: item.fingerprint.canonical_sha256))
    if len({item.fingerprint.canonical_sha256 for item in selected}) != len(selected):
        raise ValueError("v4 revision normalized failures must be unique")
    return selected


def revision_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """Derive one repair request, append one event, and publish no human route."""
    if not isinstance(state, Mapping):
        raise TypeError("v4 revision node requires a state mapping")
    if "revision_request_v4" in state:
        raise ValueError("v4 revision node derives requests and rejects caller-supplied requests")
    candidate_id = state.get("candidate_id")
    if type(candidate_id) is not str:
        raise ValueError("v4 revision node requires a candidate_id")
    raw_history = state.get("revision_history_v4", ())
    if type(raw_history) is not tuple or any(type(event) is not RevisionEventV4 for event in raw_history):
        raise ValueError("v4 revision history must contain exact revision events")
    history = tuple(raw_history)
    inferred_prior = history[-1].revision_id if history else None
    prior = state.get("prior_revision_id", inferred_prior)
    if prior != inferred_prior:
        raise ValueError("v4 revision prior identity does not match durable history")
    failures = _select_upstream_failures(_normalized_failures_from_state(state))
    request = route_revision(
        failures, history, candidate_id=candidate_id, prior_revision_id=prior,
        page_brief_set=state.get("page_brief_set", state.get("page_briefs")),
        carousel_design_plan=state.get("carousel_design_plan_v4", state.get("carousel_design_plan")),
    )
    event = append_revision_event(request, failures, candidate_id=candidate_id, revision_id=f"revision-{len(history) + 1}")
    route = _ROUTE_FOR_LAYER[request.target_layer]
    return {
        "revision_request_v4": request, "revision_history_v4": (*history, event),
        "revision_invalidation_v4": request.invalidation, "route": route, "visual_route": route,
        "revision_route": route, "current_node": "V4_REVISION",
    }


v4_revision_node = revision_node

__all__ = ["revision_node", "v4_revision_node"]
