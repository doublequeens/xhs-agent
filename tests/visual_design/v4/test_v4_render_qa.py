"""Independent Q3 tests for the v4 render evidence boundary."""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from src.rendering.scene.v4_adapter import render_v4_revision
from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.scene_graph import Box, ImageElement
from src.schemas.v4.content import canonical_json_v4, canonical_sha256_v4, sha256_text_v4
from src.schemas.v4.layout import AssetBindingEvidenceV4
from src.schemas.v4.rendering import (
    RenderAssetEvidenceV4,
    RenderBoxV4,
    RenderGlyphEvidenceV4,
    RenderManifestV4,
)
from src.visual_design.v4.render_qa import (
    RENDER_BOX_DRIFT,
    V4RenderQAInvariantError,
    _asset_issues,
    _text_matches,
    evaluate_v4_render,
)
from src.visual_design.v4.compiler import opaque_asset_ref_v4
from src.visual_design.v4.typography import measure_text_v4
from src.visual_runtime.artifact_identity import (
    ArtifactIdentity,
    ensure_artifact_paths,
    resolve_artifact_paths,
)


def _world(tmp_path: Path):
    from tests.nodes.v4.test_design_qa import _fixture, _kwargs
    from tests.rendering.scene.test_v4_adapter import _render_stub
    from src.nodes.v4.design_qa import aggregate_design_qa
    from src.rendering.scene.renderer import RenderedPageDraft
    from src.visual_design.v4.tokens import get_family_tokens

    fixture = _fixture()
    aggregate = aggregate_design_qa(**_kwargs(fixture))
    plan = aggregate.carousel_design_plan
    paths = ensure_artifact_paths(
        resolve_artifact_paths(
            tmp_path,
            ArtifactIdentity(plan.run_id, plan.candidate_id, f"revision-{plan.revision}"),
        )
    )
    base_render = _render_stub(plan, fixture["semantic_model"])

    def render(compiled_page):
        draft = base_render(compiled_page)
        page = next(item for item in plan.pages if item.page_id == compiled_page.page_id)
        family = get_family_tokens("pink_red")
        probes = []
        for raw, element in zip(
            draft.raw_probes,
            sorted(page.scene.elements, key=lambda item: item.layer),
        ):
            if element.kind == "text":
                raw = dict(raw)
                raw["font_family"] = getattr(family.font_roles, element.style.font_role)
            probes.append(raw)
        return RenderedPageDraft(
            page_id=draft.page_id,
            png_bytes=draft.png_bytes,
            raw_probes=probes,
        )

    rendered = render_v4_revision(
        design_plan=plan,
        design_plan_qa_result=aggregate,
        content_atom_set=fixture["atom_set"],
        content_lock=fixture["lock"],
        semantic_content_model=fixture["semantic_model"],
        page_brief_set=fixture["page_set"],
        visual_direction_plan=fixture["direction_plan"],
        asset_manifest=fixture["manifest"],
        family_tokens="pink_red",
        artifact_paths=paths,
        render_page_fn=render,
    )
    values = {
        "render_manifest": rendered.manifest,
        "design_plan": plan,
        "design_plan_qa_result": aggregate,
        "content_atom_set": fixture["atom_set"],
        "content_lock": fixture["lock"],
        "semantic_content_model": fixture["semantic_model"],
        "page_brief_set": fixture["page_set"],
        "visual_direction_plan": fixture["direction_plan"],
        "asset_manifest": fixture["manifest"],
        "family_tokens": "pink_red",
        "artifact_paths": paths,
    }
    return values


