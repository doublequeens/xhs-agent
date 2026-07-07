from langgraph.types import interrupt

from src.domain import DomainContext, build_content_policy, get_domain_profile
from src.domain.router import resolve_domain
from src.schemas import AgentState


def domain_confirmation_node(state: AgentState) -> dict:
    context = state.get("domain_context")
    if context is None:
        raise ValueError("domain_confirmation_node requires `domain_context` in state.")
    interactive = state.get("interactive", True)

    if (
        not interactive
        or (
            context.classification_confidence >= 0.65
            and context.classification_source != "explicit_domain_default_subdomain"
        )
    ):
        return {}

    resume = interrupt(
        {
            "kind": "domain_confirmation",
            "message": "当前内容领域判断置信度较低，请确认 domain 和 subdomain。",
            "context": context.model_dump(),
        }
    )

    if not isinstance(resume, dict):
        raise ValueError("Domain confirmation resume payload must be a dict.")

    selected_domain = resume.get("domain")
    selected_subdomain = resume.get("subdomain")
    if not selected_domain or not selected_subdomain:
        raise ValueError("Domain confirmation requires both `domain` and `subdomain`.")

    profile = get_domain_profile(selected_domain)
    if selected_subdomain not in profile.allowed_subdomains:
        raise ValueError(
            f"Unsupported subdomain: {selected_subdomain} for domain {selected_domain}"
        )

    updated_context = resolve_domain(
        domain=selected_domain,
        subdomain=selected_subdomain,
        focus_keyword="",
    )

    return {
        "domain_context": DomainContext.model_validate(updated_context),
        "content_policy": build_content_policy(profile, updated_context.risk_level),
    }
