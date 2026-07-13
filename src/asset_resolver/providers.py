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
DEFAULT_TIMEOUT = 15


@dataclass(frozen=True, slots=True)
class ExternalAssetCandidate:
    provider: str
    provider_asset_id: str
    author: str
    source_url: str
    source_file_url: str
    width: int
    height: int
    role: str
    license: str
    license_snapshot: str
    score_tags: tuple[str, ...] = ()
    palette_tags: tuple[str, ...] = ()
    dominant_color: str | None = None
    download_location: str | None = None
    has_watermark: bool = False
    has_logo: bool = False
    has_text: bool = False
    recognizable_face: bool = False
    allowed_for_publishing: bool = True
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


def _is_official_https_url(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


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


def _safety_flags(tags: tuple[str, ...]) -> dict[str, bool]:
    values = set(tags)
    return {
        "has_watermark": bool(values.intersection({"watermark", "watermarked"})),
        "has_logo": bool(values.intersection({"logo", "branded", "brand"})),
        "has_text": bool(
            values.intersection({"text", "typography", "poster", "sign", "label"})
        ),
        "recognizable_face": bool(
            values.intersection(
                {"face", "portrait", "person", "woman", "man", "model"}
            )
        ),
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
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.session = session or requests.Session()
        self.timeout = timeout

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
        response = self.session.get(
            PEXELS_SEARCH_URL,
            headers=self._headers,
            params=_search_params(requirement, provider=self.name),
            timeout=self.timeout,
        )
        response.raise_for_status()
        results: list[ExternalAssetCandidate] = []
        for photo in response.json().get("photos", []):
            source_url = photo.get("url")
            source_file_url = (photo.get("src") or {}).get("original")
            author = photo.get("photographer")
            if not (
                _is_official_https_url(source_url)
                and _is_official_https_url(source_file_url)
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
                    role=requirement.role,
                    license="Pexels License",
                    license_snapshot=PEXELS_LICENSE_URL,
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
        response = self.session.get(candidate.source_file_url, timeout=self.timeout)
        response.raise_for_status()
        return response.content


class UnsplashProvider:
    name = "unsplash"

    def __init__(
        self,
        access_key: str | None,
        *,
        session: requests.Session | None = None,
        timeout: float | tuple[float, float] = DEFAULT_TIMEOUT,
    ) -> None:
        self.access_key = (access_key or "").strip()
        self.session = session or requests.Session()
        self.timeout = timeout

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
        response = self.session.get(
            UNSPLASH_SEARCH_URL,
            headers=self._headers,
            params=_search_params(requirement, provider=self.name),
            timeout=self.timeout,
        )
        response.raise_for_status()
        results: list[ExternalAssetCandidate] = []
        for photo in response.json().get("results", []):
            links = photo.get("links") or {}
            urls = photo.get("urls") or {}
            source_url = links.get("html")
            source_file_url = urls.get("full")
            download_location = links.get("download_location")
            author = (photo.get("user") or {}).get("name")
            if not all(
                _is_official_https_url(value)
                for value in (source_url, source_file_url, download_location)
            ) or not isinstance(author, str) or not author:
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
                    role=requirement.role,
                    license="Unsplash License",
                    license_snapshot=UNSPLASH_LICENSE_URL,
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
        if not _is_official_https_url(candidate.download_location):
            raise ValueError("Unsplash candidate is missing download_location")
        response = self.session.get(
            candidate.download_location,
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()

    def download(self, candidate: ExternalAssetCandidate) -> bytes:
        response = self.session.get(candidate.source_file_url, timeout=self.timeout)
        response.raise_for_status()
        return response.content
