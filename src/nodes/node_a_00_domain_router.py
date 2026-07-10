from src.domain import build_content_policy, get_domain_profile
from src.domain.router import resolve_domain
from src.schemas import AgentState


def domain_router_node(state: AgentState) -> dict:
    creator_profile = state.get("creator_profile")
    domain = state.get("domain")
    subdomain = state.get("subdomain")

    if creator_profile is not None:
        if domain is None and subdomain is None:
            domain = creator_profile.default_domain
            subdomain = creator_profile.default_subdomain
        elif domain is not None and subdomain is not None:
            creator_profile.assert_domain_scope(domain, subdomain)
        elif domain is not None:
            creator_profile.assert_domain_scope(domain, creator_profile.default_subdomain)
        else:
            raise ValueError("subdomain requires domain")

    context = resolve_domain(
        domain,
        state.get("focus_keyword") or "",
        subdomain,
        interactive=state.get("interactive", True),
    )
    if creator_profile is not None:
        creator_profile.assert_domain_scope(context.domain, context.subdomain)
    profile = get_domain_profile(context.domain, version=context.profile_version)

    return {
        "domain_context": context,
        "content_policy": build_content_policy(profile, context.risk_level),
    }
