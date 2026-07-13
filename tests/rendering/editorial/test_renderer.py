from __future__ import annotations

from pathlib import Path

import pytest

from conftest import FakePage, fake_playwright


FINAL_NAMES = (
    "01-cover.png",
    "02-texture-baseline.png",
    "03-front-face-zone.png",
    "04-decision-tree.png",
    "05-saveable-reference.png",
    "contact-sheet.png",
)


def _existing_complete_set(output_dir: Path) -> dict[str, bytes]:
    output_dir.mkdir()
    old = {name: f"old:{name}".encode() for name in FINAL_NAMES}
    for name, content in old.items():
        (output_dir / name).write_bytes(content)
    return old


def _assert_existing_set_unchanged(output_dir: Path, old: dict[str, bytes]) -> None:
    assert {path.name: path.read_bytes() for path in output_dir.glob("*.png")} == old
    assert not list(output_dir.parent.glob(f".{output_dir.name}.editorial-*"))


def _add_unrelated_entries(output_dir: Path) -> None:
    (output_dir / "review-notes.json").write_text('{"keep": true}', encoding="utf-8")
    (output_dir / "audit").mkdir()
    (output_dir / "audit/source.txt").write_text("preserve me", encoding="utf-8")


def _assert_unrelated_entries_preserved(output_dir: Path) -> None:
    assert (output_dir / "review-notes.json").read_text(
        encoding="utf-8"
    ) == '{"keep": true}'
    assert (output_dir / "audit/source.txt").read_text(encoding="utf-8") == "preserve me"


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


@pytest.mark.parametrize(
    "page",
    [FakePage(fail_screenshot_at=3), FakePage(fail_before_write_at=3)],
    ids=["after-write", "before-write"],
)
def test_failed_screenshot_preserves_an_existing_complete_output_set(
    tmp_path, visual_plan, storyboard, asset_manifest, page
):
    from src.rendering.editorial.renderer import (
        EditorialCarouselRenderError,
        render_carousel,
    )

    output_dir = tmp_path / "images"
    old = _existing_complete_set(output_dir)

    with pytest.raises(EditorialCarouselRenderError, match="screenshot"):
        render_carousel(
            visual_plan,
            storyboard,
            asset_manifest,
            output_dir,
            playwright_factory=fake_playwright(page),
        )

    _assert_existing_set_unchanged(output_dir, old)


def test_browser_close_failure_preserves_an_existing_complete_output_set(
    tmp_path, visual_plan, storyboard, asset_manifest
):
    from src.rendering.editorial.renderer import (
        EditorialCarouselRenderError,
        render_carousel,
    )

    output_dir = tmp_path / "images"
    old = _existing_complete_set(output_dir)

    with pytest.raises(EditorialCarouselRenderError, match="browser close"):
        render_carousel(
            visual_plan,
            storyboard,
            asset_manifest,
            output_dir,
            playwright_factory=fake_playwright(
                FakePage(), close_error=RuntimeError("browser close failed")
            ),
        )

    _assert_existing_set_unchanged(output_dir, old)


def test_temporary_html_cleanup_failure_preserves_existing_complete_output_set(
    tmp_path, visual_plan, storyboard, asset_manifest, monkeypatch
):
    from src.rendering.editorial import renderer

    output_dir = tmp_path / "images"
    old = _existing_complete_set(output_dir)

    def fail_cleanup(_paths):
        raise renderer.EditorialCarouselRenderError("temporary HTML cleanup failed")

    monkeypatch.setattr(renderer, "_remove_paths", fail_cleanup)

    with pytest.raises(
        renderer.EditorialCarouselRenderError, match="temporary HTML cleanup"
    ):
        renderer.render_carousel(
            visual_plan,
            storyboard,
            asset_manifest,
            output_dir,
            playwright_factory=fake_playwright(FakePage()),
        )

    _assert_existing_set_unchanged(output_dir, old)


def test_successful_publication_preserves_non_renderer_owned_entries(
    tmp_path, visual_plan, storyboard, asset_manifest
):
    from src.rendering.editorial.renderer import render_carousel

    output_dir = tmp_path / "images"
    old = _existing_complete_set(output_dir)
    _add_unrelated_entries(output_dir)

    render_carousel(
        visual_plan,
        storyboard,
        asset_manifest,
        output_dir,
        playwright_factory=fake_playwright(FakePage()),
    )

    _assert_unrelated_entries_preserved(output_dir)
    assert all(
        (output_dir / name).read_bytes() != content for name, content in old.items()
    )
    assert not list(output_dir.parent.glob(f".{output_dir.name}.editorial-*"))


