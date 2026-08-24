"""Deterministic unit tests for the generic-scene DOM probe builder (Task 11).

These tests NEVER launch Chromium. They feed :func:`build_element_probes` raw
probe dicts (the shape the in-page JS evaluation returns) plus the immutable
scene metadata, and assert the resulting :class:`RenderedElementProbe` values
are validated and hash-bound.
"""

from __future__ import annotations

import hashlib

import pytest

from src.rendering.scene.probes import PROBE_SCRIPT, V4_PROBE_SCRIPT, build_element_probes
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


PAGE_BACKGROUND = "#FFFFFF"


def test_v3_probe_script_remains_the_default_and_v4_is_explicitly_stricter():
    """The v3 browser contract must not silently inherit v4 timing/coverage."""

    assert "document.fonts.ready" not in PROBE_SCRIPT
    assert "glyph_coverage" not in PROBE_SCRIPT
    assert V4_PROBE_SCRIPT != PROBE_SCRIPT
    assert "document.fonts.ready" in V4_PROBE_SCRIPT
    assert "document.fonts.check" in V4_PROBE_SCRIPT
    assert "getImageData" in V4_PROBE_SCRIPT
    assert "raster_signature" in V4_PROBE_SCRIPT
    assert "data-font-family" in V4_PROBE_SCRIPT
    assert "__v4_missing_primary_face__" in V4_PROBE_SCRIPT
    assert "tofu_raster_signature" in V4_PROBE_SCRIPT
    assert "is_whitespace" in V4_PROBE_SCRIPT
    assert "rasterEvidence(part.segment, style, primaryFamily)" in V4_PROBE_SCRIPT
    assert "rasterEvidence(part.segment, style, '__v4_missing_primary_face__')" in V4_PROBE_SCRIPT


def _fragment(fragment_id: str, text: str) -> ContentFragment:
    return ContentFragment(
        fragment_id=fragment_id,
        source_atom_id="atom-1",
        start=0,
        end=len(text),
        text=text,
    )


def _text_element(element_id: str, fragment_id: str, *, color: str = "#1A1A1A") -> TextElement:
    return TextElement(
        element_id=element_id,
        layer=1,
        box=Box(x=80, y=120, width=920, height=160),
        content_ref=fragment_id,
        style=TextStyle(
            font_role="heading",
            font_size=48,
            line_height=1.3,
            color=color,
            align="left",
            weight=700,
        ),
    )


def _image_element(
    element_id: str,
    asset_id: str,
    *,
    box: Box | None = None,
    focal: tuple[float, float] = (0.5, 0.5),
) -> ImageElement:
    return ImageElement(
        element_id=element_id,
        layer=0,
        box=box or Box(x=80, y=400, width=920, height=720),
        asset_ref=asset_id,
        fit="cover",
        focal_point=focal,
        corner_radius=0,
    )


def _asset_item(asset_id: str, *, path: str, payload: bytes) -> AssetManifestItem:
    return AssetManifestItem(
        asset_id=asset_id,
        directive_id=f"directive-{asset_id}",
        page_id="page-1",
        source_kind="catalog",
        provider="catalog",
        license="project-owned",
        local_path=path,
        width=1080,
        height=1440,
        sha256=hashlib.sha256(payload).hexdigest(),
        subject_focal_point=(0.5, 0.5),
        crop_guidance="centered",
        security_status="approved",
        human_decision="pending",
        run_id="run-1",
        transaction_id="tx-1",
        internal_provenance={"provider": "catalog"},
    )


def _raw_text_probe(
    element_id: str,
    *,
    content_ref: str,
    x: float = 80.0,
    y: float = 120.0,
    width: float = 920.0,
    height: float = 160.0,
    scroll_width: int = 900,
    scroll_height: int = 150,
    client_width: int = 920,
    client_height: int = 160,
    font_family: str = '"Test Display", sans-serif',
    font_size: float = 48.0,
    line_height: float = 62.4,
    color: str = "rgb(26, 26, 26)",
    background_color: str = "rgb(255, 255, 255)",
    line_boxes: list[dict] | None = None,
) -> dict:
    return {
        "element_id": element_id,
        "content_ref": content_ref,
        "asset_ref": None,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "scroll_width": scroll_width,
        "scroll_height": scroll_height,
        "client_width": client_width,
        "client_height": client_height,
        "font_family": font_family,
        "font_size": font_size,
        "line_height": line_height,
        "color": color,
        "background_color": background_color,
        "natural_width": None,
        "natural_height": None,
        "rendered_image_width": None,
        "rendered_image_height": None,
        "line_boxes": line_boxes,
    }