def _world_with_text(
    tmp_path: Path,
    source_text: str,
    *,
    render_wrapped: bool = False,
):
    """Recompile the real fixture after changing one source fragment.

    This keeps the public evaluator at the seam: atoms, semantic source,
    direction/page hashes, compiler measurements, Q0-Q2 and immutable render
    bytes are all rebuilt instead of calling a text helper in isolation.
    """

    import regex

    from src.nodes.v4.composition import build_layout_program
    from src.nodes.v4.design_qa import aggregate_design_qa
    from src.nodes.v4.layout import aggregate_layout_plan
    from src.rendering.scene.renderer import RenderedPageDraft
    from src.schemas.content_lock import ContentLock
    from src.schemas.v4.content import ContentAtomSetV4, ContentAtomV4
    from src.schemas.v4.direction import (
        AuthoringQAResultV4,
        CarouselNarrativeV4,
        PageBriefSetV4,
        VisualDirectionPlanV4,
    )
    from src.schemas.v4.semantic import SemanticContentModelV4, SemanticFragmentV4
    from src.visual_design.v4.compiler import LayoutCompilerInputsV4, compile_layout
    from src.visual_design.v4.semantic_qa import evaluate_semantic_model
    from src.visual_design.v4.tokens import get_family_tokens
    from src.visual_design.v4.typography import reconstruct_source_lines_v4
    from tests.rendering.scene.test_v4_adapter import _render_stub

    base = _world(tmp_path / "source-base")
    base_plan = base["design_plan"]
    base_atoms = base["content_atom_set"]
    base_semantic = base["semantic_content_model"]

    atom_payload = base_atoms.atoms[0].model_dump(mode="python")
    atom_payload.update(
        {
            "text": source_text,
            "raw_end": len(source_text),
            "raw_slice_sha256": sha256_text_v4(source_text),
        }
    )
    atom_payload.pop("sha256", None)
    first_atom = ContentAtomV4(
        **atom_payload,
        sha256=canonical_sha256_v4(atom_payload),
    )
    atom_set_payload = base_atoms.model_dump(mode="python")
    atom_set_payload["atoms"] = (first_atom, *base_atoms.atoms[1:])
    atom_set_payload.pop("canonical_sha256", None)
    atom_set = ContentAtomSetV4(
        **atom_set_payload,
        canonical_sha256=canonical_sha256_v4(atom_set_payload),
    )

    fragment_payload = base_semantic.fragments[0].model_dump(mode="python")
    fragment_payload.update(exact_text=source_text, end=len(source_text))
    first_fragment = SemanticFragmentV4(**fragment_payload)
    semantic_payload = base_semantic.model_dump(mode="python")
    semantic_payload.update(
        {
            "content_atom_set_sha256": atom_set.canonical_sha256,
            "fragments": (first_fragment, *base_semantic.fragments[1:]),
        }
    )
    semantic_payload.pop("canonical_sha256", None)
    semantic = SemanticContentModelV4(
        **semantic_payload,
        canonical_sha256=canonical_sha256_v4(semantic_payload),
    )

    page_set_payload = base["page_brief_set"].model_dump(mode="python")
    page_set_payload.update(
        {
            "content_atom_set_sha256": atom_set.canonical_sha256,
            "semantic_content_model_sha256": semantic.canonical_sha256,
        }
    )
    page_set_payload.pop("canonical_sha256", None)
    page_set = PageBriefSetV4(
        **page_set_payload,
        canonical_sha256=canonical_sha256_v4(page_set_payload),
    )

    narrative_payload = base["visual_direction_plan"].narrative.model_dump(mode="python")
    narrative_payload["content_atom_set_sha256"] = atom_set.canonical_sha256
    narrative_payload.pop("canonical_sha256", None)
    narrative = CarouselNarrativeV4(
        **narrative_payload,
        canonical_sha256=canonical_sha256_v4(narrative_payload),
    )
    direction_payload = base["visual_direction_plan"].model_dump(mode="python")
    direction_payload.update(
        {
            "narrative": narrative,
            "semantic_content_model": semantic,
            "page_brief_set": page_set,
            "content_atom_set_sha256": atom_set.canonical_sha256,
            "semantic_content_model_sha256": semantic.canonical_sha256,
            "narrative_sha256": narrative.canonical_sha256,
            "page_brief_set_sha256": page_set.canonical_sha256,
        }
    )
    direction_payload.pop("canonical_sha256", None)
    direction = VisualDirectionPlanV4(
        **direction_payload,
        canonical_sha256=canonical_sha256_v4(direction_payload),
    )

    empty_assets = AssetManifest(items=())
    compiled_pages = []
    for index, brief in enumerate(page_set.pages):
        old_program = base_plan.pages[index].layout_program
        program = build_layout_program(
            brief,
            grammar_id=old_program.grammar_id,
            family=direction.template_family,
            narrative=direction.narrative,
        )
        compiled_pages.append(
            compile_layout(
                program,
                LayoutCompilerInputsV4(
                    page_brief=brief,
                    semantic_content_model=semantic,
                    content_atom_set=atom_set,
                    asset_manifest=empty_assets,
                    candidate_id=base_plan.candidate_id,
                    revision=base_plan.revision,
                    run_id=base_plan.run_id,
                    visual_direction_plan=direction,
                ),
            )
        )
    plan = aggregate_layout_plan(
        compiled_pages,
        content_atom_set=atom_set,
        semantic_content_model=semantic,
        page_brief_set=page_set,
        asset_manifest=empty_assets,
        family_tokens=get_family_tokens(direction.template_family),
        revision=base_plan.revision,
        candidate_id=base_plan.candidate_id,
        run_id=base_plan.run_id,
        visual_direction_plan=direction,
    )

    lock_payload = base["content_lock"].model_dump(mode="python")
    lock_payload["content_atom_set_sha256"] = atom_set.canonical_sha256
    lock_payload.pop("canonical_sha256", None)
    lock = ContentLock(
        **lock_payload,
        canonical_sha256=canonical_sha256_v4(lock_payload),
    )
    semantic_qa = evaluate_semantic_model(atom_set, semantic, content_lock=lock)
    authoring_payload = base["design_plan_qa_result"].authoring_qa.model_dump(
        mode="python"
    )
    authoring_payload.update(
        {
            "content_atom_set_sha256": atom_set.canonical_sha256,
            "content_lock_sha256": lock.canonical_sha256,
            "semantic_content_model_sha256": semantic.canonical_sha256,
            "narrative_sha256": direction.narrative_sha256,
            "page_brief_set_sha256": page_set.canonical_sha256,
            "visual_direction_plan_sha256": direction.canonical_sha256,
        }
    )
    authoring_payload.pop("canonical_sha256", None)
    authoring_qa = AuthoringQAResultV4(
        **authoring_payload,
        canonical_sha256=canonical_sha256_v4(authoring_payload),
    )
    aggregate = aggregate_design_qa(
        semantic_qa=semantic_qa,
        authoring_qa=authoring_qa,
        carousel_design_plan=plan,
        content_atom_set=atom_set,
        content_lock=lock,
        semantic_content_model=semantic,
        page_brief_set=page_set,
        visual_direction_plan=direction,
        asset_manifest=empty_assets,
    )

    family = get_family_tokens(direction.template_family)
    source_fragment_id = first_fragment.fragment_id
    base_render = _render_stub(plan, semantic)

    def render(compiled_page):
        draft = base_render(compiled_page)
        page = next(item for item in plan.pages if item.page_id == compiled_page.page_id)
        probes = []
        for raw, element in zip(
            draft.raw_probes,
            sorted(page.scene.elements, key=lambda item: item.layer),
        ):
            raw = dict(raw)
            if element.kind == "text":
                raw["font_family"] = getattr(
                    family.font_roles,
                    element.style.font_role,
                )
                if element.content_ref == source_fragment_id:
                    measurement = page.compiler_provenance.text_measurement_evidence[
                        element.content_ref
                    ]
                    actual = (
                        "\n".join(
                            reconstruct_source_lines_v4(
                                source_text,
                                explicit_break_spans=measurement.explicit_break_spans,
                                inserted_break_offsets=measurement.inserted_break_offsets,
                            ).lines
                        )
                        if render_wrapped
                        else source_text.replace("\r\n", "\n").replace("\r", "\n")
                    )
                    raw["actual_text"] = actual
                    template = dict(raw["glyph_coverage"][0])
                    coverage = []
                    for grapheme in regex.findall(r"\X", actual):
                        item = dict(template)
                        whitespace = grapheme.isspace()
                        item["is_whitespace"] = whitespace
                        if whitespace:
                            item.update(
                                visible=False,
                                width=0.0,
                                height=0.0,
                                ink_pixel_count=0,
                                raster_signature="0" * 64,
                                fallback_ink_pixel_count=0,
                                fallback_raster_signature="0" * 64,
                                tofu_ink_pixel_count=0,
                                tofu_raster_signature="0" * 64,
                            )
                        coverage.append(item)
                    raw["glyph_coverage"] = coverage
                    raw["glyph_visible"] = all(
                        item["visible"]
                        for item in coverage
                        if not item["is_whitespace"]
                    )
                    raw["missing_codepoint_count"] = sum(
                        1
                        for item in coverage
                        if not item["is_whitespace"] and not item["visible"]
                    )
            probes.append(raw)
        return RenderedPageDraft(
            page_id=draft.page_id,
            png_bytes=draft.png_bytes,
            raw_probes=probes,
        )

    paths = ensure_artifact_paths(
        resolve_artifact_paths(
            tmp_path / "rendered",
            ArtifactIdentity(
                plan.run_id,
                plan.candidate_id,
                f"revision-{plan.revision}",
            ),
        )
    )
    rendered = render_v4_revision(
        design_plan=plan,
        design_plan_qa_result=aggregate,
        content_atom_set=atom_set,
        content_lock=lock,
        semantic_content_model=semantic,
        page_brief_set=page_set,
        visual_direction_plan=direction,
        asset_manifest=empty_assets,
        family_tokens=direction.template_family,
        artifact_paths=paths,
        render_page_fn=render,
    )
    return {
        "render_manifest": rendered.manifest,
        "design_plan": plan,
        "design_plan_qa_result": aggregate,
        "content_atom_set": atom_set,
        "content_lock": lock,
        "semantic_content_model": semantic,
        "page_brief_set": page_set,
        "visual_direction_plan": direction,
        "asset_manifest": empty_assets,
        "family_tokens": direction.template_family,
        "artifact_paths": paths,
    }