def test_first_publication_replace_failure_leaves_previous_directory_intact(
    tmp_path, visual_plan, storyboard, asset_manifest, monkeypatch
):
    from src.rendering.editorial import renderer

    output_dir = tmp_path / "images"
    old = _existing_complete_set(output_dir)
    _add_unrelated_entries(output_dir)
    original_replace = Path.replace

    def fail_first_replace(path, target):
        if path == output_dir:
            raise OSError("first replace failed")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_first_replace)

    with pytest.raises(renderer.EditorialCarouselRenderError, match="atomically publish"):
        renderer.render_carousel(
            visual_plan,
            storyboard,
            asset_manifest,
            output_dir,
            playwright_factory=fake_playwright(FakePage()),
        )

    _assert_existing_set_unchanged(output_dir, old)
    _assert_unrelated_entries_preserved(output_dir)


def test_second_publication_replace_failure_rolls_back_complete_previous_directory(
    tmp_path, visual_plan, storyboard, asset_manifest, monkeypatch
):
    from src.rendering.editorial import renderer

    output_dir = tmp_path / "images"
    old = _existing_complete_set(output_dir)
    _add_unrelated_entries(output_dir)
    original_replace = Path.replace
    calls = 0

    def fail_second_replace(path, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("second replace failed")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_second_replace)

    with pytest.raises(renderer.EditorialCarouselRenderError, match="atomically publish"):
        renderer.render_carousel(
            visual_plan,
            storyboard,
            asset_manifest,
            output_dir,
            playwright_factory=fake_playwright(FakePage()),
        )

    assert calls == 3
    _assert_existing_set_unchanged(output_dir, old)
    _assert_unrelated_entries_preserved(output_dir)


def test_partial_backup_retirement_keeps_new_committed_set_and_quarantines_residue(
    tmp_path, visual_plan, storyboard, asset_manifest, monkeypatch
):
    from src.rendering.editorial import renderer

    output_dir = tmp_path / "images"
    old = _existing_complete_set(output_dir)
    _add_unrelated_entries(output_dir)
    original_rmtree = renderer.shutil.rmtree

    def partially_fail_retirement(path, *args, **kwargs):
        path = Path(path)
        if path.name.endswith((".backup", ".quarantine")):
            old_page = path / "01-cover.png"
            if old_page.exists():
                old_page.unlink()
            raise OSError("backup retirement partially failed")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(renderer.shutil, "rmtree", partially_fail_retirement)

    with pytest.warns(RuntimeWarning, match="quarantine"):
        manifest = renderer.render_carousel(
            visual_plan,
            storyboard,
            asset_manifest,
            output_dir,
            playwright_factory=fake_playwright(FakePage()),
        )

    assert all(Path(page.path).read_bytes() == b"fake png" for page in manifest.pages)
    assert (output_dir / "contact-sheet.png").read_bytes() == b"fake png"
    _assert_unrelated_entries_preserved(output_dir)
    quarantines = list(
        output_dir.parent.glob(f".{output_dir.name}.editorial-*.quarantine")
    )
    assert len(quarantines) == 1
    assert not list(output_dir.parent.glob(f".{output_dir.name}.editorial-*.staging"))


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


@pytest.mark.parametrize(
    ("duplicate_in", "message"),
    [
        ("visual_plan", "visual plan has duplicate frame_id"),
        ("storyboard", "storyboard has duplicate frame_id"),
        ("both", "visual plan has duplicate frame_id"),
    ],
)
def test_renderer_rejects_schema_valid_duplicate_frame_ids_before_browser_launch(
    tmp_path,
    visual_plan,
    storyboard,
    asset_manifest,
    duplicate_in,
    message,
):
    from src.rendering.editorial.renderer import (
        EditorialCarouselRenderError,
        render_carousel,
    )
    from src.schemas.storyboard import CarouselPayload
    from src.schemas.visual_plan import VisualPlan

    plan_data = visual_plan.model_dump(mode="python")
    storyboard_data = storyboard.model_dump(mode="python")
    if duplicate_in in {"visual_plan", "both"}:
        plan_data["frame_plan"][1]["frame_id"] = plan_data["frame_plan"][0]["frame_id"]
    if duplicate_in in {"storyboard", "both"}:
        storyboard_data["storyboards"][1]["frame_id"] = storyboard_data[
            "storyboards"
        ][0]["frame_id"]
    duplicate_plan = VisualPlan.model_validate(plan_data)
    duplicate_storyboard = CarouselPayload.model_validate(storyboard_data)

    with pytest.raises(EditorialCarouselRenderError, match=message):
        render_carousel(
            duplicate_plan,
            duplicate_storyboard,
            asset_manifest,
            tmp_path,
            playwright_factory=lambda: pytest.fail("browser must not launch"),
        )


