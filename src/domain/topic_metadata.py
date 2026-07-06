from typing import Any, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from src.domain.models import ContentIntent, DomainName, RiskLevel


class TopicMetadataLike(Protocol):
    topic_id: str
    domain: "DomainName"
    subdomain: str
    content_intent: "ContentIntent"
    risk_level: "RiskLevel"
    risk_flags: list[str]


def get_topic_metadata(topics: list[Any], topic_id: str) -> dict[str, object]:
    matches = [topic for topic in topics if getattr(topic, "topic_id", None) == topic_id]

    if not matches:
        raise ValueError(f"Unknown topic_id: {topic_id}")
    if len(matches) > 1:
        raise ValueError(f"Duplicate topic_id: {topic_id}")

    topic: TopicMetadataLike = matches[0]
    return {
        "domain": topic.domain,
        "subdomain": topic.subdomain,
        "content_intent": topic.content_intent,
        "risk_level": topic.risk_level,
        "risk_flags": list(topic.risk_flags),
    }
