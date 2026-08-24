"""Independent Q3 tests for the v4 render evidence boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.rendering.scene.v4_adapter import render_v4_revision
from src.schemas.v4.content import canonical_json_v4, canonical_sha256_v4
from src.schemas.v4.rendering import RenderBoxV4, RenderManifestV4
from src.visual_design.v4.render_qa import (
    RENDER_BOX_DRIFT,
    V4RenderQAInvariantError,
    evaluate_v4_render,
)
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
