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
from src.schemas.v4.rendering import (
    RenderElementEvidenceV4,
    RenderManifestV4,
    RenderPageEvidenceV4,
    RenderQAResultV4,
)
from src.schemas.v4.quality import (
    DesignMetricEvidenceV4,
    DesignMetricsQAResultV4,
    DesignPlanQAResultV4,
)


def _inputs(
    tmp_path: Path,
    *,
    revision: int = 1,
    run_id: str = "run-a",
    candidate_id: str = "candidate-a",
) -> ReviewWorkspaceInputsV4:
    """Build a valid end-to-end source world for review-boundary tests.

    The small Q3 fixture intentionally uses one repeated composition to test
    render evidence in isolation.  Review is a Q0-Q3 hard-gate boundary, so
    this helper varies the authoring candidates and recompiles the downstream
    plan/render evidence instead of manufacturing a passing Q1 result.
    """
    from tests.nodes.v4.test_design_qa import _fixture
    from tests.rendering.scene.test_v4_adapter import _render_stub
    from src.nodes.v4.composition import build_layout_program
    from src.nodes.v4.design_qa import aggregate_design_qa
    from src.nodes.v4.layout import aggregate_layout_plan
    from src.rendering.scene.renderer import RenderedPageDraft
    from src.rendering.scene.v4_adapter import render_v4_revision
    from src.schemas.assets import AssetManifest
    from src.schemas.v4.content import canonical_sha256_v4
    from src.schemas.v4.direction import PageBriefSetV4, PageBriefV4, VisualDirectionPlanV4
    from src.visual_design.v4.authoring_qa import evaluate_authoring
    from src.visual_design.v4.semantic_qa import evaluate_semantic_model
    from src.visual_design.v4.compiler import LayoutCompilerInputsV4, compile_layout
    from src.visual_design.v4.tokens import get_family_tokens
    from src.visual_runtime.artifact_identity import ArtifactIdentity, ensure_artifact_paths, resolve_artifact_paths
    from src.visual_design.v4.render_qa import evaluate_v4_render

    fixture = _fixture()
    old_page_set = fixture["page_set"]
    preferred_compositions = (
        ("editorial_hero", "comparison_grid"),
        ("comparison_grid", "editorial_hero"),
        ("step_flow", "editorial_hero"),
        ("comparison_grid", "editorial_hero"),
        ("summary_closing", "editorial_hero"),
    )
    narrative_roles = ("cover hook", "context", "diagnosis", "step", "summary")
    pages = []
    for index, page in enumerate(old_page_set.pages):
        payload = page.model_dump(mode="python")
        payload.update(
            narrative_role=narrative_roles[index],
            preferred_compositions=preferred_compositions[index],
        )
        payload.pop("canonical_sha256", None)
        pages.append(PageBriefV4(**payload, canonical_sha256=canonical_sha256_v4(payload)))
    page_set_payload = old_page_set.model_dump(mode="python")
    page_set_payload["pages"] = tuple(pages)
    page_set_payload.pop("canonical_sha256", None)
    page_set = PageBriefSetV4(
        **page_set_payload,
        canonical_sha256=canonical_sha256_v4(page_set_payload),
    )
    direction_payload = fixture["direction_plan"].model_dump(mode="python")
    direction_payload.update(
        page_brief_set=page_set,
        page_brief_set_sha256=page_set.canonical_sha256,
    )
    direction_payload.pop("canonical_sha256", None)
    direction = VisualDirectionPlanV4(
        **direction_payload,
        canonical_sha256=canonical_sha256_v4(direction_payload),
    )
    asset_manifest = AssetManifest(items=())
    compiled_pages = []
    for page in pages:
        program = build_layout_program(
            page,
            grammar_id="editorial_hero",
            family=direction.template_family,
            narrative=direction.narrative,
        )
        compiled_pages.append(
            compile_layout(
                program,
                LayoutCompilerInputsV4(
                    page_brief=page,
                    semantic_content_model=fixture["semantic_model"],
                    content_atom_set=fixture["atom_set"],
                    asset_manifest=asset_manifest,
                    candidate_id=candidate_id,
                    revision=revision,
                    run_id=run_id,
                    visual_direction_plan=direction,
                ),
            )
        )
    plan = aggregate_layout_plan(
        compiled_pages,
        content_atom_set=fixture["atom_set"],
        semantic_content_model=fixture["semantic_model"],
        page_brief_set=page_set,
        asset_manifest=asset_manifest,
        family_tokens=get_family_tokens(direction.template_family),
        revision=revision,
        candidate_id=candidate_id,
        run_id=run_id,
        visual_direction_plan=direction,
    )
    lock = fixture["lock"]
    q0 = evaluate_semantic_model(fixture["atom_set"], fixture["semantic_model"], content_lock=lock)
    q1 = evaluate_authoring(
        page_set,
        fixture["semantic_model"],
        direction.narrative,
        direction,
        content_lock=lock,
        content_atom_set=fixture["atom_set"],
    )
    assert q1.passed
    q2 = aggregate_design_qa(
        semantic_qa=q0,
        authoring_qa=q1,
        carousel_design_plan=plan,
        content_atom_set=fixture["atom_set"],
        content_lock=lock,
        semantic_content_model=fixture["semantic_model"],
        page_brief_set=page_set,
        visual_direction_plan=direction,
        asset_manifest=asset_manifest,
    )
    paths = ensure_artifact_paths(
        resolve_artifact_paths(
            tmp_path,
            ArtifactIdentity(run_id, candidate_id, f"revision-{revision}"),
        )
    )
    base_render = _render_stub(plan, fixture["semantic_model"])

    def render(compiled_page):
        draft = base_render(compiled_page)
        source_page = next(item for item in plan.pages if item.page_id == compiled_page.page_id)
        family = get_family_tokens(direction.template_family)
        probes = []
        for raw, element in zip(
            draft.raw_probes,
            sorted(source_page.scene.elements, key=lambda item: item.layer),
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
        design_plan_qa_result=q2,
        content_atom_set=fixture["atom_set"],
        content_lock=lock,
        semantic_content_model=fixture["semantic_model"],
        page_brief_set=page_set,
        visual_direction_plan=direction,
        asset_manifest=asset_manifest,
        family_tokens=direction.template_family,
        artifact_paths=paths,
        render_page_fn=render,
    )
    world = {
        "render_manifest": rendered.manifest,
        "design_plan": plan,
        "design_plan_qa_result": q2,
        "content_atom_set": fixture["atom_set"],
        "content_lock": lock,
        "semantic_content_model": fixture["semantic_model"],
        "page_brief_set": page_set,
        "visual_direction_plan": direction,
        "asset_manifest": asset_manifest,
        "family_tokens": direction.template_family,
        "artifact_paths": paths,
    }
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


