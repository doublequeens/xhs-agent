import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest
from pydantic import ValidationError

from src.domain import get_topic_metadata
from src.schemas.decision import HashTagInput
from src.schemas.topic import TopicItem


def _creative_seed():
    return {
        "signal_type": "evergreen_context",
        "signal_name": "测试默认信号",
        "why_now": "测试中使用稳定 evergreen 信号。",
        "domain_translation": "测试中保持原 domain/subdomain。",
        "evergreen_pain": "测试核心痛点。",
        "timely_framing": "测试时机包装。",
    }


def _load_main(monkeypatch):
    models = ModuleType("src.models")
    models.set_default_provider = lambda _provider: None
    prompts = ModuleType("src.prompts")
    prompts.all_prompts = {}
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
    monkeypatch.setitem(sys.modules, "src.prompts", prompts)
    monkeypatch.setitem(sys.modules, "src.graph", graph)
    monkeypatch.setitem(sys.modules, "memory.memory_manager", memory_memory_manager)
    sys.modules.pop("main", None)
    return importlib.import_module("main")


def test_topic_item_accepts_domain_metadata():
    topic = TopicItem(
        topic_id="tp_1",
        topic="睡眠改善",
        target_group="上班族",
        core_pain="熬夜失眠",
        hook="3个习惯帮你早睡",
        content_form="listicle",
        risk_note="avoid medical claims",
        domain="wellness",
        subdomain="sleep",
        content_intent="how_to",
        risk_level="medium",
        risk_flags=["medical-adjacent", "sleep-disorder"],
        creative_seed=_creative_seed(),
    )

    assert topic.domain == "wellness"
    assert topic.subdomain == "sleep"
    assert topic.content_intent == "how_to"
    assert topic.risk_level == "medium"
    assert topic.risk_flags == ["medical-adjacent", "sleep-disorder"]


def test_get_topic_metadata_returns_expected_metadata_and_copies_risk_flags():
    topic = TopicItem(
        topic_id="tp_1",
        topic="睡眠改善",
        target_group="上班族",
        core_pain="熬夜失眠",
        hook="3个习惯帮你早睡",
        content_form="listicle",
        risk_note="avoid medical claims",
        domain="wellness",
        subdomain="sleep",
        content_intent="how_to",
        risk_level="medium",
        risk_flags=["medical-adjacent", "sleep-disorder"],
        creative_seed=_creative_seed(),
    )

    metadata = get_topic_metadata([topic], "tp_1")

    assert metadata == {
        "domain": "wellness",
        "subdomain": "sleep",
        "content_intent": "how_to",
        "risk_level": "medium",
        "risk_flags": ["medical-adjacent", "sleep-disorder"],
    }
    assert metadata["risk_flags"] is not topic.risk_flags
    metadata["risk_flags"].append("mutated")
    assert topic.risk_flags == ["medical-adjacent", "sleep-disorder"]


def test_get_topic_metadata_rejects_unknown_topic_id():
    topic = TopicItem(
        topic_id="tp_1",
        topic="睡眠改善",
        target_group="上班族",
        core_pain="熬夜失眠",
        hook="3个习惯帮你早睡",
        content_form="listicle",
        risk_note="avoid medical claims",
        domain="wellness",
        subdomain="sleep",
        content_intent="how_to",
        risk_level="medium",
        risk_flags=["medical-adjacent"],
        creative_seed=_creative_seed(),
    )

    with pytest.raises(ValueError, match="Unknown topic_id: tp_missing"):
        get_topic_metadata([topic], "tp_missing")


def test_get_topic_metadata_rejects_duplicate_topic_id():
    topics = [
        TopicItem(
            topic_id="tp_1",
            topic="睡眠改善",
            target_group="上班族",
            core_pain="熬夜失眠",
            hook="3个习惯帮你早睡",
            content_form="listicle",
            risk_note="avoid medical claims",
            domain="wellness",
            subdomain="sleep",
            content_intent="how_to",
            risk_level="medium",
            risk_flags=["medical-adjacent"],
            creative_seed=_creative_seed(),
        ),
        TopicItem(
            topic_id="tp_1",
            topic="睡眠习惯",
            target_group="上班族",
            core_pain="睡不好",
            hook="1分钟自测睡眠问题",
            content_form="checklist",
            risk_note="avoid diagnosis claims",
            domain="wellness",
            subdomain="sleep",
            content_intent="checklist",
            risk_level="medium",
            risk_flags=["medical-adjacent"],
            creative_seed=_creative_seed(),
        ),
    ]

    with pytest.raises(ValueError, match="Duplicate topic_id: tp_1"):
        get_topic_metadata(topics, "tp_1")


def test_hashtag_input_requires_complete_domain_metadata():
    hashtag_input = HashTagInput(
        final_title="睡眠改善指南",
        final_md="content",
        topic_id="tp_1",
        angle_id="angle_1",
        topic="睡眠改善",
        angle="睡眠策略",
        domain="wellness",
        subdomain="sleep",
        content_intent="how_to",
        risk_level="medium",
        risk_flags=["medical-adjacent"],
        target_group="上班族",
        core_pain="熬夜失眠",
        best_cover_copy="今晚就能试",
    )

    assert hashtag_input.domain == "wellness"
    assert hashtag_input.risk_flags == ["medical-adjacent"]


def test_hashtag_input_rejects_missing_domain_metadata():
    with pytest.raises(ValidationError) as exc_info:
        HashTagInput(
            final_title="睡眠改善指南",
            final_md="content",
            topic_id="tp_1",
            angle_id="angle_1",
            topic="睡眠改善",
            angle="睡眠策略",
            subdomain="sleep",
            content_intent="how_to",
            risk_level="medium",
            risk_flags=["medical-adjacent"],
            target_group="上班族",
            core_pain="熬夜失眠",
            best_cover_copy="今晚就能试",
    )

    assert [error["loc"] for error in exc_info.value.errors()] == [("domain",)]


def test_main_initial_state_includes_metadata_briefs(monkeypatch):
    main = _load_main(monkeypatch)
    captured = {}

    def fake_parse_args():
        return SimpleNamespace(
            domain=None,
            thread_id=None,
            focus_keyword=None,
            topic_num=10,
            provider=None,
        )

    def fake_load_run_state(_graph, _config, initial_state):
        captured["initial_state"] = initial_state
        return SimpleNamespace(values={}, next=()), initial_state

    monkeypatch.setattr(main.argparse.ArgumentParser, "parse_args", lambda self: fake_parse_args())
    monkeypatch.setattr(main, "load_run_state", fake_load_run_state)
    monkeypatch.setattr(main, "stream_graph_until_stop", lambda *args, **kwargs: None)

    main.main()

    assert captured["initial_state"]["evidence_briefs"] == {}
    assert captured["initial_state"]["final_policy_issues"] == []
