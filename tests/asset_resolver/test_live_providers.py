from __future__ import annotations

import os

import pytest


@pytest.mark.live_asset_providers
def test_live_asset_provider_smoke_is_opt_in_before_provider_construction(monkeypatch):
    if os.environ.get("RUN_LIVE_ASSET_PROVIDER_TESTS") != "1":
        pytest.skip("set RUN_LIVE_ASSET_PROVIDER_TESTS=1 to enable network smoke")
    if not (os.environ.get("PEXELS_API_KEY") or os.environ.get("UNSPLASH_ACCESS_KEY")):
        pytest.skip("set PEXELS_API_KEY or UNSPLASH_ACCESS_KEY to enable network smoke")

    # Imports and client construction intentionally happen only after the gate.
    from src.asset_resolver.providers import PexelsProvider, UnsplashProvider

    assert PexelsProvider(os.environ.get("PEXELS_API_KEY")).enabled or UnsplashProvider(
        os.environ.get("UNSPLASH_ACCESS_KEY")
    ).enabled
