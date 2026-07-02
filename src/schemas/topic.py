from pydantic import BaseModel

from src.domain.models import ContentIntent, DomainName, RiskLevel


class TopicItem(BaseModel):
    topic_id: str
    topic: str  
    target_group: str
    core_pain: str
    hook: str
    content_form: str
    risk_note: str
    domain: DomainName
    subdomain: str
    content_intent: ContentIntent
    risk_level: RiskLevel
    risk_flags: list[str]