def _rebuild_manifest(manifest: RenderManifestV4, *, pages):
    payload = manifest.model_dump(mode="python")
    payload["pages"] = tuple(pages)
    payload.pop("canonical_sha256", None)
    return RenderManifestV4(**payload, canonical_sha256=canonical_sha256_v4(payload))


def _rebuild_page(page, *, elements):
    payload = page.model_dump(mode="python")
    payload["elements"] = tuple(elements)
    payload.pop("canonical_sha256", None)
    return type(page)(**payload, canonical_sha256=canonical_sha256_v4(payload))


def _rebuild_element(element, **updates):
    payload = element.model_dump(mode="python")
    payload.update(updates)
    payload.pop("canonical_sha256", None)
    return type(element)(**payload, canonical_sha256=canonical_sha256_v4(payload))


def _rehash_model(model, **updates):
    """Rebuild one immutable evidence model without duplicating its schema."""

    payload = model.model_dump(mode="python")
    payload.update(updates)
    if "canonical_sha256" not in payload:
        return type(model)(**payload)
    payload.pop("canonical_sha256", None)
    return type(model)(**payload, canonical_sha256=canonical_sha256_v4(payload))


def _persist_manifest(values, manifest):
    values["artifact_paths"].revision_root.joinpath(
        "render/render-manifest.json"
    ).write_text(canonical_json_v4(manifest), encoding="utf-8")
    values["render_manifest"] = manifest


def _replace_page_bytes(values, raw: bytes, *, page_index: int = 0):
    manifest = values["render_manifest"]
    page = manifest.pages[page_index]
    page_path = values["artifact_paths"].revision_root / page.path
    page_path.write_bytes(raw)
    payload = page.model_dump(mode="python")
    payload["sha256"] = hashlib.sha256(raw).hexdigest()
    payload.pop("canonical_sha256", None)
    rebuilt_page = type(page)(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )
    pages = list(manifest.pages)
    pages[page_index] = rebuilt_page
    _persist_manifest(values, _rebuild_manifest(manifest, pages=tuple(pages)))


def _replace_contact_bytes(values, raw: bytes):
    manifest = values["render_manifest"]
    contact_path = values["artifact_paths"].revision_root / manifest.contact_sheet_path
    contact_path.write_bytes(raw)
    payload = manifest.model_dump(mode="python")
    payload["contact_sheet_sha256"] = hashlib.sha256(raw).hexdigest()
    payload.pop("canonical_sha256", None)
    _persist_manifest(
        values,
        RenderManifestV4(
            **payload,
            canonical_sha256=canonical_sha256_v4(payload),
        ),
    )


def _png_bytes(width: int, height: int, color):
    output = BytesIO()
    Image.new("RGBA", (width, height), color).save(output, format="PNG")
    return output.getvalue()


def test_v4_render_qa_public_boundary_is_available():
    assert callable(evaluate_v4_render)
    assert RENDER_BOX_DRIFT == "RENDER_BOX_DRIFT"


def test_q3_recomputes_a_published_manifest_and_is_deterministic(tmp_path):
    values = _world(tmp_path)
    first = evaluate_v4_render(**values)
    second = evaluate_v4_render(**values)

    assert first.passed is True
    assert first.issues == ()
    assert first.model_dump_json() == second.model_dump_json()
    with pytest.raises(Exception):
        first.issues += ()  # type: ignore[misc]


def test_q3_inclusive_two_pixel_tolerance_passes(tmp_path):
    values = _world(tmp_path)
    manifest = values["render_manifest"]
    page = manifest.pages[0]
    element = page.elements[0]
    drifted = _rebuild_element(element, actual_box={
        **element.actual_box.model_dump(mode="python"),
        "x": element.actual_box.x + 2.0,
    })
    page = _rebuild_page(page, elements=(drifted, *page.elements[1:]))
    manifest = _rebuild_manifest(manifest, pages=(page, *manifest.pages[1:]))
    render_file = values["artifact_paths"].revision_root / "render/render-manifest.json"
    render_file.write_text(canonical_json_v4(manifest), encoding="utf-8")
    values["render_manifest"] = manifest

    result = evaluate_v4_render(**values)
    assert result.passed is True
    assert RENDER_BOX_DRIFT not in {issue.code for issue in result.issues}


def test_q3_rejects_caller_tolerance_override(tmp_path):
    values = _world(tmp_path)

    with pytest.raises(V4RenderQAInvariantError):
        evaluate_v4_render(**values, tolerance_px=1e9)


