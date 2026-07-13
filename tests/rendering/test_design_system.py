from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.rendering.editorial.design_system import (
    BEAUTY_EDITORIAL_V1,
    FONT_ROOT,
    REPOSITORY_ROOT,
)


PINNED_FONT_SHA256 = {
    "display": "faf16caeaf207e1926e01af8d9f1a8e71b0e9d8f51bf3b5d9a78f9f30e7e3e31",
    "body_regular": "f1d8611151880c6c336aabeac4640ef434fa13cbfbf1ffe82d0a71b2a5637256",
    "body_medium": "1df61d31687d04fd2f928a3bb6ca6cd61f0e988cc267cf317f32406edbb49f70",
    "numeral": "dd9660ca406734a3b64f5b6c3a7a823c624f17479235761e82862e61ecdbaf57",
}

PINNED_LICENSE_SHA256 = {
    "LICENSE-source-han-serif.txt": (
        "9ff5bb567e1b92c801fc1069e5fbf992ff8efccacb9db94e5959a5b3ba9bb903"
    ),
    "LICENSE-source-han.txt": (
        "fcac737e761ec63dbfbdce11030a1780161920d80315edba9c8beff1c2bac5a2"
    ),
    "OFL-bodoni-moda.txt": (
        "86279342767d5f3e6b07b49dd591f196dcb0ec9ec8b9ea339c09221e61863d46"
    ),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_design_system_exposes_immutable_editorial_tokens() -> None:
    assert BEAUTY_EDITORIAL_V1.name == "beauty_editorial_v1"
    assert BEAUTY_EDITORIAL_V1.canvas == (1080, 1440)
    assert dict(BEAUTY_EDITORIAL_V1.colors) == {
        "background": "#F7F2EA",
        "ink": "#292625",
        "mauve": "#9A707B",
        "coral": "#D45D4C",
        "sage": "#78805E",
    }

    with pytest.raises(FrozenInstanceError):
        BEAUTY_EDITORIAL_V1.name = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        BEAUTY_EDITORIAL_V1.colors["ink"] = "#000000"  # type: ignore[index]


def test_design_system_fonts_are_repo_local_and_licensed() -> None:
    assert dict(BEAUTY_EDITORIAL_V1.font_paths) == {
        "display": FONT_ROOT / "SourceHanSerifSC-SemiBold.otf",
        "body_regular": FONT_ROOT / "SourceHanSansSC-Regular.otf",
        "body_medium": FONT_ROOT / "SourceHanSansSC-Medium.otf",
        "numeral": FONT_ROOT / "BodoniModa-Regular.ttf",
    }

    for font_path in BEAUTY_EDITORIAL_V1.font_paths.values():
        assert font_path.is_file()
        assert font_path.resolve().is_relative_to(REPOSITORY_ROOT)
        assert font_path.stat().st_size > 50_000

    assert (FONT_ROOT / "SourceHanSerifSC-SemiBold.otf").read_bytes()[:4] == b"OTTO"
    assert (FONT_ROOT / "SourceHanSansSC-Regular.otf").read_bytes()[:4] == b"OTTO"
    assert (FONT_ROOT / "SourceHanSansSC-Medium.otf").read_bytes()[:4] == b"OTTO"
    assert (FONT_ROOT / "BodoniModa-Regular.ttf").read_bytes()[:4] in {
        b"\x00\x01\x00\x00",
        b"true",
    }

    source_han_license = (FONT_ROOT / "LICENSE-source-han.txt").read_text(
        encoding="utf-8"
    )
    bodoni_license = (FONT_ROOT / "OFL-bodoni-moda.txt").read_text(
        encoding="utf-8"
    )
    assert "SIL OPEN FONT LICENSE Version 1.1" in source_han_license
    assert "SIL OPEN FONT LICENSE Version 1.1" in bodoni_license


def test_design_system_fonts_match_pinned_upstream_files() -> None:
    for role, expected_hash in PINNED_FONT_SHA256.items():
        assert _sha256(BEAUTY_EDITORIAL_V1.font_paths[role]) == expected_hash


def test_design_system_license_files_match_pinned_upstream_notices() -> None:
    for filename, expected_hash in PINNED_LICENSE_SHA256.items():
        license_path = FONT_ROOT / filename
        assert license_path.is_file(), f"missing pinned license file: {filename}"
        assert _sha256(license_path) == expected_hash

    source_han_serif_license = (
        FONT_ROOT / "LICENSE-source-han-serif.txt"
    ).read_text(encoding="utf-8")
    source_han_sans_license = (FONT_ROOT / "LICENSE-source-han.txt").read_text(
        encoding="utf-8"
    )
    bodoni_license = (FONT_ROOT / "OFL-bodoni-moda.txt").read_text(
        encoding="utf-8"
    )

    assert source_han_serif_license.startswith(
        "Copyright 2017-2022 Adobe (http://www.adobe.com/)"
    )
    assert source_han_sans_license.startswith(
        "Copyright 2014-2025 Adobe (http://www.adobe.com/)"
    )
    assert bodoni_license.startswith("Copyright 2020 The Bodoni Moda Project Authors")
    assert "SIL OPEN FONT LICENSE Version 1.1" in source_han_serif_license


def test_catalog_loader_validates_webp_dimensions(tmp_path: Path) -> None:
    from PIL import Image

    from src.rendering.editorial.design_system import load_catalog

    asset_path = tmp_path / "active" / "stock" / "serum.webp"
    asset_path.parent.mkdir(parents=True)
    Image.new("RGB", (1080, 1440), "ivory").save(
        asset_path, format="WEBP", lossless=True
    )
    manifest = {
        "catalog_id": "test-catalog",
        "assets": [
            {
                "asset_id": "serum-p1",
                "role": "serum_texture",
                "path": "active/stock/serum.webp",
                "ownership": "licensed_stock",
                "license": "Pexels License",
                "dimensions": {"width": 1080, "height": 1440},
                "sha256": hashlib.sha256(asset_path.read_bytes()).hexdigest(),
                "allowed_layouts": ["texture_baseline"],
                "tags": ["serum"],
                "disabled_contexts": [],
                "fallback_roles": ["serum_texture"],
                "usage": "production",
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    loaded = load_catalog(manifest_path)

    assert loaded.entries[0].dimensions == (1080, 1440)
