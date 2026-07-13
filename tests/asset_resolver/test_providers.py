from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.schemas.assets import AssetRequirement


@dataclass
class FakeResponse:
    payload: dict[str, Any]
    content: bytes = b""
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    status_code: int = 200
    closed: bool = False

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload

    def iter_content(self, chunk_size: int = 8192):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset : offset + chunk_size]

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("GET", url, kwargs))
        return self.responses.pop(0)


def requirement() -> AssetRequirement:
    return AssetRequirement(
        slot_id="serum-slot",
        role="serum_texture",
        layout="texture_baseline",
        min_width=1080,
        min_height=1440,
        context_tags=["serum", "drop"],
        orientation="portrait",
        palette_tags=["ivory"],
    )


def test_pexels_search_uses_official_endpoint_and_preserves_real_urls() -> None:
    from src.asset_resolver.providers import PexelsProvider

    search_response = FakeResponse(
                {
                    "photos": [
                        {
                            "id": 41,
                            "width": 1600,
                            "height": 2400,
                            "url": "https://www.pexels.com/photo/41/",
                            "photographer": "Ada",
                            "alt": "Ivory serum drop",
                            "avg_color": "#eee8df",
                            "src": {"original": "https://images.pexels.com/photos/41.jpeg"},
                        }
                    ]
                }
            )
    session = FakeSession([search_response])

    result = PexelsProvider("pexels-key", session=session, timeout=7).search(
        requirement()
    )

    method, url, kwargs = session.calls[0]
    assert (method, url) == ("GET", "https://api.pexels.com/v1/search")
    assert kwargs["headers"] == {"Authorization": "pexels-key"}
    assert kwargs["timeout"] == 7
    assert kwargs["params"]["query"] == "serum texture drop ivory"
    assert result[0].source_url == "https://www.pexels.com/photo/41/"
    assert result[0].source_file_url == "https://images.pexels.com/photos/41.jpeg"
    assert result[0].author == "Ada"
    assert "texture" not in result[0].score_tags
    assert result[0].palette_tags == ("ivory",)
    assert not result[0].license_snapshot.startswith("http")
    assert result[0].license_terms_url == "https://www.pexels.com/license/"
    assert search_response.closed is True


def test_unsplash_search_and_download_tracking_use_official_urls() -> None:
    from src.asset_resolver.providers import UnsplashProvider

    session = FakeSession(
        [
            FakeResponse(
                {
                    "results": [
                        {
                            "id": "abc",
                            "width": 1600,
                            "height": 2400,
                            "color": "#eee8df",
                            "description": "serum drop",
                            "alt_description": "ivory skincare serum",
                            "user": {"name": "Lin"},
                            "links": {
                                "html": "https://unsplash.com/photos/abc",
                                "download_location": "https://api.unsplash.com/photos/abc/download",
                            },
                            "urls": {"full": "https://images.unsplash.com/photo-abc"},
                        }
                    ]
                }
            ),
            FakeResponse({"url": "https://images.unsplash.com/tracked-abc"}),
        ]
    )
    provider = UnsplashProvider("unsplash-key", session=session, timeout=9)

    candidate = provider.search(requirement())[0]
    provider.record_download(candidate)

    search_call, tracking_call = session.calls
    assert search_call[1] == "https://api.unsplash.com/search/photos"
    assert search_call[2]["headers"] == {
        "Authorization": "Client-ID unsplash-key"
    }
    assert search_call[2]["timeout"] == 9
    assert tracking_call[1] == "https://api.unsplash.com/photos/abc/download"
    assert tracking_call[2]["headers"] == {
        "Authorization": "Client-ID unsplash-key"
    }
    assert tracking_call[2]["timeout"] == 9
    assert candidate.source_url == "https://unsplash.com/photos/abc"
    assert candidate.source_file_url == "https://images.unsplash.com/photo-abc"


def test_provider_drops_results_with_fabricated_or_incomplete_urls() -> None:
    from src.asset_resolver.providers import PexelsProvider

    session = FakeSession(
        [
            FakeResponse(
                {
                    "photos": [
                        {
                            "id": 41,
                            "width": 1600,
                            "height": 2400,
                            "url": "",
                            "photographer": "Ada",
                            "src": {},
                        }
                    ]
                }
            )
        ]
    )

    assert PexelsProvider("key", session=session).search(requirement()) == []