def test_q3_over_two_pixel_drift_is_actionable_and_sanitized(tmp_path):
    values = _world(tmp_path)
    manifest = values["render_manifest"]
    page = manifest.pages[0]
    element = page.elements[0]
    drifted = _rebuild_element(element, actual_box={
        **element.actual_box.model_dump(mode="python"),
        "x": element.actual_box.x + 2.1,
    })
    page = _rebuild_page(page, elements=(drifted, *page.elements[1:]))
    manifest = _rebuild_manifest(manifest, pages=(page, *manifest.pages[1:]))
    values["artifact_paths"].revision_root.joinpath("render/render-manifest.json").write_text(
        canonical_json_v4(manifest), encoding="utf-8"
    )
    values["render_manifest"] = manifest

    result = evaluate_v4_render(**values)

    assert result.passed is False
    issue = next(issue for issue in result.issues if issue.code == RENDER_BOX_DRIFT)
    assert issue.page_id == page.page_id
    assert issue.element_id == element.element_id
    assert issue.actual == pytest.approx(element.actual_box.x + 2.1)
    assert issue.expected == pytest.approx(element.expected_box.x)
    assert issue.tolerance_px == 2.0
    assert "provider" not in issue.evidence.lower()
    assert "path" not in issue.evidence.lower()


def test_q3_manifest_byte_binding_is_structural_and_cannot_be_spoofed(tmp_path):
    values = _world(tmp_path)
    manifest = values["render_manifest"]
    values["render_manifest"] = manifest.model_copy(update={"canonical_sha256": "0" * 64})

    with pytest.raises(V4RenderQAInvariantError):
        evaluate_v4_render(**values)


def _mutate_first_text(
    values,
    *,
    expected_text_sha256,
    actual_text="spoofed copy",
):
    manifest = values["render_manifest"]
    page = manifest.pages[0]
    element = page.elements[0]
    mutated = _rebuild_element(
        element,
        actual_text=actual_text,
        actual_text_sha256=sha256_text_v4(actual_text),
        expected_text_sha256=expected_text_sha256,
    )
    page = _rebuild_page(page, elements=(mutated, *page.elements[1:]))
    _persist_manifest(values, _rebuild_manifest(manifest, pages=(page, *manifest.pages[1:])))


def test_q3_reports_dom_mutation_against_source_hash(tmp_path):
    values = _world(tmp_path)
    element = values["render_manifest"].pages[0].elements[0]
    source_fragment = next(
        fragment
        for fragment in values["semantic_content_model"].fragments
        if fragment.fragment_id == element.content_ref
    )
    # Keeping the expected source hash intact must produce an actionable DOM
    # issue rather than accepting the rehashed outer evidence.
    _mutate_first_text(
        values,
        expected_text_sha256=sha256_text_v4(source_fragment.exact_text),
    )

    result = evaluate_v4_render(**values)

    assert result.passed is False
    assert any(issue.code == "RENDER_DOM_TEXT" for issue in result.issues)


def test_q3_rejects_dom_mutation_with_spoofed_expected_hash(tmp_path):
    values = _world(tmp_path)
    _mutate_first_text(
        values,
        expected_text_sha256=sha256_text_v4("spoofed copy"),
    )

    with pytest.raises(V4RenderQAInvariantError):
        evaluate_v4_render(**values)


def test_q3_accepts_only_compiler_approved_line_breaks_and_rejects_copy_change():
    source = "ABCD"
    measurement = measure_text_v4(
        source,
        family="pink_red",
        role="body",
        font_size_px=32,
        max_width_px=70,
        line_height=1.25,
    )
    assert measurement.inserted_break_offsets
    wrapped = "\n".join(measurement.lines)

    assert _text_matches(wrapped, source, measurement)
    assert not _text_matches(wrapped.replace("A", "X", 1), source, measurement)
    assert not _text_matches(source, source, measurement)


@pytest.mark.parametrize("newline", ("\n", "\r\n", "\r"))
def test_q3_public_preserves_explicit_newline_codepoints_and_rejects_copy_mutation(
    tmp_path, newline
):
    source = f"页面{newline}标题1"
    values = _world_with_text(tmp_path / "valid", source)
    measurement = values["design_plan"].pages[0].compiler_provenance.text_measurement_evidence[
        "fragment-1"
    ]
    expected_span = (2, 4) if newline == "\r\n" else (2, 3)
    assert measurement.exact_text_sha256 == sha256_text_v4(source)
    assert measurement.explicit_newline_count == 1
    assert measurement.explicit_break_spans == (expected_span,)

    assert evaluate_v4_render(**values).passed is True

    dropped = _world_with_text(tmp_path / "dropped", source)
    _mutate_first_text(
        dropped,
        actual_text=source.replace(newline, ""),
        expected_text_sha256=sha256_text_v4(source),
    )
    dropped_result = evaluate_v4_render(**dropped)
    assert dropped_result.passed is False
    assert any(issue.code == "RENDER_DOM_TEXT" for issue in dropped_result.issues)

    changed = _world_with_text(tmp_path / "changed", source)
    _mutate_first_text(
        changed,
        actual_text=f"页面{newline}标X1",
        expected_text_sha256=sha256_text_v4(source),
    )
    changed_result = evaluate_v4_render(**changed)
    assert changed_result.passed is False
    assert any(issue.code == "RENDER_DOM_TEXT" for issue in changed_result.issues)


def test_q3_public_accepts_only_compiler_inserted_layout_breaks(tmp_path):
    source = "页面标题" * 8
    values = _world_with_text(tmp_path / "wrapped", source, render_wrapped=True)

    assert evaluate_v4_render(**values).passed is True

    unwrapped = _world_with_text(tmp_path / "unwrapped", source)
    result = evaluate_v4_render(**unwrapped)
    assert result.passed is False
    assert any(issue.code == "RENDER_DOM_TEXT" for issue in result.issues)


def _glyph_with_missing_witness(glyph: RenderGlyphEvidenceV4):
    coverage = tuple(
        item.model_copy(update={"visible": False})
        for item in glyph.coverage
    )
    missing = sum(1 for item in coverage if not item.is_whitespace)
    return _rehash_model(
        glyph,
        visible=False,
        missing_codepoint_count=missing,
        coverage=coverage,
    )


def _glyph_with_face_unloaded(glyph: RenderGlyphEvidenceV4):
    coverage = tuple(
        item.model_copy(update={"visible": False, "face_loaded": False})
        for item in glyph.coverage
    )
    missing = sum(1 for item in coverage if not item.is_whitespace)
    return _rehash_model(
        glyph,
        visible=False,
        missing_codepoint_count=missing,
        coverage=coverage,
    )


def _glyph_with_font_check_failure(glyph: RenderGlyphEvidenceV4):
    coverage = tuple(
        item.model_copy(update={"visible": False, "font_check": False})
        for item in glyph.coverage
    )
    missing = sum(1 for item in coverage if not item.is_whitespace)
    return _rehash_model(
        glyph,
        visible=False,
        missing_codepoint_count=missing,
        coverage=coverage,
    )