def _raw_image_probe(
    element_id: str,
    *,
    asset_ref: str,
    x: float = 80.0,
    y: float = 400.0,
    width: float = 920.0,
    height: float = 720.0,
    natural_width: int = 1080,
    natural_height: int = 1440,
) -> dict:
    return {
        "element_id": element_id,
        "content_ref": None,
        "asset_ref": asset_ref,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "scroll_width": int(width),
        "scroll_height": int(height),
        "client_width": int(width),
        "client_height": int(height),
        "font_family": "",
        "font_size": 0.0,
        "line_height": 0.0,
        "color": "rgba(0, 0, 0, 0)",
        "background_color": "rgba(0, 0, 0, 0)",
        "natural_width": natural_width,
        "natural_height": natural_height,
        "rendered_image_width": width,
        "rendered_image_height": height,
    }


def test_text_probe_carries_font_content_contrast_and_rendered_text_hash(tmp_path):
    fragment = _fragment("frag-1", "清洁是早晨第一步")
    element = _text_element("text-1", "frag-1")
    page = PageScene(
        page_id="page-1",
        sequence=1,
        background=PAGE_BACKGROUND,
        elements=(element,),
    )
    raw = _raw_text_probe("text-1", content_ref="frag-1")

    probes = build_element_probes(
        raw_probes=[raw],
        page=page,
        fragments={"frag-1": fragment},
        assets={},
        page_background=PAGE_BACKGROUND,
    )

    assert len(probes) == 1
    probe = probes[0]
    assert probe.kind == "text"
    assert probe.element_id == "text-1"
    assert probe.actual_box == Box(x=80, y=120, width=920, height=160)
    assert probe.computed_font_family == '"Test Display", sans-serif'
    assert probe.computed_font_size == 48.0
    assert probe.computed_line_height == 62.4
    assert probe.content_ref == "frag-1"
    # rasterized_text_sha256 binds to the actual rendered fragment text bytes
    assert probe.rasterized_text_sha256 == hashlib.sha256(
        "清洁是早晨第一步".encode("utf-8")
    ).hexdigest()
    # contrast is a real WCAG ratio between dark text and white background
    assert 0.0 <= probe.contrast_ratio <= 21.0
    # #1A1A1A on #FFFFFF is well above the WCAG AAA threshold.
    assert probe.contrast_ratio > 10.0
    # scroll/client dimensions are reflected onto the probe
    assert probe.overflow is False
    assert probe.asset_ref is None
    assert probe.rendered_asset_sha256 is None


def test_text_probe_flags_overflow_when_scroll_exceeds_client():
    fragment = _fragment("frag-1", "短文本")
    element = _text_element("text-1", "frag-1")
    page = PageScene(
        page_id="page-1",
        sequence=1,
        background=PAGE_BACKGROUND,
        elements=(element,),
    )
    raw = _raw_text_probe(
        "text-1",
        content_ref="frag-1",
        scroll_width=1200,
        scroll_height=150,
        client_width=920,
        client_height=160,
    )

    probes = build_element_probes(
        raw_probes=[raw],
        page=page,
        fragments={"frag-1": fragment},
        assets={},
        page_background=PAGE_BACKGROUND,
    )

    assert probes[0].overflow is True


def test_text_probe_flags_layout_clipped_when_box_exceeds_canvas():
    fragment = _fragment("frag-1", "标题")
    element = _text_element("text-1", "frag-1")
    page = PageScene(
        page_id="page-1",
        sequence=1,
        background=PAGE_BACKGROUND,
        elements=(element,),
    )
    raw = _raw_text_probe(
        "text-1",
        content_ref="frag-1",
        x=900.0,
        y=1380.0,
        width=400.0,
        height=200.0,
    )

    probes = build_element_probes(
        raw_probes=[raw],
        page=page,
        fragments={"frag-1": fragment},
        assets={},
        page_background=PAGE_BACKGROUND,
    )

    assert probes[0].layout_clipped is True
    assert probes[0].ink_clipped is True


