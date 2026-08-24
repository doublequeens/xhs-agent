"""Real local-Chromium coverage for the strict v4 browser probe."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from src.rendering.scene.probes import V4_PROBE_SCRIPT
from src.visual_design.v4.typography import resolve_font_file_v4


def _local_chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            return Path(playwright.chromium.executable_path).is_file()
    except Exception:
        return False


@pytest.mark.skipif(
    not _local_chromium_available(),
    reason="local Playwright Chromium is unavailable",
)
def test_real_chromium_v4_probe_uses_valid_exact_face_font_shorthands():
    """Exercise the explicit v4 script and its primary/fallback/tofu witnesses."""

    from playwright.sync_api import sync_playwright

    exact_text = "美"
    font = resolve_font_file_v4("pink_red", "body")
    encoded_font = base64.b64encode(font.path.read_bytes()).decode("ascii")
    html = f"""
    <!doctype html>
    <meta charset="utf-8">
    <style>
      @font-face {{
        font-family: "{font.family_name}";
        src: url("data:font/ttf;base64,{encoded_font}") format("truetype");
        font-style: normal;
        font-weight: {font.nominal_weight};
      }}
      .scene-text {{
        position: absolute;
        left: 16px;
        top: 16px;
        width: 240px;
        height: 96px;
        font-family: "{font.family_name}";
        font-size: 48px;
        font-weight: {font.nominal_weight};
        line-height: 1.25;
      }}
    </style>
    <div class="scene-text"
         data-element-id="text-1"
         data-content-ref="fragment-1"
         data-font-family="{font.family_name}">{exact_text}</div>
    <div class="scene-text"
         data-element-id="text-missing-face"
         data-content-ref="fragment-missing-face"
         data-font-family="__v4_missing_declared_face__">{exact_text}</div>
    """

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 320, "height": 160})
            page.set_content(html, wait_until="load")
            page.evaluate(
                """
                (() => {
                  globalThis.__v4FontCalls = { canvas: [], checks: [] };
                  const proto = CanvasRenderingContext2D.prototype;
                  const descriptor = Object.getOwnPropertyDescriptor(proto, 'font');
                  Object.defineProperty(proto, 'font', {
                    configurable: descriptor.configurable,
                    enumerable: descriptor.enumerable,
                    get: descriptor.get,
                    set(value) {
                      const text = String(value);
                      globalThis.__v4FontCalls.canvas.push({
                        value: text,
                        valid: CSS.supports('font', text)
                      });
                      return descriptor.set.call(this, value);
                    }
                  });
                  const fontSet = document.fonts;
                  const originalCheck = fontSet.check.bind(fontSet);
                  Object.defineProperty(fontSet, 'check', {
                    configurable: true,
                    value(fontSpec, text) {
                      const value = String(fontSpec);
                      globalThis.__v4FontCalls.checks.push({
                        value,
                        valid: CSS.supports('font', value)
                      });
                      return originalCheck(fontSpec, text);
                    }
                  });
                })()
                """
            )

            probes = page.evaluate(V4_PROBE_SCRIPT)
            calls = page.evaluate("globalThis.__v4FontCalls")
        finally:
            browser.close()

    assert len(probes) == 2
    probe = next(item for item in probes if item["element_id"] == "text-1")
    assert isinstance(probe["font_loaded"], bool)
    assert probe["font_loaded"] is True
    assert probe["dom_text_measured"] is True
    assert probe["actual_text"] == exact_text
    assert probe["document_fonts_status"] == "loaded"

    assert len(probe["glyph_coverage"]) == 1
    glyph = probe["glyph_coverage"][0]
    diagnostics = {
        "geometry": {"width": glyph["width"], "height": glyph["height"]},
        "primary": {
            "ink": glyph["ink_pixel_count"],
            "sha256": glyph["raster_signature"],
        },
        "fallback": {
            "ink": glyph["fallback_ink_pixel_count"],
            "sha256": glyph["fallback_raster_signature"],
        },
        "tofu": {
            "ink": glyph["tofu_ink_pixel_count"],
            "sha256": glyph["tofu_raster_signature"],
        },
        "font_calls": calls,
    }
    assert isinstance(glyph["face_loaded"], bool)
    assert isinstance(glyph["font_check"], bool)
    assert glyph["face_loaded"] is True
    assert glyph["font_check"] is True
    assert glyph["visible"] is True, diagnostics
    assert glyph["ink_pixel_count"] > 0
    assert glyph["fallback_ink_pixel_count"] > 0
    assert glyph["tofu_ink_pixel_count"] > 0
    signatures = {
        glyph["raster_signature"],
        glyph["fallback_raster_signature"],
        glyph["tofu_raster_signature"],
    }
    assert len(signatures) == 3
    assert "0" * 64 not in signatures

    emitted = [*calls["canvas"], *calls["checks"]]
    assert calls["canvas"] and calls["checks"]
    assert all(item["valid"] for item in emitted)
    assert all("pxpx" not in item["value"] for item in emitted)
    assert all(item["value"].count("px") == 1 for item in emitted)

    missing_face = next(
        item for item in probes if item["element_id"] == "text-missing-face"
    )
    missing_glyph = missing_face["glyph_coverage"][0]
    assert missing_face["dom_text_measured"] is True
    assert missing_face["actual_text"] == exact_text
    assert missing_face["font_loaded"] is False
    assert missing_glyph["face_loaded"] is False
    assert missing_glyph["font_check"] is False
    assert missing_glyph["visible"] is False