def test_workspace_overlay_and_footer_show_bound_geometry_identity(tmp_path):
    workspace = build_review_workspace(_inputs(tmp_path))
    source_page = _inputs(tmp_path / "source").carousel_design_plan.pages[0]
    region = next(iter(source_page.compiler_provenance.region_geometry_evidence.values()))
    overlay = (workspace.root / "overlays" / "01-page-1.svg").read_text(encoding="utf-8")
    assert f'data-region-id="{region.region_id}"' in overlay
    assert f'x="{region.x:g}"' in overlay
    index = (workspace.root / "index.html").read_text(encoding="utf-8")
    assert "source RenderManifest identity:" in index
    assert "workspace manifest identity:" not in index
    assert "recovery=recorded" not in index


def test_workspace_api_rejects_legacy_previous_fields_and_forged_workspace_handle(tmp_path):
    inputs = _inputs(tmp_path)
    with pytest.raises(Exception):
        ReviewWorkspaceInputsV4.model_validate({
            **inputs.model_dump(mode="python"),
            "previous_review_root": tmp_path,
        })
    workspace = build_review_workspace(inputs)
    from dataclasses import replace

    with pytest.raises(ReviewBindingError):
        verify_review_workspace(replace(workspace, manifest_raw=b"forged"))
    with pytest.raises(ReviewBindingError):
        verify_review_workspace(replace(workspace, manifest_raw="forged"))