def _glyph_with_tofu_collision(glyph: RenderGlyphEvidenceV4):
    coverage = tuple(
        item.model_copy(
            update={
                "visible": False,
                # A tofu raster identical to the primary witness is
                # ambiguous evidence even when the geometry remains intact.
                "tofu_raster_signature": item.raster_signature,
            }
        )
        for item in glyph.coverage
    )
    missing = sum(1 for item in coverage if not item.is_whitespace)
    return _rehash_model(
        glyph,
        visible=False,
        missing_codepoint_count=missing,
        coverage=coverage,
    )


def _glyph_with_ambiguous_fallback_or_tofu(glyph: RenderGlyphEvidenceV4):
    coverage = tuple(
        item.model_copy(
            update={
                "visible": False,
                # Equal signatures model the fallback/tofu ambiguity that
                # geometry alone cannot distinguish.
                "fallback_raster_signature": item.raster_signature,
            }
        )
        for item in glyph.coverage
    )
    missing = sum(1 for item in coverage if not item.is_whitespace)
    return _rehash_model(
        glyph,
        visible=False,
        missing_codepoint_count=missing,
        coverage=coverage,
    )


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        (
            lambda element: {
                "computed_font": _rehash_model(
                    element.computed_font,
                    font_loaded=False,
                    document_fonts_status="unloaded",
                )
            },
            "RENDER_FONT",
        ),
        (
            lambda element: {
                "computed_font": _rehash_model(
                    element.computed_font,
                    computed_family="serif",
                )
            },
            "RENDER_FONT",
        ),
        (
            lambda element: {
                "computed_font": _rehash_model(
                    element.computed_font,
                    font_size_px=element.computed_font.font_size_px + 1.0,
                )
            },
            "RENDER_FONT",
        ),
        (
            lambda element: {
                "computed_font": _rehash_model(
                    element.computed_font,
                    computed_weight=element.computed_font.computed_weight + 1,
                )
            },
            "RENDER_FONT",
        ),
        (
            lambda element: {
                "computed_font": _rehash_model(
                    element.computed_font,
                    line_height_px=element.computed_font.line_height_px + 1.0,
                )
            },
            "RENDER_FONT",
        ),
        (
            lambda element: {
                "glyph": _glyph_with_missing_witness(element.glyph),
            },
            "RENDER_GLYPH",
        ),
        (
            lambda element: {
                "glyph": _glyph_with_face_unloaded(element.glyph),
            },
            "RENDER_GLYPH",
        ),
        (
            lambda element: {
                "glyph": _glyph_with_font_check_failure(element.glyph),
            },
            "RENDER_GLYPH",
        ),
        (
            lambda element: {
                "glyph": _glyph_with_tofu_collision(element.glyph),
            },
            "RENDER_GLYPH",
        ),
        (
            lambda element: {
                "glyph": _glyph_with_ambiguous_fallback_or_tofu(element.glyph),
            },
            "RENDER_GLYPH",
        ),
    ),
)
def test_q3_rejects_font_face_metric_and_glyph_witness_failures(
    tmp_path, mutation, expected_code
):
    values = _world(tmp_path)
    manifest = values["render_manifest"]
    page = manifest.pages[0]
    element = page.elements[0]
    mutated = _rebuild_element(element, **mutation(element))
    page = _rebuild_page(page, elements=(mutated, *page.elements[1:]))
    _persist_manifest(values, _rebuild_manifest(manifest, pages=(page, *manifest.pages[1:])))

    result = evaluate_v4_render(**values)

    assert result.passed is False
    assert any(issue.code == expected_code for issue in result.issues)


def test_q3_rejects_mixed_page_order_before_aesthetic_issues(tmp_path):
    values = _world(tmp_path)
    manifest = values["render_manifest"]
    values["render_manifest"] = manifest.model_copy(
        update={"pages": (manifest.pages[1], manifest.pages[0], *manifest.pages[2:])}
    )

    with pytest.raises(V4RenderQAInvariantError):
        evaluate_v4_render(**values)


def test_q3_requires_canonical_revision_relative_page_paths(tmp_path):
    values = _world(tmp_path)
    manifest = values["render_manifest"]
    page = manifest.pages[0]
    mutated_page = _rebuild_page(page, elements=page.elements)
    page_payload = mutated_page.model_dump(mode="python")
    page_payload["path"] = "render/pages/renamed-page.png"
    page_payload.pop("canonical_sha256", None)
    from src.schemas.v4.rendering import RenderPageEvidenceV4

    mutated_page = RenderPageEvidenceV4(
        **page_payload,
        canonical_sha256=canonical_sha256_v4(page_payload),
    )
    mutated_manifest = _rebuild_manifest(
        manifest,
        pages=(mutated_page, *manifest.pages[1:]),
    )
    values["artifact_paths"].revision_root.joinpath(
        "render/render-manifest.json"
    ).write_text(canonical_json_v4(mutated_manifest), encoding="utf-8")
    values["render_manifest"] = mutated_manifest

    with pytest.raises(V4RenderQAInvariantError):
        evaluate_v4_render(**values)


@pytest.mark.parametrize("artifact", ("page", "contact", "manifest"))
def test_q3_rejects_render_page_contact_and_manifest_byte_mutation(tmp_path, artifact):
    values = _world(tmp_path)
    manifest = values["render_manifest"]
    if artifact == "page":
        page_path = values["artifact_paths"].revision_root / manifest.pages[0].path
        page_path.write_bytes(page_path.read_bytes() + b"mutation")
    elif artifact == "contact":
        contact_path = values["artifact_paths"].revision_root / manifest.contact_sheet_path
        contact_path.write_bytes(contact_path.read_bytes() + b"mutation")
    else:
        manifest_path = values["artifact_paths"].revision_root / "render/render-manifest.json"
        manifest_path.write_bytes(manifest_path.read_bytes() + b"mutation")

    with pytest.raises(V4RenderQAInvariantError):
        evaluate_v4_render(**values)


@pytest.mark.parametrize(
    "raw",
    (
        b"not-a-png",
        _png_bytes(1, 1, (255, 0, 0, 255)),
    ),
)
def test_q3_rejects_bad_png_signature_or_dimensions(tmp_path, raw):
    values = _world(tmp_path)
    _replace_page_bytes(values, raw)

    with pytest.raises(V4RenderQAInvariantError):
        evaluate_v4_render(**values)


