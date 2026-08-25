"""Deterministic, bounded routing for immutable v4 visual revisions."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from src.schemas.v4.content import canonical_json_v4, canonical_sha256_v4
from src.schemas.v4.direction import PageBriefSetV4
from src.schemas.v4.layout import CarouselDesignPlanV4, GRAMMAR_IDS_V4
from src.schemas.v4.revision import (
    ApprovedGrammarAlternativeV4, FailureFingerprintV4, NormalizedFailureV4,
    RevisionEventV4, RevisionInvalidationV4, RevisionRequestV4,
    VisualExecutionInterrupted,
)

_SEMANTIC_CODES = frozenset({"VISIBLE_TEXT_MUTATED", "UNKNOWN_ATOM", "UNKNOWN_SOURCE_ATOM", "INVALID_BOUNDS", "COVERAGE_MISSING", "COVERAGE_GAP", "COVERAGE_OVERLAP", "COVERAGE_DUPLICATE", "SEQUENCE_INVALID", "PARENT_INVALID", "PARENT_CYCLE", "GROUP_INVALID", "GROUP_ORDER_INVALID", "SOURCE_ROLE_MISMATCH", "STEP_RELATION_LOST", "CHECKLIST_RELATION_LOST", "COMPARISON_RELATION_LOST", "TABLE_RELATION_LOST", "FORBIDDEN_VISIBLE_COPY", "Q0_FAILED", "HASH_BINDING_MISMATCH"})
_AUTHORING_CODES = frozenset({"SCHEMA_INVALID", "FRAGMENT_OWNERSHIP_MISSING", "FRAGMENT_OWNERSHIP_UNKNOWN", "FRAGMENT_OWNERSHIP_DUPLICATED", "PAGE_COUNT_INVALID", "PAGE_COUNT_MISMATCH", "PAGE_SEQUENCE_INVALID", "PAGE_ID_INVALID", "NARRATIVE_ROLE_EMPTY", "NARRATIVE_ROLE_REPEATED", "BEAT_OWNERSHIP_MISSING", "BEAT_OWNERSHIP_UNKNOWN", "BEAT_OWNERSHIP_DUPLICATED", "BEAT_FRAGMENT_MISSING", "BEAT_FRAGMENT_UNKNOWN", "BEAT_GROUP_UNKNOWN", "BEAT_FRAGMENT_BINDING_MISMATCH", "BEAT_TASK_KIND_MISMATCH", "PAGE_BRIEF_DUTY_EMPTY", "PAGE_BRIEF_DUPLICATE_SIGNATURE", "DENSITY_CURVE_MISMATCH", "DENSITY_CURVE_UNBALANCED", "VISUAL_PRIORITY_UNKNOWN", "NOTES_CANNOT_BE_PRIMARY", "Q1_FAILED", "REGIONAL_INFORMATION_DENSITY", "LARGEST_TEXT_BLOCK_RATIO", "RENDER_PAGE_ORDER"})
_ASSET_CODES = frozenset({"ASSET_DIRECTIVE_OWNERSHIP_MISSING", "ASSET_DIRECTIVE_OWNERSHIP_UNKNOWN", "ASSET_DIRECTIVE_OWNERSHIP_DUPLICATED", "ASSET_DIRECTIVE_PAGE_MISMATCH", "ASSET_DIRECTIVE_MISMATCH", "ASSET_DIRECTIVE_FRAGMENT_MISSING", "ASSET_DIRECTIVE_FRAGMENT_UNKNOWN", "ASSET_DIRECTIVE_FRAGMENT_CROSS_PAGE", "RENDER_ASSET", "RENDER_CROP", "RENDER_PATH"})
_COMPOSITION_CODES = frozenset({"FAMILY_MISMATCH", "COMPOSITION_REPEATED", "IMAGE_TEXT_AREA_RATIO"})
_LAYOUT_CODES = frozenset({"SAFE_MARGIN_NONCOMPLIANT", "UNINTENDED_OVERLAP", "MINIMUM_FONT_SIZE", "LOW_CONTRAST", "WHITESPACE_RATIO", "ALIGNMENT_AXIS_DEVIATION", "PAIRED_COLUMN_BALANCE", "SPACING_CONSISTENCY", "HEADING_BODY_HIERARCHY_RATIO", "VISUAL_CENTER_OFFSET", "EMPHASIS_COUNT", "LINE_LENGTH", "ORPHAN_LINE", "ORPHAN_HEADING", "RENDER_BOX_DRIFT", "RENDER_OVERFLOW"})
_RENDER_CODES = frozenset({"RENDER_INPUT_STALE", "RENDER_IDENTITY_MISMATCH", "RENDER_PAGE_MISSING", "RENDER_PAGE_BYTES", "RENDER_CONTACT_BYTES", "RENDER_DIMENSIONS", "RENDER_BLANK_OUTPUT", "RENDER_DOM_TEXT", "RENDER_FONT", "RENDER_GLYPH"})
_AESTHETIC_CODES = frozenset({"AESTHETIC_REVIEW_FAILED"})
_WHOLE_SET_CODES = frozenset({"FAMILY_MISMATCH", "PAGE_COUNT_INVALID", "PAGE_COUNT_MISMATCH", "PAGE_SEQUENCE_INVALID", "RENDER_PAGE_ORDER"})
_LAYER_ORDER = {"SEMANTIC": 0, "AUTHORING": 1, "ASSET": 2, "COMPOSITION": 3, "LAYOUT": 4, "RENDER": 5, "AESTHETIC": 6}
_INVALIDATION = {
    "SEMANTIC": ("semantic_content_model", "semantic_qa_result", "page_brief_set", "visual_direction_plan", "authoring_qa_result", "asset_manifest", "carousel_design_plan", "design_plan_qa_result", "render_manifest", "render_qa_result", "visual_critique", "human_review", "final_policy_attestation"),
    "AUTHORING": ("page_brief_set", "visual_direction_plan", "authoring_qa_result", "asset_manifest", "carousel_design_plan", "design_plan_qa_result", "render_manifest", "render_qa_result", "visual_critique", "human_review", "final_policy_attestation"),
    "ASSET": ("asset_manifest", "carousel_design_plan", "design_plan_qa_result", "render_manifest", "render_qa_result", "visual_critique", "human_review", "final_policy_attestation"),
    "COMPOSITION": ("carousel_design_plan", "design_plan_qa_result", "render_manifest", "render_qa_result", "visual_critique", "human_review", "final_policy_attestation"),
    "LAYOUT": ("carousel_design_plan", "design_plan_qa_result", "render_manifest", "render_qa_result", "visual_critique", "human_review", "final_policy_attestation"),
    "RENDER": ("render_manifest", "render_qa_result", "visual_critique", "human_review", "final_policy_attestation"),
    "AESTHETIC": ("visual_critique", "human_review", "final_policy_attestation"),
}


def layer_for_failure_code(code: str, *, node: str | None = None) -> str:
    if code == "HASH_BINDING_MISMATCH" and node == "V4_AUTHORING_QA":
        return "AUTHORING"
    for layer, codes in (("SEMANTIC", _SEMANTIC_CODES), ("AUTHORING", _AUTHORING_CODES), ("ASSET", _ASSET_CODES), ("COMPOSITION", _COMPOSITION_CODES), ("LAYOUT", _LAYOUT_CODES), ("RENDER", _RENDER_CODES), ("AESTHETIC", _AESTHETIC_CODES)):
        if code in codes:
            return layer
    raise ValueError("unknown v4 revision failure code")


def _checked_failures(value: NormalizedFailureV4 | Sequence[NormalizedFailureV4]) -> tuple[NormalizedFailureV4, ...]:
    raw = (value,) if type(value) is NormalizedFailureV4 else tuple(value)
    if not raw or any(type(item) is not NormalizedFailureV4 for item in raw):
        raise ValueError("revision router requires exact normalized failures")
    checked = tuple(sorted(raw, key=lambda item: item.fingerprint.canonical_sha256))
    if len({item.fingerprint.canonical_sha256 for item in checked}) != len(checked):
        raise ValueError("revision failures must have unique fingerprints")
    for item in checked:
        item.validate_contract()
    return checked


def _first_operation(layer: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return {
        "SEMANTIC": (("REBUILD_SEMANTIC",), ()), "AUTHORING": (("REPAGINATE",), ()),
        "ASSET": (("REBIND_ASSET",), ()), "COMPOSITION": (("CHANGE_GRAMMAR",), ()),
        "LAYOUT": (("REFLOW",), ()), "RENDER": (("RERENDER",), ()),
        "AESTHETIC": (("REVIEW_AESTHETIC",), ()),
    }[layer]


def _history_operation(layer: str, prior: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if prior == 0:
        return _first_operation(layer)
    if layer == "LAYOUT" and prior == 1:
        return ("CHANGE_GRAMMAR",), ("REFLOW",)
    raise ValueError("revision history repeats an exhausted fingerprint")


def _checked_history(history: Sequence[object], candidate_id: str) -> tuple[RevisionEventV4, ...]:
    checked: list[RevisionEventV4] = []
    counts: dict[str, int] = {}
    revision_ids: set[str] = set()
    for event in history:
        if type(event) is not RevisionEventV4:
            raise ValueError("revision history must contain exact revision events")
        event.validate_contract()
        if event.candidate_id != candidate_id or event.revision_id in revision_ids or event.prior_revision_id != (checked[-1].revision_id if checked else None):
            raise ValueError("revision history has invalid candidate identity or append lineage")
        layers = {layer_for_failure_code(item.failure_code, node=item.node) for item in event.fingerprints}
        if layers != {event.target_layer}:
            raise ValueError("revision history target layer is not derived from fingerprints")
        prior = max((counts.get(item.canonical_sha256, 0) for item in event.fingerprints), default=0)
        if event.operation != _history_operation(event.target_layer, prior)[0][0]:
            raise ValueError("revision history operation is not the derived ladder operation")
        for item in event.fingerprints:
            counts[item.canonical_sha256] = counts.get(item.canonical_sha256, 0) + 1
        revision_ids.add(event.revision_id)
        checked.append(event)
    return tuple(checked)


def _approved_alternatives(failures: tuple[NormalizedFailureV4, ...], page_brief_set: PageBriefSetV4 | None, carousel_design_plan: CarouselDesignPlanV4 | None) -> tuple[tuple[ApprovedGrammarAlternativeV4, ...], str | None, str | None]:
    if type(page_brief_set) is not PageBriefSetV4 or type(carousel_design_plan) is not CarouselDesignPlanV4:
        return (), None, None
    page_brief_set.validate_integrity()
    carousel_design_plan.validate_integrity()
    if carousel_design_plan.page_brief_set_sha256 != page_brief_set.canonical_sha256:
        raise ValueError("revision grammar context has stale page-brief binding")
    briefs = {page.page_id: page for page in page_brief_set.pages}
    plans = {page.page_id: page for page in carousel_design_plan.pages}
    alternatives = []
    for failure in failures:
        brief, plan = briefs.get(failure.page_id), plans.get(failure.page_id)
        if brief is None or plan is None:
            raise ValueError("revision grammar context is missing an affected page")
        approved = tuple(grammar for grammar in brief.preferred_compositions if grammar in GRAMMAR_IDS_V4 and grammar != plan.layout_program.grammar_id)
        if not approved:
            return (), None, None
        alternatives.append(ApprovedGrammarAlternativeV4.create(page_id=failure.page_id, grammar_id=approved[0]))
    return tuple(sorted(alternatives, key=lambda item: item.page_id)), page_brief_set.canonical_sha256, carousel_design_plan.canonical_sha256


def _invalidation(layer: str, codes: tuple[str, ...], pages: tuple[str, ...]) -> RevisionInvalidationV4:
    whole = any(code in _WHOLE_SET_CODES for code in codes)
    return RevisionInvalidationV4.create(invalidate_whole_set=whole, rebuild_page_ids=() if whole else pages, downstream_contracts=_INVALIDATION[layer])


def route_revision(failure: NormalizedFailureV4 | Sequence[NormalizedFailureV4], history: Sequence[RevisionEventV4], *, candidate_id: str, prior_revision_id: str | None, page_brief_set: PageBriefSetV4 | None = None, carousel_design_plan: CarouselDesignPlanV4 | None = None) -> RevisionRequestV4:
    failures = _checked_failures(failure)
    checked_history = _checked_history(history, candidate_id)
    expected_prior = checked_history[-1].revision_id if checked_history else None
    if prior_revision_id != expected_prior:
        raise ValueError("revision prior identity does not match durable history")
    layers = {layer_for_failure_code(item.failure_code, node=item.fingerprint.node) for item in failures}
    if len(layers) != 1:
        raise ValueError("revision router requires one target layer")
    layer = next(iter(layers))
    counts = {item.fingerprint.canonical_sha256: sum(item.fingerprint.canonical_sha256 in event.failure_fingerprints for event in checked_history) for item in failures}
    exhausted = tuple(sorted(key for key, count in counts.items() if count >= 2))
    if exhausted or (layer != "LAYOUT" and max(counts.values()) >= 1):
        raise VisualExecutionInterrupted(failure_node=failures[0].fingerprint.node, candidate_id=candidate_id, revision_id=expected_prior, repeated_fingerprints=exhausted or tuple(sorted(counts)), consumed_budget=max(counts.values()) + 1, recovery_action="START_NEW_CANDIDATE")
    prior = max(counts.values())
    permitted, forbidden = _history_operation(layer, prior)
    alternatives: tuple[ApprovedGrammarAlternativeV4, ...] = ()
    brief_hash: str | None = None
    plan_hash: str | None = None
    if layer == "LAYOUT" and permitted == ("CHANGE_GRAMMAR",):
        alternatives, brief_hash, plan_hash = _approved_alternatives(failures, page_brief_set, carousel_design_plan)
        if not alternatives:
            raise VisualExecutionInterrupted(failure_node=failures[0].fingerprint.node, candidate_id=candidate_id, revision_id=expected_prior, repeated_fingerprints=tuple(sorted(counts)), consumed_budget=prior + 1, recovery_action="START_NEW_CANDIDATE")
    pages = tuple(sorted({item.page_id for item in failures}))
    payload = {"target_layer": layer, "affected_pages": pages, "failure_codes": tuple(sorted({item.failure_code for item in failures})), "failure_fingerprints": tuple(item.fingerprint.canonical_sha256 for item in failures), "sanitized_evidence": tuple(item.sanitized_evidence for item in failures), "permitted_operations": permitted, "forbidden_operations": forbidden, "prior_revision_id": expected_prior, "page_brief_set_sha256": brief_hash, "carousel_design_plan_sha256": plan_hash, "approved_grammar_alternatives": alternatives, "invalidation": _invalidation(layer, tuple(item.failure_code for item in failures), pages)}
    return RevisionRequestV4(**payload, canonical_sha256=canonical_sha256_v4(payload))


def append_revision_event(request: RevisionRequestV4, failure: NormalizedFailureV4 | Sequence[NormalizedFailureV4], *, candidate_id: str, revision_id: str) -> RevisionEventV4:
    if type(request) is not RevisionRequestV4:
        raise ValueError("revision event requires an exact request")
    request.validate_contract()
    failures = _checked_failures(failure)
    fingerprints = tuple(item.fingerprint for item in failures)
    if request.failure_fingerprints != tuple(item.canonical_sha256 for item in fingerprints):
        raise ValueError("revision request does not bind all failure fingerprints")
    return RevisionEventV4.create(candidate_id=candidate_id, revision_id=revision_id, prior_revision_id=request.prior_revision_id, fingerprints=fingerprints, target_layer=request.target_layer, affected_pages=request.affected_pages, operation=request.permitted_operations[0])


def serialize_revision_state(state: Mapping[str, Any]) -> bytes:
    if not isinstance(state, Mapping) or not isinstance(state.get("revision_history_v4", ()), tuple):
        raise ValueError("revision state must contain tuple history")
    history = state.get("revision_history_v4", ())
    for event in history:
        if type(event) is not RevisionEventV4:
            raise ValueError("revision state history must contain exact events")
        event.validate_contract()
    return canonical_json_v4({"revision_history_v4": history}).encode("utf-8")


def deserialize_revision_state(value: bytes) -> dict[str, tuple[RevisionEventV4, ...]]:
    if type(value) is not bytes:
        raise ValueError("serialized revision state must be bytes")
    try:
        raw = json.loads(value.decode("utf-8"))
        if set(raw) != {"revision_history_v4"} or not isinstance(raw["revision_history_v4"], list):
            raise ValueError
        history = tuple(RevisionEventV4.model_validate_json(canonical_json_v4(item)) for item in raw["revision_history_v4"])
    except Exception:
        raise ValueError("serialized revision state is invalid") from None
    return {"revision_history_v4": history}


__all__ = ["append_revision_event", "deserialize_revision_state", "layer_for_failure_code", "route_revision", "serialize_revision_state"]