def test_workspace_typed_previous_revision_has_hash_bound_diff_and_paired_pages(tmp_path):
    previous = build_review_workspace(_inputs(tmp_path, revision=1))
    current_inputs = _inputs(tmp_path, revision=2)
    current = build_review_workspace(
        current_inputs.model_copy(update={"previous_review_workspace": previous})
    )
    assert current.manifest.previous_revision_id == "revision-1"
    diff = json.loads((current.root / "revision-diff.json").read_text(encoding="utf-8"))
    assert diff["summary"] == {"added": 0, "removed": 0, "changed": 0, "unchanged": 5}
    index = (current.root / "index.html").read_text(encoding="utf-8")
    assert index.count('class="revision-pair"') == 5
    assert index.count('class="current-page"') == 5
    assert index.count('class="previous-page"') == 5
    verify_review_workspace(current)


@pytest.mark.parametrize("mismatch", ("base", "run", "candidate", "same", "future"))
def test_workspace_rejects_wrong_or_non_prior_typed_previous(tmp_path, mismatch):
    if mismatch == "same":
        current = _inputs(tmp_path, revision=2)
        previous = build_review_workspace(current)
    elif mismatch == "base":
        previous = build_review_workspace(_inputs(tmp_path / "other-base", revision=1))
    elif mismatch == "run":
        previous = build_review_workspace(_inputs(tmp_path, revision=1, run_id="run-other"))
    elif mismatch == "candidate":
        previous = build_review_workspace(_inputs(tmp_path, revision=1, candidate_id="candidate-other"))
    else:
        previous = build_review_workspace(_inputs(tmp_path, revision=3))
    if mismatch != "same":
        current = _inputs(tmp_path, revision=2)
    with pytest.raises(ReviewBindingError):
        build_review_workspace(current.model_copy(update={"previous_review_workspace": previous}))


def test_workspace_rejects_forged_or_changed_typed_previous(tmp_path):
    from dataclasses import replace

    previous = build_review_workspace(_inputs(tmp_path, revision=1))
    forged = replace(previous, manifest_raw=b"forged")
    current = _inputs(tmp_path, revision=2)
    with pytest.raises(ReviewBindingError):
        build_review_workspace(current.model_copy(update={"previous_review_workspace": forged}))

    previous = build_review_workspace(_inputs(tmp_path / "changed", revision=1))
    (previous.root / "pages" / "01-page-1.png").write_bytes(b"changed")
    current = _inputs(tmp_path / "changed", revision=2)
    with pytest.raises(ReviewBindingError):
        build_review_workspace(current.model_copy(update={"previous_review_workspace": previous}))


def test_workspace_postpublish_failure_quarantines_result_and_retry_succeeds(tmp_path, monkeypatch):
    inputs = _inputs(tmp_path)
    real_verify = verify_review_workspace
    calls = {"count": 0}

    def fail_once(workspace):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ReviewBindingError("injected postpublish verification failure")
        return real_verify(workspace)

    monkeypatch.setattr("src.review.v4_workspace.verify_review_workspace", fail_once)
    with pytest.raises(ReviewBindingError):
        build_review_workspace(inputs)
    assert not inputs.artifact_paths.review_root.exists()
    assert tuple(inputs.artifact_paths.revision_root.glob("review-recovery-*.json"))
    workspace = build_review_workspace(inputs)
    verify_review_workspace(workspace)


def test_workspace_cleanup_failure_uses_quarantine_and_retry_succeeds(tmp_path, monkeypatch):
    inputs = _inputs(tmp_path)
    module = __import__("src.review.v4_workspace", fromlist=["_remove_tree_at"])
    real_verify = verify_review_workspace
    real_remove = module._remove_tree_at
    verify_calls = {"count": 0}
    remove_calls = {"count": 0}

    def fail_verify(workspace):
        verify_calls["count"] += 1
        if verify_calls["count"] == 1:
            raise ReviewBindingError("injected durability failure")
        return real_verify(workspace)

    def fail_remove(parent_fd, name):
        if name == "review" and remove_calls["count"] == 0:
            remove_calls["count"] += 1
            raise OSError("injected cleanup failure")
        return real_remove(parent_fd, name)

    monkeypatch.setattr(module, "verify_review_workspace", fail_verify)
    monkeypatch.setattr(module, "_remove_tree_at", fail_remove)
    with pytest.raises(ReviewBindingError):
        build_review_workspace(inputs)
    assert not inputs.artifact_paths.review_root.exists()
    workspace = build_review_workspace(inputs)
    real_verify(workspace)


