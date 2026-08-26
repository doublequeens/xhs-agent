"""Real-file tests for v4's offline review workspace."""

from __future__ import annotations

import os
import json
from pathlib import Path

import pytest

from src.review.v4_workspace import (
    ReviewBindingError,
    ReviewWorkspaceInputsV4,
    _html_page,
    build_review_workspace,
    read_review_intent,
    verify_review_workspace,
)
from src.schemas.v4.content import canonical_sha256_v4
from src.schemas.content_atoms import canonical_sha256
from src.schemas.v4.critique import (
    AestheticPageEvaluationV4,
    CarouselAestheticEvaluationV4,
    SetAestheticEvaluationV4,
)


def _inputs(tmp_path: Path) -> ReviewWorkspaceInputsV4:
    from tests.visual_design.v4.test_v4_render_qa import _world
    from src.visual_design.v4.render_qa import evaluate_v4_render

    world = _world(tmp_path)
    q3 = evaluate_v4_render(**world)
    render = world["render_manifest"]
    critique = CarouselAestheticEvaluationV4.create(
        render_manifest_sha256=render.canonical_sha256,
        render_qa_result_sha256=q3.canonical_sha256,
        page_brief_set_sha256=world["page_brief_set"].canonical_sha256,
        semantic_content_model_sha256=world["semantic_content_model"].canonical_sha256,
        authoring_model_identity="authoring",
        evaluator_model_identity="evaluator",
        pages=tuple(
            AestheticPageEvaluationV4.create(
                page_id=page.page_id,
                hierarchy=90, readability=90, composition=90, whitespace=90,
                visual_focus=90, asset_integration=90,
            ) for page in render.pages
        ),
        set_evaluation=SetAestheticEvaluationV4.create(
            rhythm=90, repetition=90, family_consistency=90, cover_body_consistency=90,
        ),
    )
    return ReviewWorkspaceInputsV4(
        artifact_paths=world["artifact_paths"],
        content_lock=world["content_lock"],
        content_atom_set=world["content_atom_set"],
        semantic_content_model=world["semantic_content_model"],
        carousel_narrative=world["visual_direction_plan"].narrative,
        page_brief_set=world["page_brief_set"],
        visual_direction_plan=world["visual_direction_plan"],
        asset_manifest=world["asset_manifest"],
        carousel_design_plan=world["design_plan"],
        design_plan_qa=world["design_plan_qa_result"],
        render_manifest=render,
        render_qa=q3,
        visual_critique=critique,
    )


def test_workspace_transaction_publishes_complete_hash_bound_offline_review(tmp_path):
    """Removing a copied page/manifest input integrity must make the workspace fail closed."""
    workspace = build_review_workspace(_inputs(tmp_path))
    root = workspace.root
    assert (root / "index.html").is_file()
    assert (root / "contact-sheet.png").is_file()
    assert len(tuple((root / "pages").glob("*.png"))) == len(workspace.manifest.page_sha256)
    assert (root / "overlays" / "01-page-1.svg").is_file()
    assert (root / "quality-report.json").is_file()
    assert (root / "decision.json").is_file()
    assert (root / "workspace-manifest.json").is_file()
    verify_review_workspace(workspace)


@pytest.mark.parametrize("attack", ("bytes", "symlink", "traversal"))
def test_workspace_verifier_rejects_tampered_review_page_and_paths(tmp_path, attack):
    """A verifier that trusts workspace filenames or changed bytes must fail this test."""
    workspace = build_review_workspace(_inputs(tmp_path))
    page = workspace.root / "pages" / "01-page-1.png"
    if attack == "bytes":
        page.write_bytes(b"changed")
    elif attack == "symlink":
        outside = tmp_path / "outside.png"
        outside.write_bytes(page.read_bytes())
        page.unlink()
        page.symlink_to(outside)
    else:
        payload = workspace.manifest.model_dump(mode="json", exclude={"canonical_sha256"})
        payload["page_sha256"] = {"../escape.png": "a" * 64}
        with pytest.raises(ValueError):
            type(workspace.manifest)(**payload, canonical_sha256=canonical_sha256_v4(payload))
        return
    with pytest.raises(ReviewBindingError):
        verify_review_workspace(workspace)


