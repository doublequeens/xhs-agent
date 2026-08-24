from __future__ import annotations

from pathlib import Path

import pytest

from tests.visual_design.v4.test_compiler import (
    _comparison_inputs_for_test,
    _inputs,
    _many_fragment_inputs,
    _rehash_page,
    _rehash_provenance,
)
from src.visual_design.v4.compiler import compile_layout
from src.visual_design.v4.design_metrics import (
    DesignMetricsInvariantError,
    evaluate_page_metrics,
    get_quality_policy,
)
from src.schemas.v4.content import canonical_sha256_v4
from src.schemas.v4.layout import (
    RegionGeometryEvidenceV4,
    canonical_text_measurement_sha256_v4,
)


def test_quality_policy_is_grammar_and_role_specific() -> None:
    hero = get_quality_policy("editorial_hero", "cover", "cover_hook")
    comparison = get_quality_policy("comparison_grid", "body", "comparison")
    step = get_quality_policy("step_flow", "body", "step")
    assert hero.whitespace_min != comparison.whitespace_min
    assert comparison.whitespace_min != step.whitespace_min


def test_metric_evaluator_is_public() -> None:
    assert callable(evaluate_page_metrics)


def test_compiled_page_metrics_are_complete_finite_and_deterministic() -> None:
    program, inputs = _inputs(text="美" * 12)
    page = compile_layout(program, inputs)
    page_brief_set = inputs.visual_direction_plan.page_brief_set
    first = evaluate_page_metrics(
        page,
        page_brief_set=page_brief_set,
        semantic_content_model=inputs.semantic_content_model,
    )
    second = evaluate_page_metrics(
        page,
        page_brief_set=page_brief_set,
        semantic_content_model=inputs.semantic_content_model,
    )
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


def test_canonical_asset_and_fragment_fixtures_pass_q2() -> None:
    fixtures = (
        ("hero-asset", _inputs, {"with_asset": True, "text": "美" * 12}),
        ("comparison-asset", _comparison_inputs_for_test, {"with_asset": True}),
        ("step-three-no-asset", _many_fragment_inputs, {"count": 3, "with_asset": False}),
        ("step-five-no-asset", _many_fragment_inputs, {"count": 5, "with_asset": False}),
    )
    for name, builder, kwargs in fixtures:
        if builder is _many_fragment_inputs:
            program, inputs = builder(kwargs["count"], with_asset=kwargs["with_asset"])
        else:
            program, inputs = builder(**kwargs)
        page = compile_layout(program, inputs)
        result = evaluate_page_metrics(
            page,
            page_brief_set=inputs.visual_direction_plan.page_brief_set,
            semantic_content_model=inputs.semantic_content_model,
        )
        assert result.passed is True, name


def test_line_length_uses_pillow_line_width_and_has_reachable_fail_boundary() -> None:
    program, inputs = _inputs()
    page = compile_layout(program, inputs)
    evidence = page.compiler_provenance.text_measurement_evidence["fragment-1"]
    line_widths = (901.0, *evidence.line_widths_px[1:])
    payload = evidence.model_dump(mode="python")
    for field in (
        "fragment_ref",
        "source_atom_id",
        "reserved_box_x_px",
        "reserved_box_y_px",
        "reserved_box_width_px",
        "reserved_box_height_px",
        "measurement_sha256",
    ):
        payload.pop(field)
    payload["line_widths_px"] = line_widths
    widened = evidence.model_copy(
        update={
            "line_widths_px": line_widths,
            "measurement_sha256": canonical_text_measurement_sha256_v4(payload),
        }
    )
    provenance = _rehash_provenance(
        page.compiler_provenance,
        text_measurement_evidence={"fragment-1": widened},
    )
    tampered = _rehash_page(page, compiler_provenance=provenance)
    result = evaluate_page_metrics(
        tampered,
        page_brief_set=inputs.visual_direction_plan.page_brief_set,
        semantic_content_model=inputs.semantic_content_model,
    )
    line_metric = next(metric for metric in result.metrics if metric.metric == "line_length")
    assert line_metric.actual == 901.0
    assert line_metric.threshold < 920.0
    assert line_metric.passed is False
    assert line_metric.element_id == "v4-text-fragment-1-0"


