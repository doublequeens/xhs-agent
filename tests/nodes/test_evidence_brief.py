import pytest

from src.nodes import evidence_brief_node
from src.schemas.topic import TopicItem
from src.schemas.virality_score import ScoreBreakdown, ScoreResult


def _topic(*, topic_id: str, topic: str, content_intent: str, risk_level: str) -> TopicItem:
    return TopicItem(
        topic_id=topic_id,
        topic=topic,
        target_group="上班族",
        core_pain="状态不好",
        hook="先从习惯开始",
        content_form="listicle",
        risk_note="avoid diagnosis",
        domain="wellness",
        subdomain="sleep",
        content_intent=content_intent,
        risk_level=risk_level,
        risk_flags=["medical-adjacent"],
    )


def _score(*, topic_id: str, topic: str, angle_id: str) -> ScoreResult:
    return ScoreResult(
        total_score=88,
        breakdown=ScoreBreakdown(
            click_potential=8,
            save_value=8,
            comment_potential=7,
            execution_barrier=3,
            compliance_safety=9,
            memory_fit_score=0.8,
        ),
        strengths=["clear"],
        weaknesses=["none"],
        optimization_suggestions=["keep"],
        absorbed_memory_suggestions=[],
        memory_decision="keep",
        novelty_score=0.9,
        max_similarity=0.2,
        topic_id=topic_id,
        topic=topic,
        angle_id=angle_id,
        angle="角度",
        target_group="上班族",
        core_pain="状态不好",
        opening_hook="hook",
        value_promise="value",
        suggested_structure="list",
    )


def test_evidence_brief_node_is_exported_from_nodes_package():
    import src.nodes as nodes
    from src.nodes.node_c_01_evidence_brief import evidence_brief_node as concrete_node

    assert nodes.evidence_brief_node is concrete_node


def test_evidence_brief_node_skips_non_qualifying_topics_without_provider_creation():
    state = {
        "domain_context": {"domain": "wellness", "profile_version": "wellness-v1"},
        "scores": [_score(topic_id="tp_001", topic="睡眠改善", angle_id="ag_001")],
        "trends": [_topic(topic_id="tp_001", topic="睡眠改善", content_intent="how_to", risk_level="low")],
    }

    def fail_provider_factory():
        raise AssertionError("provider should not be created")

    assert evidence_brief_node(state, provider_factory=fail_provider_factory) == {}


def test_evidence_brief_node_retrieves_medium_and_basic_science_topics():
    captured = {"queries": []}

    class FakeProvider:
        def search(self, query, domains):
            captured["queries"].append((query, tuple(domains)))
            return [
                {
                    "title": "WHO sleep guidance",
                    "url": "https://www.who.int/sleep",
                    "content": "保持规律作息有助于建立更稳定的睡眠习惯。",
                },
                {
                    "title": "attacker",
                    "url": "https://who.int.evil.com/fake",
                    "content": "bad",
                },
            ]

    state = {
        "domain_context": {"domain": "wellness", "profile_version": "wellness-v1"},
        "scores": [
            _score(topic_id="tp_001", topic="睡眠改善", angle_id="ag_001"),
            _score(topic_id="tp_002", topic="褪黑素基础知识", angle_id="ag_002"),
        ],
        "trends": [
            _topic(topic_id="tp_001", topic="睡眠改善", content_intent="how_to", risk_level="medium"),
            _topic(topic_id="tp_002", topic="褪黑素基础知识", content_intent="basic_science", risk_level="low"),
        ],
    }

    result = evidence_brief_node(state, provider_factory=lambda: FakeProvider())

    assert list(result["evidence_briefs"]) == ["tp_001", "tp_002"]
    assert captured["queries"] == [
        ("睡眠改善 基础健康科普", ("who.int", "nih.gov", "cdc.gov", "nhs.uk", "nhc.gov.cn", "chinacdc.cn")),
        ("褪黑素基础知识 基础健康科普", ("who.int", "nih.gov", "cdc.gov", "nhs.uk", "nhc.gov.cn", "chinacdc.cn")),
    ]
    first_item = result["evidence_briefs"]["tp_001"].items[0]
    second_item = result["evidence_briefs"]["tp_002"].items[0]
    assert first_item.claim == "睡眠改善"
    assert first_item.summary == "保持规律作息有助于建立更稳定的睡眠习惯。"
    assert first_item.source_title == "WHO sleep guidance"
    assert first_item.source_type == "public_health"
    assert second_item.claim == "褪黑素基础知识"
    assert result["evidence_briefs"]["tp_002"].unsupported_claims == []