def test_workspace_html_escapes_dynamic_copy_and_uses_local_only_csp(tmp_path):
    """Dropping escaping or CSP would expose this hostile locked title in file:// review."""
    inputs = _inputs(tmp_path)
    payload = inputs.content_lock.model_dump(mode="python", exclude={"canonical_sha256"})
    payload["title"] = "<img src=x onerror=alert(1)>"
    lock = inputs.content_lock.model_copy(update={
        "title": payload["title"], "canonical_sha256": canonical_sha256(payload),
    })
    html = _html_page(
        inputs.model_copy(update={"content_lock": lock}), None,
        {"pages/01-page-1.png": "a" * 64},
    ).decode()
    assert "script-src 'none'" in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "http://" not in html and "https://" not in html


def test_workspace_file_url_chromium_smoke_has_sections_and_no_network(tmp_path):
    """A missing local image/section or remote request must fail the actual browser review seam."""
    playwright = pytest.importorskip("playwright.sync_api")
    workspace = build_review_workspace(_inputs(tmp_path))
    requests: list[str] = []
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("request", lambda request: requests.append(request.url))
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto((workspace.root / "index.html").as_uri())
        assert page.locator("#contact-sheet").is_visible()
        assert page.locator(".page-card").count() == len(workspace.manifest.page_sha256)
        assert page.locator("#quality-report").is_visible()
        assert page.locator("#asset-evidence").is_visible()
        assert page.locator(".overlay").count() == len(workspace.manifest.page_sha256)
        assert not [url for url in requests if not url.startswith("file:")]
        assert not errors
        page.screenshot(path=str(tmp_path / "review.png"))
        browser.close()


def test_mutable_decision_intake_is_parseable_but_not_static_manifest_bound(tmp_path):
    """Editing the untrusted decision file must not alter immutable workspace evidence."""
    workspace = build_review_workspace(_inputs(tmp_path))
    (workspace.root / "decision.json").write_text('{"action":"REQUEST_REVISION","feedback":"adjust spacing","asset_ids":[],"rationale":null,"visible_copy_payload":null}', encoding="utf-8")
    assert read_review_intent(workspace).action == "REQUEST_REVISION"
    verify_review_workspace(workspace)


def test_workspace_verifier_rejects_hardlinked_page_and_extra_file(tmp_path):
    workspace = build_review_workspace(_inputs(tmp_path))
    page = workspace.root / "pages" / "01-page-1.png"
    outside = tmp_path / "hardlink.png"
    page.unlink()
    os.link(outside if outside.exists() else workspace.root / "contact-sheet.png", page)
    with pytest.raises(ReviewBindingError):
        verify_review_workspace(workspace)

    workspace = build_review_workspace(_inputs(tmp_path / "second"))
    (workspace.root / "unexpected.txt").write_bytes(b"unexpected")
    with pytest.raises(ReviewBindingError):
        verify_review_workspace(workspace)


def test_workspace_manifest_self_rehash_cannot_remove_required_evidence(tmp_path):
    workspace = build_review_workspace(_inputs(tmp_path))
    manifest_path = workspace.root / "workspace-manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["files"].pop("quality-report.json")
    payload["canonical_sha256"] = canonical_sha256_v4({key: value for key, value in payload.items() if key != "canonical_sha256"})
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(ReviewBindingError):
        verify_review_workspace(workspace)


def test_workspace_build_rejects_hardlinked_render_source(tmp_path):
    inputs = _inputs(tmp_path)
    source = inputs.artifact_paths.revision_root / inputs.render_manifest.pages[0].path
    os.link(source, tmp_path / "render-hardlink.png")
    with pytest.raises(ReviewBindingError):
        build_review_workspace(inputs)