def test_q2_rejects_self_rehashed_measurements_that_disagree_with_semantic_source() -> None:
    """A forged measurement digest must not sever Q2 from exact semantic text."""
    program, inputs = _inputs(text="美" * 12)
    page = compile_layout(program, inputs)
    evidence = page.compiler_provenance.text_measurement_evidence["fragment-1"]
    payload = evidence.model_dump(mode="python")
    for field in (
        "fragment_ref",
        "source_atom_id",
        "reserved_box_x_px",
        "reserved_box_y_px",
        "reserved_box_width_px",
        "reserved_box_height_px",
        "measurement_sha256",
    ):
        payload.pop(field)
    forged_counts = tuple(100 for _ in evidence.line_codepoint_counts)
    forged_widths = tuple(1.0 for _ in evidence.line_widths_px)
    payload.update(
        {
            "line_codepoint_counts": forged_counts,
            "line_widths_px": forged_widths,
        }
    )
    forged = evidence.model_copy(
        update={
            "line_codepoint_counts": forged_counts,
            "line_widths_px": forged_widths,
            "measurement_sha256": canonical_text_measurement_sha256_v4(payload),
        }
    )
    provenance = _rehash_provenance(
        page.compiler_provenance,
        text_measurement_evidence={"fragment-1": forged},
    )
    tampered = _rehash_page(page, compiler_provenance=provenance)

    with pytest.raises(DesignMetricsInvariantError, match="source|measurement|semantic"):
        evaluate_page_metrics(
            tampered,
            page_brief_set=inputs.visual_direction_plan.page_brief_set,
            semantic_content_model=inputs.semantic_content_model,
        )


def test_q2_line_length_cannot_be_lowered_by_rehashed_pillow_widths() -> None:
    program, inputs = _inputs(text="美" * 12)
    page = compile_layout(program, inputs)
    original = evaluate_page_metrics(
        page,
        page_brief_set=inputs.visual_direction_plan.page_brief_set,
        semantic_content_model=inputs.semantic_content_model,
    )
    evidence = page.compiler_provenance.text_measurement_evidence["fragment-1"]
    payload = evidence.model_dump(mode="python")
    for field in (
        "fragment_ref",
        "source_atom_id",
        "reserved_box_x_px",
        "reserved_box_y_px",
        "reserved_box_width_px",
        "reserved_box_height_px",
        "measurement_sha256",
    ):
        payload.pop(field)
    forged_widths = tuple(1.0 for _ in evidence.line_widths_px)
    payload["line_widths_px"] = forged_widths
    forged = evidence.model_copy(
        update={
            "line_widths_px": forged_widths,
            "measurement_sha256": canonical_text_measurement_sha256_v4(payload),
        }
    )
    provenance = _rehash_provenance(
        page.compiler_provenance,
        text_measurement_evidence={"fragment-1": forged},
    )
    tampered = _rehash_page(page, compiler_provenance=provenance)
    result = evaluate_page_metrics(
        tampered,
        page_brief_set=inputs.visual_direction_plan.page_brief_set,
        semantic_content_model=inputs.semantic_content_model,
    )
    original_line = next(metric for metric in original.metrics if metric.metric == "line_length")
    forged_line = next(metric for metric in result.metrics if metric.metric == "line_length")
    assert forged_line.actual == original_line.actual
    assert forged_line.passed is original_line.passed


def test_q2_rejects_rehashed_break_offsets_that_change_source_line_count() -> None:
    program, inputs = _inputs(text="美美\n美美")
    page = compile_layout(program, inputs)
    evidence = page.compiler_provenance.text_measurement_evidence["fragment-1"]
    payload = evidence.model_dump(mode="python")
    for field in (
        "fragment_ref",
        "source_atom_id",
        "reserved_box_x_px",
        "reserved_box_y_px",
        "reserved_box_width_px",
        "reserved_box_height_px",
        "measurement_sha256",
    ):
        payload.pop(field)
    payload.update({"break_offsets": (1,), "inserted_break_offsets": (1,)})
    forged = evidence.model_copy(
        update={
            "break_offsets": (1,),
            "inserted_break_offsets": (1,),
            "measurement_sha256": canonical_text_measurement_sha256_v4(payload),
        }
    )
    provenance = _rehash_provenance(
        page.compiler_provenance,
        text_measurement_evidence={"fragment-1": forged},
    )
    tampered = _rehash_page(page, compiler_provenance=provenance)
    with pytest.raises(DesignMetricsInvariantError, match="source|line"):
        evaluate_page_metrics(
            tampered,
            page_brief_set=inputs.visual_direction_plan.page_brief_set,
            semantic_content_model=inputs.semantic_content_model,
        )


