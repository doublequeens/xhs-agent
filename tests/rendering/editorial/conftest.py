from __future__ import annotations

import hashlib
import html
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from PIL import Image

from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.storyboard import CarouselFrame, CarouselPayload
from src.schemas.visual_plan import VisualPlan


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
TEST_ASSET_PATH = (
    REPOSITORY_ROOT
    / "assets/visual/beauty-editorial-v1/active/textures/serum-drops.svg"
)

FRAME_SPECS = (
    ("cover", "cover", "cover"),
    ("baseline", "texture baseline", "explanation"),
    ("zone", "front face zone", "diagnostic"),
    ("choice", "decision/tree", "qa"),
    ("save", "saveable reference", "save"),
)


def make_frame(
    page_archetype: str,
    *,
    frame_id: str = "frame",
    role: str = "detail",
) -> CarouselFrame:
    return CarouselFrame.model_validate(
        {
            "frame_id": frame_id,
            "role": role,
            "page_archetype": page_archetype,
            "content_density_hint": "auto",
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
    page_archetype: str,
    *,
    slot_id: str = "frame-visual",
    path: Path = TEST_ASSET_PATH,
) -> AssetManifestItem:
    return AssetManifestItem.model_validate(
        {
            "slot_id": slot_id,
            "role": "product_texture",
            "page_archetype": page_archetype,
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
            "design_system": "beauty_editorial_v2",
            "template_family": "pink_red",
            "template_selection": {
                "template_family": "pink_red",
                "score": 10,
                "reasons": ["deterministic renderer fixture"],
                "rejected_families": {
                    family: ["not selected in deterministic renderer fixture"]
                    for family in (
                        "deep_teal",
                        "soft_pink",
                        "coral_impact",
                        "green_catalog",
                        "white_quote",
                    )
                },
            },
            "narrative_form": "scenario_story",
            "content_job": "diagnose_and_adjust",
            "frame_plan": [
                {
                    "frame_id": frame_id,
                    "role": role,
                    "page_archetype": page_archetype,
                    "purpose": f"render {role}",
                    "allowed_density": ["standard"],
                    "asset_roles": ["product_texture"],
                }
                for frame_id, role, page_archetype in FRAME_SPECS
            ],
            "required_assets": [],
        }
    )


@pytest.fixture
def storyboard() -> CarouselPayload:
    return CarouselPayload(
        storyboards=[
            make_frame(page_archetype, frame_id=frame_id, role=role)
            for frame_id, role, page_archetype in FRAME_SPECS
        ]
    )


@pytest.fixture
def asset_manifest() -> AssetManifest:
    items = [
        make_asset(page_archetype, slot_id=f"{frame_id}-visual")
        for frame_id, _role, page_archetype in FRAME_SPECS
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
        size = (1080, 1440) if self.selector == ".card" else (1320, 2400)
        Image.new("RGB", size, "white").save(path, format="PNG")
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
        self.font_report = font_report
        self.probe_issues = probe_issues or []
        self.fail_screenshot_at = fail_screenshot_at
        self.fail_before_write_at = fail_before_write_at
        self.screenshot_calls = 0
        self.events: list[str] = []
        self.loaded_html: list[str] = []

    def _layout_report(self) -> dict:
        document = self.loaded_html[-1]
        display_family = re.search(
            r'data-display-font-family="([^"]+)"',
            document,
        ).group(1)
        body_family = re.search(
            r'data-body-font-family="([^"]+)"',
            document,
        ).group(1)

        class CopyParser(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self.active: dict | None = None
                self.depth = 0
                self.matches: list[dict] = []

            def handle_starttag(self, tag, attrs):
                values = dict(attrs)
                # void elements (br/img/...) have no end tag, so they must not
                # increment the nesting depth — otherwise a <br> inside a copy
                # atom would never let the atom close (mirrors the real probe,
                # which reads textContent and is unaffected by <br>).
                _VOID = frozenset({
                    "area", "base", "br", "col", "embed", "hr", "img",
                    "input", "link", "meta", "param", "source", "track", "wbr",
                })
                if self.active is not None:
                    if tag not in _VOID:
                        self.depth += 1
                    emoji = values.get("data-emoji-grapheme")
                    if emoji is not None:
                        self.active["emoji_graphemes"].append(emoji)
                    return
                if "data-card-copy" in values:
                    self.active = {
                        "tag": tag,
                        "role": values["data-copy-role"],
                        "text": [],
                        "emoji_graphemes": [],
                    }
                    self.depth = 0

            def handle_endtag(self, tag):
                if self.active is None:
                    return
                if self.depth:
                    self.depth -= 1
                    return
                if tag == self.active["tag"]:
                    self.matches.append(self.active)
                    self.active = None

            def handle_data(self, data):
                if self.active is not None:
                    self.active["text"].append(data)

        parser = CopyParser()
        parser.feed(document)
        texts = []
        for match in parser.matches:
            role = match["role"]
            value = html.unescape("".join(match["text"]))
            if role == "headline":
                font_family, font_size, line_height = (
                    display_family,
                    64.0,
                    74.88,
                )
            elif role.endswith(".body") or ".items[" in role:
                font_family, font_size, line_height = (
                    body_family,
                    29.0,
                    42.05,
                )
            else:
                font_family, font_size, line_height = (
                    body_family,
                    25.0,
                    33.0,
                )
            texts.append(
                {
                    "role": role,
                    "text": value,
                    "emoji_graphemes": match["emoji_graphemes"],
                    "visible": True,
                    "overflow": False,
                    "ink_clipped": False,
                    "layout_clipped": False,
                    "font_family": font_family,
                    "font_size": font_size,
                    "line_height": line_height,
                    "line_count": 1,
                    "x": 84.0,
                    "y": 84.0,
                    "width": 400.0,
                    "height": line_height,
                }
            )
        slots = re.findall(r'data-asset-slot="([^"]+)"', document)
        return {
            "canvas": {"width": 1080, "height": 1440},
            "safe_margin": 84.0,
            "texts": texts,
            "assets": [
                {
                    "slot_id": slot,
                    "natural_width": 1080,
                    "natural_height": 1440,
                    "rendered_width": 360.0,
                    "rendered_height": 480.0,
                    "object_fit": "contain",
                    "cropped": False,
                    "aspect_ratio_error": 0.0,
                }
                for slot in slots
            ],
            "issues": self.probe_issues,
        }

    def set_viewport_size(self, size: dict[str, int]) -> None:
        self.events.append(f"viewport:{size['width']}x{size['height']}")

    def goto(self, url: str, *, wait_until: str) -> None:
        self.events.append(f"goto:{wait_until}")
        assert url.startswith("file:")
        self.loaded_html.append(Path(url.removeprefix("file://")).read_text(encoding="utf-8"))

    def evaluate(self, script: str):
        if "EDITORIAL_FONT_PROBE" in script:
            self.events.append("fonts-ready")
            if self.font_report is not None:
                return self.font_report
            document = self.loaded_html[-1]
            return {
                "all_loaded": True,
                "computed_families": [
                    re.search(
                        r'data-display-font-family="([^"]+)"',
                        document,
                    ).group(1),
                    re.search(
                        r'data-body-font-family="([^"]+)"',
                        document,
                    ).group(1),
                    re.search(
                        r'data-emoji-font-family="([^"]+)"',
                        document,
                    ).group(1),
                ],
            }
        if "EDITORIAL_LAYOUT_PROBE" in script:
            self.events.append("layout-probe")
            return self._layout_report()
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
