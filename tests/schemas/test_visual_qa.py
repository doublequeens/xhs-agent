import pytest
from pydantic import ValidationError

from src.schemas.design_qa import DesignIssue, DesignPlanQAResult
from src.schemas.render_manifest import (
    FontLoadReport,
    RenderedElementProbe,
    RenderedPage,
    RenderManifest,
)
from src.schemas.render_qa import RenderIssue, RenderQAResult
from src.schemas.visual_critique import VisualCritique, VisualCritiqueIssue


def make_visual_critique(**updates) -> VisualCritique:
    payload = {
        "passed": True,
        "revision_round": 0,
        "contains_images": False,
        "overall": 86,
        "hierarchy": 82,
        "legibility": 90,
        "composition": 84,
        "family_consistency": 88,
        "page_variation": 80,
        "page_rhythm": 83,
        "color": 85,
        "spacing": 87,
        "image_relevance": "not_applicable",
        "issues": (),
        "revision_instructions": (),
    }
    payload.update(updates)
    return VisualCritique.model_validate(payload)


def test_text_only_critique_marks_image_relevance_not_applicable():
    critique = make_visual_critique()
    assert critique.image_relevance == "not_applicable"

    with pytest.raises(
        ValidationError,
        match="text-only critique must mark image relevance not_applicable",
    ):
        make_visual_critique(image_relevance=0)


def test_qa_issues_require_actionable_repair_instruction():
    with pytest.raises(ValidationError, match="at least 1 character"):
        DesignIssue(
            rule="content.coverage",
            message="fragment missing",
            repair_instruction="",
            atom_id="atom-1",
        )

    with pytest.raises(ValidationError, match="at least 1 character"):
        RenderIssue(
            rule="geometry.overflow",
            message="headline overflowed",
            repair_instruction="",
            page_id="page-1",
            element_id="headline",
        )


def test_render_probe_carries_content_attestation_fields():
    probe = RenderedElementProbe(
        element_id="headline",
        kind="text",
        actual_box={"x": 100, "y": 100, "width": 800, "height": 180},
        computed_font_family="Source Han Sans SC",
        computed_font_size=64,
        computed_line_height=76.8,
        overflow=False,
        ink_clipped=False,
        layout_clipped=False,
        contrast_ratio=8.2,
        content_ref="fragment-1",
        asset_ref=None,
        rasterized_text_sha256="e" * 64,
    )
    assert probe.content_ref == "fragment-1"
    assert probe.rasterized_text_sha256 == "e" * 64

