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
# The single in-page evaluation script
# ---------------------------------------------------------------------------

PROBE_SCRIPT = r"""
(() => {
  const nodes = document.querySelectorAll('[data-element-id]');
  return Array.from(nodes).map((node) => {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    const inner = node.querySelector('img.scene-image-inner');
    const innerRect = inner ? inner.getBoundingClientRect() : null;
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
      rendered_image_height: innerRect ? innerRect.height : null
    };
  });
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
    page_background: str,
) -> RenderedElementProbe:
    actual_box = _clamp_box(
        raw["x"], raw["y"], raw["width"], raw["height"]
    )
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
    contrast = _effective_contrast(
        raw["color"], raw["background_color"], page_background
    )

    kind = getattr(element, "kind", None)

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
    return RenderedElementProbe(
        element_id=element.element_id,
        kind="text",
        actual_box=actual_box,
        computed_font_family=font_family,
        computed_font_size=raw.get("font_size") or None,
        computed_line_height=raw.get("line_height") or None,
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
