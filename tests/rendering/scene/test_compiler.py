"""Tests for the generic scene-to-HTML compiler (Task 10).

The compiler is a SINGLE deterministic function over generic primitives
(``text``, ``image``, ``shape``, ``line``, ``icon``). It has no family-specific
layout branch; all six ``TemplateFamily`` values pass through the same
``compile_page_scene``.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from src.rendering.scene.compiler import (
    CompiledPage,
    MissingContentRefError,
    SceneAssetError,
    SceneCompilationError,
    compile_element,
    compile_page_scene,
)
from src.schemas.assets import AssetManifestItem
from src.schemas.content_atoms import ContentFragment
from src.schemas.scene_graph import (
    Box,
    IconElement,
    ImageElement,
    LineElement,
    PageScene,
    ShapeElement,
    TextElement,
    TextStyle,
)
from src.schemas.visual_style import FamilyStyleProfile

SIX_FAMILIES = (
    "pink_red",
    "deep_teal",
    "soft_pink",
    "coral_impact",
    "green_catalog",
    "white_quote",
)

# A family name must NEVER leak into the output (no family-specific templates).
FAMILY_NAME_TOKENS = set(SIX_FAMILIES)

DEFAULT_BOX = Box(x=88, y=88, width=904, height=200)
DEFAULT_IMAGE_BOX = Box(x=88, y=320, width=904, height=720)
DEFAULT_ICON_BOX = Box(x=500, y=40, width=80, height=80)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _style(family: str = "pink_red") -> FamilyStyleProfile:
    return FamilyStyleProfile(
        family=family,
        reference_image_paths=("assets/visual-families/dummy.png",),
        palette=("#F4A7BF", "#DC2333", "#FFF7F8"),
        font_roles={
            "display": "Source Han Serif SC",
            "heading": "Heading Serif Family",
            "body": "Body Sans Family",
            "caption": "Caption Sans Family",
        },
        composition_principles=("hierarchy", "rhythm"),
        whitespace_range=(0.18, 0.42),
        density_range=(0.45, 0.82),
        allowed_motifs=("oversized type",),
        prohibited_patterns=("thin low-contrast copy",),
    )


def _fragment(fragment_id: str, text: str, *, source: str = "atom-1") -> ContentFragment:
    return ContentFragment(
        fragment_id=fragment_id,
        source_atom_id=source,
        start=0,
        end=len(text),
        text=text,
    )


def _asset(
    asset_id: str,
    *,
    local_path: str,
    page_id: str = "page-1",
    security_status: str = "approved",
) -> AssetManifestItem:
    return AssetManifestItem(
        asset_id=asset_id,
        directive_id="directive-1",
        page_id=page_id,
        source_kind="search",
        provider="approved-provider",
        license="commercial-use",
        local_path=local_path,
        width=1200,
        height=1600,
        sha256="b" * 64,
        subject_focal_point=(0.5, 0.45),
        crop_guidance="keep face centered",
        security_status=security_status,  # type: ignore[arg-type]
        human_decision="approved",
        run_id="run-1",
        transaction_id="transaction-1",
        internal_provenance={"source_url_hash": "c" * 64},
    )


def _text(
    element_id: str,
    content_ref: str,
    *,
    font_role: str = "body",
    font_size: float = 28,
    color: str = "#1A1A1A",
    weight: int = 400,
    align: str = "left",
    line_height: float = 1.4,
    box: Box = DEFAULT_BOX,
    layer: int = 1,
    emphasis_ranges: tuple[tuple[int, int], ...] = (),
) -> TextElement:
    return TextElement(
        element_id=element_id,
        layer=layer,
        box=box,
        content_ref=content_ref,
        style=TextStyle(
            font_role=font_role,  # type: ignore[arg-type]
            font_size=font_size,
            line_height=line_height,
            color=color,
            align=align,  # type: ignore[arg-type]
            weight=weight,  # type: ignore[arg-type]
            emphasis_ranges=emphasis_ranges,
        ),
    )


def _image(
    element_id: str,
    asset_ref: str,
    *,
    box: Box = DEFAULT_IMAGE_BOX,
    layer: int = 0,
    fit: str = "cover",
    focal_point: tuple[float, float] = (0.5, 0.5),
    corner_radius: float = 0,
) -> ImageElement:
    return ImageElement(
        element_id=element_id,
        layer=layer,
        box=box,
        asset_ref=asset_ref,
        fit=fit,  # type: ignore[arg-type]
        focal_point=focal_point,
        corner_radius=corner_radius,
    )


def _shape(
    element_id: str,
    *,
    shape: str = "rectangle",
    fill: str = "#DC2333",
    stroke: str | None = None,
    box: Box = DEFAULT_BOX,
    layer: int = 0,
) -> ShapeElement:
    return ShapeElement(
        element_id=element_id,
        layer=layer,
        box=box,
        shape=shape,  # type: ignore[arg-type]
        fill=fill,
        stroke=stroke,
    )


def _line(
    element_id: str,
    *,
    start: tuple[float, float] = (88, 1100),
    end: tuple[float, float] = (992, 1100),
    color: str = "#1A1A1A",
    width: float = 4,
    layer: int = 0,
) -> LineElement:
    return LineElement(
        element_id=element_id,
        layer=layer,
        start=start,
        end=end,
        color=color,
        width=width,
    )


def _icon(
    element_id: str,
    *,
    icon: str = "arrow",
    color: str = "#DC2333",
    box: Box = DEFAULT_ICON_BOX,
    layer: int = 2,
) -> IconElement:
    return IconElement(
        element_id=element_id,
        layer=layer,
        box=box,
        icon=icon,  # type: ignore[arg-type]
        color=color,
    )


def _page(
    elements,
    *,
    page_id: str = "page-1",
    sequence: int = 1,
    background: str = "#FFFFFF",
) -> PageScene:
    return PageScene(
        page_id=page_id,
        sequence=sequence,
        background=background,
        elements=tuple(elements),
    )


# ---------------------------------------------------------------------------
# Genericity: all six families share one compile path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("family", SIX_FAMILIES)
def test_all_six_families_compile_through_one_function(family: str):
    fragment = _fragment("frag-1", "Shared copy line")
    page = _page([_text("text-1", "frag-1")])
    compiled = compile_page_scene(
        page,
        fragments={"frag-1": fragment},
        assets={},
        style=_style(family=family),
    )
    assert isinstance(compiled, CompiledPage)
    assert compiled.page_id == "page-1"
    assert compiled.expected_element_ids == ("text-1",)
    assert "data-element-id=\"text-1\"" in compiled.html
    assert "data-content-ref=\"frag-1\"" in compiled.html
    # No family-specific template name may leak into the output.
    for token in FAMILY_NAME_TOKENS:
        assert token not in compiled.html


# ---------------------------------------------------------------------------
# Required data attributes
# ---------------------------------------------------------------------------


def test_output_includes_data_attributes_for_each_primitive(tmp_path):
    asset_path = tmp_path / "photo.png"
    asset_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fragments = {"frag-1": _fragment("frag-1", "Hello world")}
    assets = {"asset-1": _asset("asset-1", local_path=str(asset_path))}
    page = _page(
        [
            _text("text-1", "frag-1"),
            _image("image-1", "asset-1"),
            _shape("shape-1"),
            _line("line-1"),
            _icon("icon-1"),
        ]
    )
    html = compile_page_scene(
        page, fragments=fragments, assets=assets, style=_style()
    ).html

    assert "data-element-id=\"text-1\"" in html
    assert "data-content-ref=\"frag-1\"" in html
    assert "data-element-id=\"image-1\"" in html
    assert "data-asset-ref=\"asset-1\"" in html
    assert "data-element-id=\"shape-1\"" in html
    assert "data-element-id=\"line-1\"" in html
    assert "data-element-id=\"icon-1\"" in html


# ---------------------------------------------------------------------------
# Text resolves from immutable fragments, never from element-supplied copy
# ---------------------------------------------------------------------------


def test_text_is_resolved_from_fragments_not_element_data():
    """TextElement carries no copy; text always comes from the fragment map."""
    page = _page([_text("text-1", "frag-1")])

    first = compile_page_scene(
        page,
        fragments={"frag-1": _fragment("frag-1", "Alpha copy")},
        assets={},
        style=_style(),
    ).html
    assert "Alpha copy" in first
    assert "Beta copy" not in first

    second = compile_page_scene(
        page,
        fragments={"frag-1": _fragment("frag-1", "Beta copy")},
        assets={},
        style=_style(),
    ).html
    assert "Beta copy" in second
    assert "Alpha copy" not in second

    # The element schema itself carries no text payload.
    assert not hasattr(page.elements[0], "text")


def test_missing_content_ref_is_a_hard_error():
    page = _page([_text("text-1", "missing-frag")])
    with pytest.raises(MissingContentRefError) as info:
        compile_page_scene(
            page, fragments={}, assets={}, style=_style()
        )
    assert "missing-frag" in str(info.value)


# ---------------------------------------------------------------------------
# Asset path -> safe local file URI after containment validation
# ---------------------------------------------------------------------------


def test_approved_asset_path_becomes_safe_local_file_uri(tmp_path):
    asset_path = tmp_path / "photo.png"
    asset_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    page = _page([_image("image-1", "asset-1")])
    html = compile_page_scene(
        page,
        fragments={},
        assets={"asset-1": _asset("asset-1", local_path=str(asset_path))},
        style=_style(),
    ).html
    expected_uri = asset_path.as_uri()
    assert f'src="{expected_uri}"' in html
    assert "file://" in html


@pytest.mark.parametrize(
    "bad_path",
    [
        "https://example.com/x.png",  # remote URL
        "file:///tmp/x.png",  # already a URI, not a path
        "ftp://example.com/x.png",  # other scheme
    ],
)
def test_remote_url_or_uri_asset_is_rejected(bad_path):
    page = _page([_image("image-1", "asset-1")])
    with pytest.raises(SceneAssetError):
        compile_page_scene(
            page,
            fragments={},
            assets={"asset-1": _asset("asset-1", local_path=bad_path)},
            style=_style(),
        )


def test_relative_asset_path_is_rejected():
    page = _page([_image("image-1", "asset-1")])
    with pytest.raises(SceneAssetError):
        compile_page_scene(
            page,
            fragments={},
            assets={
                "asset-1": _asset("asset-1", local_path="relative/path/x.png")
            },
            style=_style(),
        )


def test_traversal_asset_path_is_rejected(tmp_path):
    bad_path = f"{tmp_path}/safe/../../../escape.png"
    page = _page([_image("image-1", "asset-1")])
    with pytest.raises(SceneAssetError):
        compile_page_scene(
            page,
            fragments={},
            assets={"asset-1": _asset("asset-1", local_path=bad_path)},
            style=_style(),
        )


def test_symlink_asset_is_rejected(tmp_path):
    real = tmp_path / "real.png"
    real.write_bytes(b"\x89PNG\r\n\x1a\n")
    link = tmp_path / "link.png"
    link.symlink_to(real)
    page = _page([_image("image-1", "asset-1")])
    with pytest.raises(SceneAssetError):
        compile_page_scene(
            page,
            fragments={},
            assets={"asset-1": _asset("asset-1", local_path=str(link))},
            style=_style(),
        )


def test_non_approved_asset_is_rejected(tmp_path):
    asset_path = tmp_path / "photo.png"
    asset_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    page = _page([_image("image-1", "asset-1")])
    with pytest.raises(SceneAssetError):
        compile_page_scene(
            page,
            fragments={},
            assets={
                "asset-1": _asset(
                    "asset-1",
                    local_path=str(asset_path),
                    security_status="rejected",
                )
            },
            style=_style(),
        )


def test_unknown_asset_ref_is_hard_error():
    page = _page([_image("image-1", "missing-asset")])
    with pytest.raises(SceneAssetError):
        compile_page_scene(
            page, fragments={}, assets={}, style=_style()
        )


# ---------------------------------------------------------------------------
# Security: no script, no editable, no remote, no event handlers
# ---------------------------------------------------------------------------


def test_output_has_no_unsafe_constructs(tmp_path):
    asset_path = tmp_path / "photo.png"
    asset_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    xss_text = '<script>alert("x")</script> & "quoted" <img src=x onerror=alert(1)>'
    fragments = {"frag-1": _fragment("frag-1", xss_text)}
    assets = {"asset-1": _asset("asset-1", local_path=str(asset_path))}
    page = _page(
        [
            _text("text-1", "frag-1"),
            _image("image-1", "asset-1"),
            _shape("shape-1"),
            _line("line-1"),
            _icon("icon-1"),
        ]
    )
    html = compile_page_scene(
        page, fragments=fragments, assets=assets, style=_style()
    ).html

    # Parse the real DOM the compiler emits. Escaped text content is inert
    # (it is not a start tag), so the inspector only sees real attributes.
    inspector = _TagInspector()
    inspector.feed(html)

    assert "script" not in inspector.tags
    assert "iframe" not in inspector.tags
    assert "object" not in inspector.tags
    for _tag, attrs in inspector.attrs_by_tag:
        for name, value in attrs:
            assert not name.startswith("on"), (name, value)
            assert name != "contenteditable"
            if name in {"href", "src", "xlink:href"} and value is not None:
                lowered = value.lower()
                assert not lowered.startswith("javascript:"), value
                # Only local file:// URIs are permitted on resource attrs; the
                # SVG xmlns namespace identifier is a non-fetched identifier,
                # not a resource reference, so it never appears here.
                assert not lowered.startswith(("http://", "https://", "ftp://")), value

    # Raw-string defenses: no remote schemes the browser would fetch, no live
    # scripts. (The SVG XML-namespace identifier ``http://www.w3.org/2000/svg``
    # is a non-fetched identifier and is allowed; resource attrs are vetted
    # above.)
    assert "ftp://" not in html
    assert "<script" not in html
    assert "</script" not in html
    # The XSS payload must have been escaped, not rendered as live markup.
    assert "<script>alert" not in html


class _TagInspector(HTMLParser):
    """Collect start tags and their attributes for security assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.attrs_by_tag: list[tuple[str, list[tuple[str, str | None]]]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs_by_tag.append((tag, attrs))


@pytest.mark.parametrize("family", SIX_FAMILIES)
def test_no_family_specific_template_names_leak(family: str):
    fragment = _fragment("frag-1", "plain copy")
    page = _page([_text("text-1", "frag-1")])
    html = compile_page_scene(
        page,
        fragments={"frag-1": fragment},
        assets={},
        style=_style(family=family),
    ).html
    for token in FAMILY_NAME_TOKENS:
        assert token not in html


def test_self_contained_html_document():
    page = _page([_text("text-1", "frag-1")])
    html = compile_page_scene(
        page,
        fragments={"frag-1": _fragment("frag-1", "copy")},
        assets={},
        style=_style(),
    ).html
    assert html.startswith("<!DOCTYPE html>")
    assert "<html" in html
    assert "</html>" in html


# ---------------------------------------------------------------------------
# Element order: (layer, then source order)
# ---------------------------------------------------------------------------


def test_element_order_follows_layer_then_source_order():
    # layer 2 first in source, then two layer-1 elements, then a layer-3.
    elements = [
        _text("layer2-first", "frag-1", layer=2),
        _text("layer1-a", "frag-1", layer=1),
        _text("layer1-b", "frag-1", layer=1),
        _text("layer3-last", "frag-1", layer=3),
    ]
    page = _page(elements)
    compiled = compile_page_scene(
        page,
        fragments={"frag-1": _fragment("frag-1", "copy")},
        assets={},
        style=_style(),
    )

    # expected_element_ids is SOURCE order (not sorted), per the brief.
    assert compiled.expected_element_ids == (
        "layer2-first",
        "layer1-a",
        "layer1-b",
        "layer3-last",
    )

    # The rendered body order is sorted by layer (stable -> source order ties).
    ids_in_dom_order = re.findall(r'data-element-id="([^"]+)"', compiled.html)
    # Only the element wrappers carry data-element-id; the first four are the
    # text elements in body order. (Filter to our ids to be safe.)
    ordered = [element_id for element_id in ids_in_dom_order if element_id in {
        "layer2-first", "layer1-a", "layer1-b", "layer3-last"
    }]
    assert ordered == ["layer1-a", "layer1-b", "layer2-first", "layer3-last"]


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_output_is_byte_identical_for_identical_inputs(tmp_path):
    asset_path = tmp_path / "photo.png"
    asset_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fragments = {"frag-1": _fragment("frag-1", "Deterministic copy")}
    assets = {"asset-1": _asset("asset-1", local_path=str(asset_path))}
    page = _page(
        [
            _text("text-1", "frag-1", layer=1),
            _image("image-1", "asset-1", layer=0),
            _shape("shape-1", layer=0),
            _line("line-1", layer=0),
            _icon("icon-1", layer=2),
        ]
    )
    style = _style()
    first = compile_page_scene(page, fragments=fragments, assets=assets, style=style).html
    second = compile_page_scene(page, fragments=fragments, assets=assets, style=style).html
    assert first == second


# ---------------------------------------------------------------------------
# Generic primitives: every element kind renders from validated fields only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "shape_kind", ["rectangle", "rounded_rectangle", "circle", "ellipse"]
)
def test_shape_primitives_render(shape_kind):
    page = _page([_shape("shape-1", shape=shape_kind, stroke="#000000")])
    html = compile_page_scene(page, fragments={}, assets={}, style=_style()).html
    assert "data-element-id=\"shape-1\"" in html
    assert "#DC2333" in html  # fill
    assert "#000000" in html  # stroke


