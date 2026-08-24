"""The generic scene-to-HTML compiler (Task 10).

``compile_page_scene`` is a SINGLE deterministic compiler that turns one
``PageScene`` (plus immutable content fragments, an approved asset map and a
family style profile) into self-contained HTML for an offline Chromium step.

Design contract (do not violate):

* **One generic code path.** There is no ``if family == ...`` branch and no
  per-family template. The six ``TemplateFamily`` values all flow through the
  same ``compile_element`` discriminator over the five generic primitives
  (``text``, ``image``, ``shape``, ``line``, ``icon``).
* **Validated fields only.** CSS declarations are computed exclusively from
  numerically/enumerated-validated scene fields. No free-form CSS from the
  scene is ever reflected into a ``style`` attribute.
* **Escaping everywhere.** All interpolated text and attribute values are
  escaped (XSS-safe).
* **Asset containment.** Image ``local_path`` is converted to a safe local
  ``file://`` URI only after rejecting non-local URLs, relative paths, parent
  directory traversal and symlink escape. Only ``security_status == "approved"``
  assets render.
* **Deterministic.** No clock, no randomness, no network, no dict-iteration
  leaking into output. Stable attribute order and stable ``(layer, source
  order)`` element order make the output byte-identical for identical inputs.

This package is self-contained: the v3 production path has a single generic
compiler. The retired ``src/rendering/editorial`` family-template tree was
removed in the llm_scene_v3 cutover, so there is no family-template code to
import from and no per-family branch in this module.
"""

from __future__ import annotations

import html as _html
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from src.schemas.assets import AssetManifestItem
from src.schemas.content_atoms import ContentFragment
from src.schemas.scene_graph import (
    Box,
    IconElement,
    ImageElement,
    LineElement,
    PageScene,
    SceneElement,
    ShapeElement,
    TextElement,
)
from src.schemas.visual_style import FamilyStyleProfile

from .fonts import format_font_family, resolve_font_stack

# ---------------------------------------------------------------------------
# Canvas geometry
# ---------------------------------------------------------------------------

#: The fixed render canvas. Elements are absolutely positioned on this grid.
CANVAS_WIDTH: Final[int] = 1080
CANVAS_HEIGHT: Final[int] = 1440

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SceneCompilationError(ValueError):
    """Base class for scene-compilation failures."""


class MissingContentRefError(SceneCompilationError):
    """A text element referenced a content_ref absent from the fragment map."""


class SceneAssetError(SceneCompilationError):
    """An image asset failed containment, approval or path-safety checks."""


# ---------------------------------------------------------------------------
# CompiledPage + document scaffold
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompiledPage:
    page_id: str
    html: str
    expected_element_ids: tuple[str, ...]


_PAGE_DOCUMENT = (
    "<!DOCTYPE html>\n"
    '<html lang="und">\n'
    "<head>\n"
    '<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    "<style>\n"
    "*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}\n"
    "html,body{{margin:0;padding:0;background:#ffffff;}}\n"
    ".scene-page{{width:1080px;height:1440px;"
    "position:relative;overflow:hidden;}}\n"
    ".scene-element{{position:absolute;}}\n"
    ".scene-image-inner{{display:block;width:100%;height:100%;}}\n"
    "{font_faces}"
    "</style>\n"
    "</head>\n"
    "<body>\n"
    '<div class="scene-page" style="background:{background};">\n'
    "{body}\n"
    "</div>\n"
    "</body>\n"
    "</html>"
)


# ---------------------------------------------------------------------------
# Deterministic formatting / escaping helpers
# ---------------------------------------------------------------------------

_HEX_COLOR: Final[re.Pattern[str]] = re.compile(r"^#[0-9A-Fa-f]{6}$")
_URL_SCHEME: Final[re.Pattern[str]] = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def _num(value: float) -> str:
    """Deterministic compact numeric formatting for CSS values.

    Integral floats lose their trailing ``.0`` so two equivalent numeric
    inputs render identically.
    """
    if value == int(value):
        return str(int(value))
    return repr(float(value))