@pytest.mark.parametrize(
    "provider_type,orientation,expected",
    [
        ("pexels", "any", None),
        ("unsplash", "any", None),
        ("unsplash", "square", "squarish"),
    ],
)
def test_provider_maps_only_supported_orientation_values(
    provider_type: str, orientation: str, expected: str | None
) -> None:
    from src.asset_resolver.providers import PexelsProvider, UnsplashProvider

    session = FakeSession(
        [FakeResponse({"photos": []} if provider_type == "pexels" else {"results": []})]
    )
    provider = (
        PexelsProvider("key", session=session)
        if provider_type == "pexels"
        else UnsplashProvider("key", session=session)
    )
    request = requirement().model_copy(update={"orientation": orientation})

    provider.search(request)

    params = session.calls[0][2]["params"]
    if expected is None:
        assert "orientation" not in params
    else:
        assert params["orientation"] == expected


def test_package_exports_external_provider_and_lifecycle_contracts() -> None:
    from src.asset_resolver import (
        AssetProvider,
        ExternalAssetCandidate,
        PendingAsset,
        approve_external_asset,
        list_pending_assets,
        load_pending_asset,
        reject_external_asset,
    )

    assert AssetProvider is not None
    assert ExternalAssetCandidate is not None
    assert PendingAsset is not None
    assert callable(approve_external_asset)
    assert callable(list_pending_assets)
    assert callable(load_pending_asset)
    assert callable(reject_external_asset)


def test_pexels_rejects_non_official_page_and_file_hosts() -> None:
    from src.asset_resolver.providers import PexelsProvider

    payload = {
        "photos": [
            {
                "id": 41,
                "width": 1600,
                "height": 2400,
                "url": "https://evil.test/photo/41/",
                "photographer": "Ada",
                "alt": "serum drop",
                "src": {"original": "https://evil.test/41.jpeg"},
            }
        ]
    }
    session = FakeSession([FakeResponse(payload)])

    assert PexelsProvider("key", session=session).search(requirement()) == []
    assert session.calls[0][2]["allow_redirects"] is False


def test_unsplash_rejects_non_official_download_location_host() -> None:
    from src.asset_resolver.providers import UnsplashProvider

    payload = {
        "results": [
            {
                "id": "abc",
                "width": 1600,
                "height": 2400,
                "user": {"name": "Lin"},
                "links": {
                    "html": "https://unsplash.com/photos/abc",
                    "download_location": "https://evil.test/track",
                },
                "urls": {"full": "https://images.unsplash.com/photo-abc"},
            }
        ]
    }

    assert UnsplashProvider("key", session=FakeSession([FakeResponse(payload)])).search(
        requirement()
    ) == []


def test_search_rejects_redirect_and_untrusted_final_url() -> None:
    from src.asset_resolver.providers import PexelsProvider, ProviderSecurityError

    response = FakeResponse(
        {"photos": []},
        url="https://evil.test/redirected",
        status_code=302,
    )
    session = FakeSession([response])

    with pytest.raises(ProviderSecurityError, match="redirect|host"):
        PexelsProvider("key", session=session).search(requirement())


@pytest.mark.parametrize(
    "headers,content",
    [
        ({"Content-Length": "9"}, b"123456789"),
        ({}, b"123456789"),
    ],
    ids=["content-length", "stream-total"],
)
def test_download_rejects_payload_over_byte_limit(
    headers: dict[str, str], content: bytes
) -> None:
    from src.asset_resolver.providers import PexelsProvider, ProviderDownloadError

    search = FakeResponse(
        {
            "photos": [
                {
                    "id": 41,
                    "width": 1600,
                    "height": 2400,
                    "url": "https://www.pexels.com/photo/41/",
                    "photographer": "Ada",
                    "alt": "serum drop",
                    "src": {"original": "https://images.pexels.com/photos/41.jpeg"},
                }
            ]
        }
    )
    download = FakeResponse(
        {}, content=content, url="https://images.pexels.com/photos/41.jpeg", headers=headers
    )
    provider = PexelsProvider(
        "key", session=FakeSession([search, download]), max_download_bytes=8
    )
    candidate = provider.search(requirement())[0]

    with pytest.raises(ProviderDownloadError, match="byte limit"):
        provider.download(candidate)
    assert download.closed is True
