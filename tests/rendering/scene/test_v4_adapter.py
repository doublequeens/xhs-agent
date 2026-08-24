"""Task 13 RED/GREEN tests for the v4 rendering adapter."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PIL import Image

from src.rendering.scene.renderer import RenderedPageDraft
from src.rendering.scene.v4_adapter import (
    V4RenderError,
    render_v4_revision,
)
from src.visual_runtime.artifact_identity import (
    ArtifactBindingError,
    ArtifactIdentity,
    ensure_artifact_paths,
    resolve_artifact_paths,
)


def _fixture_world():
    from tests.nodes.v4.test_design_qa import _fixture, _kwargs
    from src.nodes.v4.design_qa import aggregate_design_qa

    fixture = _fixture()
    qa = aggregate_design_qa(**_kwargs(fixture))
    return fixture, qa


def _png_bytes() -> bytes:
    from io import BytesIO

    output = BytesIO()
    Image.new("RGB", (1080, 1440), "#F4A7BF").save(output, format="PNG")
    return output.getvalue()


def _render_stub(plan, *, actual_text=None):
    png = _png_bytes()

    def render(compiled_page):
        page = next(item for item in plan.pages if item.page_id == compiled_page.page_id)
        raw = []
        for element in page.scene.elements:
            if element.kind == "text":
                raw.append(
                    {
                        "element_id": element.element_id,
                        "content_ref": element.content_ref,
                        "asset_ref": None,
                        "x": element.box.x,
                        "y": element.box.y,
                        "width": element.box.width,
                        "height": element.box.height,
                        "scroll_width": element.box.width,
                        "scroll_height": element.box.height,
                        "client_width": element.box.width,
                        "client_height": element.box.height,
                        "font_family": '"HarmonyOS Sans", sans-serif',
                        "font_size": element.style.font_size,
                        "line_height": element.style.font_size * element.style.line_height,
                        "font_weight": element.style.weight,
                        "font_loaded": True,
                        "document_fonts_status": "loaded",
                        # ``None`` models the legacy offline probe seam.  An
                        # explicit empty string is a measured DOM deletion and
                        # is intentionally rejected by v4 conservation QA.
                        "actual_text": actual_text,
                        "glyph_visible": True,
                        "color": "rgb(17, 17, 17)",
                        "background_color": "rgb(255, 255, 255)",
                        "natural_width": None,
                        "natural_height": None,
                        "rendered_image_width": None,
                        "rendered_image_height": None,
                        "line_boxes": [],
                    }
                )
        return RenderedPageDraft(page_id=page.page_id, png_bytes=png, raw_probes=raw)

    return render


def test_v4_adapter_module_exposes_render_boundary():
    assert callable(render_v4_revision)
    assert issubclass(V4RenderError, Exception)


def test_v4_render_publishes_relative_immutable_revision_artifacts(tmp_path):
    fixture, qa = _fixture_world()
    plan = qa.carousel_design_plan
    identity = ArtifactIdentity(plan.run_id, plan.candidate_id, f"revision-{plan.revision}")
    paths = ensure_artifact_paths(resolve_artifact_paths(tmp_path, identity))
    result = render_v4_revision(
        design_plan=plan,
        design_plan_qa_result=qa,
        content_atom_set=fixture["atom_set"],
        content_lock=fixture["lock"],
        semantic_content_model=fixture["semantic_model"],
        page_brief_set=fixture["page_set"],
        visual_direction_plan=fixture["direction_plan"],
        asset_manifest=fixture["manifest"],
        family_tokens="pink_red",
        artifact_paths=paths,
        render_page_fn=_render_stub(plan),
    )
    assert result.manifest.workflow_version == "llm_scene_v4"
    assert result.qa.passed
    assert all(page.path.startswith("render/") for page in result.manifest.pages)
    assert result.manifest.artifact_identity.revision_id == "revision-1"
    serialized = result.manifest.model_dump_json()
    assert "provider" not in serialized
    assert "/Users/" not in serialized


def test_v4_render_second_attempt_cannot_replace_revision_bytes(tmp_path):
    fixture, qa = _fixture_world()
    plan = qa.carousel_design_plan
    identity = ArtifactIdentity(plan.run_id, plan.candidate_id, f"revision-{plan.revision}")
    paths = ensure_artifact_paths(resolve_artifact_paths(tmp_path, identity))
    kwargs = dict(
        design_plan=plan,
        design_plan_qa_result=qa,
        content_atom_set=fixture["atom_set"],
        content_lock=fixture["lock"],
        semantic_content_model=fixture["semantic_model"],
        page_brief_set=fixture["page_set"],
        visual_direction_plan=fixture["direction_plan"],
        asset_manifest=fixture["manifest"],
        family_tokens="pink_red",
        artifact_paths=paths,
        render_page_fn=_render_stub(plan),
    )
    first = render_v4_revision(**kwargs)
    original = (paths.revision_root / first.manifest.pages[0].path).read_bytes()
    with pytest.raises(ArtifactBindingError):
        render_v4_revision(**kwargs)
    assert (paths.revision_root / first.manifest.pages[0].path).read_bytes() == original


def test_v4_render_rejects_identity_drift_before_render(tmp_path):
    fixture, qa = _fixture_world()
    plan = qa.carousel_design_plan
    paths = ensure_artifact_paths(
        resolve_artifact_paths(
            tmp_path,
            ArtifactIdentity("different-run", plan.candidate_id, f"revision-{plan.revision}"),
        )
    )
    with pytest.raises((V4RenderError, ValueError)):
        render_v4_revision(
            design_plan=plan,
            design_plan_qa_result=qa,
            content_atom_set=fixture["atom_set"],
            content_lock=fixture["lock"],
            semantic_content_model=fixture["semantic_model"],
            page_brief_set=fixture["page_set"],
            visual_direction_plan=fixture["direction_plan"],
            asset_manifest=fixture["manifest"],
            family_tokens="pink_red",
            artifact_paths=paths,
            render_page_fn=_render_stub(plan),
        )


def test_v4_render_exposes_actual_probe_evidence_and_frozen_manifest(tmp_path):
    fixture, qa = _fixture_world()
    plan = qa.carousel_design_plan
    identity = ArtifactIdentity(plan.run_id, plan.candidate_id, f"revision-{plan.revision}")
    paths = ensure_artifact_paths(resolve_artifact_paths(tmp_path, identity))
    result = render_v4_revision(
        design_plan=plan,
        design_plan_qa_result=qa,
        content_atom_set=fixture["atom_set"],
        content_lock=fixture["lock"],
        semantic_content_model=fixture["semantic_model"],
        page_brief_set=fixture["page_set"],
        visual_direction_plan=fixture["direction_plan"],
        asset_manifest=fixture["manifest"],
        family_tokens="pink_red",
        artifact_paths=paths,
        render_page_fn=_render_stub(plan),
    )
    page = result.manifest.pages[0]
    evidence = page.elements[0]
    assert evidence.actual_text_sha256
    assert evidence.expected_box == evidence.actual_box
    assert result.manifest.canonical_sha256
    assert isinstance(result.manifest.pages, tuple)
    with pytest.raises(Exception):
        result.manifest.pages[0].elements = ()  # type: ignore[misc]


def test_v4_adapter_compiles_private_font_faces_and_layout_break_options(tmp_path):
    fixture, qa = _fixture_world()
    plan = qa.carousel_design_plan
    identity = ArtifactIdentity(plan.run_id, plan.candidate_id, f"revision-{plan.revision}")
    paths = ensure_artifact_paths(resolve_artifact_paths(tmp_path, identity))
    compiled_html: list[str] = []

    def renderer(compiled_page):
        compiled_html.append(compiled_page.html)
        return _render_stub(plan)(compiled_page)

    render_v4_revision(
        design_plan=plan,
        design_plan_qa_result=qa,
        content_atom_set=fixture["atom_set"],
        content_lock=fixture["lock"],
        semantic_content_model=fixture["semantic_model"],
        page_brief_set=fixture["page_set"],
        visual_direction_plan=fixture["direction_plan"],
        asset_manifest=fixture["manifest"],
        family_tokens="pink_red",
        artifact_paths=paths,
        render_page_fn=renderer,
    )
    assert len(compiled_html) == len(plan.pages)
    assert all("@font-face" in html for html in compiled_html)
    assert all("white-space:pre-wrap" in html for html in compiled_html)


def test_v4_render_rejects_failed_aggregate_before_renderer(tmp_path):
    fixture, qa = _fixture_world()
    plan = qa.carousel_design_plan
    failed = qa.model_copy(update={"passed": False})
    identity = ArtifactIdentity(plan.run_id, plan.candidate_id, f"revision-{plan.revision}")
    paths = ensure_artifact_paths(resolve_artifact_paths(tmp_path, identity))
    called = False

    def renderer(_compiled):
        nonlocal called
        called = True
        raise AssertionError("renderer must not run for a failed aggregate")

    with pytest.raises(V4RenderError):
        render_v4_revision(
            design_plan=plan,
            design_plan_qa_result=failed,
            content_atom_set=fixture["atom_set"],
            content_lock=fixture["lock"],
            semantic_content_model=fixture["semantic_model"],
            page_brief_set=fixture["page_set"],
            visual_direction_plan=fixture["direction_plan"],
            asset_manifest=fixture["manifest"],
            family_tokens="pink_red",
            artifact_paths=paths,
            render_page_fn=renderer,
        )
    assert called is False


def test_v4_render_marks_measured_dom_text_mutation_failed(tmp_path):
    fixture, qa = _fixture_world()
    plan = qa.carousel_design_plan
    identity = ArtifactIdentity(plan.run_id, plan.candidate_id, f"revision-{plan.revision}")
    paths = ensure_artifact_paths(resolve_artifact_paths(tmp_path, identity))
    result = render_v4_revision(
        design_plan=plan,
        design_plan_qa_result=qa,
        content_atom_set=fixture["atom_set"],
        content_lock=fixture["lock"],
        semantic_content_model=fixture["semantic_model"],
        page_brief_set=fixture["page_set"],
        visual_direction_plan=fixture["direction_plan"],
        asset_manifest=fixture["manifest"],
        family_tokens="pink_red",
        artifact_paths=paths,
        render_page_fn=_render_stub(plan, actual_text=""),
    )
    assert result.qa.passed is False
    assert any(issue.code == "RENDER_DOM_TEXT" for issue in result.qa.issues)
