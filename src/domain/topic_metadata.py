from src.schemas.topic import TopicItem


def get_topic_metadata(topics: list[TopicItem], topic_id: str) -> dict[str, object]:
    matches = [topic for topic in topics if topic.topic_id == topic_id]

    if not matches:
        raise ValueError(f"Unknown topic_id: {topic_id}")
    if len(matches) > 1:
        raise ValueError(f"Duplicate topic_id: {topic_id}")

    topic = matches[0]
    return {
        "domain": topic.domain,
        "subdomain": topic.subdomain,
        "content_intent": topic.content_intent,
        "risk_level": topic.risk_level,
        "risk_flags": list(topic.risk_flags),
    }