def test_renderer_rejects_duplicate_visual_slot_ids_within_one_frame_before_browser(
    tmp_path, visual_plan, storyboard, asset_manifest
):
    from src.rendering.editorial.renderer import (
        EditorialCarouselRenderError,
        render_carousel,
    )
    from src.schemas.storyboard import CarouselPayload

    storyboard_data = storyboard.model_dump(mode="python")
    duplicate_slot = dict(storyboard_data["storyboards"][0]["visual_slots"][0])
    storyboard_data["storyboards"][0]["visual_slots"].append(duplicate_slot)
    duplicate_storyboard = CarouselPayload.model_validate(storyboard_data)

    with pytest.raises(EditorialCarouselRenderError, match="duplicate visual slot_id"):
        render_carousel(
            visual_plan,
            duplicate_storyboard,
            asset_manifest,
            tmp_path,
            playwright_factory=lambda: pytest.fail("browser must not launch"),
        )


def test_renderer_rejects_asset_layout_that_does_not_match_declared_frame_slot(
    tmp_path, visual_plan, storyboard, asset_manifest
):
    from src.rendering.editorial.renderer import (
        EditorialCarouselRenderError,
        render_carousel,
    )

    first = asset_manifest.items[0].model_copy(update={"layout": "decision_tree"})
    mismatched = asset_manifest.model_copy(
        update={"items": [first, *asset_manifest.items[1:]]}
    )

    with pytest.raises(EditorialCarouselRenderError, match="does not match"):
        render_carousel(
            visual_plan,
            storyboard,
            mismatched,
            tmp_path,
            playwright_factory=lambda: pytest.fail("browser must not launch"),
        )


def test_renderer_rejects_a_missing_declared_asset_slot_before_browser_launch(
    tmp_path, visual_plan, storyboard, asset_manifest
):
    from src.rendering.editorial.renderer import (
        EditorialCarouselRenderError,
        render_carousel,
    )

    missing = asset_manifest.model_copy(update={"items": asset_manifest.items[1:]})

    with pytest.raises(EditorialCarouselRenderError, match="cover-visual.*missing"):
        render_carousel(
            visual_plan,
            storyboard,
            missing,
            tmp_path,
            playwright_factory=lambda: pytest.fail("browser must not launch"),
        )


def test_renderer_rejects_tampered_bytes_for_an_actually_used_asset(
    tmp_path, visual_plan, storyboard, asset_manifest
):
    from src.rendering.editorial.renderer import (
        EditorialCarouselRenderError,
        render_carousel,
    )

    tampered_path = tmp_path / "tampered.svg"
    original = Path(asset_manifest.items[0].path)
    tampered_path.write_bytes(original.read_bytes() + b"<!-- tampered -->")
    tampered_item = asset_manifest.items[0].model_copy(
        update={"path": str(tampered_path)}
    )
    tampered = asset_manifest.model_copy(
        update={"items": [tampered_item, *asset_manifest.items[1:]]}
    )

    with pytest.raises(EditorialCarouselRenderError, match="sha256"):
        render_carousel(
            visual_plan,
            storyboard,
            tampered,
            tmp_path / "images",
            playwright_factory=lambda: pytest.fail("browser must not launch"),
        )


def test_renderer_ignores_and_does_not_record_an_unused_manifest_asset(
    tmp_path, visual_plan, storyboard, asset_manifest
):
    from src.rendering.editorial.renderer import render_carousel

    unused = asset_manifest.items[0].model_copy(
        update={
            "slot_id": "unused-slot",
            "path": str(tmp_path / "missing-unused.svg"),
            "sha256": "a" * 64,
        }
    )
    with_unused = asset_manifest.model_copy(
        update={"items": [*asset_manifest.items, unused]}
    )

    manifest = render_carousel(
        visual_plan,
        storyboard,
        with_unused,
        tmp_path / "images",
        playwright_factory=fake_playwright(FakePage()),
    )

    assert "unused-slot" not in manifest.source_asset_sha256
    assert manifest.source_asset_sha256 == {
        item.slot_id: item.sha256 for item in asset_manifest.items
    }