@pytest.mark.parametrize(
    "icon_kind", ["arrow", "check", "cross", "sparkle", "dot", "bracket"]
)
def test_icon_primitives_render(icon_kind):
    page = _page([_icon("icon-1", icon=icon_kind, color="#112233")])
    html = compile_page_scene(page, fragments={}, assets={}, style=_style()).html
    assert "data-element-id=\"icon-1\"" in html
    assert "#112233" in html
    assert "<svg" in html


def test_line_primitive_renders_with_color_and_width():
    page = _page([_line("line-1", color="#445566", width=6)])
    html = compile_page_scene(page, fragments={}, assets={}, style=_style()).html
    assert "data-element-id=\"line-1\"" in html
    assert "#445566" in html


def test_text_primitive_renders_resolved_font_role():
    page = _page([_text("text-1", "frag-1", font_role="display")])
    style = _style()
    html = compile_page_scene(
        page,
        fragments={"frag-1": _fragment("frag-1", "Display copy")},
        assets={},
        style=style,
    ).html
    # The display-role family name from the profile is reflected in font-family.
    assert style.font_roles["display"] in html
    assert "font-family:" in html
    # font-size, line-height, color, weight, align all come from validated fields.
    assert "font-size:28px" in html
    assert "line-height:1.4" in html
    assert "#1A1A1A" in html
    assert "font-weight:400" in html
    assert "text-align:left" in html


