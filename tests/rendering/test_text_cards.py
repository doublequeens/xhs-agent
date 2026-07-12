from __future__ import annotations

from pathlib import Path
import struct

import pytest

from src.schemas.text_card import TextCardPayload


def valid_payload() -> TextCardPayload:
    return TextCardPayload.model_validate(
        {
            "storyboards": [
                {
                    "frame_id": "frame_001",
                    "template": "cover_statement",
                    "theme": "warm_neutral",
                    "kicker": "通勤底妆",
                    "headline": "通勤前3步避开防晒搓泥",
                    "footer": "先防晒再上妆",
                },
                {
                    "frame_id": "frame_002",
                    "template": "wrong_vs_right",
                    "theme": "warm_neutral",
                    "kicker": "避坑对照",
                    "headline": "别让底妆越补越糟",
                    "footer": "对照后再执行",
                    "wrong_items": ["防晒刚涂就上妆", "反复叠加粉底"],
                    "right_items": ["等待防晒成膜", "薄涂底妆", "局部补妆"],
                },
                {
                    "frame_id": "frame_003",
                    "template": "step_timeline",
                    "theme": "warm_neutral",
                    "kicker": "三步顺序",
                    "headline": "按顺序留出成膜时间",
                    "footer": "每步都别赶",
                    "steps": [
                        {"name": "防晒", "hint": "薄涂全脸"},
                        {"name": "等待", "hint": "静置三分钟"},
                        {"name": "底妆", "hint": "少量点涂"},
                    ],
                },
                {
                    "frame_id": "frame_004",
                    "template": "saveable_checklist",
                    "theme": "warm_neutral",
                    "kicker": "截图保存",
                    "headline": "上妆前快速检查",
                    "footer": "照着清单做",
                    "checklist_items": ["薄涂防晒", "等待成膜", "少量点涂", "局部补妆"],
                },
                {
                    "frame_id": "frame_005",
                    "template": "decision_rule",
                    "theme": "warm_neutral",
                    "kicker": "选择规则",
                    "headline": "搓泥时先减少叠加",
                    "footer": "先减量再调整",
                    "condition": "底妆开始搓泥",
                    "recommendation": "减少用量并等待",
                },
                {
                    "frame_id": "frame_006",
                    "template": "question_closer",
                    "theme": "warm_neutral",
                    "kicker": "留言聊聊",
                    "headline": "你的防晒会搓泥吗",
                    "footer": "按肤质再微调",
                    "question": "你最常在哪一步出现搓泥？",
                },
            ]
        }
    )


def test_render_card_html_uses_theme_tokens_and_only_template_content():
    from src.rendering.text_cards import render_card_html

    html = render_card_html(valid_payload().storyboards[1])

    assert "#F7F2EB" in html
    assert "错误顺序" in html
    assert "wrong-vs-right" in html
    assert "image_prompt_cn" not in html


def test_render_card_html_escapes_content_strings():
    from src.rendering.text_cards import render_card_html

    payload = valid_payload()
    frame = payload.storyboards[0].model_copy(update={"headline": "<strong>安全</strong>"})

    html = render_card_html(frame)

    assert "&lt;strong&gt;安全&lt;/strong&gt;" in html
    assert "<strong>安全</strong>" not in html


def test_output_paths_follow_the_fixed_publish_sequence(tmp_path):
    from src.rendering.text_cards import output_paths

    assert output_paths(tmp_path) == [
        tmp_path / "01-cover.png",
        tmp_path / "02-wrong-vs-right.png",
        tmp_path / "03-timeline.png",
        tmp_path / "04-checklist.png",
        tmp_path / "05-decision.png",
        tmp_path / "06-question.png",
    ]


def test_render_text_cards_removes_partial_pngs_when_a_later_screenshot_fails(tmp_path):
    from src.rendering.text_cards import TextCardRenderError, render_text_cards

    class CopyLocator:
        def evaluate_all(self, _script):
            return []

    class CardLocator:
        def __init__(self):
            self.calls = 0

        def screenshot(self, *, path):
            self.calls += 1
            Path(path).write_bytes(b"partial")
            if self.calls == 2:
                raise RuntimeError("screenshot failed")

    class Page:
        def __init__(self):
            self.card = CardLocator()

        def set_viewport_size(self, _size):
            pass

        def set_content(self, _html, *, wait_until):
            assert wait_until == "load"

        def locator(self, selector):
            return CopyLocator() if selector == "[data-card-copy]" else self.card

    class Browser:
        def new_page(self):
            return Page()

        def close(self):
            pass

    class Playwright:
        class Chromium:
            def launch(self):
                return Browser()

        chromium = Chromium()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    with pytest.raises(TextCardRenderError, match="screenshot"):
        render_text_cards(valid_payload(), tmp_path, playwright_factory=Playwright)

    assert not list(tmp_path.glob("*.png"))


def _local_chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            return Path(playwright.chromium.executable_path).is_file()
    except Exception:
        return False


@pytest.mark.skipif(not _local_chromium_available(), reason="local Playwright Chromium is unavailable")
def test_render_text_cards_creates_six_1080_by_1440_pngs(tmp_path):
    from src.rendering.text_cards import render_text_cards

    paths = render_text_cards(valid_payload(), tmp_path)

    assert paths == [path for path in paths if path.is_file()]
    assert len(paths) == 6
    for path in paths:
        try:
            from PIL import Image
        except ImportError:
            with path.open("rb") as png:
                assert png.read(8) == b"\x89PNG\r\n\x1a\n"
                width, height = struct.unpack(">II", png.read(16)[8:])
            assert (width, height) == (1080, 1440)
        else:
            with Image.open(path) as image:
                assert image.size == (1080, 1440)
