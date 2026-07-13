from __future__ import annotations

import struct
from pathlib import Path

import pytest


def _local_chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            return Path(playwright.chromium.executable_path).is_file()
    except Exception:
        return False


def _png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", header[16:24])


@pytest.mark.skipif(
    not _local_chromium_available(),
    reason="local Playwright Chromium is unavailable",
)
def test_real_chromium_renders_complete_editorial_carousel(
    tmp_path, visual_plan, storyboard, asset_manifest
):
    from src.rendering.editorial.renderer import render_carousel

    manifest = render_carousel(visual_plan, storyboard, asset_manifest, tmp_path)

    assert len(manifest.pages) == 5
    assert manifest.fonts.all_loaded is True
    assert set(manifest.fonts.computed_families) == {
        "Source Han Serif SC",
        "Source Han Sans SC",
        "Bodoni Moda",
    }
    for rendered_page in manifest.pages:
        page_path = Path(rendered_page.path)
        assert page_path.is_file()
        assert _png_dimensions(page_path) == (1080, 1440)
    contact_sheet = Path(manifest.contact_sheet_path)
    assert contact_sheet.is_file()
    assert _png_dimensions(contact_sheet)[0] > 0
    assert not list(tmp_path.glob("*.html"))