def test_text_probe_contrast_falls_back_to_page_background_when_transparent():
    fragment = _fragment("frag-1", "标题")
    element = _text_element("text-1", "frag-1", color="#1A1A1A")
    page = PageScene(
        page_id="page-1",
        sequence=1,
        background=PAGE_BACKGROUND,
        elements=(element,),
    )
    raw = _raw_text_probe(
        "text-1",
        content_ref="frag-1",
        background_color="rgba(0, 0, 0, 0)",
    )

    probes = build_element_probes(
        raw_probes=[raw],
        page=page,
        fragments={"frag-1": fragment},
        assets={},
        page_background=PAGE_BACKGROUND,
    )

    # The fallback should produce the same contrast as against solid white.
    fallback = probes[0]
    solid = build_element_probes(
        raw_probes=[_raw_text_probe("text-1", content_ref="frag-1")],
        page=page,
        fragments={"frag-1": fragment},
        assets={},
        page_background=PAGE_BACKGROUND,
    )[0]
    assert fallback.contrast_ratio == pytest.approx(solid.contrast_ratio)


def test_text_probe_contrast_uses_shape_panel_behind_text():
    """Render QA must measure text against the shape panel painted behind it,
    not the page background. A light-text-on-dark-panel design is legible and
    must not be falsely reported as low contrast (regression for run 12)."""
    fragment = _fragment("frag-1", "标题")
    text = _text_element("text-1", "frag-1", color="#F3FFFF")
    panel = ShapeElement(
        element_id="panel-1",
        layer=0,
        box=Box(x=80, y=120, width=920, height=160),
        shape="rectangle",
        fill="#0E5A5A",
    )
    page = PageScene(
        page_id="page-1",
        sequence=1,
        background=PAGE_BACKGROUND,
        elements=(panel, text),
    )
    raw = _raw_text_probe(
        "text-1",
        content_ref="frag-1",
        color="rgb(243, 255, 255)",
        background_color="rgba(0, 0, 0, 0)",
    )
    raw_panel = {
        "element_id": "panel-1",
        "content_ref": None,
        "asset_ref": None,
        "x": 80.0,
        "y": 120.0,
        "width": 920.0,
        "height": 160.0,
        "scroll_width": 920,
        "scroll_height": 160,
        "client_width": 920,
        "client_height": 160,
        "font_family": "",
        "font_size": 0.0,
        "line_height": 0.0,
        "color": "rgba(0, 0, 0, 0)",
        "background_color": "rgb(14, 90, 90)",
        "natural_width": None,
        "natural_height": None,
        "rendered_image_width": None,
        "rendered_image_height": None,
    }

    probes = build_element_probes(
        raw_probes=[raw, raw_panel],
        page=page,
        fragments={"frag-1": fragment},
        assets={},
        page_background=PAGE_BACKGROUND,
    )

    # #F3FFFF on #0E5A5A is a high-contrast pair (well above the 3:1 large-text
    # threshold). Against the white page background it would be ~1.0:1.
    assert probes[0].contrast_ratio >= 3.0


def test_image_probe_carries_asset_hash_focal_point_and_crop_box(tmp_path):
    payload = b"\x89PNG\r\n\x1a\nasset-bytes"
    asset_path = tmp_path / "asset.png"
    asset_path.write_bytes(payload)
    asset = _asset_item("asset-1", path=str(asset_path), payload=payload)
    element = _image_element("image-1", "asset-1", focal=(0.25, 0.75))
    page = PageScene(
        page_id="page-1",
        sequence=1,
        background=PAGE_BACKGROUND,
        elements=(element,),
    )
    raw = _raw_image_probe("image-1", asset_ref="asset-1")

    probes = build_element_probes(
        raw_probes=[raw],
        page=page,
        fragments={},
        assets={"asset-1": asset},
        page_background=PAGE_BACKGROUND,
    )

    assert len(probes) == 1
    probe = probes[0]
    assert probe.kind == "image"
    assert probe.asset_ref == "asset-1"
    # rendered_asset_sha256 binds to the actual file bytes on disk
    assert probe.rendered_asset_sha256 == hashlib.sha256(payload).hexdigest()
    assert probe.actual_focal_point == (0.25, 0.75)
    assert probe.crop_box is not None
    assert probe.crop_box == Box(x=80, y=400, width=920, height=720)
    assert probe.content_ref is None
    assert probe.rasterized_text_sha256 is None


