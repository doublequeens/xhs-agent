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


SHA_BINDINGS = {
    "content_atom_set_sha256": "a" * 64,
    "direction_plan_sha256": "b" * 64,
    "design_plan_sha256": "c" * 64,
    "render_manifest_sha256": "d" * 64,
}


def make_visual_critique(**updates) -> VisualCritique:
    payload = {
        **SHA_BINDINGS,
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


def make_render_manifest() -> RenderManifest:
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
    pages = tuple(
        RenderedPage(
            page_id=f"page-{index}",
            sequence=index,
            path=f"page-{index}.png",
            width=1080,
            height=1440,
            sha256=f"{index}" * 64,
            element_probes=(probe.model_copy(update={"element_id": f"text-{index}"}),),
        )
        for index in range(1, 6)
    )
    return RenderManifest(
        design_plan_sha256="a" * 64,
        content_atom_set_sha256="b" * 64,
        asset_manifest_sha256="c" * 64,
        revision=0,
        pages=pages,
        fonts=FontLoadReport(
            all_loaded=True,
            computed_families=("Source Han Sans SC",),
        ),
        contact_sheet_path="contact-sheet.png",
        contact_sheet_sha256="d" * 64,
        source_asset_sha256={"asset-1": "f" * 64},
    )


def test_render_manifest_source_asset_mapping_is_immutable_and_serializable():
    manifest = make_render_manifest()

    with pytest.raises(
        TypeError,
        match="'mappingproxy' object does not support item assignment",
    ):
        manifest.source_asset_sha256["asset-1"] = "0" * 64

    assert manifest.model_dump(mode="json")["source_asset_sha256"] == {
        "asset-1": "f" * 64
    }


def test_visual_critique_requires_all_exact_input_bindings():
    critique = make_visual_critique()
    assert {
        field: getattr(critique, field)
        for field in SHA_BINDINGS
    } == SHA_BINDINGS

    payload = critique.model_dump(mode="python")
    payload.pop("render_manifest_sha256")
    with pytest.raises(ValidationError) as exc_info:
        VisualCritique.model_validate(payload)

    error = exc_info.value.errors()[0]
    assert error["loc"] == ("render_manifest_sha256",)
    assert error["type"] == "missing"


@pytest.mark.parametrize("field", tuple(SHA_BINDINGS))
def test_visual_critique_rejects_malformed_input_binding_hash(field):
    with pytest.raises(ValidationError) as exc_info:
        make_visual_critique(**{field: "not-a-sha256"})

    error = exc_info.value.errors()[0]
    assert error["loc"] == (field,)
    assert error["type"] == "string_pattern_mismatch"
