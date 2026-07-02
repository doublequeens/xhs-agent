from typing import Literal

from pydantic import BaseModel, Field, model_validator

DomainName = Literal["beauty", "wellness", "healthy_lifestyle"]
RiskLevel = Literal["low", "medium"]
ContentIntent = Literal["experience", "myth_busting", "how_to", "checklist", "basic_science"]


class DomainContext(BaseModel):
    domain: DomainName
    subdomain: str
    classification_source: Literal["explicit", "inferred", "default"]
    classification_confidence: float = Field(ge=0, le=1)
    profile_version: str
    risk_level: RiskLevel


class ContentPolicy(BaseModel):
    allowed_topics: list[str]
    prohibited_topics: list[str]
    prohibited_claims: list[str]
    required_disclaimers: list[str]
    risk_level: RiskLevel
    require_evidence_brief: bool
    require_human_review: bool = True


class DomainProfile(BaseModel):
    domain: DomainName
    version: str = Field(min_length=1, pattern=r"^[a-z0-9-]+-v[1-9][0-9]*$")
    default_subdomain: str
    allowed_subdomains: tuple[str, ...] = Field(min_length=1)
    keyword_map: dict[str, tuple[str, ...]]
    prohibited_topics: tuple[str, ...] = Field(min_length=1)
    prohibited_claims: tuple[str, ...] = Field(min_length=1)
    required_disclaimers: tuple[str, ...] = Field(min_length=1)
    hashtag_seeds: tuple[str, ...] = Field(min_length=1)
    visual_guidelines: tuple[str, ...] = Field(min_length=1)
    evidence_domains: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_invariants(self) -> "DomainProfile":
        errors: list[str] = []

        if self.default_subdomain not in self.allowed_subdomains:
            errors.append("default_subdomain must be in allowed_subdomains")

        for subdomain, keywords in self.keyword_map.items():
            if subdomain not in self.allowed_subdomains:
                errors.append(f"keyword_map key not allowed: {subdomain}")
            if not keywords:
                errors.append(f"keyword_map keywords must be non-empty: {subdomain}")

        if errors:
            raise ValueError("DomainProfile invariant check failed: " + "; ".join(errors))

        return self
