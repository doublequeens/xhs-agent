from __future__ import annotations

from src.schemas.v4.critique import (
    AestheticIssueV4,
    AestheticPageEvaluationV4,
    CarouselAestheticEvaluationV4,
    SetAestheticEvaluationV4,
)
import pytest


def _hash(value: str) -> str:
    return value * 64


def _page(page_id: str, *, critical: bool = False) -> AestheticPageEvaluationV4:
    issue = AestheticIssueV4.create(
        severity="critical" if critical else "minor",
        dimension="composition",
        page_ids=(page_id,),
        evidence="visible text block overlaps the focal illustration",
    )
    return AestheticPageEvaluationV4.create(
        page_id=page_id,
        hierarchy=95,
        readability=95,
        composition=95,
        whitespace=95,
        visual_focus=95,
        asset_integration=95,
        issues=(issue,),
    )


def test_one_critical_page_fails_the_carousel_even_with_high_average():
    pages = (
        _page("page-1"), _page("page-2"), _page("page-3"),
        _page("page-4", critical=True), _page("page-5"),
    )
    set_evaluation = SetAestheticEvaluationV4.create(
        rhythm=95,
        repetition=95,
        family_consistency=95,
        cover_body_consistency=95,
        issues=(),
    )

    critique = CarouselAestheticEvaluationV4.create(
        render_manifest_sha256=_hash("a"),
        render_qa_result_sha256=_hash("b"),
        page_brief_set_sha256=_hash("c"),
        semantic_content_model_sha256=_hash("d"),
        authoring_model_identity="author-model",
        evaluator_model_identity="evaluator-model",
        pages=pages,
        set_evaluation=set_evaluation,
    )

    assert critique.passed is False


def test_two_low_dimensions_or_low_rhythm_fail_without_model_pass_bit():
    pages = tuple(
        _page(f"page-{index}") if index != 4 else AestheticPageEvaluationV4.create(
            page_id="page-4", hierarchy=60, readability=60, composition=95,
            whitespace=95, visual_focus=95, asset_integration=95,
            issues=(
                AestheticIssueV4.create(severity="major", dimension="hierarchy", page_ids=("page-4",), evidence="heading is visually smaller than body copy"),
                AestheticIssueV4.create(severity="major", dimension="readability", page_ids=("page-4",), evidence="small reversed type merges into its background"),
            ),
        )
        for index in range(1, 6)
    )
    set_evaluation = SetAestheticEvaluationV4.create(
        rhythm=95, repetition=95, family_consistency=95, cover_body_consistency=95,
    )
    critique = CarouselAestheticEvaluationV4.create(
        render_manifest_sha256=_hash("a"), render_qa_result_sha256=_hash("b"),
        page_brief_set_sha256=_hash("c"), semantic_content_model_sha256=_hash("d"),
        authoring_model_identity="same", evaluator_model_identity="same", pages=pages,
        set_evaluation=set_evaluation,
    )
    assert critique.passed is False
    assert critique.critic_independence == "degraded"
    with pytest.raises(Exception, match="extra_forbidden"):
        AestheticPageEvaluationV4.model_validate({**pages[0].model_dump(mode="python"), "passed": True})


def test_sub_quality_score_without_same_dimension_issue_is_rejected():
    with pytest.raises(ValueError, match="same-dimension"):
        AestheticPageEvaluationV4.create(
            page_id="page-1", hierarchy=60, readability=90, composition=90,
            whitespace=90, visual_focus=90, asset_integration=90, issues=(),
        )
    issue = AestheticIssueV4.create(
        severity="major", dimension="rhythm", page_ids=("page-1",),
        evidence="three adjacent pages repeat the same centered text stack",
    )
    result = SetAestheticEvaluationV4.create(
        rhythm=60, repetition=90, family_consistency=90, cover_body_consistency=90,
        issues=(issue,),
    )
    pages = tuple(_page(f"page-{index}") for index in range(1, 6))
    critique = CarouselAestheticEvaluationV4.create(
        render_manifest_sha256=_hash("a"), render_qa_result_sha256=_hash("b"),
        page_brief_set_sha256=_hash("c"), semantic_content_model_sha256=_hash("d"),
        authoring_model_identity=None, evaluator_model_identity=None, pages=pages,
        set_evaluation=result,
    )
    assert critique.passed is False


def test_page_and_set_issue_dimensions_are_closed_by_container():
    rhythm = AestheticIssueV4.create(
        severity="major", dimension="rhythm", page_ids=("page-1",),
        evidence="adjacent pages repeat the same text column rhythm",
    )
    with pytest.raises(ValueError, match="page.*dimension"):
        AestheticPageEvaluationV4.create(
            page_id="page-1", hierarchy=90, readability=90, composition=90,
            whitespace=90, visual_focus=90, asset_integration=90, issues=(rhythm,),
        )