def test_image_probe_crop_box_is_clamped_to_canvas(tmp_path):
    payload = b"asset-bytes-clamped"
    asset_path = tmp_path / "asset.png"
    asset_path.write_bytes(payload)
    asset = _asset_item("asset-1", path=str(asset_path), payload=payload)
    # Element extends beyond the canvas on the right and bottom.
    element = _image_element(
        "image-1",
        "asset-1",
        box=Box(x=900, y=1300, width=400, height=400),
    )
    page = PageScene(
        page_id="page-1",
        sequence=1,
        background=PAGE_BACKGROUND,
        elements=(element,),
    )
    raw = _raw_image_probe(
        "image-1",
        asset_ref="asset-1",
        x=900.0,
        y=1300.0,
        width=400.0,
        height=400.0,
    )

    probe = build_element_probes(
        raw_probes=[raw],
        page=page,
        fragments={},
        assets={"asset-1": asset},
        page_background=PAGE_BACKGROUND,
    )[0]

    # crop_box is the visible rectangle intersected with the canvas.
    assert probe.crop_box == Box(x=900, y=1300, width=180, height=140)
    assert probe.layout_clipped is True


def test_every_planned_element_produces_one_probe_in_scene_order(tmp_path):
    payload = b"asset-bytes-mixed"
    asset_path = tmp_path / "asset.png"
    asset_path.write_bytes(payload)
    asset = _asset_item("asset-1", path=str(asset_path), payload=payload)
    frag = _fragment("frag-1", "复合场景文本")
    elements = (
        _image_element("image-1", "asset-1"),
        _text_element("text-1", "frag-1"),
        ShapeElement(
            element_id="shape-1",
            layer=2,
            box=Box(x=80, y=1180, width=920, height=80),
            shape="rectangle",
            fill="#F4A7BF",
        ),
        LineElement(
            element_id="line-1",
            layer=3,
            start=(80.0, 1280.0),
            end=(1000.0, 1280.0),
            color="#1A1A1A",
            width=2,
        ),
        IconElement(
            element_id="icon-1",
            layer=4,
            box=Box(x=500, y=700, width=80, height=80),
            icon="sparkle",
            color="#D45D4C",
        ),
    )
    page = PageScene(
        page_id="page-1",
        sequence=1,
        background=PAGE_BACKGROUND,
        elements=elements,
    )
    raws = [
        _raw_image_probe("image-1", asset_ref="asset-1"),
        _raw_text_probe("text-1", content_ref="frag-1"),
        {
            "element_id": "shape-1",
            "content_ref": None,
            "asset_ref": None,
            "x": 80.0,
            "y": 1180.0,
            "width": 920.0,
            "height": 80.0,
            "scroll_width": 920,
            "scroll_height": 80,
            "client_width": 920,
            "client_height": 80,
            "font_family": "",
            "font_size": 0.0,
            "line_height": 0.0,
            "color": "rgba(0, 0, 0, 0)",
            "background_color": "rgb(244, 167, 191)",
            "natural_width": None,
            "natural_height": None,
            "rendered_image_width": None,
            "rendered_image_height": None,
        },
        {
            "element_id": "line-1",
            "content_ref": None,
            "asset_ref": None,
            "x": 80.0,
            "y": 1280.0,
            "width": 920.0,
            "height": 2.0,
            "scroll_width": 920,
            "scroll_height": 2,
            "client_width": 920,
            "client_height": 2,
            "font_family": "",
            "font_size": 0.0,
            "line_height": 0.0,
            "color": "rgb(26, 26, 26)",
            "background_color": "rgba(0, 0, 0, 0)",
            "natural_width": None,
            "natural_height": None,
            "rendered_image_width": None,
            "rendered_image_height": None,
        },
        {
            "element_id": "icon-1",
            "content_ref": None,
            "asset_ref": None,
            "x": 500.0,
            "y": 700.0,
            "width": 80.0,
            "height": 80.0,
            "scroll_width": 80,
            "scroll_height": 80,
            "client_width": 80,
            "client_height": 80,
            "font_family": "",
            "font_size": 0.0,
            "line_height": 0.0,
            "color": "rgb(212, 93, 76)",
            "background_color": "rgba(0, 0, 0, 0)",
            "natural_width": None,
            "natural_height": None,
            "rendered_image_width": None,
            "rendered_image_height": None,
        },
    ]

    probes = build_element_probes(
        raw_probes=raws,
        page=page,
        fragments={"frag-1": frag},
        assets={"asset-1": asset},
        page_background=PAGE_BACKGROUND,
    )

    assert [probe.element_id for probe in probes] == [
        "image-1",
        "text-1",
        "shape-1",
        "line-1",
        "icon-1",
    ]
    assert [probe.kind for probe in probes] == [
        "image",
        "text",
        "shape",
        "line",
        "icon",
    ]