def test_text_emphasis_ranges_render_strong():
    page = _page(
        [_text("text-1", "frag-1", emphasis_ranges=((0, 4),))]
    )
    html = compile_page_scene(
        page,
        fragments={"frag-1": _fragment("frag-1", "Bold start rest")},
        assets={},
        style=_style(),
    ).html
    assert "<strong>Bold</strong>" in html
    # The non-emphasized tail is still present and escaped.
    assert "start rest" in html


def test_image_primitive_renders_fit_focal_point_and_corner_radius(tmp_path):
    asset_path = tmp_path / "photo.png"
    asset_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    page = _page(
        [
            _image(
                "image-1",
                "asset-1",
                fit="cover",
                focal_point=(0.3, 0.4),
                corner_radius=16,
            )
        ]
    )
    html = compile_page_scene(
        page,
        fragments={},
        assets={"asset-1": _asset("asset-1", local_path=str(asset_path))},
        style=_style(),
    ).html
    assert "object-fit:cover" in html
    assert "object-position:30% 40%" in html
    assert "border-radius:16px" in html


# ---------------------------------------------------------------------------
# Attribute escaping on content_ref / asset_ref
# ---------------------------------------------------------------------------


def test_content_ref_with_quote_is_escaped_in_attribute():
    frag_id = 'a"b'
    page = _page([_text("text-1", frag_id)])
    html = compile_page_scene(
        page,
        fragments={frag_id: _fragment(frag_id, "copy")},
        assets={},
        style=_style(),
    ).html
    # The quote must be escaped, not reflected raw (no attribute injection).
    assert 'data-content-ref="a&quot;b"' in html
    assert 'data-content-ref="a"b"' not in html