def _escape_text(text: str) -> str:
    """Escape interpolated text for HTML text-content / attribute context."""
    return _html.escape(text, quote=True)


def _format_color(value: str) -> str:
    """Validate a HexColor before reflecting it into CSS.

    The scene schema already constrains colors to ``#RRGGBB``; this is the
    compiler's defense in depth so a malformed value can never reach a style
    attribute.
    """
    if not isinstance(value, str) or not _HEX_COLOR.match(value):
        raise SceneCompilationError(f"refusing to reflect invalid color: {value!r}")
    return value


def _box_position(box: Box) -> str:
    return (
        f"left:{_num(box.x)}px;"
        f"top:{_num(box.y)}px;"
        f"width:{_num(box.width)}px;"
        f"height:{_num(box.height)}px;"
    )


# ---------------------------------------------------------------------------
# Asset containment -> safe local file URI
# ---------------------------------------------------------------------------


def _safe_local_file_uri(local_path: str) -> str:
    """Convert a validated local asset path to a ``file://`` URI.

    Containment / path-safety defenses (the asset resolver performs the full
    catalog-root containment check at manifest-build time; the compiler adds
    defense in depth so a bad path can never become a live resource reference):

    * reject anything that looks like a URL (any ``scheme://`` form) or a
      network-path (``//host``);
    * require an absolute filesystem path;
    * reject any literal ``..`` parent-directory component (traversal);
    * reject symlinks (symlink escape).
    """
    if not isinstance(local_path, str) or not local_path:
        raise SceneAssetError("asset local path is empty")
    if _URL_SCHEME.match(local_path) or local_path.startswith("//"):
        raise SceneAssetError(
            "asset local path must be a local filesystem path, not a URL"
        )
    asset_path = Path(local_path)
    if not asset_path.is_absolute():
        raise SceneAssetError("asset local path must be absolute")
    if ".." in asset_path.parts:
        raise SceneAssetError(
            "asset local path must not contain parent-directory traversal"
        )
    try:
        if asset_path.is_symlink():
            raise SceneAssetError("asset local path must not be a symlink")
    except OSError as error:
        raise SceneAssetError(
            "asset local path is not a trusted regular file"
        ) from error
    try:
        return asset_path.as_uri()
    except ValueError as error:
        raise SceneAssetError(
            "asset local path cannot be encoded as a file URI"
        ) from error


def _safe_font_file_uri(font_path: Path) -> str:
    """Return a no-follow local URI for a checked-in v4 font file.

    The generic v3 compiler never calls this helper.  The optional v4 seam
    supplies already-resolved repository font paths and uses this final
    defense-in-depth check before a path reaches Chromium CSS.
    """

    if not isinstance(font_path, Path) or not font_path.is_absolute():
        raise SceneCompilationError("v4 font source must be an absolute path")
    if ".." in font_path.parts or font_path.is_symlink():
        raise SceneCompilationError("v4 font source must not traverse or follow symlinks")
    try:
        if not font_path.is_file():
            raise SceneCompilationError("v4 font source must be a regular file")
        return font_path.as_uri()
    except OSError as error:
        raise SceneCompilationError("v4 font source is not readable") from error


# ---------------------------------------------------------------------------
# Text emphasis (applied to the ORIGINAL text so fragment indices stay valid)
# ---------------------------------------------------------------------------


def _merge_ranges(
    ranges: tuple[tuple[int, int], ...], length: int
) -> list[tuple[int, int]]:
    """Clamp, sort and merge emphasis ranges deterministically."""
    clamped: list[tuple[int, int]] = []
    for start, end in ranges:
        if start < 0 or end <= start:
            continue
        start = max(0, min(start, length))
        end = max(0, min(end, length))
        if end <= start:
            continue
        clamped.append((start, end))
    clamped.sort()
    merged: list[tuple[int, int]] = []
    for start, end in clamped:
        if merged and start <= merged[-1][1]:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


