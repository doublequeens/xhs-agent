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


def _approved_layout_context():
    from src.nodes.v4.composition import build_layout_program
    from src.nodes.v4.layout import aggregate_layout_plan
    from src.schemas.assets import AssetManifest
    from src.schemas.v4.content import canonical_sha256_v4
    from src.schemas.v4.direction import PageBriefSetV4, PageBriefV4, VisualDirectionPlanV4
    from src.visual_design.v4.compiler import LayoutCompilerInputsV4, compile_layout
    from src.visual_design.v4.tokens import get_family_tokens
    from tests.nodes.v4.test_layout import _direction_upstream

    atom_set, semantic, page_set, narrative, direction, _compiled = _direction_upstream()
    first_payload = page_set.pages[0].model_dump(mode="python")
    first_payload["preferred_compositions"] = ("editorial_hero", "comparison_grid")
    first_payload.pop("canonical_sha256", None)
    first_page = PageBriefV4(**first_payload, canonical_sha256=canonical_sha256_v4(first_payload))
    page_payload = page_set.model_dump(mode="python")
    page_payload["pages"] = (first_page, *page_set.pages[1:])
    page_payload.pop("canonical_sha256", None)
    updated_pages = PageBriefSetV4(**page_payload, canonical_sha256=canonical_sha256_v4(page_payload))
    direction_payload = direction.model_dump(mode="python")
    direction_payload.update({"page_brief_set": updated_pages, "page_brief_set_sha256": updated_pages.canonical_sha256})
    direction_payload.pop("canonical_sha256", None)
    updated_direction = VisualDirectionPlanV4(**direction_payload, canonical_sha256=canonical_sha256_v4(direction_payload))
    compiled = tuple(
        compile_layout(
            build_layout_program(page, "editorial_hero", family="pink_red", narrative=narrative),
            LayoutCompilerInputsV4(
                page_brief=page, semantic_content_model=semantic, content_atom_set=atom_set,
                asset_manifest=AssetManifest(items=()), candidate_id="candidate-a", revision=1,
                run_id="run-a", visual_direction_plan=updated_direction,
            ),
        )
        for page in updated_pages.pages
    )
    plan = aggregate_layout_plan(
        compiled, content_atom_set=atom_set, semantic_content_model=semantic,
        page_brief_set=updated_pages, asset_manifest=AssetManifest(items=()),
        family_tokens=get_family_tokens("pink_red"), revision=1, candidate_id="candidate-a",
        run_id="run-a", visual_direction_plan=updated_direction,
    )
    return updated_pages, plan


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


def test_second_same_fingerprint_without_approved_grammar_exhausts() -> None:
    """Would fail if layout could choose an arbitrary grammar without Page Brief approval."""
    failure = _failure()

    with pytest.raises(VisualExecutionInterrupted):
        route_revision(
            failure,
            history=(_event(failure, "REFLOW", "revision-1"),),
            candidate_id="candidate-a",
            prior_revision_id="revision-1",
        )


def test_second_layout_uses_only_hash_bound_page_brief_alternative() -> None:
    """Would fail if second layout repair could choose a grammar outside Page Brief approval."""
    failure = _failure(page_id="page-1")
    page_set, plan = _approved_layout_context()

    request = route_revision(
        failure, history=(_event(failure, "REFLOW", "revision-1"),),
        candidate_id="candidate-a", prior_revision_id="revision-1",
        page_brief_set=page_set, carousel_design_plan=plan,
    )

    assert request.permitted_operations == ("CHANGE_GRAMMAR",)
    assert request.approved_grammar_alternatives[0].grammar_id == "comparison_grid"
    assert request.page_brief_set_sha256 == page_set.canonical_sha256
    assert request.carousel_design_plan_sha256 == plan.canonical_sha256


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


