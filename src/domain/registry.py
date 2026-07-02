from .models import ContentPolicy, DomainProfile, RiskLevel
from .profiles import PROFILES


def get_domain_profile(domain: str, version: str | None = None) -> DomainProfile:
    try:
        profile = PROFILES[domain]
    except KeyError as exc:
        raise ValueError(f"Unsupported domain: {domain}") from exc

    if version is not None and version != profile.version:
        raise ValueError(
            f"Unsupported profile version: {version} for domain {domain}; expected {profile.version}"
        )

    return profile


def build_content_policy(profile: DomainProfile, risk_level: RiskLevel = "low") -> ContentPolicy:
    return ContentPolicy(
        allowed_topics=list(profile.allowed_subdomains),
        prohibited_topics=list(profile.prohibited_topics),
        prohibited_claims=list(profile.prohibited_claims),
        required_disclaimers=list(profile.required_disclaimers),
        risk_level=risk_level,
        require_evidence_brief=profile.domain != "beauty",
        require_human_review=True,
    )