@pytest.mark.parametrize("target", ("page", "contact"))
def test_q3_reports_blank_or_transparent_output(tmp_path, target):
    values = _world(tmp_path)
    manifest = values["render_manifest"]
    if target == "page":
        _replace_page_bytes(values, _png_bytes(1080, 1440, (0, 0, 0, 0)))
    else:
        contact_path = values["artifact_paths"].revision_root / manifest.contact_sheet_path
        with Image.open(contact_path) as image:
            raw = _png_bytes(image.width, image.height, (0, 0, 0, 0))
        _replace_contact_bytes(values, raw)

    result = evaluate_v4_render(**values)

    assert result.passed is False
    assert any(issue.code == "RENDER_BLANK_OUTPUT" for issue in result.issues)


def test_q3_rejects_missing_render_file(tmp_path):
    values = _world(tmp_path)
    page_path = values["artifact_paths"].revision_root / values["render_manifest"].pages[0].path
    page_path.unlink()

    with pytest.raises(V4RenderQAInvariantError):
        evaluate_v4_render(**values)


def test_q3_rejects_symlink_substitution_for_render_file(tmp_path):
    values = _world(tmp_path)
    page = values["render_manifest"].pages[0]
    page_path = values["artifact_paths"].revision_root / page.path
    outside = tmp_path / "outside-page.png"
    outside.write_bytes(page_path.read_bytes())
    page_path.unlink()
    page_path.symlink_to(outside)

    with pytest.raises(V4RenderQAInvariantError):
        evaluate_v4_render(**values)


def test_q3_reports_scroll_overflow_as_a_closed_issue(tmp_path):
    values = _world(tmp_path)
    manifest = values["render_manifest"]
    page = manifest.pages[0]
    element = page.elements[0]
    mutated = _rebuild_element(
        element,
        scroll_width=element.client_width + 1.0,
    )
    mutated_page = _rebuild_page(page, elements=(mutated, *page.elements[1:]))
    mutated_manifest = _rebuild_manifest(
        manifest,
        pages=(mutated_page, *manifest.pages[1:]),
    )
    values["artifact_paths"].revision_root.joinpath(
        "render/render-manifest.json"
    ).write_text(canonical_json_v4(mutated_manifest), encoding="utf-8")
    values["render_manifest"] = mutated_manifest

    result = evaluate_v4_render(**values)

    assert result.passed is False
    assert any(issue.code == "RENDER_OVERFLOW" for issue in result.issues)


def _replace_first_line_box(values, line_box):
    manifest = values["render_manifest"]
    page = manifest.pages[0]
    element = page.elements[0]
    mutated = _rebuild_element(element, line_boxes=(line_box,))
    mutated_page = _rebuild_page(page, elements=(mutated, *page.elements[1:]))
    mutated_manifest = _rebuild_manifest(
        manifest,
        pages=(mutated_page, *manifest.pages[1:]),
    )
    values["artifact_paths"].revision_root.joinpath(
        "render/render-manifest.json"
    ).write_text(canonical_json_v4(mutated_manifest), encoding="utf-8")
    values["render_manifest"] = mutated_manifest


def test_q3_ignores_font_metric_leading_when_painted_ink_fits(tmp_path):
    values = _world(tmp_path)
    element = values["render_manifest"].pages[0].elements[0]
    _replace_first_line_box(
        values,
        RenderBoxV4(
            x=element.actual_box.x,
            y=element.actual_box.y - 10.0,
            width=401.375,
            height=120.0,
        ),
    )

    result = evaluate_v4_render(**values)

    assert result.passed is True
    assert not any(issue.code == "RENDER_OVERFLOW" for issue in result.issues)


def test_q3_rejects_line_box_beyond_font_metric_leading(tmp_path):
    values = _world(tmp_path)
    element = values["render_manifest"].pages[0].elements[0]
    _replace_first_line_box(
        values,
        RenderBoxV4(
            x=element.actual_box.x,
            y=element.actual_box.y - 15.0,
            width=401.375,
            height=120.0,
        ),
    )

    result = evaluate_v4_render(**values)

    assert result.passed is False
    assert any(issue.code == "RENDER_OVERFLOW" for issue in result.issues)