@pytest.mark.parametrize(
    ("node", "code", "first_operation"),
    [
        ("V4_SEMANTIC_QA", "VISIBLE_TEXT_MUTATED", "REBUILD_SEMANTIC"),
        ("V4_AUTHORING_QA", "PAGE_BRIEF_DUTY_EMPTY", "REPAGINATE"),
        ("V4_AUTHORING_QA", "ASSET_DIRECTIVE_MISMATCH", "REBIND_ASSET"),
        ("V4_AUTHORING_QA", "COMPOSITION_REPEATED", "CHANGE_GRAMMAR"),
        ("V4_RENDER_QA", "RENDER_FONT", "RERENDER"),
        ("V4_VISUAL_CRITIC", "AESTHETIC_REVIEW_FAILED", "REVIEW_AESTHETIC"),
    ],
)
def test_second_identical_nonlayout_failure_never_repeats_operation(node: str, code: str, first_operation: str) -> None:
    """Would fail if any non-layout layer consumed a second identical slot unchanged."""
    failure = NormalizedFailureV4.from_fingerprint(
        FailureFingerprintV4.create(
            node=node,
            page_id="page-9",
            failure_code=code,
            affected_fragment_ids=(),
            geometry_region=None,
        )
    )
    event = RevisionEventV4.create(
        candidate_id="candidate-a",
        revision_id="revision-1",
        prior_revision_id=None,
        fingerprint=failure.fingerprint,
        target_layer={
            "VISIBLE_TEXT_MUTATED": "SEMANTIC",
            "PAGE_BRIEF_DUTY_EMPTY": "AUTHORING",
            "ASSET_DIRECTIVE_MISMATCH": "ASSET",
            "COMPOSITION_REPEATED": "COMPOSITION",
            "RENDER_FONT": "RENDER",
            "AESTHETIC_REVIEW_FAILED": "AESTHETIC",
        }[code],
        affected_pages=("page-9",),
        operation=first_operation,
    )

    with pytest.raises(VisualExecutionInterrupted):
        route_revision(failure, history=(event,), candidate_id="candidate-a", prior_revision_id="revision-1")


@pytest.mark.parametrize(
    ("failure", "contracts"),
    [
        (_failure(code="VISIBLE_TEXT_MUTATED"), ("semantic_content_model", "semantic_qa_result", "page_brief_set", "visual_direction_plan", "authoring_qa_result", "asset_manifest", "carousel_design_plan", "design_plan_qa_result", "render_manifest", "render_qa_result", "visual_critique", "human_review", "final_policy_attestation")),
        (_failure(code="PAGE_BRIEF_DUTY_EMPTY"), ("page_brief_set", "visual_direction_plan", "authoring_qa_result", "asset_manifest", "carousel_design_plan", "design_plan_qa_result", "render_manifest", "render_qa_result", "visual_critique", "human_review", "final_policy_attestation")),
        (_failure(code="ASSET_DIRECTIVE_MISMATCH"), ("asset_manifest", "carousel_design_plan", "design_plan_qa_result", "render_manifest", "render_qa_result", "visual_critique", "human_review", "final_policy_attestation")),
        (_failure(code="COMPOSITION_REPEATED"), ("carousel_design_plan", "design_plan_qa_result", "render_manifest", "render_qa_result", "visual_critique", "human_review", "final_policy_attestation")),
        (_failure(code="RENDER_OVERFLOW"), ("carousel_design_plan", "design_plan_qa_result", "render_manifest", "render_qa_result", "visual_critique", "human_review", "final_policy_attestation")),
        (_failure(code="RENDER_FONT"), ("render_manifest", "render_qa_result", "visual_critique", "human_review", "final_policy_attestation")),
        (_failure(code="AESTHETIC_REVIEW_FAILED"), ("visual_critique", "human_review", "final_policy_attestation")),
    ],
)
def test_layer_aware_invalidation_matrix(failure: NormalizedFailureV4, contracts: tuple[str, ...]) -> None:
    """Would fail if a repair invalidated too little or used one generic downstream set."""
    request = route_revision(failure, history=(), candidate_id="candidate-a", prior_revision_id=None)

    assert request.invalidation.downstream_contracts == contracts
    assert request.invalidation.rebuild_page_ids == ("page-9",)
    assert "content_lock" not in request.invalidation.downstream_contracts
    assert "content_atom_set" not in request.invalidation.downstream_contracts


def test_direct_router_rejects_stale_prior_identity() -> None:
    """Would fail if caller-supplied prior revision could fork durable history."""
    failure = _failure()
    with pytest.raises(ValueError):
        route_revision(
            failure,
            history=(_event(failure, "REFLOW", "revision-1"),),
            candidate_id="candidate-a",
            prior_revision_id="revision-stale",
        )
