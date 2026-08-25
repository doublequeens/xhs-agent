"""RED regression tests for durable v4 revision routing state."""

from __future__ import annotations

import pytest

from src.schemas.v4.revision import FailureFingerprintV4, NormalizedFailureV4, RevisionEventV4, VisualExecutionInterrupted
from src.visual_design.v4.revisions import deserialize_revision_state, route_revision, serialize_revision_state


def _failure(page_id: str) -> NormalizedFailureV4:
    return NormalizedFailureV4.from_fingerprint(
        FailureFingerprintV4.create(
            node="V4_RENDER_QA",
            page_id=page_id,
            failure_code="RENDER_OVERFLOW",
            affected_fragment_ids=("fragment-1",),
            geometry_region="body",
        )
    )


def _event(failure: NormalizedFailureV4) -> RevisionEventV4:
    return RevisionEventV4.create(
        candidate_id="candidate-a",
        revision_id="revision-1",
        prior_revision_id=None,
        fingerprint=failure.fingerprint,
        target_layer="LAYOUT",
        affected_pages=(failure.page_id,),
        operation="REFLOW",
    )


def test_resume_serialization_preserves_budget_and_canonical_bytes() -> None:
    """Would fail if ordinary resume reset the first identical-failure repair."""
    failure = _failure("page-2")
    state = {"revision_history_v4": (_event(failure),)}

    serialized = serialize_revision_state(state)
    resumed = deserialize_revision_state(serialized)
    with pytest.raises(VisualExecutionInterrupted):
        route_revision(
            failure,
            history=resumed["revision_history_v4"],
            candidate_id="candidate-a",
            prior_revision_id="revision-1",
        )

    assert serialize_revision_state(resumed) == serialized


def test_different_fingerprint_does_not_share_candidate_budget() -> None:
    """Would fail if a candidate-wide counter exhausted an unrelated page."""
    first = _failure("page-2")
    second = _failure("page-3")

    request = route_revision(
        second,
        history=(_event(first),),
        candidate_id="candidate-a",
        prior_revision_id="revision-1",
    )

    assert request.permitted_operations == ("REFLOW",)
    assert request.affected_pages == ("page-3",)


def test_invalidation_is_whole_set_only_for_family_or_page_order_changes() -> None:
    """Would fail if a page-only repair invalidated unrelated rendered pages."""
    layout = _failure("page-2")
    whole_set = NormalizedFailureV4.from_fingerprint(
        FailureFingerprintV4.create(
            node="V4_AUTHORING_QA",
            page_id="page-2",
            failure_code="PAGE_COUNT_INVALID",
            affected_fragment_ids=(),
            geometry_region=None,
        )
    )

    page_request = route_revision(layout, history=(), candidate_id="candidate-a", prior_revision_id=None)
    whole_request = route_revision(whole_set, history=(), candidate_id="candidate-a", prior_revision_id=None)

    assert page_request.invalidate_whole_set is False
    assert page_request.affected_pages == ("page-2",)
    assert whole_request.invalidate_whole_set is True
