from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

import requests

from src.schemas.assets import AssetRequirement


PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
UNSPLASH_SEARCH_URL = "https://api.unsplash.com/search/photos"
PEXELS_LICENSE_URL = "https://www.pexels.com/license/"
UNSPLASH_LICENSE_URL = "https://unsplash.com/license"
PEXELS_LICENSE_SUMMARY = """Pexels License terms summary v1 (2026-07-14)
Official terms: https://www.pexels.com/license/
Stock photos require provenance retention and explicit human rights review before production use.
This local summary is not the complete license text and is not legal advice.
"""
UNSPLASH_LICENSE_SUMMARY = """Unsplash License terms summary v1 (2026-07-14)
Official terms: https://unsplash.com/license
Stock photos require provenance retention, download tracking, and explicit human rights review before production use.
This local summary is not the complete license text and is not legal advice.
"""
DEFAULT_TIMEOUT = 15
DEFAULT_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
_PEXELS_API_HOSTS = frozenset({"api.pexels.com"})
_PEXELS_PAGE_HOSTS = frozenset({"pexels.com", "www.pexels.com"})
_PEXELS_FILE_HOSTS = frozenset({"images.pexels.com"})
_UNSPLASH_API_HOSTS = frozenset({"api.unsplash.com"})
_UNSPLASH_PAGE_HOSTS = frozenset({"unsplash.com", "www.unsplash.com"})
_UNSPLASH_FILE_HOSTS = frozenset({"images.unsplash.com"})


class ProviderSecurityError(RuntimeError):
    """Raised when a provider URL or response violates the network policy."""


class ProviderDownloadError(RuntimeError):
    """Raised when a provider download exceeds its resource budget."""


@dataclass(frozen=True, slots=True)
class ExternalAssetCandidate:
    provider: str
    provider_asset_id: str
    author: str
    source_url: str
    source_file_url: str
    width: int
    height: int
    role: str | None
    license: str
    license_snapshot: str
    license_terms_url: str | None = None
    score_tags: tuple[str, ...] = ()
    palette_tags: tuple[str, ...] = ()
    dominant_color: str | None = None
    download_location: str | None = None
    has_watermark: bool | None = None
    has_logo: bool | None = None
    has_text: bool | None = None
    recognizable_face: bool | None = None
    allowed_for_publishing: bool | None = None
    provider_attribution: tuple[tuple[str, str], ...] = ()

    @property
    def orientation(self) -> str:
        if self.width == self.height:
            return "square"
        if self.width > self.height:
            return "landscape"
        return "portrait"


class AssetProvider(Protocol):
    name: str

    def search(self, requirement: AssetRequirement) -> list[ExternalAssetCandidate]: ...

    def record_download(self, candidate: ExternalAssetCandidate) -> None: ...

    def download(self, candidate: ExternalAssetCandidate) -> bytes: ...


def _is_allowed_https_url(value: Any, allowed_hosts: frozenset[str]) -> bool:
    if not isinstance(value, str) or not value:
        return False
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname in allowed_hosts
        and parsed.username is None
        and parsed.password is None
        and parsed.port in (None, 443)
    )


def _validated_get(
    session: requests.Session,
    url: str,
    *,
    allowed_hosts: frozenset[str],
    **kwargs: Any,
):
    if not _is_allowed_https_url(url, allowed_hosts):
        raise ProviderSecurityError(f"provider URL host is not allowlisted: {url}")
    response = session.get(url, allow_redirects=False, **kwargs)
    try:
        final_url = getattr(response, "url", None) or url
        if not _is_allowed_https_url(final_url, allowed_hosts):
            raise ProviderSecurityError(
                f"provider response final URL host is not allowlisted: {final_url}"
            )
        status_code = getattr(response, "status_code", 200)
        if 300 <= status_code < 400:
            raise ProviderSecurityError("provider redirect responses are disabled")
        response.raise_for_status()
    except Exception:
        close = getattr(response, "close", None)
        if callable(close):
            close()
        raise
    return response