def test_icon_probe_does_not_flag_font_metric_overflow():
    """A decorative icon's font glyph can report scroll dims exceeding its
    client box without any visible ink being lost; that must not be treated as
    overflow / ink clipping (render QA was falsely rejecting such icons)."""
    frag = _fragment("frag-1", "文本")
    icon = IconElement(
        element_id="icon-1",
        layer=1,
        box=Box(x=500, y=700, width=80, height=80),
        icon="check",
        color="#1E5A2E",
    )
    page = PageScene(
        page_id="page-1",
        sequence=1,
        background=PAGE_BACKGROUND,
        elements=(icon,),
    )
    raw = {
        "element_id": "icon-1",
        "content_ref": None,
        "asset_ref": None,
        "x": 500.0,
        "y": 700.0,
        "width": 80.0,
        "height": 80.0,
        # Font metrics report the glyph overflowing the 80px client box.
        "scroll_width": 120,
        "scroll_height": 120,
        "client_width": 80,
        "client_height": 80,
        "font_family": "",
        "font_size": 0.0,
        "line_height": 0.0,
        "color": "rgb(30, 90, 46)",
        "background_color": "rgba(0, 0, 0, 0)",
        "natural_width": None,
        "natural_height": None,
        "rendered_image_width": None,
        "rendered_image_height": None,
    }

    probes = build_element_probes(
        raw_probes=[raw],
        page=page,
        fragments={"frag-1": frag},
        assets={},
        page_background=PAGE_BACKGROUND,
    )

    assert probes[0].overflow is False
    assert probes[0].ink_clipped is False


def test_probe_builder_ignores_raw_probes_for_unknown_element_ids(tmp_path):
    frag = _fragment("frag-1", "已知文本")
    element = _text_element("text-1", "frag-1")
    page = PageScene(
        page_id="page-1",
        sequence=1,
        background=PAGE_BACKGROUND,
        elements=(element,),
    )
    raws = [
        _raw_text_probe("text-1", content_ref="frag-1"),
        # Stray probe without a matching scene element must be dropped.
        _raw_text_probe("phantom", content_ref="frag-1"),
    ]

    probes = build_element_probes(
        raw_probes=raws,
        page=page,
        fragments={"frag-1": frag},
        assets={},
        page_background=PAGE_BACKGROUND,
    )

    assert [probe.element_id for probe in probes] == ["text-1"]


def test_probe_builder_rejects_text_element_missing_from_raw_probes():
    frag = _fragment("frag-1", "文本")
    element = _text_element("text-1", "frag-1")
    page = PageScene(
        page_id="page-1",
        sequence=1,
        background=PAGE_BACKGROUND,
        elements=(element,),
    )

    with pytest.raises(ValueError, match="missing.*text-1"):
        build_element_probes(
            raw_probes=[],
            page=page,
            fragments={"frag-1": frag},
            assets={},
            page_background=PAGE_BACKGROUND,
        )


