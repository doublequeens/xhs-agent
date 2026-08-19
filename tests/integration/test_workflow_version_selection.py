from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest

import main as main_module
from src.editorial_carousel.workflow_selection import (
    WorkflowContext,
    build_graph_for_run,
    select_workflow_context,
)
from src.run_registry import RunRegistry, RunRegistryError


class OrderedGraph:
    def __init__(self, version: str, calls: list[str]) -> None:
        self.version = version
        self._calls = calls

    def get_state(self, _config):
        self._calls.append(f"get-state-{self.version}")
        return SimpleNamespace(values={}, next=())


@pytest.fixture
def registry(tmp_path):
    instance = RunRegistry(tmp_path / "agent_runs.sqlite")
    yield instance
    instance.close()


def test_resume_selects_graph_before_get_state(registry):
    registry.create_run("v4-thread", workflow_version="llm_scene_v4")
    calls: list[str] = []
    factories = {
        "llm_scene_v3": lambda: calls.append("build-v3") or OrderedGraph("v3", calls),
        "llm_scene_v4": lambda: calls.append("build-v4") or OrderedGraph("v4", calls),
    }

    graph = build_graph_for_run(registry.get_by_thread_id("v4-thread"), factories)
    graph.get_state({"configurable": {"thread_id": "v4-thread"}})

    assert calls == ["build-v4", "get-state-v4"]


def test_existing_run_identity_mismatch_is_rejected_before_graph_access(registry):
    registry.create_run("v4-thread", workflow_version="llm_scene_v4", run_mode="shadow")
    calls: list[str] = []

    with pytest.raises(RunRegistryError, match="workflow_version"):
        select_workflow_context(
            registry,
            "v4-thread",
            requested_version="llm_scene_v3",
            run_mode="shadow",
        )

    assert calls == []
    assert registry.get_by_thread_id("v4-thread").workflow_version == "llm_scene_v4"


def test_existing_run_mode_mismatch_is_rejected_before_graph_access(registry):
    registry.create_run("v4-thread", workflow_version="llm_scene_v4", run_mode="shadow")

    with pytest.raises(RunRegistryError, match="run_mode"):
        select_workflow_context(
            registry,
            "v4-thread",
            requested_version="llm_scene_v4",
            run_mode="production",
        )


def test_missing_thread_defaults_to_v3_production_without_mutating_registry(registry):
    context = select_workflow_context(registry, "old-checkpoint", None, None)

    assert context == WorkflowContext("llm_scene_v3", "production")
    assert registry.get_by_thread_id("old-checkpoint") is None


def test_main_import_does_not_require_v4_graph_module(monkeypatch):
    monkeypatch.delitem(sys.modules, "src.graph_v4", raising=False)

    loaded_main = importlib.import_module("main")

    assert "src.graph_v4" not in sys.modules
    assert loaded_main is sys.modules["main"]


def test_v4_graph_import_fails_only_at_the_lazy_factory_boundary(monkeypatch):
    monkeypatch.delitem(sys.modules, "src.graph_v4", raising=False)

    with pytest.raises(ModuleNotFoundError, match="src.graph_v4"):
        main_module._create_v4_graph()

    assert "src.graph_v4" not in sys.modules
