from __future__ import annotations

import pytest

from tests.visual_design.v4.test_compiler import _comparison_inputs_for_test, _inputs
from src.visual_design.v4.compiler import compile_layout
from src.visual_design.v4.design_metrics import (
    DesignMetricsInvariantError,
    evaluate_page_metrics,
    get_quality_policy,
)
from src.schemas.v4.content import canonical_sha256_v4


def test_quality_policy_is_grammar_and_role_specific() -> None:
    hero = get_quality_policy("editorial_hero", "cover", "cover_hook")
    comparison = get_quality_policy("comparison_grid", "body", "comparison")
    step = get_quality_policy("step_flow", "body", "step")
    assert hero.whitespace_min != comparison.whitespace_min
    assert comparison.whitespace_min != step.whitespace_min


def test_metric_evaluator_is_public() -> None:
    assert callable(evaluate_page_metrics)


def test_compiled_page_metrics_are_complete_finite_and_deterministic() -> None:
    program, inputs = _inputs()
    page = compile_layout(program, inputs)
    first = evaluate_page_metrics(page, page_brief=inputs.page_brief)
    second = evaluate_page_metrics(page, page_brief=inputs.page_brief)
    assert first.passed is True
    assert first.canonical_sha256 == second.canonical_sha256
    assert first.model_dump_json() == second.model_dump_json()
    assert {metric.metric for metric in first.metrics} == {
        "safe_margin_compliance",
        "unintended_overlap",
        "minimum_font_size",
        "contrast",
        "whitespace_ratio",
        "largest_text_block_ratio",
        "regional_information_density",
        "alignment_axis_deviation",
        "paired_column_balance",
        "spacing_consistency",
        "heading_body_hierarchy_ratio",
        "visual_center_offset",
        "emphasis_count",
        "line_length",
        "orphan_line",
        "orphan_heading",
        "image_text_area_ratio",
    }
    assert all(metric.actual == metric.actual for metric in first.metrics)


def test_comparison_page_uses_its_own_metric_policy() -> None:
    program, inputs = _comparison_inputs_for_test()
    page = compile_layout(program, inputs)
    result = evaluate_page_metrics(page, page_brief=inputs.page_brief)
    assert result.passed is True
    assert result.policy_sha256 != get_quality_policy(
        "editorial_hero", "body", "context"
    ).canonical_sha256


def test_page_brief_and_typed_role_are_required_for_direct_evaluation() -> None:
    program, inputs = _inputs()
    page = compile_layout(program, inputs)
    with pytest.raises(DesignMetricsInvariantError):
        evaluate_page_metrics(page)
    with pytest.raises(DesignMetricsInvariantError):
        evaluate_page_metrics(page, page_brief=inputs.page_brief, narrative_role="comparison")
    with pytest.raises(DesignMetricsInvariantError):
        get_quality_policy("checklist", "body", "checklist")


def test_policy_page_role_cannot_be_injected_wider_than_typed_beat() -> None:
    with pytest.raises(DesignMetricsInvariantError):
        get_quality_policy("editorial_hero", "cover", "context")


def test_policy_rehash_is_detected() -> None:
    policy = get_quality_policy("editorial_hero", "cover", "cover_hook")
    stale = policy.model_copy(update={"whitespace_min": 0.01})
    with pytest.raises(ValueError):
        stale.validate_integrity()
