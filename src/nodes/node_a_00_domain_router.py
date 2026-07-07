from src.domain import build_content_policy, get_domain_profile
from src.domain.router import resolve_domain
from src.schemas import AgentState


def domain_router_node(state: AgentState) -> dict:
    context = resolve_domain(
        state.get("domain"),
        state.get("focus_keyword") or "",
        state.get("subdomain"),
        interactive=True,
    )
    profile = get_domain_profile(context.domain, version=context.profile_version)

    return {
        "domain_context": context,
        "content_policy": build_content_policy(profile, context.risk_level),
    }
