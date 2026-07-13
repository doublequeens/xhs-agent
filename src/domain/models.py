from typing import Literal

from pydantic import BaseModel, Field, model_validator

DomainName = Literal["beauty", "wellness", "healthy_lifestyle"]
RiskLevel = Literal["low", "medium"]
ContentIntent = Literal["experience", "myth_busting", "how_to", "checklist", "basic_science"]


class DomainContext(BaseModel):
    domain: DomainName
    subdomain: str
    classification_source: Literal[
        "explicit",
        "explicit_domain_default_subdomain",
        "inferred",
        "default",
    ]
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
        expected_prefix = {
            "beauty": "beauty-v",
            "wellness": "wellness-v",
            "healthy_lifestyle": "healthy-lifestyle-v",
        }[self.domain]

        if self.default_subdomain not in self.allowed_subdomains:
            errors.append("default_subdomain must be in allowed_subdomains")

        if not self.keyword_map:
            errors.append("keyword_map must be non-empty")
        else:
            expected_subdomains = set(self.allowed_subdomains)
            actual_subdomains = set(self.keyword_map)
            if actual_subdomains != expected_subdomains:
                missing = sorted(expected_subdomains - actual_subdomains)
                extra = sorted(actual_subdomains - expected_subdomains)
                if missing:
                    errors.append(f"keyword_map missing subdomains: {', '.join(missing)}")
                if extra:
                    errors.append(f"keyword_map has extra subdomains: {', '.join(extra)}")

            for subdomain, keywords in self.keyword_map.items():
                if not keywords:
                    errors.append(f"keyword_map keywords must be non-empty: {subdomain}")

        if not self.version.startswith(expected_prefix):
            errors.append(f"version must start with {expected_prefix}")

        if errors:
            raise ValueError("DomainProfile invariant check failed: " + "; ".join(errors))

        return self