def _asset_evaluator_world(tmp_path: Path):
    """Build a complete image-bearing comparison world at the public seam."""

    from src.nodes.v4.composition import build_layout_program
    from src.nodes.v4.design_qa import aggregate_design_qa
    from src.nodes.v4.layout import aggregate_layout_plan
    from src.rendering.scene.renderer import RenderedPageDraft
    from src.schemas.content_lock import ContentLock
    from src.schemas.v4.direction import (
        AssetDirectiveV4,
        PageBriefSetV4,
        PageBriefV4,
        VisualDirectionPlanV4,
    )
    from src.visual_design.v4.compiler import LayoutCompilerInputsV4, compile_layout
    from src.visual_design.v4.semantic_qa import evaluate_semantic_model
    from src.visual_design.v4.tokens import get_family_tokens
    from tests.integration.test_v4_three_grammar_render import _rebuild_upstream
    from tests.nodes.v4.test_design_qa import _fixture
    from tests.rendering.scene.test_v4_adapter import _render_stub

    atoms, semantic, original_page_set, original_direction, _, base_plan = _rebuild_upstream(
        "comparison_grid"
    )
    fixture = _fixture()
    identity = ArtifactIdentity(
        base_plan.run_id,
        base_plan.candidate_id,
        f"revision-{base_plan.revision}",
    )
    paths = ensure_artifact_paths(resolve_artifact_paths(tmp_path, identity))

    page_models: list[PageBriefV4] = []
    manifest_items: list[AssetManifestItem] = []
    for sequence, brief in enumerate(original_page_set.pages, start=1):
        directive = AssetDirectiveV4(
            directive_id=f"q3-asset-directive-{sequence}",
            page_id=brief.page_id,
            role="object",
            purpose="supporting",
            supports_fragment_refs=(brief.fragment_refs[0],),
            required=True,
            preferred_source="search",
            query_or_prompt="text-free comparison support object",
            orientation="portrait",
        )
        page_payload = brief.model_dump(mode="python")
        page_payload["asset_directives"] = (directive,)
        page_payload.pop("canonical_sha256", None)
        page_models.append(
            PageBriefV4(
                **page_payload,
                canonical_sha256=canonical_sha256_v4(page_payload),
            )
        )
        raw = _png_bytes(1200, 1600, (255, 0, 0, 255))
        source = paths.asset_root / f"q3-asset-{sequence}.png"
        source.write_bytes(raw)
        manifest_items.append(
            AssetManifestItem(
                asset_id=f"q3-asset-{sequence}",
                directive_id=directive.directive_id,
                page_id=brief.page_id,
                source_kind="search",
                provider="fixture-provider",
                license="fixture-license",
                local_path=str(source),
                width=1200,
                height=1600,
                sha256=hashlib.sha256(raw).hexdigest(),
                subject_focal_point=(0.5, 0.5),
                crop_guidance="center",
                security_status="approved",
                human_decision="pending",
                run_id=base_plan.run_id,
                transaction_id=f"revision-{base_plan.revision}",
                internal_provenance={"fixture": "q3-public-asset"},
            )
        )

    page_set_payload = original_page_set.model_dump(mode="python")
    page_set_payload["pages"] = tuple(page_models)
    page_set_payload.pop("canonical_sha256", None)
    page_set = PageBriefSetV4(
        **page_set_payload,
        canonical_sha256=canonical_sha256_v4(page_set_payload),
    )
    direction_payload = original_direction.model_dump(mode="python")
    direction_payload["page_brief_set"] = page_set
    direction_payload["page_brief_set_sha256"] = page_set.canonical_sha256
    direction_payload.pop("canonical_sha256", None)
    direction = VisualDirectionPlanV4(
        **direction_payload,
        canonical_sha256=canonical_sha256_v4(direction_payload),
    )
    asset_manifest = AssetManifest(items=tuple(manifest_items))
    compiled_pages = []
    for brief in page_set.pages:
        program = build_layout_program(
            brief,
            grammar_id="comparison_grid",
            family=direction.template_family,
            narrative=direction.narrative,
        )
        compiled_pages.append(
            compile_layout(
                program,
                LayoutCompilerInputsV4(
                    page_brief=brief,
                    semantic_content_model=semantic,
                    content_atom_set=atoms,
                    asset_manifest=asset_manifest,
                    candidate_id=base_plan.candidate_id,
                    revision=base_plan.revision,
                    run_id=base_plan.run_id,
                    visual_direction_plan=direction,
                ),
            )
        )
    plan = aggregate_layout_plan(
        compiled_pages,
        content_atom_set=atoms,
        semantic_content_model=semantic,
        page_brief_set=page_set,
        asset_manifest=asset_manifest,
        family_tokens=get_family_tokens(direction.template_family),
        revision=base_plan.revision,
        candidate_id=base_plan.candidate_id,
        run_id=base_plan.run_id,
        visual_direction_plan=direction,
    )

    lock_payload = fixture["lock"].model_dump(mode="python")
    lock_payload["content_atom_set_sha256"] = atoms.canonical_sha256
    lock_payload.pop("canonical_sha256", None)
    lock = ContentLock(
        **lock_payload,
        canonical_sha256=canonical_sha256_v4(lock_payload),
    )
    q0 = evaluate_semantic_model(atoms, semantic, content_lock=lock)
    q1_payload = fixture["q1"].model_dump(mode="python")
    q1_payload.update(
        {
            "content_atom_set_sha256": atoms.canonical_sha256,
            "content_lock_sha256": lock.canonical_sha256,
            "semantic_content_model_sha256": semantic.canonical_sha256,
            "narrative_sha256": direction.narrative_sha256,
            "page_brief_set_sha256": page_set.canonical_sha256,
            "visual_direction_plan_sha256": direction.canonical_sha256,
        }
    )
    q1_payload.pop("canonical_sha256", None)
    q1 = type(fixture["q1"])(
        **q1_payload,
        canonical_sha256=canonical_sha256_v4(q1_payload),
    )
    qa = aggregate_design_qa(
        semantic_qa=q0,
        authoring_qa=q1,
        carousel_design_plan=plan,
        content_atom_set=atoms,
        content_lock=lock,
        semantic_content_model=semantic,
        page_brief_set=page_set,
        visual_direction_plan=direction,
        asset_manifest=asset_manifest,
    )

    family = get_family_tokens(direction.template_family)
    base_render = _render_stub(plan, semantic)

    def render(compiled_page):
        draft = base_render(compiled_page)
        text_by_id = {
            raw["element_id"]: dict(raw)
            for raw in draft.raw_probes
            if raw.get("element_id")
        }
        page = next(item for item in plan.pages if item.page_id == compiled_page.page_id)
        probes = []
        for element in sorted(page.scene.elements, key=lambda item: item.layer):
            if element.kind == "text":
                raw = text_by_id[element.element_id]
                raw["font_family"] = getattr(
                    family.font_roles,
                    element.style.font_role,
                )
            else:
                raw = {
                    "element_id": element.element_id,
                    "content_ref": None,
                    "asset_ref": element.asset_ref,
                    "x": element.box.x,
                    "y": element.box.y,
                    "width": element.box.width,
                    "height": element.box.height,
                    "scroll_width": element.box.width,
                    "scroll_height": element.box.height,
                    "client_width": element.box.width,
                    "client_height": element.box.height,
                    "line_boxes": [],
                    "asset_loaded": True,
                    "natural_width": 1200.0,
                    "natural_height": 1600.0,
                    "rendered_image_width": element.box.width,
                    "rendered_image_height": element.box.height,
                }
            probes.append(raw)
        return RenderedPageDraft(
            page_id=draft.page_id,
            png_bytes=draft.png_bytes,
            raw_probes=probes,
        )

    rendered = render_v4_revision(
        design_plan=plan,
        design_plan_qa_result=qa,
        content_atom_set=atoms,
        content_lock=lock,
        semantic_content_model=semantic,
        page_brief_set=page_set,
        visual_direction_plan=direction,
        asset_manifest=asset_manifest,
        family_tokens=direction.template_family,
        artifact_paths=paths,
        render_page_fn=render,
    )
    return {
        "render_manifest": rendered.manifest,
        "design_plan": plan,
        "design_plan_qa_result": qa,
        "content_atom_set": atoms,
        "content_lock": lock,
        "semantic_content_model": semantic,
        "page_brief_set": page_set,
        "visual_direction_plan": direction,
        "asset_manifest": asset_manifest,
        "family_tokens": direction.template_family,
        "artifact_paths": paths,
    }