def _bounded_response_bytes(response: Any, *, max_bytes: int) -> bytes:
    content_length = (getattr(response, "headers", {}) or {}).get("Content-Length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except (TypeError, ValueError) as error:
            raise ProviderDownloadError("invalid Content-Length") from error
        if declared_length < 0:
            raise ProviderDownloadError("invalid Content-Length")
        if declared_length > max_bytes:
            raise ProviderDownloadError("download exceeds byte limit")
    chunks: list[bytes] = []
    total = 0
    iterator = getattr(response, "iter_content", None)
    if callable(iterator):
        stream = iterator(chunk_size=64 * 1024)
    else:
        stream = (getattr(response, "content", b""),)
    for chunk in stream:
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise ProviderDownloadError("download exceeds byte limit")
        chunks.append(chunk)
    return b"".join(chunks)


def candidate_urls_are_allowed(
    provider: str,
    *,
    source_url: str,
    source_file_url: str,
    license_terms_url: str,
) -> bool:
    if provider == "pexels":
        return (
            _is_allowed_https_url(source_url, _PEXELS_PAGE_HOSTS)
            and _is_allowed_https_url(source_file_url, _PEXELS_FILE_HOSTS)
            and _is_allowed_https_url(license_terms_url, _PEXELS_PAGE_HOSTS)
        )
    if provider == "unsplash":
        return (
            _is_allowed_https_url(source_url, _UNSPLASH_PAGE_HOSTS)
            and _is_allowed_https_url(source_file_url, _UNSPLASH_FILE_HOSTS)
            and _is_allowed_https_url(license_terms_url, _UNSPLASH_PAGE_HOSTS)
        )
    return False


def structured_query(requirement: AssetRequirement) -> str:
    """Build deterministic English-only provider search terms from a slot."""

    raw_terms = [
        *requirement.role.replace("_", " ").split(),
        *requirement.context_tags,
        *requirement.palette_tags,
    ]
    terms: list[str] = []
    seen: set[str] = set()
    for raw in raw_terms:
        for term in re.findall(r"[a-z0-9-]+", str(raw).lower()):
            if term not in seen:
                seen.add(term)
                terms.append(term)
    return " ".join(terms)


def _score_tags(*values: Any) -> tuple[str, ...]:
    words: list[str] = []
    seen: set[str] = set()
    for value in values:
        for word in re.findall(r"[a-z0-9-]+", str(value or "").lower()):
            if word not in seen:
                seen.add(word)
                words.append(word)
    return tuple(words)


def _safety_flags(tags: tuple[str, ...]) -> dict[str, bool | None]:
    values = set(tags)
    return {
        "has_watermark": True
        if values.intersection({"watermark", "watermarked"})
        else None,
        "has_logo": True if values.intersection({"logo", "branded", "brand"}) else None,
        "has_text": True
        if values.intersection({"text", "typography", "poster", "sign", "label"})
        else None,
        "recognizable_face": True
        if values.intersection({"face", "portrait", "person", "woman", "man", "model"})
        else None,
    }


def _search_params(
    requirement: AssetRequirement, *, provider: str
) -> dict[str, str | int]:
    params: dict[str, str | int] = {
        "query": structured_query(requirement),
        "per_page": 15,
    }
    if requirement.orientation != "any":
        orientation = requirement.orientation
        if provider == "unsplash" and orientation == "square":
            orientation = "squarish"
        params["orientation"] = orientation
    return params


class PexelsProvider:
    name = "pexels"

    def __init__(
        self,
        api_key: str | None,
        *,
        session: requests.Session | None = None,
        timeout: float | tuple[float, float] = DEFAULT_TIMEOUT,
        max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_download_bytes = max_download_bytes

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": self.api_key}

    def search(self, requirement: AssetRequirement) -> list[ExternalAssetCandidate]:
        if not self.enabled:
            return []
        query = structured_query(requirement)
        response = _validated_get(
            self.session,
            PEXELS_SEARCH_URL,
            allowed_hosts=_PEXELS_API_HOSTS,
            headers=self._headers,
            params=_search_params(requirement, provider=self.name),
            timeout=self.timeout,
        )
        try:
            photos = response.json().get("photos", [])
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        results: list[ExternalAssetCandidate] = []
        for photo in photos:
            source_url = photo.get("url")
            source_file_url = (photo.get("src") or {}).get("original")
            author = photo.get("photographer")
            if not (
                _is_allowed_https_url(source_url, _PEXELS_PAGE_HOSTS)
                and _is_allowed_https_url(source_file_url, _PEXELS_FILE_HOSTS)
                and isinstance(author, str)
                and author
            ):
                continue
            try:
                width = int(photo["width"])
                height = int(photo["height"])
                asset_id = str(photo["id"])
            except (KeyError, TypeError, ValueError):
                continue
            results.append(
                # Provider descriptions are evidence; request terms are not candidate
                # metadata and therefore must not inflate semantic ranking.
                ExternalAssetCandidate(
                    provider=self.name,
                    provider_asset_id=asset_id,
                    author=author,
                    source_url=source_url,
                    source_file_url=source_file_url,
                    width=width,
                    height=height,
                    role=None,
                    license="Pexels License",
                    license_snapshot=PEXELS_LICENSE_SUMMARY,
                    license_terms_url=PEXELS_LICENSE_URL,
                    score_tags=(tags := _score_tags(photo.get("alt"))),
                    palette_tags=tuple(
                        tag
                        for tag in requirement.palette_tags
                        if tag.lower() in tags
                    ),
                    dominant_color=photo.get("avg_color"),
                    provider_attribution=(("photographer", author),),
                    **_safety_flags(tags),
                )
            )
        return results

    def record_download(self, candidate: ExternalAssetCandidate) -> None:
        return None

    def download(self, candidate: ExternalAssetCandidate) -> bytes:
        response = _validated_get(
            self.session,
            candidate.source_file_url,
            allowed_hosts=_PEXELS_FILE_HOSTS,
            timeout=self.timeout,
            stream=True,
        )
        try:
            return _bounded_response_bytes(
                response, max_bytes=self.max_download_bytes
            )
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()


class UnsplashProvider:
    name = "unsplash"

    def __init__(
        self,
        access_key: str | None,
        *,
        session: requests.Session | None = None,
        timeout: float | tuple[float, float] = DEFAULT_TIMEOUT,
        max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
    ) -> None:
        self.access_key = (access_key or "").strip()
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_download_bytes = max_download_bytes

    @property
    def enabled(self) -> bool:
        return bool(self.access_key)

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Client-ID {self.access_key}"}

    def search(self, requirement: AssetRequirement) -> list[ExternalAssetCandidate]:
        if not self.enabled:
            return []
        query = structured_query(requirement)
        response = _validated_get(
            self.session,
            UNSPLASH_SEARCH_URL,
            allowed_hosts=_UNSPLASH_API_HOSTS,
            headers=self._headers,
            params=_search_params(requirement, provider=self.name),
            timeout=self.timeout,
        )
        try:
            photos = response.json().get("results", [])
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        results: list[ExternalAssetCandidate] = []
        for photo in photos:
            links = photo.get("links") or {}
            urls = photo.get("urls") or {}
            source_url = links.get("html")
            source_file_url = urls.get("full")
            download_location = links.get("download_location")
            author = (photo.get("user") or {}).get("name")
            if not (
                _is_allowed_https_url(source_url, _UNSPLASH_PAGE_HOSTS)
                and _is_allowed_https_url(source_file_url, _UNSPLASH_FILE_HOSTS)
                and _is_allowed_https_url(download_location, _UNSPLASH_API_HOSTS)
                and isinstance(author, str)
                and author
            ):
                continue
            try:
                width = int(photo["width"])
                height = int(photo["height"])
                asset_id = str(photo["id"])
            except (KeyError, TypeError, ValueError):
                continue
            description_tags = _score_tags(
                photo.get("description"), photo.get("alt_description")
            )
            results.append(
                ExternalAssetCandidate(
                    provider=self.name,
                    provider_asset_id=asset_id,
                    author=author,
                    source_url=source_url,
                    source_file_url=source_file_url,
                    width=width,
                    height=height,
                    role=None,
                    license="Unsplash License",
                    license_snapshot=UNSPLASH_LICENSE_SUMMARY,
                    license_terms_url=UNSPLASH_LICENSE_URL,
                    score_tags=description_tags,
                    palette_tags=tuple(
                        tag
                        for tag in requirement.palette_tags
                        if tag.lower() in description_tags
                    ),
                    dominant_color=photo.get("color"),
                    download_location=download_location,
                    provider_attribution=tuple(
                        (key, str(value))
                        for key, value in {
                            "name": author,
                            "username": (photo.get("user") or {}).get("username"),
                        }.items()
                        if value
                    ),
                    **_safety_flags(description_tags),
                )
            )
        return results

    def record_download(self, candidate: ExternalAssetCandidate) -> None:
        if not _is_allowed_https_url(candidate.download_location, _UNSPLASH_API_HOSTS):
            raise ValueError("Unsplash candidate is missing download_location")
        response = _validated_get(
            self.session,
            candidate.download_location,
            allowed_hosts=_UNSPLASH_API_HOSTS,
            headers=self._headers,
            timeout=self.timeout,
        )
        close = getattr(response, "close", None)
        if callable(close):
            close()

    def download(self, candidate: ExternalAssetCandidate) -> bytes:
        response = _validated_get(
            self.session,
            candidate.source_file_url,
            allowed_hosts=_UNSPLASH_FILE_HOSTS,
            timeout=self.timeout,
            stream=True,
        )
        try:
            return _bounded_response_bytes(
                response, max_bytes=self.max_download_bytes
            )
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