def _render_text_with_emphasis(text: str, emphasis_ranges) -> str:
    """Escape the fragment text and wrap clamped emphasis ranges in <strong>."""
    length = len(text)
    merged = _merge_ranges(tuple(emphasis_ranges), length)
    cursor = 0
    rendered: list[str] = []
    for start, end in merged:
        if start > cursor:
            rendered.append(_escape_text(text[cursor:start]))
        rendered.append(f"<strong>{_escape_text(text[start:end])}</strong>")
        cursor = end
    if cursor < length:
        rendered.append(_escape_text(text[cursor:]))
    return "".join(rendered)


# ---------------------------------------------------------------------------
# Per-primitive renderers (generic; no family branching)
# ---------------------------------------------------------------------------


def _render_text(
    element: TextElement,
    *,
    fragments: Mapping[str, ContentFragment],
    style: FamilyStyleProfile,
    text_render_options: Mapping[str, object] | None = None,
) -> str:
    fragment = fragments.get(element.content_ref)
    if fragment is None:
        raise MissingContentRefError(
            "text element references an unknown content fragment: "
            f"{element.content_ref!r}"
        )
    text_style = element.style
    font_stack = resolve_font_stack(text_style.font_role, style)
    options = (text_render_options or {}).get(element.content_ref, {})
    if not isinstance(options, Mapping):
        options = {}
    rendered_text = options.get("text", fragment.text)
    if not isinstance(rendered_text, str):
        raise SceneCompilationError("v4 text render option must be a string")
    declarations = (
        _box_position(element.box)
        + f"font-family:{format_font_family(font_stack)};"
        + f"font-size:{_num(text_style.font_size)}px;"
        + f"line-height:{_num(text_style.line_height)};"
        + f"color:{_format_color(text_style.color)};"
        + f"text-align:{text_style.align};"
        + f"font-weight:{_num(text_style.weight)};"
    )
    if bool(options.get("preformatted")):
        declarations += "white-space:pre-wrap;overflow-wrap:anywhere;"
    inset = options.get("content_inset")
    if inset is not None:
        if (
            not isinstance(inset, (tuple, list))
            or len(inset) != 4
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or float(value) < 0
                or not math.isfinite(float(value))
                for value in inset
            )
        ):
            raise SceneCompilationError("v4 content inset must contain four finite values")
        left, top, right, bottom = (float(value) for value in inset)
        declarations += (
            f"padding-left:{_num(left)}px;"
            f"padding-top:{_num(top)}px;"
            f"padding-right:{_num(right)}px;"
            f"padding-bottom:{_num(bottom)}px;"
        )
    # A v4 break layout is generated from the original fragment.  Emphasis
    # ranges are source offsets, so the adapter only enables them when no
    # inserted break offsets are present; ordinary v3 text keeps its exact
    # historical path.
    inner = _render_text_with_emphasis(
        rendered_text,
        text_style.emphasis_ranges if rendered_text == fragment.text else (),
    )
    # HTML-escape the declarations at the attribute boundary so the literal
    # double quotes ``format_font_family`` emits around multi-word family
    # names (e.g. ``"Source Han Sans SC"``) cannot terminate the style
    # attribute early nor carry an attacker-controlled ``on*`` handler
    # through. The browser decodes ``&quot;`` back to ``"`` for the CSS
    # parser, so ``font-family:"Source Han Sans SC"`` round-trips intact
    # AND the attribute stays XSS-safe by construction (defense in depth:
    # this must hold even if a future schema validator loosens font names).
    probe_attrs = ""
    if text_render_options is not None:
        # v4-only probe metadata makes the browser prove the exact role face;
        # the default v3 compiler output remains byte-compatible.
        probe_attrs = (
            f' data-font-role="{_escape_text(element.style.font_role)}"'
            f' data-font-family="{_escape_text(font_stack[0])}"'
            f' data-font-weight="{_num(text_style.weight)}"'
        )
    return (
        f'<div class="scene-element scene-text"'
        f' data-element-id="{_escape_text(element.element_id)}"'
        f' data-content-ref="{_escape_text(element.content_ref)}"'
        f'{probe_attrs}'
        f' style="{_html.escape(declarations, quote=True)}">{inner}</div>'
    )


