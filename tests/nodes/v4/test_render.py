"""Task 13 RED/GREEN tests for the v4 render node."""

from __future__ import annotations

from types import SimpleNamespace
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
    assert route_after_render_qa(result) == "visual_critic"


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
    assert route_after_render_qa(result) == "design_reviser"
