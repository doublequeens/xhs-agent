"""Generic scene DOM probes (Task 11).

This module contains the single in-page JavaScript evaluation script that
reads ONLY generated ``data-*`` attributes and computed layout (no arbitrary
DOM, no network, no state mutation), plus the pure Python side that maps the
raw JS return value into validated :class:`RenderedElementProbe` instances —
one per planned ``data-element-id``.

Design contract (do not violate):

* **One probe per planned element.** Probes are emitted in
  ``(layer, source order)`` (the same order the compiler emits HTML), matched
  to the scene by ``element_id``. A planned element missing from the raw probe
  return is a hard error.
* **No browser dependency.** :func:`build_element_probes` is a pure function.
  It never imports Playwright and never opens a page — the renderer hands it
  the raw dict the browser returned.
* **Hash-bound attestations.** Text probes bind ``rasterized_text_sha256`` to
  the resolved fragment's UTF-8 bytes; image probes bind
  ``rendered_asset_sha256`` to the actual asset file bytes on disk.
* **Honest geometry.** ``overflow`` / ``ink_clipped`` / ``layout_clipped`` are
  derived from the measured rect and scroll/client dimensions, never echoed
  from the plan.

The JavaScript baseline (the ``data-*`` + computed-layout reader from the
Task 11 brief) is extended minimally with computed ``lineHeight`` and the
``<img>`` element's intrinsic ``naturalWidth`` / ``naturalHeight`` plus its
rendered rect, because :class:`RenderedElementProbe`'s kind attestation
requires line-height for text probes and natural/rendered dimensions for image
probes. These additions are still computed style / intrinsic image geometry —
they do NOT read arbitrary DOM text, attributes, or network state.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Final

from src.schemas.assets import AssetManifestItem
from src.schemas.content_atoms import ContentFragment, sha256_text
from src.schemas.render_manifest import RenderedElementProbe
from src.schemas.scene_graph import (
    Box,
    ImageElement,
    PageScene,
    SceneElement,
    ShapeElement,
    TextElement,
)

CANVAS_WIDTH: Final[int] = 1080
CANVAS_HEIGHT: Final[int] = 1440

# Sub-pixel tolerance. Browsers report fractional pixels; a tolerance of ~1px
# keeps the overflow / clip flags stable against rounding noise.
_EPS: Final[float] = 1.0
# Smallest non-zero dimension we ever store in a Box (Box requires width/height
# strictly greater than zero).
_BOX_MIN: Final[float] = 1e-3


# ---------------------------------------------------------------------------
# The v3 in-page evaluation script. Keep this byte-for-byte compatible with
# the generic renderer's established browser contract. v4's stricter
# observation contract is opt-in below and must never change v3 consumers.
# ---------------------------------------------------------------------------

PROBE_SCRIPT = r"""
(() => {
  const nodes = document.querySelectorAll('[data-element-id]');
  return Array.from(nodes).map((node) => {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    const inner = node.querySelector('img.scene-image-inner');
    const innerRect = inner ? inner.getBoundingClientRect() : null;
    // Per CSS line-box rectangles (text probes). For text nodes getClientRects
    // yields one rect per wrapped line; for other nodes it yields the border
    // box(es). Read geometry only.
    const lineRects = Array.from(node.getClientRects()).map((r) => ({
      x: r.x, y: r.y, width: r.width, height: r.height
    }));
    return {
      element_id: node.dataset.elementId,
      content_ref: node.dataset.contentRef || null,
      asset_ref: node.dataset.assetRef || null,
      x: rect.x,
      y: rect.y,
      width: rect.width,
      height: rect.height,
      scroll_width: node.scrollWidth,
      scroll_height: node.scrollHeight,
      client_width: node.clientWidth,
      client_height: node.clientHeight,
      font_family: style.fontFamily,
      font_size: parseFloat(style.fontSize),
      line_height: parseFloat(style.lineHeight),
      color: style.color,
      background_color: style.backgroundColor,
      natural_width: inner ? inner.naturalWidth : null,
      natural_height: inner ? inner.naturalHeight : null,
      rendered_image_width: innerRect ? innerRect.width : null,
      rendered_image_height: innerRect ? innerRect.height : null,
      line_boxes: lineRects
    };
  });
})();
"""


# Strict browser evidence for the hash-bound v4 adapter. This is intentionally
# a separate script so the v3 generic renderer keeps its historical probe
# timing and geometry behavior. Geometry alone is not glyph evidence: v4 also
# checks the exact face, FontFaceSet coverage, and raster pixels for each
# grapheme, retaining false measurements for Q3 instead of inventing success.
V4_PROBE_SCRIPT = r"""
(async () => {
  await document.fonts.ready;
  const rectPayload = (r) => ({
    x: r.x, y: r.y, width: r.width, height: r.height
  });
  const normalize = (value) => String(value || '').trim().replace(/^['"]|['"]$/g, '');
  const sha256Fallback = (pixels) => {
    const rotateRight = (value, amount) =>
      (value >>> amount) | (value << (32 - amount));
    const constants = new Uint32Array([
      0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
      0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
      0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
      0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
      0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
      0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
      0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
      0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
      0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
      0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
      0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
      0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
      0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
      0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
      0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
      0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
    ]);
    const state = new Uint32Array([
      0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
      0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
    ]);
    const bytes = new Uint8Array(pixels);
    const bitLength = bytes.length * 8;
    const wordCount = Math.ceil((bytes.length + 9) / 64) * 16;
    const words = new Uint32Array(wordCount);
    for (let index = 0; index < bytes.length; index += 1) {
      words[index >>> 2] |= bytes[index] << (24 - (index % 4) * 8);
    }
    words[bytes.length >>> 2] |= 0x80 << (24 - (bytes.length % 4) * 8);
    words[wordCount - 2] = Math.floor(bitLength / 0x100000000);
    words[wordCount - 1] = bitLength >>> 0;
    const schedule = new Uint32Array(64);
    for (let offset = 0; offset < words.length; offset += 16) {
      schedule.set(words.subarray(offset, offset + 16));
      for (let index = 16; index < 64; index += 1) {
        const value15 = schedule[index - 15];
        const value2 = schedule[index - 2];
        const sigma0 = rotateRight(value15, 7)
          ^ rotateRight(value15, 18) ^ (value15 >>> 3);
        const sigma1 = rotateRight(value2, 17)
          ^ rotateRight(value2, 19) ^ (value2 >>> 10);
        schedule[index] = (
          schedule[index - 16] + sigma0 + schedule[index - 7] + sigma1
        ) >>> 0;
      }
      let [a, b, c, d, e, f, g, h] = state;
      for (let index = 0; index < 64; index += 1) {
        const sum1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
        const choice = (e & f) ^ (~e & g);
        const temp1 = (h + sum1 + choice + constants[index] + schedule[index]) >>> 0;
        const sum0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
        const majority = (a & b) ^ (a & c) ^ (b & c);
        const temp2 = (sum0 + majority) >>> 0;
        h = g;
        g = f;
        f = e;
        e = (d + temp1) >>> 0;
        d = c;
        c = b;
        b = a;
        a = (temp1 + temp2) >>> 0;
      }
      state[0] = (state[0] + a) >>> 0;
      state[1] = (state[1] + b) >>> 0;
      state[2] = (state[2] + c) >>> 0;
      state[3] = (state[3] + d) >>> 0;
      state[4] = (state[4] + e) >>> 0;
      state[5] = (state[5] + f) >>> 0;
      state[6] = (state[6] + g) >>> 0;
      state[7] = (state[7] + h) >>> 0;
    }
    return Array.from(state)
      .map((value) => value.toString(16).padStart(8, '0')).join('');
  };
  const digestPixels = async (pixels) => {
    const bytes = new Uint8Array(pixels);
    if (globalThis.crypto && globalThis.crypto.subtle) {
      try {
        const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
        return Array.from(new Uint8Array(digest))
          .map((value) => value.toString(16).padStart(2, '0')).join('');
      } catch (_error) {
        // Opaque local documents may expose crypto without SubtleCrypto access.
      }
    }
    return sha256Fallback(bytes);
  };
  const fontShorthand = (style, family) => {
    const quotedFamily = `"${String(family).replaceAll('"', '\\"')}"`;
    return `${style.fontWeight} ${style.fontSize} ${quotedFamily}`;
  };
  const rasterEvidence = async (text, style, family) => {
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('2d', { willReadFrequently: true });
    if (!context) return { ink_pixel_count: 0, raster_signature: '0'.repeat(64) };
    const font = fontShorthand(style, family);
    context.font = font;
    const measured = context.measureText(text);
    canvas.width = Math.max(32, Math.ceil(measured.width) + 8);
    canvas.height = Math.max(32, Math.ceil(parseFloat(style.fontSize) * 2.0));
    context.font = font;
    context.fillStyle = '#000000';
    context.textBaseline = 'top';
    context.fillText(text, 2, 2);
    const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
    let inkPixelCount = 0;
    for (let index = 3; index < data.length; index += 4) {
      if (data[index] > 0) inkPixelCount += 1;
    }
    return {
      ink_pixel_count: inkPixelCount,
      raster_signature: inkPixelCount ? await digestPixels(data) : '0'.repeat(64)
    };
  };
  const exactFaceLoaded = (node, style, primaryFamily) => {
    if (!primaryFamily || document.fonts.status !== 'loaded') return false;
    const computed = normalize((style.fontFamily || '').split(',')[0]);
    if (computed !== primaryFamily) return false;
    return Array.from(document.fonts).some((face) => {
      const weight = face.weight === 'normal' ? '400' : face.weight;
      return normalize(face.family) === primaryFamily
        && weight === String(style.fontWeight)
        && face.status === 'loaded';
    });
  };
  const isWhitespace = (value) => /^\s+$/u.test(value);
  const graphemes = (text) => {
    if (typeof Intl !== 'undefined' && Intl.Segmenter) {
      return Array.from(new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(text));
    }
    const result = [];
    let offset = 0;
    for (const segment of Array.from(text)) {
      result.push({ segment, index: offset });
      offset += segment.length;
    }
    return result;
  };
  const glyphCoverage = async (node, style, primaryFamily, exactFace) => {
    const text = node.textContent || '';
    if (!text) return [];
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    const textNodes = [];
    let current;
    while ((current = walker.nextNode())) textNodes.push(current);
    const offsets = [];
    let cursor = 0;
    for (const textNode of textNodes) {
      offsets.push({ node: textNode, start: cursor, end: cursor + textNode.data.length });
      cursor += textNode.data.length;
    }
    return Promise.all(graphemes(text).map(async (part) => {
      const start = part.index;
      const end = start + part.segment.length;
      const first = offsets.find((item) => start >= item.start && start < item.end);
      const last = offsets.find((item) => end > item.start && end <= item.end);
      const range = first && last ? document.createRange() : null;
      if (!range) {
        return {
          visible: false, width: 0, height: 0, face_loaded: false,
          font_check: false, ink_pixel_count: 0, raster_signature: '0'.repeat(64),
          fallback_ink_pixel_count: 0,
          fallback_raster_signature: '0'.repeat(64),
          tofu_ink_pixel_count: 0,
          tofu_raster_signature: '0'.repeat(64),
          is_whitespace: isWhitespace(part.segment)
        };
      }
      range.setStart(first.node, start - first.start);
      range.setEnd(last.node, end - last.start);
      const rects = Array.from(range.getClientRects());
      const visible = rects.some((rect) => rect.width > 0 && rect.height > 0);
      const whitespace = isWhitespace(part.segment);
      const fontSpec = fontShorthand(style, primaryFamily);
      const fontCheck = !whitespace
        && exactFace
        && document.fonts.check(fontSpec, part.segment);
      const primaryRaster = whitespace
        ? { ink_pixel_count: 0, raster_signature: '0'.repeat(64) }
        : await rasterEvidence(part.segment, style, primaryFamily);
      const fallbackRaster = whitespace
        ? { ink_pixel_count: 0, raster_signature: '0'.repeat(64) }
        : await rasterEvidence(part.segment, style, '__v4_missing_primary_face__');
      const tofuRaster = whitespace
        ? { ink_pixel_count: 0, raster_signature: '0'.repeat(64) }
        : await rasterEvidence('\uFFFD', style, primaryFamily);
      const distinctRaster = new Set([
        primaryRaster.raster_signature,
        fallbackRaster.raster_signature,
        tofuRaster.raster_signature
      ]).size === 3;
      return {
        visible: !whitespace && visible && fontCheck
          && primaryRaster.ink_pixel_count > 0
          && fallbackRaster.ink_pixel_count > 0
          && tofuRaster.ink_pixel_count > 0
          && primaryRaster.raster_signature !== '0'.repeat(64)
          && distinctRaster,
        width: rects.reduce((total, rect) => total + rect.width, 0),
        height: rects.reduce((maximum, rect) => Math.max(maximum, rect.height), 0),
        face_loaded: exactFace,
        font_check: fontCheck,
        ink_pixel_count: primaryRaster.ink_pixel_count,
        raster_signature: primaryRaster.raster_signature,
        fallback_ink_pixel_count: fallbackRaster.ink_pixel_count,
        fallback_raster_signature: fallbackRaster.raster_signature,
        tofu_ink_pixel_count: tofuRaster.ink_pixel_count,
        tofu_raster_signature: tofuRaster.raster_signature,
        is_whitespace: whitespace
      };
    }));
  };
  const nodes = document.querySelectorAll('[data-element-id]');
  return Promise.all(Array.from(nodes).map(async (node) => {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    const inner = node.querySelector('img.scene-image-inner');
    const innerRect = inner ? inner.getBoundingClientRect() : null;
    const isText = node.classList.contains('scene-text');
    const primaryFamily = normalize(node.getAttribute('data-font-family'));
    const exactFace = isText && exactFaceLoaded(node, style, primaryFamily);
    const coverage = isText
      ? await glyphCoverage(node, style, primaryFamily, exactFace)
      : null;
    const nonWhitespace = isText
      ? coverage.filter((item) => !item.is_whitespace)
      : [];
    const range = document.createRange();
    if (isText) range.selectNodeContents(node);
    return {
      element_id: node.dataset.elementId,
      content_ref: node.dataset.contentRef || null,
      asset_ref: node.dataset.assetRef || null,
      x: rect.x, y: rect.y, width: rect.width, height: rect.height,
      scroll_width: node.scrollWidth, scroll_height: node.scrollHeight,
      client_width: node.clientWidth, client_height: node.clientHeight,
      font_family: style.fontFamily,
      font_size: parseFloat(style.fontSize),
      line_height: parseFloat(style.lineHeight),
      font_weight: parseInt(style.fontWeight, 10),
      color: style.color, background_color: style.backgroundColor,
      natural_width: inner ? inner.naturalWidth : null,
      natural_height: inner ? inner.naturalHeight : null,
      rendered_image_width: innerRect ? innerRect.width : null,
      rendered_image_height: innerRect ? innerRect.height : null,
      actual_text: isText ? node.textContent : null,
      dom_text_measured: isText,
      font_loaded: isText ? exactFace : null,
      document_fonts_status: document.fonts.status,
      glyph_visible: isText
        ? nonWhitespace.length > 0 && nonWhitespace.every((item) => item.visible)
        : null,
      missing_codepoint_count: isText
        ? nonWhitespace.filter((item) => !item.visible).length
        : null,
      glyph_coverage: coverage,
      asset_loaded: inner ? Boolean(inner.complete && inner.naturalWidth > 0) : null,
      line_boxes: isText ? Array.from(range.getClientRects()).map(rectPayload) : []
    };
  }));
})();
"""


# ---------------------------------------------------------------------------
# Color parsing + WCAG contrast (self-contained; no cross-module import)
# ---------------------------------------------------------------------------


class ProbeBuildError(ValueError):
    """Raised when raw probe data cannot be mapped to a valid probe."""


_RGB_RE: Final[re.Pattern[str]] = re.compile(
    r"^rgba?\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*(?:,\s*([0-9.]+)\s*)?\)$"
)
_HEX_RE: Final[re.Pattern[str]] = re.compile(r"^#([0-9a-fA-F]{6})$")


def _parse_color(value: str) -> tuple[int, int, int, float]:
    """Parse a CSS color into ``(r, g, b, alpha)`` with channels in 0..255.

    Supports ``rgb()``, ``rgba()`` and ``#RRGGBB``. Any unrecognized value
    (including ``transparent``) is treated as fully transparent black so the
    caller can fall back to the page background.
    """
    if not isinstance(value, str):
        return (0, 0, 0, 0.0)
    text = value.strip()
    hex_match = _HEX_RE.match(text)
    if hex_match is not None:
        digits = hex_match.group(1)
        return (
            int(digits[0:2], 16),
            int(digits[2:4], 16),
            int(digits[4:6], 16),
            1.0,
        )
    rgb_match = _RGB_RE.match(text)
    if rgb_match is not None:
        r, g, b = (int(round(float(rgb_match.group(i)))) for i in (1, 2, 3))
        raw_alpha = rgb_match.group(4)
        alpha = float(raw_alpha) if raw_alpha is not None else 1.0
        alpha = max(0.0, min(alpha, 1.0))
        return (r, g, b, alpha)
    return (0, 0, 0, 0.0)


def _blend_to_opaque(
    fg: tuple[int, int, int, float],
    bg: tuple[int, int, int, float],
) -> tuple[int, int, int]:
    """Alpha-composite ``fg`` over ``bg`` (both RGBA 4-tuples) to opaque RGB."""
    out_alpha = fg[3] + bg[3] * (1.0 - fg[3])
    if out_alpha <= 0.0:
        if bg[3] > 0.0:
            return (bg[0], bg[1], bg[2])
        return (255, 255, 255)
    channels = []
    for index in range(3):
        composited = (
            fg[index] * fg[3] + bg[index] * bg[3] * (1.0 - fg[3])
        ) / out_alpha
        channels.append(int(round(composited)))
    return (channels[0], channels[1], channels[2])


def _linearize(channel: int) -> float:
    normalized = channel / 255.0
    if normalized <= 0.03928:
        return normalized / 12.92
    return ((normalized + 0.055) / 1.055) ** 2.4


def _relative_luminance(color: tuple[int, int, int]) -> float:
    return (
        0.2126 * _linearize(color[0])
        + 0.7152 * _linearize(color[1])
        + 0.0722 * _linearize(color[2])
    )


def _contrast_ratio(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    fg_lum = _relative_luminance(fg)
    bg_lum = _relative_luminance(bg)
    lighter, darker = max(fg_lum, bg_lum), min(fg_lum, bg_lum)
    return (lighter + 0.05) / (darker + 0.05)


def _effective_contrast(
    raw_color: str,
    raw_background: str,
    page_background: str,
) -> float:
    """WCAG contrast between the effective foreground and background.

    Transparent colors (alpha < 1) are alpha-composited over the page
    background so the ratio reflects what a viewer actually sees.
    """
    page_bg = _parse_color(page_background)
    if page_bg[3] <= 0.0:
        # An unparseable/transparent page background falls back to opaque white.
        page_bg = (255, 255, 255, 1.0)
    fg = _blend_to_opaque(_parse_color(raw_color), page_bg)
    bg = _blend_to_opaque(_parse_color(raw_background), page_bg)
    ratio = _contrast_ratio(fg, bg)
    # Clamp into the schema's allowed range to absorb sub-pixel float drift.
    return max(0.0, min(ratio, 21.0))


def _boxes_intersect(a: Box, b: Box) -> bool:
    # Touching edges (<=) do not count as an overlap.
    return not (
        a.x + a.width <= b.x + _EPS
        or b.x + b.width <= a.x + _EPS
        or a.y + a.height <= b.y + _EPS
        or b.y + b.height <= a.y + _EPS
    )


def _effective_text_background(page: PageScene, text: TextElement) -> str:
    """The background a viewer actually sees behind ``text``.

    Text often sits on a shape/card element over the page background (e.g.
    light text on a dark header bar). Comparing the text color to the page
    background in that case is a false contrast failure, so pick the topmost
    shape painted *behind* the text (lower layer, overlapping box) and use its
    fill; fall back to the page background when nothing sits behind it. Mirrors
    ``plan_qa._effective_text_background`` so render QA and design QA agree on
    the same effective background.
    """
    behind = [
        shape
        for shape in page.elements
        if isinstance(shape, ShapeElement)
        and shape.layer < text.layer
        and _boxes_intersect(shape.box, text.box)
    ]
    if not behind:
        return page.background
    return max(behind, key=lambda shape: shape.layer).fill


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _clamp_box(
    x: float, y: float, width: float, height: float
) -> Box:
    safe_x = min(max(float(x), 0.0), float(CANVAS_WIDTH))
    safe_y = min(max(float(y), 0.0), float(CANVAS_HEIGHT))
    safe_width = min(max(float(width), _BOX_MIN), float(CANVAS_WIDTH))
    safe_height = min(max(float(height), _BOX_MIN), float(CANVAS_HEIGHT))
    return Box(x=safe_x, y=safe_y, width=safe_width, height=safe_height)


def _optional_dim(raw: dict, key: str) -> float | None:
    """Return a non-negative raw measurement, preserving a legitimate 0.0."""
    value = raw.get(key)
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric >= 0 else None


def _line_boxes_from_raw(raw_boxes: object) -> tuple[Box, ...]:
    """Map raw JS line-box rects to validated ``Box`` instances.

    Degenerate rects (non-positive width/height) are dropped rather than
    clamped up, so the attestation reflects real painted line boxes only.
    """
    if not isinstance(raw_boxes, (list, tuple)):
        return ()
    boxes: list[Box] = []
    for item in raw_boxes:
        if not isinstance(item, dict):
            continue
        try:
            x = float(item.get("x"))
            y = float(item.get("y"))
            width = float(item.get("width"))
            height = float(item.get("height"))
        except (TypeError, ValueError):
            continue
        if width <= 0 or height <= 0:
            continue
        boxes.append(_clamp_box(x, y, width, height))
    return tuple(boxes)


def _visible_crop_box(x: float, y: float, width: float, height: float) -> Box:
    """Intersect the rect with the canvas to get the visible (cropped) box."""
    x0 = max(float(x), 0.0)
    y0 = max(float(y), 0.0)
    x1 = min(float(x) + float(width), float(CANVAS_WIDTH))
    y1 = min(float(y) + float(height), float(CANVAS_HEIGHT))
    crop_w = max(x1 - x0, _BOX_MIN)
    crop_h = max(y1 - y0, _BOX_MIN)
    return Box(
        x=min(x0, float(CANVAS_WIDTH)),
        y=min(y0, float(CANVAS_HEIGHT)),
        width=min(crop_w, float(CANVAS_WIDTH)),
        height=min(crop_h, float(CANVAS_HEIGHT)),
    )


def _is_off_canvas(x: float, y: float, width: float, height: float) -> bool:
    return (
        x < -_EPS
        or y < -_EPS
        or (x + width) > (CANVAS_WIDTH + _EPS)
        or (y + height) > (CANVAS_HEIGHT + _EPS)
    )


def _overflows(
    scroll_width: float,
    scroll_height: float,
    client_width: float,
    client_height: float,
) -> bool:
    return (
        scroll_width > client_width + _EPS
        or scroll_height > client_height + _EPS
    )


# ---------------------------------------------------------------------------
# Raw probe normalization
# ---------------------------------------------------------------------------


def _as_float(value, *, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_raw(raw: dict) -> dict:
    return {
        "element_id": raw.get("element_id"),
        "content_ref": raw.get("content_ref") or None,
        "asset_ref": raw.get("asset_ref") or None,
        "x": _as_float(raw.get("x")),
        "y": _as_float(raw.get("y")),
        "width": _as_float(raw.get("width")),
        "height": _as_float(raw.get("height")),
        "scroll_width": _as_float(raw.get("scroll_width")),
        "scroll_height": _as_float(raw.get("scroll_height")),
        "client_width": _as_float(raw.get("client_width")),
        "client_height": _as_float(raw.get("client_height")),
        "font_family": raw.get("font_family") if raw.get("font_family") else None,
        "font_size": _as_float(raw.get("font_size")),
        "line_height": _as_float(raw.get("line_height")),
        "color": raw.get("color") if isinstance(raw.get("color"), str) else "rgba(0,0,0,0)",
        "background_color": (
            raw.get("background_color")
            if isinstance(raw.get("background_color"), str)
            else "rgba(0,0,0,0)"
        ),
        "natural_width": raw.get("natural_width"),
        "natural_height": raw.get("natural_height"),
        "rendered_image_width": raw.get("rendered_image_width"),
        "rendered_image_height": raw.get("rendered_image_height"),
        "line_boxes": raw.get("line_boxes"),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_element_probes(
    *,
    raw_probes: list[dict],
    page: PageScene,
    fragments: Mapping[str, ContentFragment],
    assets: Mapping[str, AssetManifestItem],
    page_background: str,
) -> tuple[RenderedElementProbe, ...]:
    """Map raw in-page probe dicts into validated probes for one page.

    Iterates the page's elements in ``(layer, source order)`` — the same order
    the compiler emits HTML and the DOM exposes them — and emits one probe per
    planned element. Unknown stray probes (no matching scene element) are
    dropped; a planned element missing from ``raw_probes`` raises
    :class:`ProbeBuildError`.
    """
    raw_by_id: dict[str, dict] = {}
    for raw in raw_probes:
        normalized = _normalize_raw(raw if isinstance(raw, dict) else {})
        element_id = normalized.get("element_id")
        if isinstance(element_id, str) and element_id and element_id not in raw_by_id:
            raw_by_id[element_id] = normalized

    ordered_elements: list[SceneElement] = sorted(
        page.elements, key=lambda item: item.layer
    )
    probes: list[RenderedElementProbe] = []
    for element in ordered_elements:
        raw = raw_by_id.get(element.element_id)
        if raw is None:
            raise ProbeBuildError(
                f"probe data is missing for planned element: {element.element_id}"
            )
        probes.append(
            _build_one_probe(
                element=element,
                raw=raw,
                fragments=fragments,
                assets=assets,
                page=page,
                page_background=page_background,
            )
        )
    return tuple(probes)


def _build_one_probe(
    *,
    element: SceneElement,
    raw: dict,
    fragments: Mapping[str, ContentFragment],
    assets: Mapping[str, AssetManifestItem],
    page: PageScene,
    page_background: str,
) -> RenderedElementProbe:
    actual_box = _clamp_box(
        raw["x"], raw["y"], raw["width"], raw["height"]
    )
    # Icon glyphs are rendered with font metrics whose scroll dimensions can
    # exceed the box without any visible ink being lost (the glyph stays
    # centered and decorative). Treating that as overflow/ink-clipping is a
    # false positive that the reviser cannot fix, so icons never flag overflow.
    kind = getattr(element, "kind", None)
    if kind == "icon":
        overflow = False
    else:
        overflow = _overflows(
            raw["scroll_width"],
            raw["scroll_height"],
            raw["client_width"],
            raw["client_height"],
        )
    layout_clipped = _is_off_canvas(
        raw["x"], raw["y"], raw["width"], raw["height"]
    )
    # Ink is considered clipped whenever content overflows the element's own
    # client box or the element's box lies (partially) off-canvas, since the
    # scene page always clips at 1080x1440 and image containers clip at their
    # box. This is a conservative "visible ink was lost" signal.
    ink_clipped = bool(overflow or layout_clipped)
    # Text contrast is measured against the topmost shape painted behind the
    # text (or the page background when none), so a light-text-on-dark-panel
    # design is not falsely reported as low contrast against the page background.
    kind = getattr(element, "kind", None)
    effective_background = raw["background_color"]
    if kind == "text":
        effective_background = _effective_text_background(page, element)
    contrast = _effective_contrast(
        raw["color"], effective_background, page_background
    )

    if kind == "text":
        return _build_text_probe(
            element=element,
            raw=raw,
            actual_box=actual_box,
            overflow=overflow,
            ink_clipped=ink_clipped,
            layout_clipped=layout_clipped,
            contrast=contrast,
            fragments=fragments,
        )
    if kind == "image":
        return _build_image_probe(
            element=element,
            raw=raw,
            actual_box=actual_box,
            overflow=overflow,
            ink_clipped=ink_clipped,
            layout_clipped=layout_clipped,
            contrast=contrast,
            assets=assets,
        )
    return _build_shape_probe(
        element=element,
        actual_box=actual_box,
        overflow=overflow,
        ink_clipped=ink_clipped,
        layout_clipped=layout_clipped,
        contrast=contrast,
    )


def _build_text_probe(
    *,
    element: TextElement,
    raw: dict,
    actual_box: Box,
    overflow: bool,
    ink_clipped: bool,
    layout_clipped: bool,
    contrast: float,
    fragments: Mapping[str, ContentFragment],
) -> RenderedElementProbe:
    fragment = fragments.get(element.content_ref)
    if fragment is None:
        raise ProbeBuildError(
            f"text element {element.element_id} references unknown fragment "
            f"{element.content_ref!r}"
        )
    font_family = raw.get("font_family")
    if not font_family:
        raise ProbeBuildError(
            f"text probe for {element.element_id} is missing computed font family"
        )
    # The rasterized-text hash binds the probe to the UTF-8 bytes of the text
    # the compiler rendered (the fragment text). For a faithful scene this
    # equals the text the browser painted.
    rasterized_sha = sha256_text(fragment.text)
    # M3: guard the numeric fields with an explicit ``is not None`` check so a
    # legitimate ``0.0`` (e.g. a defensive default) is preserved instead of being
    # swallowed by ``or None`` and then failing the text-probe attestation.
    raw_font_size = raw.get("font_size")
    raw_line_height = raw.get("line_height")
    line_boxes = _line_boxes_from_raw(raw.get("line_boxes"))
    return RenderedElementProbe(
        element_id=element.element_id,
        kind="text",
        actual_box=actual_box,
        computed_font_family=font_family,
        computed_font_size=raw_font_size if raw_font_size is not None else None,
        computed_line_height=raw_line_height if raw_line_height is not None else None,
        overflow=overflow,
        ink_clipped=ink_clipped,
        layout_clipped=layout_clipped,
        contrast_ratio=contrast,
        content_ref=element.content_ref,
        asset_ref=None,
        rasterized_text_sha256=rasterized_sha,
        rendered_asset_sha256=None,
        actual_focal_point=None,
        crop_box=None,
        scroll_width=_optional_dim(raw, "scroll_width"),
        scroll_height=_optional_dim(raw, "scroll_height"),
        client_width=_optional_dim(raw, "client_width"),
        client_height=_optional_dim(raw, "client_height"),
        line_boxes=line_boxes,
    )


def _build_image_probe(
    *,
    element: ImageElement,
    raw: dict,
    actual_box: Box,
    overflow: bool,
    ink_clipped: bool,
    layout_clipped: bool,
    contrast: float,
    assets: Mapping[str, AssetManifestItem],
) -> RenderedElementProbe:
    asset = assets.get(element.asset_ref)
    if asset is None:
        raise ProbeBuildError(
            f"image element {element.element_id} references unknown asset "
            f"{element.asset_ref!r}"
        )
    try:
        rendered_bytes = hashlib.sha256(
            _read_asset_bytes(asset.local_path)
        ).hexdigest()
    except OSError as exc:
        raise ProbeBuildError(
            f"image element {element.element_id} asset is not readable: "
            f"{asset.local_path}: {exc}"
        ) from exc
    crop_box = _visible_crop_box(
        raw["x"], raw["y"], raw["width"], raw["height"]
    )
    return RenderedElementProbe(
        element_id=element.element_id,
        kind="image",
        actual_box=actual_box,
        computed_font_family=None,
        computed_font_size=None,
        computed_line_height=None,
        overflow=overflow,
        ink_clipped=ink_clipped,
        layout_clipped=layout_clipped,
        contrast_ratio=contrast,
        content_ref=None,
        asset_ref=element.asset_ref,
        rasterized_text_sha256=None,
        rendered_asset_sha256=rendered_bytes,
        actual_focal_point=element.focal_point,
        crop_box=crop_box,
        natural_width=_optional_dim(raw, "natural_width"),
        natural_height=_optional_dim(raw, "natural_height"),
    )


def _build_shape_probe(
    *,
    element: SceneElement,
    actual_box: Box,
    overflow: bool,
    ink_clipped: bool,
    layout_clipped: bool,
    contrast: float,
) -> RenderedElementProbe:
    return RenderedElementProbe(
        element_id=element.element_id,
        kind=getattr(element, "kind"),
        actual_box=actual_box,
        computed_font_family=None,
        computed_font_size=None,
        computed_line_height=None,
        overflow=overflow,
        ink_clipped=ink_clipped,
        layout_clipped=layout_clipped,
        contrast_ratio=contrast,
        content_ref=None,
        asset_ref=None,
        rasterized_text_sha256=None,
        rendered_asset_sha256=None,
        actual_focal_point=None,
        crop_box=None,
    )


def _read_asset_bytes(local_path: str) -> bytes:
    with open(local_path, "rb") as handle:
        return handle.read()


__all__ = [
    "CANVAS_HEIGHT",
    "CANVAS_WIDTH",
    "PROBE_SCRIPT",
    "ProbeBuildError",
    "build_element_probes",
]