def _render_image(
    element: ImageElement,
    *,
    assets: Mapping[str, AssetManifestItem],
) -> str:
    asset = assets.get(element.asset_ref)
    if asset is None:
        raise SceneAssetError(
            f"image element references an unknown asset: {element.asset_ref!r}"
        )
    if asset.security_status != "approved":
        raise SceneAssetError(
            "image element references a non-approved asset: "
            f"{element.asset_ref!r}"
        )
    src_uri = _safe_local_file_uri(asset.local_path)
    fit_x, fit_y = element.focal_point
    declarations = (
        _box_position(element.box)
        + "overflow:hidden;"
        + f"border-radius:{_num(element.corner_radius)}px;"
    )
    img_style = (
        "width:100%;"
        "height:100%;"
        f"object-fit:{element.fit};"
        f"object-position:{_num(round(fit_x * 100, 2))}% "
        f"{_num(round(fit_y * 100, 2))}%;"
    )
    return (
        f'<div class="scene-element scene-image"'
        f' data-element-id="{_escape_text(element.element_id)}"'
        f' data-asset-ref="{_escape_text(element.asset_ref)}"'
        f' style="{declarations}">'
        f'<img class="scene-image-inner" src="{src_uri}" alt="" '
        f'style="{img_style}"/>'
        f"</div>"
    )


def _shape_border_radius(element: ShapeElement) -> str:
    if element.shape == "rectangle":
        return "0"
    if element.shape == "rounded_rectangle":
        smaller = min(element.box.width, element.box.height)
        return f"{_num(round(smaller * 0.25, 2))}px"
    # circle / ellipse
    return "50%"


def _render_shape(element: ShapeElement) -> str:
    declarations = (
        _box_position(element.box)
        + f"background:{_format_color(element.fill)};"
        + f"border-radius:{_shape_border_radius(element)};"
    )
    if element.stroke is not None:
        declarations += f"border:2px solid {_format_color(element.stroke)};"
    return (
        f'<div class="scene-element scene-shape"'
        f' data-element-id="{_escape_text(element.element_id)}"'
        f' style="{declarations}"></div>'
    )


def _render_line(element: LineElement) -> str:
    start_x, start_y = element.start
    end_x, end_y = element.end
    delta_x = end_x - start_x
    delta_y = end_y - start_y
    length = math.hypot(delta_x, delta_y)
    angle = math.degrees(math.atan2(delta_y, delta_x))
    declarations = (
        f"left:{_num(start_x)}px;"
        f"top:{_num(start_y)}px;"
        f"width:{_num(length)}px;"
        f"height:{_num(element.width)}px;"
        "transform-origin:0 0;"
        f"transform:rotate({_num(round(angle, 4))}deg);"
        f"background:{_format_color(element.color)};"
    )
    return (
        f'<div class="scene-element scene-line"'
        f' data-element-id="{_escape_text(element.element_id)}"'
        f' style="{declarations}"></div>'
    )


