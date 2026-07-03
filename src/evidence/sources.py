from urllib.parse import urlsplit

from .models import SourceType

PUBLIC_HEALTH_DOMAINS = (
    "who.int",
    "nih.gov",
    "cdc.gov",
    "nhs.uk",
    "nhc.gov.cn",
    "chinacdc.cn",
)
ACADEMIC_SUFFIXES = (".edu", ".ac.uk", ".edu.cn")


def _normalize_host(host: str | None) -> str:
    if not host:
        return ""
    return host.rstrip(".").casefold()


def _host_matches_domain(host: str, domain: str) -> bool:
    normalized_domain = _normalize_host(domain)
    return host == normalized_domain or host.endswith(f".{normalized_domain}")


def is_allowlisted_source_url(url: str, allowed_domains: tuple[str, ...] | list[str]) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        return False

    host = _normalize_host(parts.hostname)
    if not host:
        return False

    return any(_host_matches_domain(host, domain) for domain in allowed_domains)


def classify_source_type(url: str) -> SourceType:
    host = _normalize_host(urlsplit(url).hostname)
    if not host:
        return "professional"

    if any(_host_matches_domain(host, domain) for domain in PUBLIC_HEALTH_DOMAINS):
        return "public_health"

    if any(host.endswith(suffix) for suffix in ACADEMIC_SUFFIXES):
        return "academic"

    return "professional"
