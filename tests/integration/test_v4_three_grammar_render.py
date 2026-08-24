"""Real local-Chromium v4 vertical slice for the first three grammars."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.nodes.v4.design_qa import aggregate_design_qa
from src.nodes.v4.layout import aggregate_layout_plan
from src.rendering.scene.v4_adapter import render_v4_revision
from src.schemas.assets import AssetManifest
from src.schemas.content_lock import ContentLock
from src.schemas.v4.content import canonical_sha256_v4
from src.schemas.v4.direction import (
    AuthoringQAResultV4,
    CarouselNarrativeV4,
    NarrativeBeatV4,
    PageBriefSetV4,
    PageBriefV4,
    VisualDirectionPlanV4,
)
from src.visual_design.v4.render_qa import evaluate_v4_render
from src.visual_design.v4.tokens import get_family_tokens
from src.visual_runtime.artifact_identity import (
    ArtifactIdentity,
    ensure_artifact_paths,
    resolve_artifact_paths,
)


def _box_diagnostics(box):
    if box is None:
        return None
    return {
        "x": float(box.x),
        "y": float(box.y),
        "width": float(box.width),
        "height": float(box.height),
    }


def _line_extrema(line_boxes, *, actual_box=None, tolerance=0.0):
    if not line_boxes:
        return None
    if actual_box is not None:
        right_edge = float(actual_box.x) + float(actual_box.width)
        bottom_edge = float(actual_box.y) + float(actual_box.height)
        line_boxes = tuple(
            box
            for box in line_boxes
            if (
                float(box.x) < float(actual_box.x) - tolerance
                or float(box.y) < float(actual_box.y) - tolerance
                or float(box.x) + float(box.width) > right_edge + tolerance
                or float(box.y) + float(box.height) > bottom_edge + tolerance
            )
        )
        if not line_boxes:
            return None
    right = [float(box.x) + float(box.width) for box in line_boxes]
    bottom = [float(box.y) + float(box.height) for box in line_boxes]
    return {
        "count": len(line_boxes),
        "min_x": min(float(box.x) for box in line_boxes),
        "min_y": min(float(box.y) for box in line_boxes),
        "max_right": max(right),
        "max_bottom": max(bottom),
    }


def _format_box(box):
    if box is None:
        return "none"
    return "(" + ",".join(f"{float(value):.2f}" for value in (box.x, box.y, box.width, box.height)) + ")"


def _format_line_diagnostic(element, *, tolerance):
    actual = element.actual_box
    extrema = _line_extrema(
        element.line_boxes,
        actual_box=actual,
        tolerance=tolerance,
    )
    if extrema is None:
        line = "none"
    else:
        right_edge = float(actual.x) + float(actual.width)
        bottom_edge = float(actual.y) + float(actual.height)
        line = (
            f"count={extrema['count']}"
            f" min=({extrema['min_x']:.2f},{extrema['min_y']:.2f})"
            f" max=({extrema['max_right']:.2f},{extrema['max_bottom']:.2f})"
            f" delta=({extrema['min_x'] - float(actual.x):.2f},"
            f"{extrema['min_y'] - float(actual.y):.2f},"
            f"{extrema['max_right'] - right_edge:.2f},"
            f"{extrema['max_bottom'] - bottom_edge:.2f})"
        )
    return line


def _q3_issue_diagnostics(result, render_manifest):
    """Return one non-abbreviable numeric line per failing element."""

    observed = {
        (page.page_id, element.element_id): element
        for page in render_manifest.pages
        for element in page.elements
    }
    diagnostics = []
    for issue in result.issues:
        tolerance = float(issue.tolerance_px or 0.0)
        element = observed.get((issue.page_id, issue.element_id))
        if element is None:
            diagnostics.append(
                f"code={issue.code} page={issue.page_id} element={issue.element_id}"
                f" actual=none tolerance={tolerance:.2f}"
            )
            continue
        diagnostics.append(
            f"code={issue.code} page={issue.page_id} element={issue.element_id}"
            f" overflow={element.overflow} clipped={element.clipped}"
            f" scroll=({float(element.scroll_width):.2f},{float(element.scroll_height):.2f})"
            f" client=({float(element.client_width):.2f},{float(element.client_height):.2f})"
            f" actual={_format_box(element.actual_box)}"
            f" expected={_format_box(element.expected_box)}"
            f" line={_format_line_diagnostic(element, tolerance=tolerance)}"
            f" tolerance={tolerance:.2f}"
        )
    return "\n".join(diagnostics)


def _probe_failure_summary(raw, element, *, fragments, assets):
    """Summarize the legacy base-probe seam without exposing copy or paths."""

    kind = getattr(element, "kind", None)
    required = {
        "x",
        "y",
        "width",
        "height",
        "scroll_width",
        "scroll_height",
        "client_width",
        "client_height",
        "line_boxes",
    }
    if kind == "text":
        required.update(
            {
                "font_family",
                "font_size",
                "line_height",
            }
        )
    elif kind == "image":
        required.update(
            {
                "natural_width",
                "natural_height",
            }
        )
    missing = tuple(sorted(key for key in required if raw.get(key) is None))
    reasons = []
    if kind == "text":
        if not isinstance(raw.get("font_family"), str) or not raw["font_family"].strip():
            reasons.append("missing_computed_font_family")
        if getattr(element, "content_ref", None) not in fragments:
            reasons.append("missing_fragment_binding")
    elif kind == "image" and getattr(element, "asset_ref", None) not in assets:
        reasons.append("missing_asset_binding")
    return {
        "element_id": getattr(element, "element_id", None),
        "kind": kind,
        "missing_fields": missing,
        "reasons": tuple(reasons),
        "raw_key_count": len(raw),
    }


def _comparison_probe_diagnostics(*, raw_probes, page, fragments, assets):
    """Summarize raw/base-probe invariants without exposing copy or paths."""

    raw_by_id = {
        raw.get("element_id"): raw
        for raw in raw_probes
        if isinstance(raw, dict) and raw.get("element_id")
    }
    planned = {item.element_id: item for item in page.elements}
    summaries = tuple(
        _probe_failure_summary(
            raw_by_id[element_id],
            planned[element_id],
            fragments=fragments,
            assets=assets,
        )
        for element_id in sorted(raw_by_id)
        if element_id in planned
    )
    return {
        "missing_planned_element_ids": tuple(sorted(set(planned) - set(raw_by_id))),
        "unknown_raw_element_ids": tuple(sorted(set(raw_by_id) - set(planned))),
        "raw_probe_summaries": summaries,
    }


def test_comparison_probe_diagnostic_identifies_missing_font_family():
    element = SimpleNamespace(
        element_id="v4-text-comparison-fragment-1-1-0",
        kind="text",
        content_ref="fragment-1",
        asset_ref=None,
    )
    summary = _probe_failure_summary(
        {
            "element_id": element.element_id,
            "font_family": None,
            "x": 0.0,
            "y": 0.0,
            "width": 1.0,
            "height": 1.0,
            "scroll_width": 1.0,
            "scroll_height": 1.0,
            "client_width": 1.0,
            "client_height": 1.0,
            "line_boxes": (),
        },
        element,
        fragments={"fragment-1": object()},
        assets={},
    )
    assert summary["reasons"] == ("missing_computed_font_family",)


def test_q3_issue_diagnostics_include_numeric_overflow_evidence():
    element = SimpleNamespace(
        element_id="text-1",
        overflow=True,
        clipped=False,
        scroll_width=400.25,
        scroll_height=120.0,
        client_width=398.0,
        client_height=120.0,
        actual_box=SimpleNamespace(x=10.0, y=20.0, width=398.0, height=120.0),
        expected_box=SimpleNamespace(x=10.0, y=20.0, width=398.0, height=120.0),
        line_boxes=(
            SimpleNamespace(x=10.0, y=20.0, width=400.25, height=24.0),
        ),
    )
    manifest = SimpleNamespace(
        pages=(SimpleNamespace(page_id="page-1", elements=(element,)),)
    )
    issue = SimpleNamespace(
        code="RENDER_OVERFLOW",
        page_id="page-1",
        element_id="text-1",
        actual=None,
        expected=None,
        tolerance_px=2.0,
    )
    diagnostics = _q3_issue_diagnostics(
        SimpleNamespace(issues=(issue,)), manifest
    )
    assert diagnostics == (
        "code=RENDER_OVERFLOW page=page-1 element=text-1"
        " overflow=True clipped=False scroll=(400.25,120.00)"
        " client=(398.00,120.00) actual=(10.00,20.00,398.00,120.00)"
        " expected=(10.00,20.00,398.00,120.00)"
        " line=count=1 min=(10.00,20.00) max=(410.25,44.00)"
        " delta=(0.00,0.00,2.25,-96.00) tolerance=2.00"
    )


def test_comparison_probe_diagnostic_identifies_missing_planned_element():
    page = SimpleNamespace(
        elements=(
            SimpleNamespace(element_id="text-1", kind="text", content_ref="f-1"),
            SimpleNamespace(element_id="text-2", kind="text", content_ref="f-2"),
        )
    )
    diagnostics = _comparison_probe_diagnostics(
        raw_probes=[
            {
                "element_id": "text-1",
                "font_family": '"HarmonyOS Sans"',
            }
        ],
        page=page,
        fragments={"f-1": object()},
        assets={},
    )
    assert diagnostics["missing_planned_element_ids"] == ("text-2",)


def _rebuild_upstream(grammar_id: str):
    from tests.nodes.v4.test_layout import _direction_upstream
    from src.nodes.v4.composition import build_layout_program
    from src.visual_design.v4.compiler import LayoutCompilerInputsV4, compile_layout

    if grammar_id == "comparison_grid":
        from tests.visual_design.v4.test_compiler import _comparison_inputs_for_test

        _program, inputs = _comparison_inputs_for_test()
        source_atom_set = inputs.content_atom_set
        source_semantic = inputs.semantic_content_model
        base_direction = inputs.visual_direction_plan
        base_page_set = base_direction.page_brief_set
        base_narrative = base_direction.narrative
        from src.schemas.v4.content import ContentAtomSetV4, ContentAtomV4
        from src.schemas.v4.semantic import SemanticContentModelV4, SemanticFragmentV4

        atoms_list = []
        fragments_list = []
        refs_by_page = []
        for sequence in range(1, 6):
            page_refs = []
            for index, (source_atom, source_fragment) in enumerate(
                zip(source_atom_set.atoms, source_semantic.fragments),
                start=1,
            ):
                atom_payload = source_atom.model_dump(mode="python")
                atom_payload["atom_id"] = f"comparison-atom-{sequence}-{index}"
                atom_payload["source_unit_id"] = f"comparison-unit-{sequence}-{index}"
                atom_payload.pop("sha256", None)
                atom = ContentAtomV4(
                    **atom_payload,
                    sha256=canonical_sha256_v4(atom_payload),
                )
                fragment_payload = source_fragment.model_dump(mode="python")
                fragment_payload["fragment_id"] = f"comparison-fragment-{sequence}-{index}"
                fragment_payload["source_atom_id"] = atom.atom_id
                fragment_payload["sequence_index"] = len(fragments_list)
                fragment = SemanticFragmentV4(**fragment_payload)
                atoms_list.append(atom)
                fragments_list.append(fragment)
                page_refs.append(fragment.fragment_id)
            refs_by_page.append(tuple(page_refs))
        atom_payload_set = {
            "projection_sha256": source_atom_set.projection_sha256,
            "atoms": tuple(atoms_list),
        }
        atoms = ContentAtomSetV4(
            **atom_payload_set,
            canonical_sha256=canonical_sha256_v4(atom_payload_set),
        )
        semantic_payload = {
            "content_atom_set_sha256": atoms.canonical_sha256,
            "fragments": tuple(fragments_list),
            "groups": (),
        }
        semantic = SemanticContentModelV4(
            **semantic_payload,
            canonical_sha256=canonical_sha256_v4(semantic_payload),
        )
        task_kind = "comparison"
        narrative_beats = tuple(
            NarrativeBeatV4(
                beat_id=f"beat-{sequence}",
                sequence=sequence,
                task_kind=task_kind,
                fragment_refs=refs_by_page[sequence - 1],
                task="comparison task",
            )
            for sequence in range(1, 6)
        )
        narrative_payload = base_narrative.model_dump(mode="python")
        narrative_payload["beats"] = narrative_beats
        narrative_payload["content_atom_set_sha256"] = atoms.canonical_sha256
        narrative_payload.pop("canonical_sha256", None)
        narrative = CarouselNarrativeV4(
            **narrative_payload,
            canonical_sha256=canonical_sha256_v4(narrative_payload),
        )
        page_models = []
        first = base_page_set.pages[0]
        for sequence in range(1, 6):
            page_payload = first.model_dump(mode="python")
            page_payload.update(
                {
                    "page_id": f"page-{sequence}",
                    "sequence": sequence,
                    "narrative_role": task_kind,
                    "beat_ref": f"beat-{sequence}",
                    "preferred_compositions": (grammar_id,),
                    "fragment_refs": refs_by_page[sequence - 1],
                    "visual_priority": (refs_by_page[sequence - 1][0],),
                }
            )
            page_payload.pop("canonical_sha256", None)
            page_models.append(
                PageBriefV4(
                    **page_payload,
                    canonical_sha256=canonical_sha256_v4(page_payload),
                )
            )
        family = "pink_red"
    else:
        atoms, semantic, base_page_set, base_narrative, base_direction, _ = _direction_upstream()
        task_kind = "context" if grammar_id == "editorial_hero" else "step"
        narrative_beats = []
        for beat in base_narrative.beats:
            payload = beat.model_dump(mode="python")
            payload["task_kind"] = task_kind
            narrative_beats.append(NarrativeBeatV4(**payload))
        narrative_payload = base_narrative.model_dump(mode="python")
        narrative_payload["beats"] = tuple(narrative_beats)
        narrative_payload.pop("canonical_sha256", None)
        narrative = CarouselNarrativeV4(
            **narrative_payload,
            canonical_sha256=canonical_sha256_v4(narrative_payload),
        )
        page_models = []
        for page in base_page_set.pages:
            page_payload = page.model_dump(mode="python")
            page_payload["preferred_compositions"] = (grammar_id,)
            page_payload["narrative_role"] = task_kind
            page_payload.pop("canonical_sha256", None)
            page_models.append(
                PageBriefV4(
                    **page_payload,
                    canonical_sha256=canonical_sha256_v4(page_payload),
                )
            )
        family = "pink_red"

    page_set_payload = {
        "page_count": 5,
        "pages": tuple(page_models),
        "template_family": family,
        "content_atom_set_sha256": atoms.canonical_sha256,
        "semantic_content_model_sha256": semantic.canonical_sha256,
    }
    page_set = PageBriefSetV4(
        **page_set_payload,
        canonical_sha256=canonical_sha256_v4(page_set_payload),
    )
    direction_payload = {
        "semantic_content_model": semantic,
        "narrative": narrative,
        "page_brief_set": page_set,
        "template_family": family,
        "page_count": 5,
        "content_atom_set_sha256": atoms.canonical_sha256,
        "semantic_content_model_sha256": semantic.canonical_sha256,
        "narrative_sha256": narrative.canonical_sha256,
        "page_brief_set_sha256": page_set.canonical_sha256,
    }
    direction = VisualDirectionPlanV4(
        **direction_payload,
        canonical_sha256=canonical_sha256_v4(direction_payload),
    )
    empty_manifest = AssetManifest(items=())
    compiled = tuple(
        compile_layout(
            build_layout_program(
                page,
                grammar_id=grammar_id,
                family=family,
                narrative=narrative,
            ),
            LayoutCompilerInputsV4(
                page_brief=page,
                semantic_content_model=semantic,
                content_atom_set=atoms,
                asset_manifest=empty_manifest,
                candidate_id="candidate-a",
                revision=1,
                run_id="run-a",
                visual_direction_plan=direction,
            ),
        )
        for page in page_set.pages
    )
    plan = aggregate_layout_plan(
        compiled,
        content_atom_set=atoms,
        semantic_content_model=semantic,
        page_brief_set=page_set,
        asset_manifest=empty_manifest,
        family_tokens=get_family_tokens(family),
        revision=1,
        run_id="run-a",
        candidate_id="candidate-a",
        visual_direction_plan=direction,
    )
    return atoms, semantic, page_set, direction, empty_manifest, plan


def _world_for_grammar(grammar_id: str, tmp_path: Path):
    from tests.nodes.v4.test_design_qa import _fixture, _kwargs
    from src.visual_design.v4.semantic_qa import evaluate_semantic_model

    fixture = _fixture()
    atoms, semantic, page_set, direction, asset_manifest, plan = _rebuild_upstream(grammar_id)
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
    q1 = AuthoringQAResultV4(
        **q1_payload,
        canonical_sha256=canonical_sha256_v4(q1_payload),
    )
    fixture.update(
        {
            "atom_set": atoms,
            "semantic_model": semantic,
            "page_set": page_set,
            "direction_plan": direction,
            "manifest": asset_manifest,
            "lock": lock,
            "q0": q0,
            "q1": q1,
            "plan": plan,
        }
    )
    qa = aggregate_design_qa(**_kwargs(fixture))
    identity = ArtifactIdentity(
        qa.carousel_design_plan.run_id,
        qa.carousel_design_plan.candidate_id,
        f"revision-{qa.carousel_design_plan.revision}",
    )
    paths = ensure_artifact_paths(resolve_artifact_paths(tmp_path, identity))
    return fixture, qa, paths


@pytest.mark.parametrize(
    "grammar_id",
    ("editorial_hero", "comparison_grid", "step_flow"),
)
def test_v4_three_grammar_render_is_real_chromium_and_q3_verified(
    grammar_id, tmp_path, monkeypatch
):
    fixture, qa, paths = _world_for_grammar(grammar_id, tmp_path)
    if grammar_id == "comparison_grid":
        # This wrapper exists only in the test process. Production keeps its
        # fixed sanitized V4RenderError; an external run gets a structural
        # summary if the legacy base-probe seam rejects a raw browser record.
        import src.rendering.scene.v4_adapter as adapter
        from src.rendering.scene.probes import ProbeBuildError

        original_build = adapter.build_element_probes

        def diagnostic_build(*, raw_probes, page, fragments, assets, page_background):
            try:
                return original_build(
                    raw_probes=raw_probes,
                    page=page,
                    fragments=fragments,
                    assets=assets,
                    page_background=page_background,
                )
            except ProbeBuildError as exc:
                summary = _comparison_probe_diagnostics(
                    raw_probes=raw_probes,
                    page=page,
                    fragments=fragments,
                    assets=assets,
                )
                raise AssertionError(
                    f"comparison base-probe invariant failed: {summary}"
                ) from exc

        monkeypatch.setattr(adapter, "build_element_probes", diagnostic_build)
    try:
        rendered = render_v4_revision(
            design_plan=qa.carousel_design_plan,
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
    except Exception as exc:
        message = str(exc.__cause__ or exc)
        if "MachPortRendezvousServer" in message:
            pytest.skip(f"Chromium sandbox launch blocked: {message}")
        raise

    result = evaluate_v4_render(
        render_manifest=rendered.manifest,
        design_plan=qa.carousel_design_plan,
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
    assert result.passed is True, _q3_issue_diagnostics(result, rendered.manifest)
    assert tuple(page.page_id for page in rendered.manifest.pages) == tuple(
        page.page_id for page in qa.carousel_design_plan.pages
    )
    assert all(page.width == 1080 and page.height == 1440 for page in rendered.manifest.pages)
    assert all(page.path.startswith("render/pages/") for page in rendered.manifest.pages)
    assert all(
        element.actual_box.width > 0 and element.actual_box.height > 0
        for page in rendered.manifest.pages
        for element in page.elements
    )
    assert all(
        element.actual_text is not None
        and element.computed_font is not None
        and element.glyph is not None
        for page in rendered.manifest.pages
        for element in page.elements
        if element.kind == "text"
    )
    assert (paths.render_root / "render-manifest.json").is_file()
    assert (paths.render_root / "contact-sheet.png").is_file()