def test_asset_ref_with_quote_is_escaped_in_attribute(tmp_path):
    asset_path = tmp_path / "photo.png"
    asset_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    asset_id = 'x"y'
    page = _page([_image("image-1", asset_id)])
    html = compile_page_scene(
        page,
        fragments={},
        assets={asset_id: _asset(asset_id, local_path=str(asset_path))},
        style=_style(),
    ).html
    assert 'data-asset-ref="x&quot;y"' in html
    assert 'data-asset-ref="x"y"' not in html


# ---------------------------------------------------------------------------
# CompiledPage contract
# ---------------------------------------------------------------------------


def test_compiled_page_is_frozen_with_tuple_ids():
    page = _page([_text("text-1", "frag-1")])
    compiled = compile_page_scene(
        page,
        fragments={"frag-1": _fragment("frag-1", "copy")},
        assets={},
        style=_style(),
    )
    assert isinstance(compiled.expected_element_ids, tuple)
    with pytest.raises(Exception):
        compiled.html = "mutated"  # type: ignore[misc]


def test_compile_element_is_the_discriminator_dispatch():
    """compile_element dispatches over kind and is the single entry per element."""
    fragment = _fragment("frag-1", "copy")
    style = _style()
    text_html = compile_element(
        _text("text-1", "frag-1"), fragments={"frag-1": fragment}, assets={}, style=style
    )
    shape_html = compile_element(
        _shape("shape-1"), fragments={"frag-1": fragment}, assets={}, style=style
    )
    assert "scene-text" in text_html
    assert "scene-shape" in shape_html
    # compile_element raises a SceneCompilationError on unknown kinds (defensive).
    with pytest.raises(SceneCompilationError):
        compile_element(
            "not-an-element",  # type: ignore[arg-type]
            fragments={"frag-1": fragment},
            assets={},
            style=style,
        )


# ---------------------------------------------------------------------------
# Background color is reflected from validated field, not free-form CSS.
# ---------------------------------------------------------------------------


def test_page_background_is_emitted_from_validated_hex_field():
    page = _page([_text("text-1", "frag-1")], background="#FFE5EC")
    html = compile_page_scene(
        page,
        fragments={"frag-1": _fragment("frag-1", "copy")},
        assets={},
        style=_style(),
    ).html
    assert "#FFE5EC" in html