def test_q2_rejects_self_rehashed_unconsumed_break_at_explicit_segment_start() -> None:
    program, inputs = _inputs(text="美美\n美美")
    page = compile_layout(program, inputs)
    evidence = page.compiler_provenance.text_measurement_evidence["fragment-1"]
    payload = evidence.model_dump(mode="python")
    for field in (
        "fragment_ref",
        "source_atom_id",
        "reserved_box_x_px",
        "reserved_box_y_px",
        "reserved_box_width_px",
        "reserved_box_height_px",
        "measurement_sha256",
    ):
        payload.pop(field)
    payload.update({"break_offsets": (3,), "inserted_break_offsets": (3,)})
    forged = evidence.model_copy(
        update={
            "break_offsets": (3,),
            "inserted_break_offsets": (3,),
            "measurement_sha256": canonical_text_measurement_sha256_v4(payload),
        }
    )
    provenance = _rehash_provenance(
        page.compiler_provenance,
        text_measurement_evidence={"fragment-1": forged},
    )
    tampered = _rehash_page(page, compiler_provenance=provenance)

    with pytest.raises(DesignMetricsInvariantError, match="source|line|structure"):
        evaluate_page_metrics(
            tampered,
            page_brief_set=inputs.visual_direction_plan.page_brief_set,
            semantic_content_model=inputs.semantic_content_model,
        )


def test_regional_density_has_reachable_fail_boundary_from_current_region_geometry() -> None:
    program, inputs = _inputs(with_asset=True)
    page = compile_layout(program, inputs)
    image = next(element for element in page.scene.elements if element.kind == "image")
    raw_region = page.compiler_provenance.region_geometry_evidence["support"].model_dump(
        mode="python"
    )
    raw_region.update(
        {
            "x": image.box.x,
            "y": image.box.y,
            "width": image.box.width,
            "height": image.box.height,
        }
    )
    raw_region.pop("geometry_sha256", None)
    support = RegionGeometryEvidenceV4(
        **raw_region,
        geometry_sha256=canonical_sha256_v4(raw_region),
    )
    regions = dict(page.compiler_provenance.region_geometry_evidence)
    regions["support"] = support
    provenance = _rehash_provenance(
        page.compiler_provenance,
        region_geometry_evidence=regions,
    )
    tampered = _rehash_page(page, compiler_provenance=provenance)
    result = evaluate_page_metrics(
        tampered,
        page_brief_set=inputs.visual_direction_plan.page_brief_set,
        semantic_content_model=inputs.semantic_content_model,
    )
    density = next(
        metric for metric in result.metrics if metric.metric == "regional_information_density"
    )
    assert density.actual == 1.0
    assert density.threshold < 1.0
    assert density.passed is False
    assert density.region_id == "support"


def test_spacing_consistency_ignores_cross_region_gaps_and_unions_step_rows() -> None:
    program, inputs = _many_fragment_inputs(5, with_asset=False)
    page = compile_layout(program, inputs)
    result = evaluate_page_metrics(
        page,
        page_brief_set=inputs.visual_direction_plan.page_brief_set,
        semantic_content_model=inputs.semantic_content_model,
    )
    spacing = next(metric for metric in result.metrics if metric.metric == "spacing_consistency")
    assert spacing.actual == 0.0
    assert spacing.passed is True


