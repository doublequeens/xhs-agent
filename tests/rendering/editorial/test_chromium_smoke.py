from __future__ import annotations

import struct
from pathlib import Path
from typing import get_args

import pytest

from src.schemas.editorial_templates import TemplateFamily


ALL_TEMPLATE_FAMILIES = get_args(TemplateFamily)


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
    from src.rendering.editorial.probes import expected_font_families
    from src.rendering.editorial.renderer import render_carousel

    manifest = render_carousel(visual_plan, storyboard, asset_manifest, tmp_path)

    assert len(manifest.pages) == 5
    assert manifest.fonts.all_loaded is True
    assert set(manifest.fonts.computed_families) == set(
        expected_font_families(visual_plan.template_family)
    )
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
@pytest.mark.parametrize("family", ALL_TEMPLATE_FAMILIES)
def test_real_chromium_renders_each_family_with_disjoint_copy_and_asset_space(
    family,
    tmp_path,
):
    from playwright.sync_api import sync_playwright

    from conftest import make_asset, make_frame
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.probes import (
        expected_font_families,
        probe_fonts,
        probe_layout,
    )
    from src.rendering.editorial.renderer import _document_html
    from src.rendering.editorial.variant_resolver import resolve_variant

    archetype = "explanation"
    frame = make_frame(archetype, frame_id=f"smoke-{family}").model_copy(
        update={"content_blocks": make_frame(archetype).content_blocks[:2]}
    )
    asset = make_asset(archetype, slot_id=f"{frame.frame_id}-visual")
    variant = resolve_variant(
        family,
        archetype,
        "auto",
        measure_frame_copy(frame),
    )
    document_path = tmp_path / f"{family}.html"
    screenshot_path = tmp_path / f"{family}.png"
    document_path.write_text(
        _document_html(
            TEMPLATE_RENDERERS[family](frame, [asset], variant),
            family,
        ),
        encoding="utf-8",
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1080, "height": 1440})
            page.goto(document_path.as_uri(), wait_until="load")
            font_report = probe_fonts(page)
            report = probe_layout(page)
            page.locator(".card").screenshot(path=str(screenshot_path))
            overlaps = page.evaluate(
                """
                () => {
                  const rects = selector => [...document.querySelectorAll(selector)]
                    .map(element => element.getBoundingClientRect())
                    .filter(rect => rect.width > 0 && rect.height > 0);
                  const blocks = rects('.template-body .content-block');
                  const assets = rects('.template-body img[data-asset-slot]');
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
        finally:
            browser.close()

    assert font_report["all_loaded"] is True
    assert set(font_report["computed_families"]) == set(
        expected_font_families(family)
    )
    assert report["issues"] == []
    assert len(report["texts"]) > 0
    assert len(report["assets"]) == 1
    assert overlaps == []
    assert screenshot_path.is_file()


@pytest.mark.skipif(
    not _local_chromium_available(),
    reason="local Playwright Chromium is unavailable",
)
def test_real_chromium_renders_emoji_without_tofu_or_text_drift(
    tmp_path, visual_plan, storyboard, asset_manifest
):
    from src.rendering.editorial.probes import expected_font_families
    from src.rendering.editorial.renderer import render_carousel

    emoji_headline = "防晒成膜后再上妆✨👩‍🔬"
    emoji_storyboard = storyboard.model_copy(
        update={
            "storyboards": [
                storyboard.storyboards[0].model_copy(
                    update={"headline": emoji_headline}
                ),
                *storyboard.storyboards[1:],
            ]
        }
    )
    manifest = render_carousel(
        visual_plan, emoji_storyboard, asset_manifest, tmp_path
    )

    assert manifest.fonts.all_loaded is True
    assert set(manifest.fonts.computed_families) == set(
        expected_font_families(visual_plan.template_family)
    )
    probe = manifest.pages[0].probe
    headlines = [
        item.text for item in probe.text_results if item.role == "headline"
    ]
    assert headlines == [emoji_headline]
    assert not any(
        "missing_glyph" in issue or "missing-glyph" in issue
        for issue in probe.issues
    )
