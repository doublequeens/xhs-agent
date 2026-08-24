"""Task 13 RED/GREEN tests for the v4 rendering adapter."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.rendering.scene.renderer import RenderedPageDraft
from src.rendering.scene.probes import V4_PROBE_SCRIPT
from src.rendering.scene.v4_adapter import (
    V4RenderError,
    _private_assets,
    _text_options,
    render_v4_revision,
)
from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.v4.layout import AssetBindingEvidenceV4
from src.schemas.v4.content import canonical_sha256_v4
from src.schemas.v4.rendering import RenderPageEvidenceV4
from src.visual_runtime.artifact_identity import (
    ArtifactBindingError,
    ArtifactIdentity,
    ensure_artifact_paths,
    resolve_artifact_paths,
)


_UNSET = object()


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


def _render_stub(
    plan,
    semantic_model,
    *,
    actual_text=_UNSET,
    missing_field=None,
    font_loaded=True,
    glyph_face_loaded=True,
    glyph_font_check=True,
):
    png = _png_bytes()
    fragments = {item.fragment_id: item for item in semantic_model.fragments}

    def render(compiled_page):
        page = next(item for item in plan.pages if item.page_id == compiled_page.page_id)
        raw = []
        for element in page.scene.elements:
            if element.kind == "text":
                fragment = fragments[element.content_ref]
                measured_text = (
                    fragment.exact_text if actual_text is _UNSET else actual_text
                )
                coverage = [
                    {
                        "visible": bool(glyph_face_loaded and glyph_font_check),
                        "width": 12.0,
                        "height": 24.0,
                        "face_loaded": glyph_face_loaded,
                        "font_check": glyph_font_check,
                        "ink_pixel_count": 42 if glyph_face_loaded else 0,
                        "raster_signature": (
                            "a" * 64 if glyph_face_loaded else "0" * 64
                        ),
                    }
                    for _grapheme in measured_text
                ] if measured_text else []
                visible = bool(coverage) and all(item["visible"] for item in coverage)
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
                        "font_loaded": font_loaded,
                        "document_fonts_status": "loaded",
                        "actual_text": measured_text,
                        "dom_text_measured": True,
                        "glyph_visible": visible,
                        "missing_codepoint_count": sum(
                            1 for item in coverage if not item["visible"]
                        ),
                        "glyph_coverage": coverage,
                        "color": "rgb(17, 17, 17)",
                        "background_color": "rgb(255, 255, 255)",
                        "natural_width": None,
                        "natural_height": None,
                        "rendered_image_width": None,
                        "rendered_image_height": None,
                        "line_boxes": (
                            [
                                {
                                    "x": element.box.x,
                                    "y": element.box.y,
                                    "width": element.box.width,
                                    "height": element.box.height,
                                }
                            ]
                            if measured_text
                            else []
                        ),
                    }
                )
        if missing_field is not None and raw:
            raw[0].pop(missing_field, None)
        return RenderedPageDraft(page_id=page.page_id, png_bytes=png, raw_probes=raw)

    return render


def test_v4_adapter_module_exposes_render_boundary():
    assert callable(render_v4_revision)
    assert issubclass(V4RenderError, Exception)


def test_v4_adapter_selects_strict_probe_script_for_owned_renderer(tmp_path, monkeypatch):
    import src.rendering.scene.v4_adapter as adapter

    fixture, qa = _fixture_world()
    plan = qa.carousel_design_plan
    identity = ArtifactIdentity(plan.run_id, plan.candidate_id, f"revision-{plan.revision}")
    paths = ensure_artifact_paths(resolve_artifact_paths(tmp_path, identity))
    seen: list[str] = []
    stub = _render_stub(plan, fixture["semantic_model"])

    class Recorder:
        def __init__(self, *, playwright_factory, probe_script):
            del playwright_factory
            seen.append(probe_script)

        def __enter__(self):
            return stub

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(adapter, "_ChromiumPageRenderer", Recorder)
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
    )
    assert seen == [V4_PROBE_SCRIPT]


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
        render_page_fn=_render_stub(plan, fixture["semantic_model"]),
    )
    assert result.manifest.workflow_version == "llm_scene_v4"
    assert not hasattr(result, "qa")
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
        render_page_fn=_render_stub(plan, fixture["semantic_model"]),
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
            render_page_fn=_render_stub(plan, fixture["semantic_model"]),
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
        render_page_fn=_render_stub(plan, fixture["semantic_model"]),
    )
    page = result.manifest.pages[0]
    evidence = page.elements[0]
    assert evidence.actual_text_sha256
    assert evidence.expected_box == evidence.actual_box
    assert result.manifest.canonical_sha256
    assert isinstance(result.manifest.pages, tuple)
    with pytest.raises(Exception):
        result.manifest.pages[0].elements = ()  # type: ignore[misc]


def test_v4_render_serialization_and_page_scoped_options_are_deterministic(tmp_path):
    fixture, qa = _fixture_world()
    plan = qa.carousel_design_plan
    options = _text_options(plan, fixture["semantic_model"])
    assert options
    assert all(isinstance(key, tuple) and len(key) == 2 for key in options)
    assert {key[0] for key in options} == {page.page_id for page in plan.pages}

    def render_once(root):
        identity = ArtifactIdentity(plan.run_id, plan.candidate_id, f"revision-{plan.revision}")
        return render_v4_revision(
            design_plan=plan,
            design_plan_qa_result=qa,
            content_atom_set=fixture["atom_set"],
            content_lock=fixture["lock"],
            semantic_content_model=fixture["semantic_model"],
            page_brief_set=fixture["page_set"],
            visual_direction_plan=fixture["direction_plan"],
            asset_manifest=fixture["manifest"],
            family_tokens="pink_red",
            artifact_paths=ensure_artifact_paths(resolve_artifact_paths(root, identity)),
            render_page_fn=_render_stub(plan, fixture["semantic_model"]),
        )

    first = render_once(tmp_path / "first")
    second = render_once(tmp_path / "second")
    assert first.manifest.model_dump_json() == second.manifest.model_dump_json()


@pytest.mark.parametrize(
    "path",
    [
        "/render/pages/01-page.png",
        "render\\pages\\01-page.png",
        "render/../page.png",
        "render/./page.png",
        "render/pages/",
    ],
)
def test_v4_render_evidence_rejects_noncanonical_paths(tmp_path, path):
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
        render_page_fn=_render_stub(plan, fixture["semantic_model"]),
    )
    payload = result.manifest.pages[0].model_dump(mode="python")
    payload["path"] = path
    payload.pop("canonical_sha256")
    payload["canonical_sha256"] = canonical_sha256_v4(payload)
    with pytest.raises(ValueError, match="path|canonical"):
        RenderPageEvidenceV4.model_validate(payload)


def test_v4_adapter_compiles_private_font_faces_and_layout_break_options(tmp_path):
    fixture, qa = _fixture_world()
    plan = qa.carousel_design_plan
    identity = ArtifactIdentity(plan.run_id, plan.candidate_id, f"revision-{plan.revision}")
    paths = ensure_artifact_paths(resolve_artifact_paths(tmp_path, identity))
    compiled_html: list[str] = []

    def renderer(compiled_page):
        compiled_html.append(compiled_page.html)
        return _render_stub(plan, fixture["semantic_model"])(compiled_page)

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
        render_page_fn=_render_stub(
            plan, fixture["semantic_model"], actual_text=""
        ),
    )
    assert result.manifest.pages[0].elements[0].actual_text == ""


def test_v4_render_rejects_missing_browser_observation(tmp_path):
    fixture, qa = _fixture_world()
    plan = qa.carousel_design_plan
    identity = ArtifactIdentity(plan.run_id, plan.candidate_id, f"revision-{plan.revision}")
    paths = ensure_artifact_paths(resolve_artifact_paths(tmp_path, identity))
    with pytest.raises(V4RenderError, match="actual_text"):
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
            render_page_fn=_render_stub(
                plan, fixture["semantic_model"], missing_field="actual_text"
            ),
        )
    assert not paths.render_root.exists()


@pytest.mark.parametrize("missing_field", ["dom_text_measured", "glyph_coverage"])
def test_v4_render_rejects_missing_required_dom_and_glyph_observations(
    tmp_path, missing_field
):
    fixture, qa = _fixture_world()
    plan = qa.carousel_design_plan
    identity = ArtifactIdentity(plan.run_id, plan.candidate_id, f"revision-{plan.revision}")
    paths = ensure_artifact_paths(resolve_artifact_paths(tmp_path, identity))
    with pytest.raises(V4RenderError, match=missing_field):
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
            render_page_fn=_render_stub(
                plan, fixture["semantic_model"], missing_field=missing_field
            ),
        )


def test_v4_render_preserves_measured_fallback_glyph_failure_for_q3(tmp_path):
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
        render_page_fn=_render_stub(
            plan,
            fixture["semantic_model"],
            font_loaded=False,
            glyph_face_loaded=False,
            glyph_font_check=False,
        ),
    )
    glyph = result.manifest.pages[0].elements[0].glyph
    assert glyph is not None
    assert glyph.loaded is False
    assert glyph.coverage and glyph.coverage[0].face_loaded is False
    assert glyph.coverage[0].ink_pixel_count == 0


@pytest.mark.parametrize("failure_boundary", ["page", "contact", "manifest"])
def test_v4_render_failure_never_exposes_partial_canonical_directory(
    tmp_path, monkeypatch, failure_boundary
):
    fixture, qa = _fixture_world()
    plan = qa.carousel_design_plan
    identity = ArtifactIdentity(plan.run_id, plan.candidate_id, f"revision-{plan.revision}")
    paths = ensure_artifact_paths(resolve_artifact_paths(tmp_path, identity))
    renderer = _render_stub(plan, fixture["semantic_model"])
    if failure_boundary == "page":
        calls = 0

        def render_fn(compiled):
            nonlocal calls
            calls += 1
            if calls >= 2:
                raise RuntimeError("injected page failure")
            return renderer(compiled)

        contact_fn = None
    elif failure_boundary == "contact":
        render_fn = renderer

        def contact_fn(_pages):
            raise RuntimeError("injected contact failure")
    else:
        render_fn = renderer
        contact_fn = None
        import src.rendering.scene.v4_adapter as adapter

        original_write = adapter._atomic_write_bytes

        def fail_manifest(path, body):
            if path.name == "render-manifest.json":
                raise OSError("injected manifest failure")
            return original_write(path, body)

        monkeypatch.setattr(adapter, "_atomic_write_bytes", fail_manifest)
    with pytest.raises((V4RenderError, OSError)):
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
            render_page_fn=render_fn,
            contact_sheet_fn=contact_fn,
        )
    assert not paths.render_root.exists()


def _asset_binding(digest: str) -> AssetBindingEvidenceV4:
    return AssetBindingEvidenceV4(
        directive_id="directive-sentinel",
        asset_ref=f"v4-asset-{digest}",
        asset_sha256=digest,
        page_id="page-1",
        region_id="region-1",
        orientation="landscape",
        fit="contain",
        box_ratio=1.5,
        crop_factor=1.0,
    )


def _asset_fixture(tmp_path: Path, *, transaction_id: str = "revision-1"):
    paths = ensure_artifact_paths(
        resolve_artifact_paths(
            tmp_path,
            ArtifactIdentity("run-a", "candidate-a", "revision-1"),
        )
    )
    source = paths.asset_root / "sentinel.png"
    source.write_bytes(b"asset-sentinel")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    item = AssetManifestItem(
        asset_id="provider-opaque-id",
        directive_id="directive-sentinel",
        page_id="page-1",
        source_kind="catalog",
        provider="fixture-provider",
        license="fixture-license",
        local_path=str(source),
        width=1200,
        height=800,
        sha256=digest,
        subject_focal_point=(0.5, 0.5),
        crop_guidance="center",
        security_status="approved",
        human_decision="pending",
        run_id="run-a",
        transaction_id=transaction_id,
        internal_provenance={"sentinel": "private"},
    )
    plan = SimpleNamespace(
        run_id="run-a",
        pages=(
            SimpleNamespace(
                page_id="page-1",
                compiler_provenance=SimpleNamespace(
                    asset_binding_evidence={
                        "directive-sentinel": _asset_binding(digest)
                    }
                ),
            ),
        ),
    )
    manifest = AssetManifest(items=(item,))
    return source, digest, plan, manifest, paths


def test_v4_asset_binding_reads_real_sentinel_and_rejects_substitution(tmp_path):
    source, _digest, plan, manifest, paths = _asset_fixture(tmp_path)
    verified_bytes: dict[str, bytes] = {}
    assets = _private_assets(plan, manifest, paths, verified_bytes=verified_bytes)
    assert assets[next(iter(assets))].local_path == str(source)

    source.write_bytes(b"substituted-asset")
    assert verified_bytes[next(iter(verified_bytes))] == b"asset-sentinel"
    with pytest.raises(V4RenderError, match="unsafe|stale"):
        _private_assets(plan, manifest, paths)


def test_v4_asset_binding_rejects_transaction_and_symlink_identity(tmp_path):
    source, digest, plan, manifest, paths = _asset_fixture(
        tmp_path, transaction_id="wrong-revision"
    )
    with pytest.raises(V4RenderError, match="transaction"):
        _private_assets(plan, manifest, paths)

    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    source.unlink()
    source.symlink_to(outside)
    item = manifest.items[0].model_copy(update={"transaction_id": "revision-1"})
    linked_manifest = AssetManifest(items=(item,))
    with pytest.raises(V4RenderError, match="unsafe"):
        _private_assets(plan, linked_manifest, paths)
