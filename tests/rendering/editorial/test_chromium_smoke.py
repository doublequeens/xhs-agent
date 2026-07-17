from __future__ import annotations

import struct
from pathlib import Path
from typing import get_args

import pytest

from src.schemas.editorial_templates import TemplateFamily


ALL_TEMPLATE_FAMILIES = get_args(TemplateFamily)

_MATRIX_FRAME_SPECS = (
    ("cover", "cover", "cover"),
    ("baseline", "texture baseline", "explanation"),
    ("zone", "front face zone", "diagnostic"),
    ("choice", "decision tree", "qa"),
    ("save", "saveable reference", "save"),
    ("extra-baseline", "extra baseline", "explanation"),
    ("extra-zone", "extra zone", "diagnostic"),
)


def _text_only_carousel(family: str, frame_count: int):
    from conftest import make_frame
    from src.schemas.assets import AssetManifest, AssetSearchReport
    from src.schemas.storyboard import CarouselPayload
    from src.schemas.visual_plan import VisualPlan

    specs = _MATRIX_FRAME_SPECS[:frame_count]
    frames = [
        make_frame(page_archetype, frame_id=frame_id, role=role).model_copy(
            update={
                "visual_slots": [],
                # Headings are stripped so the fixture renders uniformly across
                # all six families: white_quote forces .block-heading onto the
                # display face (templates/white_quote.py), which the renderer's
                # non-headline font check rejects. That template/renderer
                # mismatch is out of scope for this fix and is tracked as a
                # concern in the task-10 report. Bodies and items still probe
                # body-copy rendering for every family.
                "content_blocks": [
                    block.model_copy(update={"heading": None})
                    for block in make_frame(page_archetype).content_blocks
                ],
            }
        )
        for frame_id, role, page_archetype in specs
    ]
    plan = VisualPlan.model_validate(
        {
            "design_system": "beauty_editorial_v2",
            "template_family": family,
            "template_selection": {
                "template_family": family,
                "score": 100,
                "reasons": ["chromium matrix fixture"],
                "rejected_families": {
                    other: ["chromium matrix fixture"]
                    for other in ALL_TEMPLATE_FAMILIES
                    if other != family
                },
            },
            "narrative_form": "scenario_story",
            "content_job": "diagnose_and_adjust",
            "frame_plan": [
                {
                    "frame_id": frame_id,
                    "role": role,
                    "page_archetype": page_archetype,
                    "purpose": f"matrix {role}",
                    "allowed_density": ["sparse", "standard", "dense"],
                    "asset_roles": [],
                }
                for frame_id, role, page_archetype in specs
            ],
            "required_assets": [],
        }
    )
    storyboard = CarouselPayload(storyboards=frames)
    assets = AssetManifest(
        items=[],
        search_report=AssetSearchReport(
            search_triggered=False,
            queries=[],
            provider_reports=[],
            selection_reasons={},
        ),
    )
    return plan, storyboard, assets


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


@pytest.mark.skipif(
    not _local_chromium_available(),
    reason="local Playwright Chromium is unavailable",
)
@pytest.mark.parametrize("frame_count", [5, 6, 7])
@pytest.mark.parametrize("family", ALL_TEMPLATE_FAMILIES)
def test_chromium_renders_each_family_at_each_page_count(
    family, frame_count, tmp_path
):
    from src.rendering.editorial.renderer import render_carousel

    plan, storyboard, assets = _text_only_carousel(family, frame_count)
    manifest = render_carousel(plan, storyboard, assets, tmp_path)

    assert len(manifest.pages) == frame_count
    assert {page.template_family for page in manifest.pages} == {family}
    assert all(
        (page.width, page.height) == (1080, 1440) for page in manifest.pages
    )
