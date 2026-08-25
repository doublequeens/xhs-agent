"""Deterministic revision routing for immutable v4 visual contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.schemas.v4.content import canonical_json_v4, canonical_sha256_v4
from src.schemas.v4.revision import (
    FailureFingerprintV4,
    NormalizedFailureV4,
    RevisionEventV4,
    RevisionInvalidationV4,
    RevisionRequestV4,
    VisualExecutionInterrupted,
)


_SEMANTIC_CODES = frozenset({
    "VISIBLE_TEXT_MUTATED", "UNKNOWN_ATOM", "UNKNOWN_SOURCE_ATOM", "INVALID_BOUNDS",
    "COVERAGE_MISSING", "COVERAGE_GAP", "COVERAGE_OVERLAP", "COVERAGE_DUPLICATE",
    "SEQUENCE_INVALID", "PARENT_INVALID", "PARENT_CYCLE", "GROUP_INVALID", "GROUP_ORDER_INVALID",
    "SOURCE_ROLE_MISMATCH", "STEP_RELATION_LOST", "CHECKLIST_RELATION_LOST",
    "COMPARISON_RELATION_LOST", "TABLE_RELATION_LOST", "FORBIDDEN_VISIBLE_COPY", "Q0_FAILED",
    "HASH_BINDING_MISMATCH",
})
_AUTHORING_CODES = frozenset({
    "SCHEMA_INVALID", "FRAGMENT_OWNERSHIP_MISSING", "FRAGMENT_OWNERSHIP_UNKNOWN",
    "FRAGMENT_OWNERSHIP_DUPLICATED", "PAGE_COUNT_INVALID", "PAGE_COUNT_MISMATCH",
    "PAGE_SEQUENCE_INVALID", "PAGE_ID_INVALID", "NARRATIVE_ROLE_EMPTY", "NARRATIVE_ROLE_REPEATED",
    "BEAT_OWNERSHIP_MISSING", "BEAT_OWNERSHIP_UNKNOWN", "BEAT_OWNERSHIP_DUPLICATED",
    "BEAT_FRAGMENT_MISSING", "BEAT_FRAGMENT_UNKNOWN", "BEAT_GROUP_UNKNOWN",
    "BEAT_FRAGMENT_BINDING_MISMATCH", "BEAT_TASK_KIND_MISMATCH", "PAGE_BRIEF_DUTY_EMPTY",
    "PAGE_BRIEF_DUPLICATE_SIGNATURE", "DENSITY_CURVE_MISMATCH", "DENSITY_CURVE_UNBALANCED",
    "VISUAL_PRIORITY_UNKNOWN", "NOTES_CANNOT_BE_PRIMARY", "Q1_FAILED",
    "REGIONAL_INFORMATION_DENSITY", "LARGEST_TEXT_BLOCK_RATIO",
    "RENDER_PAGE_ORDER",
})
_ASSET_CODES = frozenset({
    "ASSET_DIRECTIVE_OWNERSHIP_MISSING", "ASSET_DIRECTIVE_OWNERSHIP_UNKNOWN",
    "ASSET_DIRECTIVE_OWNERSHIP_DUPLICATED", "ASSET_DIRECTIVE_PAGE_MISMATCH",
    "ASSET_DIRECTIVE_MISMATCH", "ASSET_DIRECTIVE_FRAGMENT_MISSING",
    "ASSET_DIRECTIVE_FRAGMENT_UNKNOWN", "ASSET_DIRECTIVE_FRAGMENT_CROSS_PAGE",
    "RENDER_ASSET", "RENDER_CROP", "RENDER_PATH",
})
_COMPOSITION_CODES = frozenset({"FAMILY_MISMATCH", "COMPOSITION_REPEATED", "IMAGE_TEXT_AREA_RATIO"})
_LAYOUT_CODES = frozenset({
    "SAFE_MARGIN_NONCOMPLIANT", "UNINTENDED_OVERLAP", "MINIMUM_FONT_SIZE", "LOW_CONTRAST",
    "WHITESPACE_RATIO", "ALIGNMENT_AXIS_DEVIATION", "PAIRED_COLUMN_BALANCE",
    "SPACING_CONSISTENCY", "HEADING_BODY_HIERARCHY_RATIO", "VISUAL_CENTER_OFFSET",
    "EMPHASIS_COUNT", "LINE_LENGTH", "ORPHAN_LINE", "ORPHAN_HEADING",
    "RENDER_BOX_DRIFT", "RENDER_OVERFLOW",
})
_RENDER_CODES = frozenset({
    "RENDER_INPUT_STALE", "RENDER_IDENTITY_MISMATCH", "RENDER_PAGE_MISSING", "RENDER_PAGE_BYTES",
    "RENDER_CONTACT_BYTES", "RENDER_DIMENSIONS", "RENDER_BLANK_OUTPUT", "RENDER_DOM_TEXT",
    "RENDER_FONT", "RENDER_GLYPH",
})
_AESTHETIC_CODES = frozenset({"AESTHETIC_REVIEW_FAILED"})
_WHOLE_SET_CODES = frozenset({"FAMILY_MISMATCH", "PAGE_COUNT_INVALID", "PAGE_COUNT_MISMATCH", "PAGE_SEQUENCE_INVALID", "RENDER_PAGE_ORDER"})
_PAGE_CONTRACTS = ("carousel_design_plan", "design_plan_qa_result", "render_manifest", "render_qa_result", "visual_critique")
_WHOLE_CONTRACTS = ("page_brief_set", "visual_direction_plan", "asset_manifest", *_PAGE_CONTRACTS)


def layer_for_failure_code(code: str, *, node: str | None = None) -> str:
    """Map every closed v4 code to its narrowest permitted repair layer."""
    if code == "HASH_BINDING_MISMATCH" and node == "V4_AUTHORING_QA":
        return "AUTHORING"
    if code in _SEMANTIC_CODES:
        return "SEMANTIC"
    if code in _AUTHORING_CODES:
        return "AUTHORING"
    if code in _ASSET_CODES:
        return "ASSET"
    if code in _COMPOSITION_CODES:
        return "COMPOSITION"
    if code in _LAYOUT_CODES:
        return "LAYOUT"
    if code in _RENDER_CODES:
        return "RENDER"
    if code in _AESTHETIC_CODES:
        return "AESTHETIC"
    raise ValueError("unknown v4 revision failure code")


def _checked_failure(value: object) -> NormalizedFailureV4:
    if type(value) is not NormalizedFailureV4:
        raise ValueError("revision router requires an exact normalized failure")
    value.validate_contract()
    return value


def _checked_history(history: Sequence[object], candidate_id: str) -> tuple[RevisionEventV4, ...]:
    checked: list[RevisionEventV4] = []
    seen_revision_ids: set[str] = set()
    for value in history:
        if type(value) is not RevisionEventV4:
            raise ValueError("revision history must contain exact revision events")
        value.validate_contract()
        if value.candidate_id != candidate_id or value.revision_id in seen_revision_ids:
            raise ValueError("revision history has mixed candidate identity or duplicate revision id")
        if value.prior_revision_id != (checked[-1].revision_id if checked else None):
            raise ValueError("revision history revision lineage is not append-only")
        expected_layer = layer_for_failure_code(value.fingerprint.failure_code, node=value.fingerprint.node)
        if value.target_layer != expected_layer:
            raise ValueError("revision history target layer is not derived from its failure code")
        previous_matches = sum(
            event.fingerprint.canonical_sha256 == value.fingerprint.canonical_sha256
            for event in checked
        )
        if previous_matches >= 2:
            raise ValueError("revision history exceeds the bounded fingerprint budget")
        permitted, _forbidden = _operation(expected_layer, previous_matches)
        if value.operation != permitted[0]:
            raise ValueError("revision history operation is not the derived ladder operation")
        seen_revision_ids.add(value.revision_id)
        checked.append(value)
    return tuple(checked)


def _operation(layer: str, prior_count: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if prior_count >= 2:
        raise AssertionError("exhaustion must be handled before operation selection")
    if layer == "LAYOUT":
        return (("REFLOW",), ()) if prior_count == 0 else (("CHANGE_GRAMMAR",), ("REFLOW",))
    if layer == "SEMANTIC":
        return (("REBUILD_SEMANTIC",), ())
    if layer == "AUTHORING":
        return (("REPAGINATE",), ())
    if layer == "ASSET":
        return (("REBIND_ASSET",), ())
    if layer == "COMPOSITION":
        return (("CHANGE_GRAMMAR",), ())
    if layer == "RENDER":
        return (("RERENDER",), ())
    if layer == "AESTHETIC":
        return (("REVIEW_AESTHETIC",), ())
    raise ValueError("unknown revision layer")


def _invalidation(code: str, pages: tuple[str, ...]) -> RevisionInvalidationV4:
    whole = code in _WHOLE_SET_CODES
    return RevisionInvalidationV4.create(
        invalidate_whole_set=whole,
        rebuild_page_ids=() if whole else pages,
        downstream_contracts=_WHOLE_CONTRACTS if whole else _PAGE_CONTRACTS,
    )


def route_revision(
    failure: NormalizedFailureV4,
    history: Sequence[RevisionEventV4],
    *,
    candidate_id: str,
    prior_revision_id: str | None,
) -> RevisionRequestV4:
    """Derive a single repair request or exhaust the exact repeated failure.

    Counts are keyed by fingerprint and candidate, never by a global or
    candidate-wide counter.  This is intentionally independent of wall clock,
    UUIDs, provider attempts, and checkpoint serialization format.
    """
    failure = _checked_failure(failure)
    checked_history = _checked_history(history, candidate_id)
    layer = layer_for_failure_code(failure.failure_code, node=failure.fingerprint.node)
    matches = tuple(
        event for event in checked_history
        if event.fingerprint.canonical_sha256 == failure.fingerprint.canonical_sha256
    )
    if len(matches) >= 2:
        raise VisualExecutionInterrupted(
            failure_node=failure.fingerprint.node,
            candidate_id=candidate_id,
            revision_id=prior_revision_id,
            repeated_fingerprints=(failure.fingerprint.canonical_sha256,),
            consumed_budget=len(matches) + 1,
            recovery_action="START_NEW_CANDIDATE",
        )
    permitted, forbidden = _operation(layer, len(matches))
    payload = {
        "target_layer": layer,
        "affected_pages": (failure.page_id,),
        "failure_codes": (failure.failure_code,),
        "failure_fingerprints": (failure.fingerprint.canonical_sha256,),
        "sanitized_evidence": (failure.sanitized_evidence,),
        "permitted_operations": permitted,
        "forbidden_operations": forbidden,
        "prior_revision_id": prior_revision_id,
        "invalidation": _invalidation(failure.failure_code, (failure.page_id,)),
    }
    return RevisionRequestV4(**payload, canonical_sha256=canonical_sha256_v4(payload))


def append_revision_event(
    request: RevisionRequestV4,
    failure: NormalizedFailureV4,
    *,
    candidate_id: str,
    revision_id: str,
) -> RevisionEventV4:
    """Record exactly the operation selected by this request, not caller input."""
    if type(request) is not RevisionRequestV4 or type(failure) is not NormalizedFailureV4:
        raise ValueError("revision event requires exact request and normalized failure")
    request.validate_contract()
    failure.validate_contract()
    if request.failure_fingerprints != (failure.fingerprint.canonical_sha256,):
        raise ValueError("revision request does not bind the failure fingerprint")
    return RevisionEventV4.create(
        candidate_id=candidate_id,
        revision_id=revision_id,
        prior_revision_id=request.prior_revision_id,
        fingerprint=failure.fingerprint,
        target_layer=request.target_layer,
        affected_pages=request.affected_pages,
        operation=request.permitted_operations[0],
    )


def serialize_revision_state(state: Mapping[str, Any]) -> bytes:
    """Serialize only strict history in canonical form for resume tests/checkpoints."""
    if not isinstance(state, Mapping):
        raise ValueError("revision state must be a mapping")
    history = state.get("revision_history_v4", ())
    if not isinstance(history, tuple):
        raise ValueError("revision state history must be a tuple")
    for event in history:
        if type(event) is not RevisionEventV4:
            raise ValueError("revision state history must contain exact events")
        event.validate_contract()
    return canonical_json_v4({"revision_history_v4": history}).encode("utf-8")


def deserialize_revision_state(value: bytes) -> dict[str, tuple[RevisionEventV4, ...]]:
    """Restore strict history; an ordinary resume never clears it."""
    if type(value) is not bytes:
        raise ValueError("serialized revision state must be bytes")
    import json
    try:
        raw = json.loads(value.decode("utf-8"))
        if set(raw) != {"revision_history_v4"} or not isinstance(raw["revision_history_v4"], list):
            raise ValueError
        history = tuple(RevisionEventV4.model_validate_json(canonical_json_v4(item)) for item in raw["revision_history_v4"])
    except Exception:
        raise ValueError("serialized revision state is invalid") from None
    return {"revision_history_v4": history}


__all__ = [
    "append_revision_event", "deserialize_revision_state", "layer_for_failure_code", "route_revision", "serialize_revision_state",
]
