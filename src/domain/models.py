from typing import Literal

from pydantic import BaseModel, Field

DomainName = Literal["beauty", "wellness", "healthy_lifestyle"]
RiskLevel = Literal["low", "medium"]
ContentIntent = Literal["experience", "myth_busting", "how_to", "checklist", "basic_science"]


class DomainContext(BaseModel):
    domain: DomainName
    subdomain: str
    classification_source: Literal["explicit", "inferred", "default"]
    confidence: float = Field(ge=0, le=1)
    profile_version: str
    risk_level: RiskLevel


class ContentPolicy(BaseModel):
    allowed_topics: tuple[str, ...]
    prohibited_topics: tuple[str, ...]
    prohibited_claims: tuple[str, ...]
    required_disclaimers: str
    risk_level: RiskLevel
    require_evidence_brief: bool
    require_human_review: bool = True


class DomainProfile(BaseModel):
    domain: DomainName
    version: str
    default_subdomain: str
    allowed_subdomains: tuple[str, ...]
    keyword_map: dict[str, tuple[str, ...]]
    prohibited_topics: tuple[str, ...]
    prohibited_claims: tuple[str, ...]
    required_disclaimers: str
    hashtag_seeds: tuple[str, ...]
    visual_guidelines: str
    evidence_domains: tuple[str, ...]
