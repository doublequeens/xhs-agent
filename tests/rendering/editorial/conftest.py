from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.storyboard import CarouselFrame, CarouselPayload
from src.schemas.visual_plan import VisualPlan


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
TEST_ASSET_PATH = (
    REPOSITORY_ROOT
    / "assets/visual/beauty-editorial-v1/active/textures/serum-drops.svg"
)

FRAME_SPECS = (
    ("cover", "cover", "editorial_cover"),
    ("baseline", "texture baseline", "texture_baseline"),
    ("zone", "front face zone", "front_face_zone"),
    ("choice", "decision/tree", "decision_tree"),
    ("save", "saveable reference", "saveable_reference"),
)


def make_frame(
    layout: str,
    *,
    frame_id: str = "frame",
    role: str = "detail",
) -> CarouselFrame:
    return CarouselFrame.model_validate(
        {
            "frame_id": frame_id,
            "role": role,
            "layout": layout,
            "headline": "先看懂 <分区> & 再调整",
            "kicker": '编辑型 "护肤"',
            "content_blocks": [
                {
                    "block_type": "text",
                    "heading": "判断基线",
                    "body": "根据肤感调整用量与等待时间。",
                },
                {
                    "block_type": "bullets",
                    "heading": "观察清单",
                    "items": ["先看触感", "再看光泽", "最后记录变化"],
                },
                {
                    "block_type": "comparison",
                    "heading": "左右对照",
                    "items": ["偏干：减少清洁", "稳定：保持节奏"],
                },
            ],
            "emphasis": ["肤感", "等待"],
            "visual_slots": [
                {
                    "slot_id": f"{frame_id}-visual",
                    "role": "product_texture",
                    "semantic_tags": ["serum"],
                    "composition": "right",
                    "palette_tags": ["mauve"],
                }
            ],
            "footer": "按当天状态微调",
        }
    )


def make_asset(
    layout: str,
    *,
    slot_id: str = "frame-visual",
    path: Path = TEST_ASSET_PATH,
) -> AssetManifestItem:
    return AssetManifestItem.model_validate(
        {
            "slot_id": slot_id,
            "role": "product_texture",
            "layout": layout,
            "status": "active",
            "path": str(path.resolve()),
            "asset_id": f"asset-{slot_id}",
            "source_type": "local_catalog",
            "license": "project-owned",
            "width": 1080,
            "height": 1440,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    )


@pytest.fixture
def visual_plan() -> VisualPlan:
    return VisualPlan.model_validate(
        {
            "design_system": "beauty_editorial_v1",
            "content_job": "diagnose_and_adjust",
            "primary_visual_family": "face_zone_map",
            "supporting_families": ["beauty_editorial", "saveable_reference"],
            "frame_plan": [
                {
                    "frame_id": frame_id,
                    "role": role,
                    "layout": layout,
                    "purpose": f"render {role}",
                    "asset_roles": ["product_texture"],
                }
                for frame_id, role, layout in FRAME_SPECS
            ],
            "required_assets": [],
        }
    )


@pytest.fixture
def storyboard() -> CarouselPayload:
    return CarouselPayload(
        storyboards=[
            make_frame(layout, frame_id=frame_id, role=role)
            for frame_id, role, layout in FRAME_SPECS
        ]
    )


@pytest.fixture
def asset_manifest() -> AssetManifest:
    items = [
        make_asset(layout, slot_id=f"{frame_id}-visual")
        for frame_id, _role, layout in FRAME_SPECS
    ]
    return AssetManifest.model_validate(
        {
            "items": [item.model_dump() for item in items],
            "search_report": {
                "search_triggered": False,
                "queries": [],
                "provider_reports": [],
                "selection_reasons": {},
            },
        }
    )


class FakeLocator:
    def __init__(self, page: "FakePage", selector: str) -> None:
        self.page = page
        self.selector = selector

    def screenshot(self, *, path: str) -> None:
        self.page.events.append(f"screenshot:{self.selector}:{Path(path).name}")
        self.page.screenshot_calls += 1
        if self.page.fail_before_write_at == self.page.screenshot_calls:
            raise RuntimeError("screenshot failed before write")
        Path(path).write_bytes(b"fake png")
        if self.page.fail_screenshot_at == self.page.screenshot_calls:
            raise RuntimeError("screenshot failed")


class FakePage:
    def __init__(
        self,
        *,
        font_report: dict | None = None,
        probe_issues: list[dict] | None = None,
        fail_screenshot_at: int | None = None,
        fail_before_write_at: int | None = None,
    ) -> None:
        self.font_report = font_report or {
            "all_loaded": True,
            "computed_families": [
                "Source Han Serif SC",
                "Source Han Sans SC",
                "Bodoni Moda",
            ],
        }
        self.probe_issues = probe_issues or []
        self.fail_screenshot_at = fail_screenshot_at
        self.fail_before_write_at = fail_before_write_at
        self.screenshot_calls = 0
        self.events: list[str] = []
        self.loaded_html: list[str] = []

    def set_viewport_size(self, size: dict[str, int]) -> None:
        self.events.append(f"viewport:{size['width']}x{size['height']}")

    def goto(self, url: str, *, wait_until: str) -> None:
        self.events.append(f"goto:{wait_until}")
        assert url.startswith("file:")
        self.loaded_html.append(Path(url.removeprefix("file://")).read_text(encoding="utf-8"))

    def evaluate(self, script: str):
        if "EDITORIAL_FONT_PROBE" in script:
            self.events.append("fonts-ready")
            return self.font_report
        if "EDITORIAL_LAYOUT_PROBE" in script:
            self.events.append("layout-probe")
            return self.probe_issues
        raise AssertionError("unexpected browser probe")

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)


class FakeBrowser:
    def __init__(self, page: FakePage, *, close_error: Exception | None = None) -> None:
        self.page = page
        self.closed = False
        self.close_error = close_error

    def new_page(self, **_kwargs) -> FakePage:
        return self.page

    def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class FakePlaywrightContext:
    def __init__(
        self, page: FakePage, *, close_error: Exception | None = None
    ) -> None:
        self.page = page
        self.browser = FakeBrowser(page, close_error=close_error)

        class Chromium:
            def __init__(self, browser: FakeBrowser) -> None:
                self.browser = browser

            def launch(self) -> FakeBrowser:
                return self.browser

        self.chromium = Chromium(self.browser)

    def __enter__(self) -> "FakePlaywrightContext":
        return self

    def __exit__(self, *_args) -> bool:
        return False


def fake_playwright(
    page: FakePage | None = None, *, close_error: Exception | None = None
):
    actual_page = page or FakePage()
    return lambda: FakePlaywrightContext(actual_page, close_error=close_error)
