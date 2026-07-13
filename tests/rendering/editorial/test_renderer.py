from __future__ import annotations

from pathlib import Path

import pytest

from conftest import FakePage, fake_playwright


def test_renderer_uses_repo_fonts_without_system_fallback(
    tmp_path, visual_plan, storyboard, asset_manifest
):
    from src.rendering.editorial.renderer import render_carousel

    page = FakePage()
    manifest = render_carousel(
        visual_plan,
        storyboard,
        asset_manifest,
        tmp_path,
        playwright_factory=fake_playwright(page),
    )

    assert manifest.fonts.all_loaded is True
    assert set(manifest.fonts.computed_families) == {
        "Source Han Serif SC",
        "Source Han Sans SC",
        "Bodoni Moda",
    }
    assert all("document.fonts" in html for html in page.loaded_html[:5])
    assert all("@font-face" in html for html in page.loaded_html[:5])
    assert all("PingFang" not in html for html in page.loaded_html[:5])
    assert all("http://" not in html and "https://" not in html for html in page.loaded_html)


def test_renderer_emits_ordered_manifest_contact_sheet_and_source_hashes(
    tmp_path, visual_plan, storyboard, asset_manifest
):
    from src.rendering.editorial.renderer import render_carousel

    page = FakePage()
    manifest = render_carousel(
        visual_plan,
        storyboard,
        asset_manifest,
        tmp_path,
        playwright_factory=fake_playwright(page),
    )

    assert [Path(item.path).name for item in manifest.pages] == [
        "01-cover.png",
        "02-texture-baseline.png",
        "03-front-face-zone.png",
        "04-decision-tree.png",
        "05-saveable-reference.png",
    ]
    assert all((item.width, item.height) == (1080, 1440) for item in manifest.pages)
    assert Path(manifest.contact_sheet_path) == tmp_path / "contact-sheet.png"
    assert (tmp_path / "contact-sheet.png").is_file()
    assert manifest.source_asset_sha256 == {
        item.slot_id: item.sha256 for item in asset_manifest.items
    }
    assert not list(tmp_path.glob("*.html"))
    assert 'class="contact-sheet"' in page.loaded_html[-1]
    assert page.events.count("fonts-ready") == 6
    assert page.events.count("layout-probe") == 5


def test_renderer_waits_for_fonts_and_probes_before_each_card_screenshot(
    tmp_path, visual_plan, storyboard, asset_manifest
):
    from src.rendering.editorial.renderer import render_carousel

    page = FakePage()
    render_carousel(
        visual_plan,
        storyboard,
        asset_manifest,
        tmp_path,
        playwright_factory=fake_playwright(page),
    )

    for index, event in enumerate(page.events):
        if event.startswith("screenshot:.card"):
            assert page.events[index - 2:index] == ["fonts-ready", "layout-probe"]


@pytest.mark.parametrize(
    ("page", "message"),
    [
        (
            FakePage(
                font_report={
                    "all_loaded": False,
                    "computed_families": ["Source Han Sans SC"],
                }
            ),
            "font",
        ),
        (FakePage(probe_issues=[{"kind": "overflow", "role": "headline"}]), "probe"),
        (FakePage(fail_screenshot_at=3), "screenshot"),
    ],
    ids=["font", "probe", "screenshot"],
)
def test_renderer_removes_every_invocation_output_on_failure(
    tmp_path,
    visual_plan,
    storyboard,
    asset_manifest,
    page,
    message,
):
    from src.rendering.editorial.renderer import (
        EditorialCarouselRenderError,
        render_carousel,
    )

    unrelated = tmp_path / "keep.png"
    unrelated.write_bytes(b"pre-existing")

    with pytest.raises(EditorialCarouselRenderError, match=message):
        render_carousel(
            visual_plan,
            storyboard,
            asset_manifest,
            tmp_path,
            playwright_factory=fake_playwright(page),
        )

    assert unrelated.read_bytes() == b"pre-existing"
    assert list(tmp_path.glob("*.png")) == [unrelated]
    assert not list(tmp_path.glob("*.html"))


def test_renderer_rejects_plan_storyboard_drift_before_launch(
    tmp_path, visual_plan, storyboard, asset_manifest
):
    from src.rendering.editorial.renderer import (
        EditorialCarouselRenderError,
        render_carousel,
    )

    drifted = storyboard.model_copy(
        update={
            "storyboards": [
                storyboard.storyboards[0].model_copy(update={"frame_id": "wrong"}),
                *storyboard.storyboards[1:],
            ]
        }
    )

    with pytest.raises(EditorialCarouselRenderError, match="does not match"):
        render_carousel(
            visual_plan,
            drifted,
            asset_manifest,
            tmp_path,
            playwright_factory=lambda: pytest.fail("browser must not launch"),
        )
