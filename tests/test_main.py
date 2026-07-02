import importlib
import sys
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from typing import get_args

from src.domain import DomainName


def _load_main(monkeypatch):
    models = ModuleType("src.models")
    models.set_default_provider = lambda _provider: None
    prompts = ModuleType("src.prompts")
    prompts.all_prompts = {}
    monkeypatch.setitem(sys.modules, "src.models", models)
    monkeypatch.setitem(sys.modules, "src.prompts", prompts)
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
