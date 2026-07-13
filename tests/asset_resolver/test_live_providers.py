from __future__ import annotations

import os

import pytest

from src.schemas.assets import AssetRequirement


pytestmark = [
    pytest.mark.live_asset_providers,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE_ASSET_PROVIDER_TESTS") != "1",
        reason="set RUN_LIVE_ASSET_PROVIDER_TESTS=1 to call stock provider APIs",
    ),
]


def _requirement() -> AssetRequirement:
    return AssetRequirement(
        slot_id="live-serum",
        role="serum_texture",
        layout="texture_baseline",
        min_width=800,
        min_height=1000,
        context_tags=["serum", "drop"],
        orientation="portrait",
        palette_tags=["ivory"],
    )


def test_live_pexels_search_returns_official_candidates() -> None:
    from src.asset_resolver.providers import PexelsProvider

    api_key = os.getenv("PEXELS_API_KEY")
    if not api_key:
        pytest.skip("PEXELS_API_KEY is not configured")

    results = PexelsProvider(api_key).search(_requirement())

    assert results
    assert all(candidate.provider == "pexels" for candidate in results)
    assert all(candidate.source_url.startswith("https://") for candidate in results)


def test_live_unsplash_search_returns_official_candidates() -> None:
    from src.asset_resolver.providers import UnsplashProvider

    access_key = os.getenv("UNSPLASH_ACCESS_KEY")
    if not access_key:
        pytest.skip("UNSPLASH_ACCESS_KEY is not configured")

    results = UnsplashProvider(access_key).search(_requirement())

    assert results
    assert all(candidate.provider == "unsplash" for candidate in results)
    assert all(candidate.download_location for candidate in results)
