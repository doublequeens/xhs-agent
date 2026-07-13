from __future__ import annotations

from pathlib import Path

import pytest


def _local_chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            return Path(playwright.chromium.executable_path).is_file()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _local_chromium_available(),
    reason="local Playwright Chromium is unavailable",
)


def test_probe_detects_text_range_clipped_by_an_overflow_ancestor():
    from playwright.sync_api import sync_playwright

    from src.rendering.editorial.probes import probe_layout

    html = """
    <style>
      * { box-sizing: border-box; }
      html, body { margin: 0; width: 1080px; height: 1440px; }
      .card { width: 1080px; height: 1440px; }
      .layout-body { width: 900px; height: 300px; overflow: hidden; }
      .clip { width: 500px; height: 28px; overflow: hidden; }
      .copy { display: inline-block; font-size: 64px; line-height: 1; }
    </style>
    <main class="card" data-layout="editorial_cover" data-frame-role="cover">
      <section class="layout-body">
        <div class="clip"><span class="copy" data-card-copy data-copy-role="body">护肤判断</span></div>
      </section>
    </main>
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1080, "height": 1440})
            page.set_content(html, wait_until="load")
            report = probe_layout(page)
        finally:
            browser.close()

    assert any(
        issue["kind"] == "ink_clip" and issue["role"] == "body"
        for issue in report["issues"]
    )


def test_probe_persists_exact_visible_text_typography_and_asset_geometry(tmp_path):
    from playwright.sync_api import sync_playwright

    from conftest import make_asset, make_frame
    from src.rendering.editorial.layouts import LAYOUT_RENDERERS
    from src.rendering.editorial.probes import probe_fonts, probe_layout
    from src.rendering.editorial.renderer import _document_html

    frame = make_frame("editorial_cover", frame_id="cover", role="cover")
    document = _document_html(
        LAYOUT_RENDERERS["editorial_cover"](
            frame,
            [make_asset("editorial_cover", slot_id="cover-visual")],
        )
    )
    path = tmp_path / "probe-attestation.html"
    path.write_text(document, encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1080, "height": 1440})
            page.goto(path.as_uri(), wait_until="load")
            probe_fonts(page)
            report = probe_layout(page)
        finally:
            browser.close()

    assert report["canvas"] == {"width": 1080, "height": 1440}
    headline = next(item for item in report["texts"] if item["role"] == "headline")
    assert headline["text"] == frame.headline
    assert headline["font_family"] == "Source Han Serif SC"
    assert headline["font_size"] > 0
    assert headline["line_count"] in {1, 2}
    asset = next(item for item in report["assets"] if item["slot_id"] == "cover-visual")
    assert asset["natural_width"] > 0
    assert asset["rendered_width"] > 0
    assert asset["object_fit"] == "contain"


def test_probe_allows_normal_source_han_vertical_metric_overhang(tmp_path):
    from playwright.sync_api import sync_playwright

    from conftest import make_asset, make_frame
    from src.rendering.editorial.layouts import LAYOUT_RENDERERS
    from src.rendering.editorial.probes import probe_fonts, probe_layout
    from src.rendering.editorial.renderer import _document_html

    frame = make_frame("editorial_cover", frame_id="cover", role="cover")
    document = _document_html(
        LAYOUT_RENDERERS["editorial_cover"](
            frame,
            [make_asset("editorial_cover", slot_id="cover-visual")],
        )
    )
    document_path = tmp_path / "source-han-overhang.html"
    document_path.write_text(document, encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1080, "height": 1440})
            page.goto(document_path.as_uri(), wait_until="load")
            probe_fonts(page)
            metrics = page.locator(".headline").evaluate(
                "element => ({clientHeight: element.clientHeight, scrollHeight: element.scrollHeight})"
            )
            report = probe_layout(page)
        finally:
            browser.close()

    assert metrics["scrollHeight"] > metrics["clientHeight"]
    assert not any(issue["kind"] == "ink_clip" for issue in report["issues"])


def test_probe_rejects_body_line_height_outside_the_hard_range():
    from playwright.sync_api import sync_playwright

    from src.rendering.editorial.probes import probe_layout

    html = """
    <style>
      * { box-sizing: border-box; }
      html, body { margin: 0; width: 1080px; height: 1440px; }
      .card { width: 1080px; height: 1440px; }
      .layout-body { width: 900px; height: 800px; overflow: hidden; }
      .block-body { font-size: 30px; line-height: 1.6; }
    </style>
    <main class="card" data-layout="editorial_cover" data-frame-role="cover">
      <section class="layout-body">
        <p class="block-body" data-card-copy data-copy-role="body">正文行高必须受控</p>
      </section>
    </main>
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1080, "height": 1440})
            page.set_content(html, wait_until="load")
            report = probe_layout(page)
        finally:
            browser.close()

    assert any(
        issue["kind"] == "body_line_height" for issue in report["issues"]
    )


def test_rendered_body_copy_uses_line_height_between_1_4_and_1_5(tmp_path):
    from playwright.sync_api import sync_playwright

    from conftest import make_asset, make_frame
    from src.rendering.editorial.layouts import LAYOUT_RENDERERS
    from src.rendering.editorial.probes import probe_fonts
    from src.rendering.editorial.renderer import _document_html

    frame = make_frame("editorial_cover", frame_id="cover", role="cover")
    document = _document_html(
        LAYOUT_RENDERERS["editorial_cover"](
            frame,
            [make_asset("editorial_cover", slot_id="cover-visual")],
        )
    )
    document_path = tmp_path / "body-line-height.html"
    document_path.write_text(document, encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1080, "height": 1440})
            page.goto(document_path.as_uri(), wait_until="load")
            probe_fonts(page)
            ratios = page.locator(".block-body, .item-copy").evaluate_all(
                "elements => elements.map(element => { const style = getComputedStyle(element); return parseFloat(style.lineHeight) / parseFloat(style.fontSize); })"
            )
        finally:
            browser.close()

    assert ratios
    assert all(1.4 <= ratio <= 1.5 for ratio in ratios)


def test_probe_rejects_a_headline_that_wraps_to_more_than_two_lines(tmp_path):
    from playwright.sync_api import sync_playwright

    from conftest import make_asset, make_frame
    from src.rendering.editorial.layouts import LAYOUT_RENDERERS
    from src.rendering.editorial.probes import probe_fonts, probe_layout
    from src.rendering.editorial.renderer import _document_html

    frame = make_frame("editorial_cover", frame_id="cover", role="cover").model_copy(
        update={"headline": "分区护理判断标准" * 8}
    )
    document = _document_html(
        LAYOUT_RENDERERS["editorial_cover"](
            frame,
            [make_asset("editorial_cover", slot_id="cover-visual")],
        )
    )
    document_path = tmp_path / "three-line-headline.html"
    document_path.write_text(document, encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1080, "height": 1440})
            page.goto(document_path.as_uri(), wait_until="load")
            probe_fonts(page)
            report = probe_layout(page)
        finally:
            browser.close()

    assert any(
        issue["kind"] == "headline_lines" and issue["lines"] > 2
        for issue in report["issues"]
    )