_ICON_SVGS: Final[dict[str, str]] = {
    "arrow": (
        '<path d="M12,50 H70 M52,22 L82,50 L52,78" '
        'fill="none" stroke="{color}" stroke-width="12" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    "check": (
        '<path d="M15,52 L40,76 L82,24" '
        'fill="none" stroke="{color}" stroke-width="12" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    "cross": (
        '<path d="M22,22 L78,78 M78,22 L22,78" '
        'fill="none" stroke="{color}" stroke-width="12" '
        'stroke-linecap="round"/>'
    ),
    "sparkle": (
        '<path d="M50,10 L57,43 L90,50 L57,57 L50,90 L43,57 L10,50 L43,43 Z" '
        'fill="{color}"/>'
    ),
    "dot": '<circle cx="50" cy="50" r="40" fill="{color}"/>',
    "bracket": (
        '<path d="M32,14 H14 V86 H32" '
        'fill="none" stroke="{color}" stroke-width="12" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    ),
}


def _render_icon(element: IconElement) -> str:
    color = _format_color(element.color)
    body = _ICON_SVGS[element.icon].replace("{color}", color)
    svg = (
        '<svg viewBox="0 0 100 100" width="100%" height="100%" '
        'xmlns="http://www.w3.org/2000/svg" '
        'preserveAspectRatio="xMidYMid meet" '
        f'aria-hidden="true">{body}</svg>'
    )
    declarations = _box_position(element.box)
    return (
        f'<div class="scene-element scene-icon"'
        f' data-element-id="{_escape_text(element.element_id)}"'
        f' style="{declarations}">{svg}</div>'
    )


# ---------------------------------------------------------------------------
# Discriminator dispatch
# ---------------------------------------------------------------------------


def compile_element(
    element: SceneElement,
    *,
    fragments: Mapping[str, ContentFragment],
    assets: Mapping[str, AssetManifestItem],
    style: FamilyStyleProfile,
    text_render_options: Mapping[str, object] | None = None,
) -> str:
    """Render one scene element to HTML via generic primitive dispatch.

    No family-specific branching: every family shares this exact dispatch.
    """
    kind = getattr(element, "kind", None)
    if kind == "text":
        return _render_text(
            element,
            fragments=fragments,
            style=style,
            text_render_options=text_render_options,
        )
    if kind == "image":
        return _render_image(element, assets=assets)
    if kind == "shape":
        return _render_shape(element)
    if kind == "line":
        return _render_line(element)
    if kind == "icon":
        return _render_icon(element)
    raise SceneCompilationError(f"unknown scene element kind: {kind!r}")


def compile_page_scene(
    page: PageScene,
    *,
    fragments: Mapping[str, ContentFragment],
    assets: Mapping[str, AssetManifestItem],
    style: FamilyStyleProfile,
    font_face_sources: Mapping[str, tuple[Path, int]] | None = None,
    text_render_options: Mapping[str, object] | None = None,
) -> CompiledPage:
    """Compile one :class:`PageScene` into a self-contained HTML document.

    Elements are rendered in ``(layer, source order)`` order (``sorted`` is
    stable, so source order is preserved within a layer). The output is
    deterministic for identical inputs.
    """
    page_text_options: Mapping[str, object] | None = text_render_options
    if text_render_options is not None:
        # v4 adapters may pass a plan-wide `(page_id, fragment_ref)` map.
        # Reduce it to this page only at the compiler boundary so a fragment
        # reused on multiple pages cannot inherit another page's breaks.
        page_text_options = {}
        for key, value in text_render_options.items():
            if isinstance(key, tuple) and len(key) == 2:
                if key[0] == page.page_id:
                    page_text_options[key[1]] = value
            else:
                page_text_options[key] = value
    body = "\n".join(
        compile_element(
            element,
            fragments=fragments,
            assets=assets,
            style=style,
            text_render_options=page_text_options,
        )
        for element in sorted(page.elements, key=lambda item: item.layer)
    )
    font_faces = ""
    if font_face_sources:
        declarations: list[str] = []
        for family_name, source in sorted(font_face_sources.items()):
            if (
                not isinstance(family_name, str)
                or not family_name.strip()
                or not isinstance(source, tuple)
                or len(source) != 2
                or not isinstance(source[0], Path)
                or type(source[1]) is not int
                or source[1] < 1
                or source[1] > 1000
            ):
                raise SceneCompilationError("invalid v4 font-face source")
            uri = _safe_font_file_uri(source[0])
            family_css = format_font_family((family_name,))
            declarations.append(
                "@font-face{"
                f"font-family:{family_css};"
                f"src:url('{_html.escape(uri, quote=True)}') format('truetype');"
                f"font-weight:{source[1]};font-style:normal;font-display:block;"
                "}"
            )
        font_faces = "\n".join(declarations) + "\n"
    return CompiledPage(
        page_id=page.page_id,
        html=_PAGE_DOCUMENT.format(
            background=_format_color(page.background),
            body=body,
            font_faces=font_faces,
        ),
        expected_element_ids=tuple(
            element.element_id for element in page.elements
        ),
    )


__all__ = [
    "CANVAS_HEIGHT",
    "CANVAS_WIDTH",
    "CompiledPage",
    "MissingContentRefError",
    "SceneAssetError",
    "SceneCompilationError",
    "compile_element",
    "compile_page_scene",
]
