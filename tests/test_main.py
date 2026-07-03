import importlib
import sys
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from typing import get_args

import pytest

from src.domain import DomainName


def _load_main(monkeypatch):
    models = ModuleType("src.models")
    models.set_default_provider = lambda _provider: None
    graph = ModuleType("src.graph")
    graph.create_graph = lambda: object()
    memory_memory_manager = ModuleType("memory.memory_manager")

    class FakeMemoryManager:
        def __init__(self, *args, **kwargs):
            pass

        def init_db(self, *args, **kwargs):
            pass

    memory_memory_manager.XHSMemoryManager = FakeMemoryManager

    monkeypatch.setitem(sys.modules, "src.models", models)
    monkeypatch.setitem(sys.modules, "src.graph", graph)
    monkeypatch.setitem(sys.modules, "memory.memory_manager", memory_memory_manager)
    sys.modules.pop("main", None)
    return importlib.import_module("main")


def test_build_thread_id_preserves_explicit_resume_id(monkeypatch):
    main = _load_main(monkeypatch)

    assert main.build_thread_id("existing-conversation") == "existing-conversation"


def test_build_thread_id_generates_fresh_ids(monkeypatch):
    main = _load_main(monkeypatch)
    now = datetime(2026, 7, 3, 10, 30, tzinfo=timezone.utc)

    first = main.build_thread_id(None, now=now)
    second = main.build_thread_id(None, now=now)

    assert first.startswith("xhs_conversation_20260703T103000_")
    assert second.startswith("xhs_conversation_20260703T103000_")
    assert first != second


def test_supported_domains_come_from_domain_name(monkeypatch):
    main = _load_main(monkeypatch)

    assert main.SUPPORTED_DOMAINS == get_args(DomainName)


def test_fresh_thread_keeps_new_routing_initial_state(monkeypatch):
    main = _load_main(monkeypatch)
    old_thread_id = "xhs_conversation_database_20260517_01"
    old_state = SimpleNamespace(values={"domain": "beauty"}, next=("trend_scout",))
    empty_state = SimpleNamespace(values={}, next=())

    class FakeGraph:
        def get_state(self, config):
            if config["configurable"]["thread_id"] == old_thread_id:
                return old_state
            return empty_state

    initial_state = {
        "domain": "wellness",
        "focus_keyword": "改善睡眠",
        "domain_context": None,
        "content_policy": None,
    }
    config = main.build_run_config(None)

    current_state, run_input = main.load_run_state(
        FakeGraph(), config, initial_state
    )

    assert config["configurable"]["thread_id"] != old_thread_id
    assert current_state is empty_state
    assert run_input is initial_state


def test_explicit_thread_id_resumes_existing_checkpoint(monkeypatch):
    main = _load_main(monkeypatch)
    existing_state = SimpleNamespace(values={"domain": "beauty"}, next=("trend_scout",))

    class FakeGraph:
        def get_state(self, config):
            assert config["configurable"]["thread_id"] == "existing-conversation"
            return existing_state

    current_state, run_input = main.load_run_state(
        FakeGraph(),
        main.build_run_config("existing-conversation"),
        {"domain": "wellness"},
    )

    assert current_state is existing_state
    assert run_input is None


def test_export_publish_package_uses_wellness_composed_prompt(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    monkeypatch.chdir(tmp_path)

    publish_package = {
        "title": "睡眠改善指南",
        "content": "body",
        "cover_copy": "cover",
        "storyboards": [{"frame_id": "frame_001"}],
        "domain": "wellness",
        "profile_version": "wellness-v1",
    }

    main.export_publish_package(publish_package)

    prompt_files = list(tmp_path.glob("outputs/publish/*/Storyboard_images_generator_prompt.txt"))
    assert len(prompt_files) == 1
    prompt_text = prompt_files[0].read_text(encoding="utf-8")
    assert "睡眠、压力、作息与恢复" in prompt_text
    assert '"domain": "wellness"' in prompt_text
    assert "夏季底妆搓泥脱妆" not in prompt_text


def test_export_publish_package_uses_healthy_lifestyle_composed_prompt(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    monkeypatch.chdir(tmp_path)

    publish_package = {
        "title": "久坐活动指南",
        "content": "body",
        "cover_copy": "cover",
        "storyboards": [{"frame_id": "frame_001"}],
        "domain": "healthy_lifestyle",
        "profile_version": "healthy-lifestyle-v1",
    }

    main.export_publish_package(publish_package)

    prompt_files = list(tmp_path.glob("outputs/publish/*/Storyboard_images_generator_prompt.txt"))
    assert len(prompt_files) == 1
    prompt_text = prompt_files[0].read_text(encoding="utf-8")
    assert "基础饮食、运动、饮水、久坐与日常健康习惯" in prompt_text
    assert '"domain": "healthy_lifestyle"' in prompt_text
    assert "夏季底妆搓泥脱妆" not in prompt_text


def test_export_publish_package_requires_valid_domain_metadata(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    monkeypatch.chdir(tmp_path)

    publish_package = {
        "title": "睡眠改善指南",
        "content": "body",
        "cover_copy": "cover",
        "storyboards": [],
        "domain": "wellness",
    }

    with pytest.raises(ValueError, match="publish_package requires valid domain and profile_version metadata"):
        main.export_publish_package(publish_package)
