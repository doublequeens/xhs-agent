from src.domain.models import DomainContext, RiskLevel
from src.domain.profiles import PROFILES
from src.domain.registry import get_domain_profile

DEFAULT_DOMAIN = "healthy_lifestyle"


def _risk_level_for_domain(domain: str) -> RiskLevel:
    return "low"


def resolve_domain(domain: str | None, focus_keyword: str) -> DomainContext:
    keyword = (focus_keyword or "").casefold()

    if domain:
        profile = get_domain_profile(domain)
        return DomainContext(
            domain=profile.domain,
            subdomain=profile.default_subdomain,
            classification_source="explicit",
            classification_confidence=1,
            profile_version=profile.version,
            risk_level=_risk_level_for_domain(profile.domain),
        )

    top_score = 0
    top_candidates: list[tuple[str, str]] = []

    for domain_name, profile in PROFILES.items():
        for subdomain, keywords in profile.keyword_map.items():
            score = sum(1 for candidate in keywords if candidate.casefold() in keyword)
            if score <= 0:
                continue
            if score > top_score:
                top_score = score
                top_candidates = [(domain_name, subdomain)]
            elif score == top_score:
                top_candidates.append((domain_name, subdomain))

    if not top_candidates:
        profile = get_domain_profile(DEFAULT_DOMAIN)
        return DomainContext(
            domain=profile.domain,
            subdomain=profile.default_subdomain,
            classification_source="default",
            classification_confidence=0.5,
            profile_version=profile.version,
            risk_level=_risk_level_for_domain(profile.domain),
        )

    selected_domain, selected_subdomain = top_candidates[0]
    profile = get_domain_profile(selected_domain)
    confidence = min(0.8 + 0.05 * (top_score - 1), 0.95)
    if len(top_candidates) > 1:
        confidence = 0.6

    return DomainContext(
        domain=profile.domain,
        subdomain=selected_subdomain,
        classification_source="inferred",
        classification_confidence=confidence,
        profile_version=profile.version,
        risk_level=_risk_level_for_domain(profile.domain),
    )
