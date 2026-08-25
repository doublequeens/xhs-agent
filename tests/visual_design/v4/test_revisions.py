"""RED tests for deterministic, bounded v4 revision routing."""

from __future__ import annotations

import pytest

from src.schemas.v4.revision import (
    FailureFingerprintV4,
    NormalizedFailureV4,
    RevisionEventV4,
    VisualExecutionInterrupted,
)
from src.visual_design.v4.revisions import route_revision


def _failure(*, page_id: str = "page-9", code: str = "RENDER_OVERFLOW") -> NormalizedFailureV4:
    fingerprint = FailureFingerprintV4.create(
        node="V4_RENDER_QA",
        page_id=page_id,
        failure_code=code,
        affected_fragment_ids=("fragment-1",),
        geometry_region="body",
    )
    return NormalizedFailureV4.from_fingerprint(fingerprint)


def _event(failure: NormalizedFailureV4, operation: str, revision_id: str, prior_revision_id: str | None = None) -> RevisionEventV4:
    return RevisionEventV4.create(
        candidate_id="candidate-a",
        revision_id=revision_id,
        prior_revision_id=prior_revision_id,
        fingerprint=failure.fingerprint,
        target_layer="LAYOUT",
        affected_pages=("page-9",),
        operation=operation,
    )


def test_second_same_fingerprint_must_change_operation() -> None:
    """Would fail if the router repeats the first deterministic repair."""
    failure = _failure()

    request = route_revision(
        failure,
        history=(_event(failure, "REFLOW", "revision-1"),),
        candidate_id="candidate-a",
        prior_revision_id="revision-1",
    )

    assert request.permitted_operations == ("CHANGE_GRAMMAR",)
    assert request.forbidden_operations == ("REFLOW",)
    assert request.target_layer == "LAYOUT"


def test_third_same_fingerprint_exhausts_candidate() -> None:
    """Would fail if a third identical failure silently repaginates."""
    failure = _failure()
    history = (
        _event(failure, "REFLOW", "revision-1"),
        _event(failure, "CHANGE_GRAMMAR", "revision-2", "revision-1"),
    )

    with pytest.raises(VisualExecutionInterrupted) as exc:
        route_revision(
            failure,
            history=history,
            candidate_id="candidate-a",
            prior_revision_id="revision-2",
        )

    assert exc.value.execution_state == "INTERRUPTED_EXHAUSTED"
    assert exc.value.repeated_fingerprints == (failure.fingerprint.canonical_sha256,)


def test_unknown_code_and_forged_fingerprint_fail_closed() -> None:
    """Would fail if routing trusted caller-controlled code or digest fields."""
    with pytest.raises(ValueError):
        FailureFingerprintV4.create(
            node="V4_RENDER_QA",
            page_id="page-9",
            failure_code="INVENTED_FAILURE",
            affected_fragment_ids=(),
            geometry_region=None,
        )

    failure = _failure()
    forged = failure.model_copy(
        update={"fingerprint": failure.fingerprint.model_copy(update={"canonical_sha256": "0" * 64})}
    )
    with pytest.raises(ValueError):
        route_revision(forged, history=(), candidate_id="candidate-a", prior_revision_id=None)


def test_history_with_forged_operation_does_not_consume_budget() -> None:
    """Would fail if a caller could spend a repair slot using a mismatched operation."""
    failure = _failure()
    forged_event = _event(failure, "RERENDER", "revision-1")

    with pytest.raises(ValueError):
        route_revision(
            failure,
            history=(forged_event,),
            candidate_id="candidate-a",
            prior_revision_id="revision-1",
        )
