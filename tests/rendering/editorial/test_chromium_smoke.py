from __future__ import annotations

import struct
from pathlib import Path
from typing import get_args

import pytest

from src.schemas.assets import LayoutName


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


@pytest.mark.skipif(
    not _local_chromium_available(),
    reason="local Playwright Chromium is unavailable",
)
@pytest.mark.parametrize("layout", get_args(LayoutName))
def test_real_chromium_keeps_dual_content_blocks_and_assets_in_disjoint_layout_space(
    layout,
    tmp_path,
):
    from playwright.sync_api import sync_playwright

    from conftest import make_asset, make_frame
    from src.rendering.editorial.layouts import LAYOUT_RENDERERS
    from src.rendering.editorial.probes import probe_fonts, probe_layout
    from src.rendering.editorial.renderer import _document_html

    frame = make_frame(layout, frame_id=f"geometry-{layout}").model_copy(
        update={"content_blocks": make_frame(layout).content_blocks[:2]}
    )
    asset = make_asset(layout, slot_id=f"geometry-{layout}-visual")
    document_path = tmp_path / f"{layout}.html"
    screenshot_path = tmp_path / f"{layout}.png"
    document_path.write_text(
        _document_html(LAYOUT_RENDERERS[layout](frame, [asset])),
        encoding="utf-8",
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1080, "height": 1440})
            page.goto(document_path.as_uri(), wait_until="load")
            probe_fonts(page)
            report = probe_layout(page)
            page.locator(".card").screenshot(path=str(screenshot_path))
            overlaps = page.evaluate(
                """
                () => {
                  const rects = selector => [...document.querySelectorAll(selector)]
                    .map(element => element.getBoundingClientRect())
                    .filter(rect => rect.width > 0 && rect.height > 0);
                  const blocks = rects('.layout-body .content-block');
                  const assets = rects('.layout-body img[data-asset-slot]');
                  return blocks.flatMap((block, blockIndex) =>
                    assets.flatMap((asset, assetIndex) => {
                      const width = Math.max(0, Math.min(block.right, asset.right) - Math.max(block.left, asset.left));
                      const height = Math.max(0, Math.min(block.bottom, asset.bottom) - Math.max(block.top, asset.top));
                      return width * height > 0.5 ? [{blockIndex, assetIndex, area: width * height}] : [];
                    })
                  );
                }
                """
            )
            gallery_position = page.locator(".asset-gallery").evaluate(
                "element => getComputedStyle(element).position"
            )
            if layout == "morning_evening_flow":
                side_counts = page.locator(".flow-panel").evaluate_all(
                    "elements => elements.map(element => element.querySelectorAll('.content-block').length)"
                )
            elif layout == "left_right_comparison":
                side_counts = page.locator(".comparison-panel").evaluate_all(
                    "elements => elements.map(element => element.querySelectorAll('.content-block').length)"
                )
            else:
                side_counts = None
        finally:
            browser.close()

    assert report["issues"] == []
    assert len(report["texts"]) > 0
    assert len(report["assets"]) == 1
    assert overlaps == []
    assert screenshot_path.is_file()
    if layout in {"morning_evening_flow", "left_right_comparison"}:
        assert gallery_position != "absolute"
        assert side_counts == [1, 1]
