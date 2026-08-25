"""Strict graph boundary for deterministic v4 visual repair routing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.schemas.v4.direction import AuthoringQAResultV4
from src.schemas.v4.quality import DesignPlanQAResultV4
from src.schemas.v4.rendering import RenderManifestV4, RenderQAResultV4
from src.schemas.v4.direction import PageBriefSetV4
from src.schemas.v4.semantic import SemanticContentModelV4
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
    values = tuple(value for value in (
        state.get("render_qa_result_v4", state.get("render_qa_result")),
        state.get("design_plan_qa_result_v4", state.get("design_plan_qa_result")),
        state.get("authoring_qa_result"), state.get("semantic_qa_result"),
    ) if value is not None)
    if len(values) != 1:
        raise ValueError("v4 revision node requires exactly one failed Q0-Q3 state result")
    return values[0]


def _normalized_failures_from_state(state: Mapping[str, Any]) -> tuple[NormalizedFailureV4, ...]:
    if "normalized_failures_v4" not in state:
        return _failures_from_result(_result_from_state(state))
    values = state["normalized_failures_v4"]
    if type(values) is not tuple or not values or any(type(item) is not NormalizedFailureV4 for item in values):
        raise ValueError("v4 revision node requires exact normalized failure tuple")
    for value in values:
        value.validate_contract()
    retained = (
        state.get("render_qa_result_v4", state.get("render_qa_result")),
        state.get("design_plan_qa_result_v4", state.get("design_plan_qa_result")),
        state.get("authoring_qa_result"), state.get("semantic_qa_result"),
    )
    if all(item is None for item in retained) and all(item.fingerprint.node == "V4_VISUAL_CRITIC" for item in values):
        raise ValueError("v4 aesthetic revision requires retained passed Q0-Q3 evidence")
    if any(item is not None for item in retained):
        # Q4 is the one valid normalized consumer that follows passed Q0-Q3.
        # It must carry only the exact closed critic failure and every retained
        # hard gate must still be exact, validated and passed.
        if any(item.fingerprint.node != "V4_VISUAL_CRITIC" or item.failure_code != "AESTHETIC_REVIEW_FAILED" for item in values):
            raise ValueError("v4 revision node cannot mix non-aesthetic normalized failures with hard-QA evidence")
        expected = (RenderQAResultV4, DesignPlanQAResultV4, AuthoringQAResultV4, SemanticQAResultV4)
        if any(type(item) is not model for item, model in zip(retained, expected, strict=True)):
            raise ValueError("v4 aesthetic revision requires all exact retained Q0-Q3 evidence")
        try:
            for item in retained:
                item.validate_integrity()
                if not item.passed:
                    raise ValueError
            manifest = state.get("render_manifest_v4", state.get("render_manifest"))
            page_set = state.get("page_brief_set", state.get("page_briefs"))
            semantic = state.get("semantic_content_model", state.get("semantic_model"))
            if type(manifest) is not RenderManifestV4 or type(page_set) is not PageBriefSetV4 or type(semantic) is not SemanticContentModelV4:
                raise ValueError
            manifest.validate_integrity(); page_set.validate_integrity(); semantic.validate_integrity()
            q3, q2 = retained[0], retained[1]
            if q2.semantic_qa != retained[3] or q2.authoring_qa != retained[2]:
                raise ValueError
            if (q3.render_manifest_sha256 != manifest.canonical_sha256 or q3.design_plan_qa_sha256 != q2.canonical_sha256 or q3.page_brief_set_sha256 != page_set.canonical_sha256 or q3.semantic_content_model_sha256 != semantic.canonical_sha256):
                raise ValueError
        except Exception:
            raise ValueError("v4 aesthetic revision requires fresh passed Q0-Q3 evidence") from None
    return values


def _select_upstream_failures(failures: tuple[NormalizedFailureV4, ...]) -> tuple[NormalizedFailureV4, ...]:
    """Repair the earliest layer; its exact failures invalidate later symptoms."""
    ordered_layers = ("SEMANTIC", "AUTHORING", "ASSET", "COMPOSITION", "LAYOUT", "RENDER", "AESTHETIC")
    unique: dict[str, NormalizedFailureV4] = {}
    for item in failures:
        key = item.fingerprint.canonical_sha256
        previous = unique.get(key)
        if previous is not None and previous.model_dump(mode="json") != item.model_dump(mode="json"):
            raise ValueError("same v4 revision fingerprint has inconsistent normalized payload")
        unique[key] = item
    deduplicated = tuple(unique[key] for key in sorted(unique))
    layer_by_failure = {
        item.fingerprint.canonical_sha256: layer_for_failure_code(item.failure_code, node=item.fingerprint.node)
        for item in deduplicated
    }
    target = next(layer for layer in ordered_layers if layer in layer_by_failure.values())
    selected = tuple(item for item in deduplicated if layer_by_failure[item.fingerprint.canonical_sha256] == target)
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
    event = append_revision_event(
        request, failures, candidate_id=candidate_id, revision_id=f"revision-{len(history) + 1}",
        page_brief_set=state.get("page_brief_set", state.get("page_briefs")),
        carousel_design_plan=state.get("carousel_design_plan_v4", state.get("carousel_design_plan")),
    )
    route = _ROUTE_FOR_LAYER[request.target_layer]
    return {
        "revision_request_v4": request, "revision_history_v4": (*history, event),
        "revision_invalidation_v4": request.invalidation, "route": route, "visual_route": route,
        "revision_route": route, "current_node": "V4_REVISION",
    }


v4_revision_node = revision_node

__all__ = ["revision_node", "v4_revision_node"]
