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


def test_revision_node_deduplicates_exact_normalized_failures_before_budgeting() -> None:
    """Would fail if duplicate QA evidence formed two event fingerprints or spent two slots."""
    failure = NormalizedFailureV4.from_fingerprint(
        FailureFingerprintV4.create(
            node="V4_RENDER_QA", page_id="page-1", failure_code="RENDER_OVERFLOW",
            affected_fragment_ids=(), geometry_region=None,
        )
    )

    result = revision_node(
        {"normalized_failures_v4": (failure, failure), "candidate_id": "candidate-a", "revision_history_v4": ()}
    )

    assert len(result["revision_request_v4"].failure_fingerprints) == 1
    assert len(result["revision_history_v4"][0].failure_fingerprints) == 1


def test_revision_node_rejects_same_fingerprint_with_tampered_payload() -> None:
    """Would fail if hash-key dedup hid a non-canonical duplicate payload attack."""
    failure = NormalizedFailureV4.from_fingerprint(
        FailureFingerprintV4.create(
            node="V4_RENDER_QA", page_id="page-1", failure_code="RENDER_OVERFLOW",
            affected_fragment_ids=(), geometry_region=None,
        )
    )
    forged = failure.model_copy(update={"page_id": "page-2"})

    with pytest.raises(ValueError):
        revision_node(
            {"normalized_failures_v4": (failure, forged), "candidate_id": "candidate-a", "revision_history_v4": ()}
        )


def test_revision_node_accepts_only_critic_failure_with_retained_passed_hard_gates(tmp_path) -> None:
    from tests.visual_design.v4.test_v4_render_qa import _world
    from tests.nodes.v4.test_design_qa import _fixture
    from src.visual_design.v4.render_qa import evaluate_v4_render
    from src.nodes.v4.design_qa import aggregate_design_qa

    values = _world(tmp_path)
    fixture = _fixture()
    q2 = aggregate_design_qa(
        semantic_qa=fixture["q0"], authoring_qa=fixture["q1"], carousel_design_plan=values["design_plan"],
        content_atom_set=values["content_atom_set"], content_lock=values["content_lock"],
        semantic_content_model=values["semantic_content_model"], page_brief_set=values["page_brief_set"],
        visual_direction_plan=values["visual_direction_plan"], asset_manifest=values["asset_manifest"],
    )
    assert q2.passed
    q3 = evaluate_v4_render(**values)
    failure = NormalizedFailureV4.from_fingerprint(FailureFingerprintV4.create(
        node="V4_VISUAL_CRITIC", page_id="page-1", failure_code="AESTHETIC_REVIEW_FAILED",
        affected_fragment_ids=(), geometry_region=None,
    ))
    result = revision_node({
        **values,
        "normalized_failures_v4": (failure,), "candidate_id": values["render_manifest"].candidate_id,
        "revision_history_v4": (), "semantic_qa_result": fixture["q0"],
        "authoring_qa_result": fixture["q1"], "design_plan_qa_result_v4": q2,
        "render_qa_result_v4": q3,
    })
    assert result["revision_request_v4"].target_layer == "AESTHETIC"