def test_evidence_brief_node_deduplicates_topic_ids_before_search():
    calls = []

    class FakeProvider:
        def search(self, query, domains):
            calls.append((query, tuple(domains)))
            return [
                {
                    "title": "WHO sleep guidance",
                    "url": "https://www.who.int/sleep",
                    "content": "保持规律作息有助于建立更稳定的睡眠习惯。",
                }
            ]

    state = {
        "domain_context": {"domain": "wellness", "profile_version": "wellness-v1"},
        "scores": [
            _score(topic_id="tp_001", topic="睡眠改善", angle_id="ag_001"),
            _score(topic_id="tp_001", topic="睡眠改善", angle_id="ag_002"),
        ],
        "trends": [_topic(topic_id="tp_001", topic="睡眠改善", content_intent="how_to", risk_level="medium")],
    }

    result = evidence_brief_node(state, provider_factory=lambda: FakeProvider())

    assert list(result["evidence_briefs"]) == ["tp_001"]
    assert calls == [
        ("睡眠改善 基础健康科普", ("who.int", "nih.gov", "cdc.gov", "nhs.uk", "nhc.gov.cn", "chinacdc.cn"))
    ]


def test_evidence_brief_node_rejects_duplicate_trend_topic_ids_before_provider_creation():
    state = {
        "domain_context": {"domain": "wellness", "profile_version": "wellness-v1"},
        "scores": [_score(topic_id="tp_001", topic="睡眠改善", angle_id="ag_001")],
        "trends": [
            _topic(topic_id="tp_001", topic="睡眠改善", content_intent="how_to", risk_level="medium"),
            _topic(topic_id="tp_001", topic="另一条重复趋势", content_intent="basic_science", risk_level="low"),
        ],
    }
    provider_factory_calls = 0

    def provider_factory():
        nonlocal provider_factory_calls
        provider_factory_calls += 1
        raise AssertionError("provider should not be created")

    with pytest.raises(ValueError, match="^Duplicate topic_id: tp_001$"):
        evidence_brief_node(state, provider_factory=provider_factory)

    assert provider_factory_calls == 0


def test_evidence_brief_node_rejects_scores_referencing_missing_trend_before_provider_creation():
    state = {
        "domain_context": {"domain": "wellness", "profile_version": "wellness-v1"},
        "scores": [_score(topic_id="tp_missing", topic="睡眠改善", angle_id="ag_001")],
        "trends": [_topic(topic_id="tp_001", topic="睡眠改善", content_intent="how_to", risk_level="medium")],
    }
    provider_factory_calls = 0

    def provider_factory():
        nonlocal provider_factory_calls
        provider_factory_calls += 1
        raise AssertionError("provider should not be created")

    with pytest.raises(ValueError, match="^Unknown topic_id: tp_missing$"):
        evidence_brief_node(state, provider_factory=provider_factory)

    assert provider_factory_calls == 0


@pytest.mark.parametrize(
    ("domain_context", "expected_error"),
    [
        (None, r"^evidence_brief_node requires state\.domain_context with domain and profile_version$"),
        ({"domain": "wellness"}, r"^evidence_brief_node requires state\.domain_context with domain and profile_version$"),
        (
            {"domain": "wellness", "profile_version": "beauty-v1"},
            r"^Unsupported profile version: beauty-v1 for domain wellness; expected wellness-v1$",
        ),
    ],
)
def test_evidence_brief_node_rejects_invalid_domain_context_before_provider_creation(
    domain_context,
    expected_error,
):
    state = {
        "domain_context": domain_context,
        "scores": [_score(topic_id="tp_001", topic="睡眠改善", angle_id="ag_001")],
        "trends": [_topic(topic_id="tp_001", topic="睡眠改善", content_intent="how_to", risk_level="medium")],
    }
    provider_factory_calls = 0

    def provider_factory():
        nonlocal provider_factory_calls
        provider_factory_calls += 1
        raise AssertionError("provider should not be created")

    with pytest.raises(ValueError, match=expected_error):
        evidence_brief_node(state, provider_factory=provider_factory)

    assert provider_factory_calls == 0


def test_evidence_brief_node_fails_when_no_allowlisted_results_remain():
    class FakeProvider:
        def search(self, _query, _domains):
            return [
                {
                    "title": "attacker",
                    "url": "https://who.int.evil.com/fake",
                    "content": "bad",
                }
            ]

    state = {
        "domain_context": {"domain": "wellness", "profile_version": "wellness-v1"},
        "scores": [_score(topic_id="tp_001", topic="睡眠改善", angle_id="ag_001")],
        "trends": [_topic(topic_id="tp_001", topic="睡眠改善", content_intent="how_to", risk_level="medium")],
    }

    with pytest.raises(RuntimeError, match="No allowlisted evidence results found for topic_id tp_001"):
        evidence_brief_node(state, provider_factory=lambda: FakeProvider())


def test_evidence_brief_node_propagates_provider_failures():
    class FakeProvider:
        def search(self, _query, _domains):
            raise RuntimeError("provider boom")

    state = {
        "domain_context": {"domain": "wellness", "profile_version": "wellness-v1"},
        "scores": [_score(topic_id="tp_001", topic="睡眠改善", angle_id="ag_001")],
        "trends": [_topic(topic_id="tp_001", topic="睡眠改善", content_intent="how_to", risk_level="medium")],
    }

    with pytest.raises(RuntimeError, match="provider boom"):
        evidence_brief_node(state, provider_factory=lambda: FakeProvider())