def test_workspace_recovery_journal_failure_preserves_primary_and_retry(tmp_path, monkeypatch):
    inputs = _inputs(tmp_path)
    module = __import__("src.review.v4_workspace", fromlist=["_write_recovery_journal"])
    real_verify = verify_review_workspace
    verify_calls = {"count": 0}

    def fail_verify_once(workspace):
        verify_calls["count"] += 1
        if verify_calls["count"] == 1:
            raise ReviewBindingError("injected postpublish failure")
        return real_verify(workspace)

    monkeypatch.setattr(module, "verify_review_workspace", fail_verify_once)
    monkeypatch.setattr(
        module,
        "_write_recovery_journal",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("injected recovery failure")),
    )
    with pytest.raises(ReviewBindingError) as error:
        build_review_workspace(inputs)
    assert not inputs.artifact_paths.review_root.exists()
    assert "recovery journal failed" in " ".join(getattr(error.value.__cause__, "__notes__", ()))

    monkeypatch.setattr(module, "verify_review_workspace", real_verify)
    workspace = build_review_workspace(inputs)
    real_verify(workspace)


@pytest.mark.parametrize("failure", ("write", "verify", "publish"))
def test_workspace_transaction_failures_leave_no_visible_review(tmp_path, monkeypatch, failure):
    inputs = _inputs(tmp_path)
    if failure == "write":
        original = __import__("src.review.v4_workspace", fromlist=["_stage_write"])._stage_write
        calls = {"count": 0}

        def fail_write(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 2:
                raise OSError("injected write failure")
            return original(*args, **kwargs)

        monkeypatch.setattr("src.review.v4_workspace._stage_write", fail_write)
    elif failure == "verify":
        monkeypatch.setattr(
            "src.review.v4_workspace._verify_staging",
            lambda *args, **kwargs: (_ for _ in ()).throw(ReviewBindingError("injected prepublish failure")),
        )
    else:
        monkeypatch.setattr(
            "src.review.v4_workspace._publish_stage",
            lambda *args, **kwargs: (_ for _ in ()).throw(ReviewBindingError("injected publish failure")),
        )
    with pytest.raises(ReviewBindingError):
        build_review_workspace(inputs)
    assert not inputs.artifact_paths.review_root.exists()
    assert not tuple(inputs.artifact_paths.revision_root.glob(".review-staging-*"))


def test_workspace_refuses_staging_inode_replacement_between_verify_and_publish(tmp_path, monkeypatch):
    inputs = _inputs(tmp_path)
    module = __import__("src.review.v4_workspace", fromlist=["_verify_staging"])
    original = module._verify_staging

    def replace_after_verify(paths, stage, manifest, raw, lease):
        identity = original(paths, stage, manifest, raw, lease)
        replacement = paths.revision_root / (stage + ".replacement")
        os.rename(paths.revision_root / stage, replacement)
        os.mkdir(paths.revision_root / stage)
        return identity

    monkeypatch.setattr(module, "_verify_staging", replace_after_verify)
    with pytest.raises(ReviewBindingError):
        build_review_workspace(inputs)
    assert not inputs.artifact_paths.review_root.exists()


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


def _rehash_model(model_type, payload):
    payload = dict(payload)
    payload.pop("canonical_sha256", None)
    return model_type(**payload, canonical_sha256=canonical_sha256_v4(payload))


def test_workspace_recomputes_q3_after_rehashed_geometry_mutation(tmp_path):
    """Rehashing a changed RenderManifest/Q3/Q4 must not bypass fresh hard gates."""
    inputs = _inputs(tmp_path)
    render_payload = inputs.render_manifest.model_dump(mode="python")
    first_element = dict(render_payload["pages"][0]["elements"][0])
    actual_box = dict(first_element["actual_box"])
    actual_box["x"] = float(actual_box["x"]) + 200.0
    first_element["actual_box"] = actual_box
    first_element_model = _rehash_model(RenderElementEvidenceV4, first_element)
    first_page = dict(render_payload["pages"][0])
    first_page["elements"] = (first_element_model,)
    first_page_model = _rehash_model(RenderPageEvidenceV4, first_page)
    render_payload["pages"] = (first_page_model,) + tuple(render_payload["pages"][1:])
    mutated_render = _rehash_model(RenderManifestV4, render_payload)
    q3_payload = inputs.render_qa.model_dump(mode="python")
    q3_payload["render_manifest_sha256"] = mutated_render.canonical_sha256
    mutated_q3 = _rehash_model(RenderQAResultV4, q3_payload)
    mutated_critique = CarouselAestheticEvaluationV4.create(
        render_manifest_sha256=mutated_render.canonical_sha256,
        render_qa_result_sha256=mutated_q3.canonical_sha256,
        page_brief_set_sha256=inputs.page_brief_set.canonical_sha256,
        semantic_content_model_sha256=inputs.semantic_content_model.canonical_sha256,
        authoring_model_identity="authoring",
        evaluator_model_identity="evaluator",
        pages=inputs.visual_critique.pages,
        set_evaluation=inputs.visual_critique.set_evaluation,
    )
    mutated = inputs.model_copy(update={
        "render_manifest": mutated_render,
        "render_qa": mutated_q3,
        "visual_critique": mutated_critique,
    })
    with pytest.raises(ReviewBindingError):
        build_review_workspace(mutated)


def test_workspace_recomputes_q2_after_rehashed_metric_mutation(tmp_path):
    """Changing a Q2 numeric observation and rehashing every outer result is rejected."""
    inputs = _inputs(tmp_path)
    q2_payload = inputs.design_plan_qa.model_dump(mode="python")
    first_q2 = dict(q2_payload["page_metrics"][0])
    first_metric = dict(first_q2["metrics"][0])
    first_metric["actual"] = float(first_metric["actual"]) + 0.1
    first_metric_model = _rehash_model(DesignMetricEvidenceV4, first_metric)
    first_q2["metrics"] = (first_metric_model,) + tuple(first_q2["metrics"][1:])
    first_q2_model = _rehash_model(DesignMetricsQAResultV4, first_q2)
    q2_payload["page_metrics"] = (first_q2_model,) + tuple(q2_payload["page_metrics"][1:])
    mutated_q2 = _rehash_model(DesignPlanQAResultV4, q2_payload)
    render_payload = inputs.render_manifest.model_dump(mode="python")
    render_payload["design_plan_qa_sha256"] = mutated_q2.canonical_sha256
    mutated_render = _rehash_model(RenderManifestV4, render_payload)
    q3_payload = inputs.render_qa.model_dump(mode="python")
    q3_payload["render_manifest_sha256"] = mutated_render.canonical_sha256
    q3_payload["design_plan_qa_sha256"] = mutated_q2.canonical_sha256
    mutated_q3 = _rehash_model(RenderQAResultV4, q3_payload)
    mutated_critique = CarouselAestheticEvaluationV4.create(
        render_manifest_sha256=mutated_render.canonical_sha256,
        render_qa_result_sha256=mutated_q3.canonical_sha256,
        page_brief_set_sha256=inputs.page_brief_set.canonical_sha256,
        semantic_content_model_sha256=inputs.semantic_content_model.canonical_sha256,
        authoring_model_identity="authoring",
        evaluator_model_identity="evaluator",
        pages=inputs.visual_critique.pages,
        set_evaluation=inputs.visual_critique.set_evaluation,
    )
    mutated = inputs.model_copy(update={
        "design_plan_qa": mutated_q2,
        "render_manifest": mutated_render,
        "render_qa": mutated_q3,
        "visual_critique": mutated_critique,
    })
    with pytest.raises(ReviewBindingError):
        build_review_workspace(mutated)
