from collections.abc import Callable, Mapping
from typing import Any

from src.domain import get_domain_profile
from src.evidence import (
    EvidenceBrief,
    EvidenceItem,
    TavilyEvidenceProvider,
    classify_source_type,
    is_allowlisted_source_url,
)
from src.schemas import AgentState


def _get_value(payload: Any, key: str) -> Any:
    if isinstance(payload, Mapping):
        return payload.get(key)
    return getattr(payload, key, None)


def _topic_index(trends: list[Any]) -> dict[str, Any]:
    indexed: dict[str, Any] = {}
    for trend in trends:
        topic_id = _get_value(trend, "topic_id")
        if not topic_id:
            continue
        if topic_id in indexed:
            raise ValueError(f"Duplicate topic_id: {topic_id}")
        indexed[topic_id] = trend
    return indexed


def _selected_topic_ids(scores: list[Any]) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()

    for score in scores:
        topic_id = _get_value(score, "topic_id")
        if not topic_id or topic_id in seen:
            continue
        seen.add(topic_id)
        selected.append(topic_id)

    return selected


def _topic_qualifies(topic: Any) -> bool:
    risk_level = _get_value(topic, "risk_level")
    content_intent = _get_value(topic, "content_intent")
    return risk_level == "medium" or content_intent == "basic_science"


def _build_evidence_items(topic_name: str, results: list[Any], allowed_domains: tuple[str, ...]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []

    for result in results:
        title = _get_value(result, "title")
        url = _get_value(result, "url")
        content = _get_value(result, "content")
        if not isinstance(title, str) or not title.strip():
            continue
        if not isinstance(url, str) or not url.strip():
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        if not is_allowlisted_source_url(url, allowed_domains):
            continue

        items.append(
            EvidenceItem(
                claim=topic_name,
                summary=content.strip(),
                source_title=title.strip(),
                source_url=url.strip(),
                source_type=classify_source_type(url),
            )
        )
        if len(items) == 5:
            break

    return items


def evidence_brief_node(
    state: AgentState,
    *,
    provider_factory: Callable[[], TavilyEvidenceProvider] = TavilyEvidenceProvider,
) -> dict[str, dict[str, EvidenceBrief]]:
    trends = state.get("trends", [])
    scores = state.get("scores", [])
    selected_ids = _selected_topic_ids(scores)
    indexed_topics = _topic_index(trends)
    qualifying_topics = []

    for topic_id in selected_ids:
        try:
            topic = indexed_topics[topic_id]
        except KeyError as exc:
            raise ValueError(f"Unknown topic_id: {topic_id}") from exc
        if _topic_qualifies(topic):
            qualifying_topics.append(topic)

    if not qualifying_topics:
        return {}

    domain_context = state.get("domain_context") or {}
    domain = _get_value(domain_context, "domain")
    profile_version = _get_value(domain_context, "profile_version")
    if not domain or not profile_version:
        raise ValueError("evidence_brief_node requires state.domain_context with domain and profile_version")

    profile = get_domain_profile(domain, version=profile_version)
    provider = provider_factory()
    briefs: dict[str, EvidenceBrief] = {}

    for topic in qualifying_topics:
        topic_id = _get_value(topic, "topic_id")
        topic_name = _get_value(topic, "topic")
        results = provider.search(f"{topic_name} 基础健康科普", profile.evidence_domains)
        items = _build_evidence_items(topic_name, results, profile.evidence_domains)
        if not items:
            raise RuntimeError(f"No allowlisted evidence results found for topic_id {topic_id}")

        briefs[topic_id] = EvidenceBrief(
            topic_id=topic_id,
            items=items,
            unsupported_claims=[],
        )

    return {"evidence_briefs": briefs}
