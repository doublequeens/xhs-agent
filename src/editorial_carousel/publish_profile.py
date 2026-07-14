from __future__ import annotations

from src.domain import get_domain_profile


def resolve_publish_package_profile(publish_package: dict):
    """Resolve the domain profile bound to a modern publish package."""

    domain = publish_package.get("domain")
    profile_version = publish_package.get("profile_version")
    if not domain or not profile_version:
        raise ValueError(
            "publish_package requires valid domain and profile_version metadata"
        )
    try:
        return get_domain_profile(domain, version=profile_version)
    except ValueError as exc:
        raise ValueError(
            "publish_package requires valid domain and profile_version metadata: "
            f"{exc}"
        ) from exc