def test_text_probe_preserves_zero_font_size_and_line_height():
    # M3: a latent falsy-zero bug. `raw.get("font_size") or None` would turn a
    # legitimate 0.0 into None, which then fails the text-probe kind attestation
    # (font_size is required). Real Chromium never returns 0 for text, but the
    # numeric fields must be guarded with an explicit `is not None` check.
    fragment = _fragment("frag-1", "短文本")
    element = _text_element("text-1", "frag-1")
    page = PageScene(
        page_id="page-1",
        sequence=1,
        background=PAGE_BACKGROUND,
        elements=(element,),
    )
    raw = _raw_text_probe(
        "text-1",
        content_ref="frag-1",
        font_size=0.0,
        line_height=0.0,
    )

    probes = build_element_probes(
        raw_probes=[raw],
        page=page,
        fragments={"frag-1": fragment},
        assets={},
        page_background=PAGE_BACKGROUND,
    )

    probe = probes[0]
    assert probe.kind == "text"
    assert probe.computed_font_size == 0.0
    assert probe.computed_line_height == 0.0


def test_text_probe_surfaces_scroll_client_and_line_boxes():
    """I3: the measured scroll/client box and per-line rects are surfaced."""
    fragment = _fragment("frag-1", "清晨第一步温和清洁")
    element = _text_element("text-1", "frag-1")
    page = PageScene(
        page_id="page-1",
        sequence=1,
        background=PAGE_BACKGROUND,
        elements=(element,),
    )
    raw = _raw_text_probe(
        "text-1",
        content_ref="frag-1",
        scroll_width=1400,
        scroll_height=320,
        client_width=920,
        client_height=160,
        line_boxes=[
            {"x": 80.0, "y": 120.0, "width": 920.0, "height": 80.0},
            {"x": 80.0, "y": 208.0, "width": 900.0, "height": 80.0},
            # Degenerate rects must be dropped, not clamped into phantom lines.
            {"x": 0.0, "y": 0.0, "width": 0.0, "height": 80.0},
            {"x": 0.0, "y": 0.0, "width": 10.0, "height": -5.0},
            "not-a-dict",
        ],
    )

    probes = build_element_probes(
        raw_probes=[raw],
        page=page,
        fragments={"frag-1": fragment},
        assets={},
        page_background=PAGE_BACKGROUND,
    )

    probe = probes[0]
    assert probe.scroll_width == 1400
    assert probe.scroll_height == 320
    assert probe.client_width == 920
    assert probe.client_height == 160
    assert probe.line_boxes == (
        Box(x=80.0, y=120.0, width=920.0, height=80.0),
        Box(x=80.0, y=208.0, width=900.0, height=80.0),
    )


def test_image_probe_surfaces_natural_dimensions(tmp_path):
    """I3: the <img> intrinsic dimensions are surfaced on image probes."""
    asset_payload_path = tmp_path / "asset.png"
    asset_payload_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    payload_digest = hashlib.sha256(asset_payload_path.read_bytes()).hexdigest()
    asset = AssetManifestItem(
        asset_id="asset-1",
        directive_id="directive-1",
        page_id="page-1",
        source_kind="catalog",
        provider="catalog",
        license="project-owned",
        local_path=str(asset_payload_path),
        width=2160,
        height=2880,
        sha256=payload_digest,
        subject_focal_point=(0.5, 0.5),
        crop_guidance="centered",
        security_status="approved",
        human_decision="pending",
        run_id="run-1",
        transaction_id="tx-1",
        internal_provenance={"provider": "catalog"},
    )
    element = ImageElement(
        element_id="image-1",
        layer=1,
        box=Box(x=80, y=400, width=920, height=720),
        asset_ref="asset-1",
        fit="cover",
        focal_point=(0.5, 0.5),
        corner_radius=0.0,
    )
    page = PageScene(
        page_id="page-1",
        sequence=1,
        background=PAGE_BACKGROUND,
        elements=(element,),
    )
    raw = _raw_image_probe(
        "image-1", asset_ref="asset-1", natural_width=2160, natural_height=2880
    )

    probes = build_element_probes(
        raw_probes=[raw],
        page=page,
        fragments={},
        assets={"asset-1": asset},
        page_background=PAGE_BACKGROUND,
    )

    probe = probes[0]
    assert probe.natural_width == 2160
    assert probe.natural_height == 2880