@pytest.mark.parametrize(
    ("text", "expected_counts", "should_pass"),
    (
        ("美" * 11, (10, 1), False),
        ("美\n美美美美", (1, 4), False),
        ("美美\n美美", (2, 2), True),
    ),
)
def test_orphan_metrics_use_every_persisted_line_codepoint_count(
    text: str,
    expected_counts: tuple[int, ...],
    should_pass: bool,
) -> None:
    program, inputs = _inputs(text=text)
    page = compile_layout(program, inputs)
    evidence = page.compiler_provenance.text_measurement_evidence["fragment-1"]
    assert evidence.line_codepoint_counts == expected_counts
    result = evaluate_page_metrics(
        page,
        page_brief_set=inputs.visual_direction_plan.page_brief_set,
        semantic_content_model=inputs.semantic_content_model,
    )
    orphan_line = next(metric for metric in result.metrics if metric.metric == "orphan_line")
    orphan_heading = next(metric for metric in result.metrics if metric.metric == "orphan_heading")
    expected_actual = 0.0 if should_pass else 1.0
    assert orphan_line.actual == expected_actual
    assert orphan_heading.actual == expected_actual
    assert orphan_line.passed is should_pass
    assert orphan_heading.passed is should_pass


def test_orphan_metric_rejects_empty_explicit_newline_line_in_current_provenance() -> None:
    program, inputs = _inputs(text="标题\n")
    page = compile_layout(program, inputs)
    result = evaluate_page_metrics(
        page,
        page_brief_set=inputs.visual_direction_plan.page_brief_set,
        semantic_content_model=inputs.semantic_content_model,
    )
    orphan = next(metric for metric in result.metrics if metric.metric == "orphan_line")
    assert orphan.actual == 1.0
    assert orphan.passed is False


def test_comparison_page_uses_its_own_metric_policy() -> None:
    program, inputs = _comparison_inputs_for_test()
    page = compile_layout(program, inputs)
    result = evaluate_page_metrics(
        page,
        page_brief_set=inputs.visual_direction_plan.page_brief_set,
        semantic_content_model=inputs.semantic_content_model,
    )
    assert result.passed is True
    assert result.policy_sha256 != get_quality_policy(
        "editorial_hero", "body", "context"
    ).canonical_sha256


def test_page_brief_and_typed_role_are_required_for_direct_evaluation() -> None:
    program, inputs = _inputs()
    page = compile_layout(program, inputs)
    with pytest.raises(TypeError):
        evaluate_page_metrics(page)
    with pytest.raises(TypeError):
        evaluate_page_metrics(page, page_brief=inputs.page_brief, narrative_role="comparison")
    with pytest.raises(DesignMetricsInvariantError):
        get_quality_policy("checklist", "body", "checklist")


def test_policy_page_role_cannot_be_injected_wider_than_typed_beat() -> None:
    with pytest.raises(DesignMetricsInvariantError):
        get_quality_policy("editorial_hero", "cover", "context")


def test_public_q2_requires_exact_page_brief_set_not_single_brief() -> None:
    program, inputs = _inputs()
    page = compile_layout(program, inputs)
    with pytest.raises(TypeError):
        evaluate_page_metrics(page, page_brief=inputs.page_brief)


def test_public_q2_rejects_stale_page_brief_set_hash() -> None:
    program, inputs = _inputs()
    page = compile_layout(program, inputs)
    raw = inputs.visual_direction_plan.page_brief_set.model_dump(mode="python")
    first = dict(raw["pages"][0])
    first["canonical_sha256"] = "f" * 64
    raw["pages"] = (first, *raw["pages"][1:])
    with pytest.raises(DesignMetricsInvariantError):
        evaluate_page_metrics(
            page,
            page_brief_set=raw,
            semantic_content_model=inputs.semantic_content_model,
        )


def test_q2_revalidation_does_not_read_font_files(monkeypatch: pytest.MonkeyPatch) -> None:
    program, inputs = _inputs(text="美" * 12)
    page = compile_layout(program, inputs)
    page_set = inputs.visual_direction_plan.page_brief_set

    def fail_read_bytes(_path: Path) -> bytes:
        raise AssertionError("Q2 must not read font bytes")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)
    result = evaluate_page_metrics(
        page,
        page_brief_set=page_set,
        semantic_content_model=inputs.semantic_content_model,
    )
    assert result.passed is True


def test_policy_rehash_is_detected() -> None:
    policy = get_quality_policy("editorial_hero", "cover", "cover_hook")
    stale = policy.model_copy(update={"whitespace_min": 0.01})
    with pytest.raises(ValueError):
        stale.validate_integrity()
