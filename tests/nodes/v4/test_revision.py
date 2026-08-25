"""RED tests for the strict v4 revision node boundary."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.nodes.v4.revision import revision_node
from src.schemas.v4.revision import FailureFingerprintV4, NormalizedFailureV4


def test_revision_node_rejects_duck_typed_failed_result() -> None:
    """Would fail if a caller could bypass exact Q0-Q3 model validation."""
    with pytest.raises(ValueError):
        revision_node(
            {
                "render_qa_result_v4": SimpleNamespace(
                    passed=False,
                    issues=(SimpleNamespace(code="RENDER_OVERFLOW"),),
                ),
                "candidate_id": "candidate-a",
                "revision_history_v4": (),
            }
        )


def test_revision_node_rejects_caller_forged_operations() -> None:
    """Would fail if node routing accepted an externally supplied request."""
    with pytest.raises(ValueError):
        revision_node(
            {
                "revision_request_v4": {"permitted_operations": ("REPAGINATE",)},
                "candidate_id": "candidate-a",
                "revision_history_v4": (),
            }
        )


def test_revision_node_aggregates_exact_normalized_same_layer_failures() -> None:
    """Would fail if multi-page hard-QA failures were discarded or routed one at a time."""
    failures = tuple(
        NormalizedFailureV4.from_fingerprint(
            FailureFingerprintV4.create(
                node="V4_RENDER_QA",
                page_id=page_id,
                failure_code="RENDER_OVERFLOW",
                affected_fragment_ids=(),
                geometry_region=None,
            )
        )
        for page_id in ("page-2", "page-1")
    )

    result = revision_node(
        {
            "normalized_failures_v4": failures,
            "candidate_id": "candidate-a",
            "revision_history_v4": (),
        }
    )

    assert result["revision_request_v4"].target_layer == "LAYOUT"
    assert result["revision_request_v4"].affected_pages == ("page-1", "page-2")
    assert len(result["revision_history_v4"][0].failure_fingerprints) == 2


def test_revision_node_selects_earliest_layer_and_drops_downstream_failures() -> None:
    """Would fail if a mixed hard-QA set spent budget on downstream symptoms."""
    semantic = NormalizedFailureV4.from_fingerprint(
        FailureFingerprintV4.create(
            node="V4_SEMANTIC_QA", page_id="all", failure_code="VISIBLE_TEXT_MUTATED",
            affected_fragment_ids=(), geometry_region=None,
        )
    )
    render = NormalizedFailureV4.from_fingerprint(
        FailureFingerprintV4.create(
            node="V4_RENDER_QA", page_id="page-1", failure_code="RENDER_OVERFLOW",
            affected_fragment_ids=(), geometry_region=None,
        )
    )

    result = revision_node(
        {"normalized_failures_v4": (render, semantic), "candidate_id": "candidate-a", "revision_history_v4": ()}
    )

    assert result["revision_request_v4"].target_layer == "SEMANTIC"
    assert result["revision_request_v4"].failure_codes == ("VISIBLE_TEXT_MUTATED",)