def _mutate_first_image_asset(values, **updates):
    manifest = values["render_manifest"]
    page = manifest.pages[0]
    index = next(index for index, item in enumerate(page.elements) if item.kind == "image")
    element = page.elements[index]
    mutated = _rebuild_element(
        element,
        asset=_rehash_model(element.asset, **updates),
    )
    elements = list(page.elements)
    elements[index] = mutated
    mutated_page = _rebuild_page(page, elements=tuple(elements))
    pages = list(manifest.pages)
    pages[0] = mutated_page
    _persist_manifest(values, _rebuild_manifest(manifest, pages=tuple(pages)))


def test_q3_public_evaluator_accepts_a_valid_asset_world(tmp_path):
    values = _asset_evaluator_world(tmp_path)

    result = evaluate_v4_render(**values)

    assert result.passed is True
    assert result.issues == ()


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        (lambda: {"asset_sha256": "0" * 64}, "RENDER_ASSET"),
        (
            lambda: {"asset_ref": "v4-asset-" + "1" * 64},
            "RENDER_ASSET",
        ),
        (lambda: {"loaded": False}, "RENDER_ASSET"),
        (lambda: {"crop_factor": 1.0}, "RENDER_CROP"),
        (lambda: {"orientation": "landscape"}, "RENDER_CROP"),
    ),
)
def test_q3_public_evaluator_rejects_asset_binding_mutations(
    tmp_path, mutation, expected_code
):
    values = _asset_evaluator_world(tmp_path)
    _mutate_first_image_asset(values, **mutation())

    result = evaluate_v4_render(**values)

    assert result.passed is False
    assert any(issue.code == expected_code for issue in result.issues)


def test_q3_public_evaluator_rejects_substituted_asset_bytes(tmp_path):
    values = _asset_evaluator_world(tmp_path)
    item = values["asset_manifest"].items[0]
    Path(item.local_path).write_bytes(_png_bytes(1200, 1600, (0, 0, 255, 255)))

    with pytest.raises(V4RenderQAInvariantError):
        evaluate_v4_render(**values)


def _asset_world(tmp_path: Path):
    paths = ensure_artifact_paths(
        resolve_artifact_paths(
            tmp_path,
            ArtifactIdentity("run-a", "candidate-a", "revision-1"),
        )
    )
    source = paths.asset_root / "q3-asset.png"
    raw = _png_bytes(120, 80, (255, 0, 0, 255))
    source.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    element = ImageElement(
        element_id="image-1",
        layer=1,
        box=Box(x=80, y=100, width=120, height=80),
        asset_ref="v4-asset-" + "0" * 64,
        fit="contain",
        focal_point=(0.5, 0.5),
    )
    asset_ref = opaque_asset_ref_v4(
        candidate_id="candidate-a",
        revision=1,
        page_id="page-1",
        directive_id="directive-1",
        asset_sha256=digest,
    )
    element = element.model_copy(update={"asset_ref": asset_ref})
    binding = AssetBindingEvidenceV4(
        directive_id="directive-1",
        asset_ref=asset_ref,
        asset_sha256=digest,
        page_id="page-1",
        region_id="region-1",
        orientation="landscape",
        fit="contain",
        box_ratio=1.5,
        crop_factor=1.0,
    )
    page = SimpleNamespace(
        page_id="page-1",
        compiler_provenance=SimpleNamespace(
            asset_binding_evidence={"directive-1": binding}
        ),
    )
    plan = SimpleNamespace(
        run_id="run-a",
        candidate_id="candidate-a",
        revision=1,
    )
    item = AssetManifestItem(
        asset_id="asset-1",
        directive_id="directive-1",
        page_id="page-1",
        source_kind="catalog",
        provider="fixture-provider",
        license="fixture-license",
        local_path=str(source),
        width=120,
        height=80,
        sha256=digest,
        subject_focal_point=(0.5, 0.5),
        crop_guidance="center",
        security_status="approved",
        human_decision="pending",
        run_id="run-a",
        transaction_id="revision-1",
        internal_provenance={"fixture": "private"},
    )
    manifest = AssetManifest(items=(item,))
    observed_payload = {
        "directive_id": "directive-1",
        "asset_ref": asset_ref,
        "asset_sha256": digest,
        "fit": "contain",
        "orientation": "landscape",
        "loaded": True,
        "natural_width": 120.0,
        "natural_height": 80.0,
        "rendered_width": 120.0,
        "rendered_height": 80.0,
        "box_ratio": 1.5,
        "crop_factor": 1.0,
    }
    observed = RenderAssetEvidenceV4(
        **observed_payload,
        canonical_sha256=canonical_sha256_v4(observed_payload),
    )
    return paths, element, page, plan, manifest, observed, source


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        (lambda observed: {"asset_sha256": "0" * 64}, "RENDER_ASSET"),
        (
            lambda observed: {"asset_ref": "v4-asset-" + "1" * 64},
            "RENDER_ASSET",
        ),
        (lambda observed: {"loaded": False}, "RENDER_ASSET"),
        (lambda observed: {"crop_factor": 1.2}, "RENDER_CROP"),
        (lambda observed: {"orientation": "portrait"}, "RENDER_CROP"),
    ),
)
def test_q3_asset_evaluator_rejects_hash_ref_load_crop_and_orientation_mismatch(
    tmp_path, mutation, expected_code
):
    paths, element, page, plan, manifest, observed, _source = _asset_world(tmp_path)
    mutated = _rehash_model(observed, **mutation(observed))

    issues = _asset_issues(
        page_id="page-1",
        element=element,
        observed=mutated,
        plan_page=page,
        asset_manifest=manifest,
        paths=paths,
        plan=plan,
    )

    assert expected_code in {issue.code for issue in issues}


def test_q3_asset_evaluator_rejects_substituted_asset_bytes(tmp_path):
    paths, element, page, plan, manifest, observed, source = _asset_world(tmp_path)
    source.write_bytes(_png_bytes(120, 80, (0, 0, 255, 255)))

    with pytest.raises(V4RenderQAInvariantError):
        _asset_issues(
            page_id="page-1",
            element=element,
            observed=observed,
            plan_page=page,
            asset_manifest=manifest,
            paths=paths,
            plan=plan,
        )
