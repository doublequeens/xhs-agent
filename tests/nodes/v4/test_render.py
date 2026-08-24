"""Task 13 RED/GREEN tests for the v4 render node."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.nodes.v4.render import (
    render_node,
    render_qa_node,
    route_after_render_qa,
    v4_render_node,
)


def test_v4_render_node_public_names_are_available():
    assert callable(render_node)
    assert v4_render_node is render_node


def test_v4_render_node_routes_every_published_manifest_to_render_qa(monkeypatch):
    import src.nodes.v4.render as module

    calls = []
    manifest = object()
    paths = object()

    def fake_render(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(manifest=manifest, artifact_paths=paths)

    monkeypatch.setattr(module, "render_v4_revision", fake_render)
    state = {
        "carousel_design_plan": object(),
        "design_plan_qa_result": object(),
        "content_atom_set": object(),
        "content_lock": object(),
        "semantic_content_model": object(),
        "page_brief_set": object(),
        "visual_direction_plan": object(),
        "asset_manifest": object(),
        "family_tokens": object(),
        "artifact_paths": paths,
    }

    result = render_node(state)

    assert calls
    assert result["route"] == "render_qa"
    assert result["visual_route"] == "render_qa"
    assert result["render_manifest_v4"] is manifest
    assert "render_qa_result_v4" not in result


def test_v4_q3_route_rejects_duck_typed_spoofed_result():
    with pytest.raises(ValueError):
        route_after_render_qa(
            {"render_qa_result_v4": SimpleNamespace(passed=True)}
        )


def test_v4_q3_node_recomputes_and_routes_passed_result_to_critic(monkeypatch):
    import src.nodes.v4.render as module

    seen = []

    class Result:
        passed = True

    def fake_evaluate(**kwargs):
        seen.append(kwargs)
        return Result()

    monkeypatch.setattr(module, "evaluate_v4_render", fake_evaluate)
    state = {
        "render_manifest_v4": object(),
        "carousel_design_plan": object(),
        "design_plan_qa_result": object(),
        "content_atom_set": object(),
        "content_lock": object(),
        "semantic_content_model": object(),
        "page_brief_set": object(),
        "visual_direction_plan": object(),
        "asset_manifest": object(),
        "family_tokens": object(),
        "artifact_paths": object(),
    }

    result = render_qa_node(state)

    assert seen
    assert result["render_qa_result_v4"].passed is True
    assert result["route"] == "visual_critic"


def test_v4_q3_node_routes_failed_result_only_to_reviser(monkeypatch):
    import src.nodes.v4.render as module

    class Result:
        passed = False

    monkeypatch.setattr(module, "evaluate_v4_render", lambda **kwargs: Result())
    state = {
        "render_manifest_v4": object(),
        "carousel_design_plan": object(),
        "design_plan_qa_result": object(),
        "content_atom_set": object(),
        "content_lock": object(),
        "semantic_content_model": object(),
        "page_brief_set": object(),
        "visual_direction_plan": object(),
        "asset_manifest": object(),
        "family_tokens": object(),
        "artifact_paths": object(),
    }

    result = render_qa_node(state)
    assert result["route"] == "design_reviser"


def _real_q3_route_state(tmp_path: Path):
    from tests.visual_design.v4.test_v4_render_qa import _world
    from src.visual_design.v4.render_qa import evaluate_v4_render

    values = _world(tmp_path)
    result = evaluate_v4_render(**values)
    return {
        **values,
        "render_qa_result_v4": result,
        "render_qa_result": result,
    }


def test_v4_q3_route_revalidates_exact_source_bindings(tmp_path):
    state = _real_q3_route_state(tmp_path)

    assert route_after_render_qa(state) == "visual_critic"


def test_v4_q3_route_preserves_failed_result_to_reviser(tmp_path):
    from tests.visual_design.v4.test_v4_render_qa import (
        _world,
        _rebuild_element,
        _rebuild_manifest,
        _rebuild_page,
    )
    from src.schemas.v4.content import canonical_json_v4
    from src.visual_design.v4.render_qa import evaluate_v4_render

    values = _world(tmp_path)
    manifest = values["render_manifest"]
    page = manifest.pages[0]
    element = page.elements[0]
    drifted = _rebuild_element(
        element,
        actual_box={
            **element.actual_box.model_dump(mode="python"),
            "x": element.actual_box.x + 2.1,
        },
    )
    page = _rebuild_page(page, elements=(drifted, *page.elements[1:]))
    manifest = _rebuild_manifest(manifest, pages=(page, *manifest.pages[1:]))
    values["artifact_paths"].revision_root.joinpath(
        "render/render-manifest.json"
    ).write_text(canonical_json_v4(manifest), encoding="utf-8")
    values["render_manifest"] = manifest
    result = evaluate_v4_render(**values)
    assert result.passed is False

    state = {**values, "render_qa_result_v4": result}
    assert route_after_render_qa(state) == "design_reviser"


@pytest.mark.parametrize(
    "tamper",
    [
        lambda result: result.model_copy(update={"passed": False}),
        lambda result: result.model_copy(
            update={"render_manifest_sha256": "0" * 64}
        ),
    ],
)
def test_v4_q3_route_rejects_tampered_result_integrity(tmp_path, tamper):
    state = _real_q3_route_state(tmp_path)
    state["render_qa_result_v4"] = tamper(state["render_qa_result_v4"])

    with pytest.raises(ValueError):
        route_after_render_qa(state)


def test_v4_q3_route_rejects_stale_source_binding(tmp_path):
    state = _real_q3_route_state(tmp_path)
    atoms = state["content_atom_set"]
    state["content_atom_set"] = atoms.model_copy(
        update={"canonical_sha256": "0" * 64}
    )

    with pytest.raises(ValueError):
        route_after_render_qa(state)
