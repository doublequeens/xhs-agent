from __future__ import annotations

from pathlib import Path
import struct

import pytest

from src.schemas.text_card import TextCardPayload


def _local_chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            return Path(playwright.chromium.executable_path).is_file()
    except Exception:
        return False


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
                    "conditions": [
                        {"situation": "底妆开始搓泥", "recommendation": "减少用量并等待"},
                        {"situation": "时间不足", "recommendation": "先缩减步骤"},
                    ],
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

    assert "&lt;strong&gt;" in html
    assert "<strong>安全</strong>" not in html


def test_question_closer_renders_its_footer_exactly_once():
    from src.rendering.text_cards import render_card_html

    frame = valid_payload().storyboards[-1]
    html = render_card_html(frame)

    assert html.count('data-copy-role="footer"') == 1
    assert html.count(frame.footer) == 1


def test_render_card_html_omits_empty_optional_kicker_and_footer():
    from src.rendering.text_cards import render_card_html

    frame = valid_payload().storyboards[0].model_copy(update={"kicker": None, "footer": None})
    html = render_card_html(frame)

    assert 'data-copy-role="kicker"' not in html
    assert 'data-copy-role="footer"' not in html


def test_cover_renders_the_headline_once_and_uses_the_approved_type_scale():
    from src.rendering.text_cards import render_card_html

    frame = valid_payload().storyboards[0]
    html = render_card_html(frame)

    assert html.count('data-copy-role="headline"') == 1
    assert "font-size: 76px" in html
    assert "line-height: 1.18" in html


def test_html_uses_the_approved_body_and_footer_typography_tokens():
    from src.rendering.text_cards import render_card_html

    html = render_card_html(valid_payload().storyboards[1])

    assert "font-size: 36px; line-height: 1.45" in html
    assert "font-size: 28px; line-height: 1.35" in html


def test_comparison_html_uses_distinct_fixed_wrong_and_right_tokens():
    from src.rendering.text_cards import render_card_html

    html = render_card_html(valid_payload().storyboards[1])

    assert "--wrong: #B06A6A" in html
    assert "--right: #6F9275" in html
    assert 'comparison-column comparison-wrong' in html
    assert 'comparison-column comparison-right' in html


@pytest.mark.skipif(not _local_chromium_available(), reason="local Playwright Chromium is unavailable")
def test_boundary_length_chinese_headline_stays_within_two_lines_in_real_browser(tmp_path):
    from playwright.sync_api import sync_playwright
    from src.rendering.text_cards import render_card_html

    frame = valid_payload().storyboards[0].model_copy(update={"headline": "甲乙丙丁戊己庚辛壬癸子丑寅卯甲乙丙丁戊己庚辛壬癸子丑寅卯"})
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1080, "height": 1440})
            page.set_content(render_card_html(frame), wait_until="load")
            metrics = page.locator(".headline").evaluate("element => ({height: element.clientHeight, lineHeight: parseFloat(getComputedStyle(element).lineHeight)})")
            lines = page.locator(".headline-line").all_inner_texts()
        finally:
            browser.close()

    assert metrics["height"] <= metrics["lineHeight"] * 2
    assert [len(line) for line in lines] == [14, 14]


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


def test_render_text_cards_surfaces_cleanup_failure_with_render_error_as_cause(tmp_path, monkeypatch):
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

    original_unlink = Path.unlink

    def fail_first_cleanup(path, *args, **kwargs):
        if path.name == "01-cover.png":
            raise OSError("permission denied")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_first_cleanup)

    with pytest.raises(TextCardRenderError, match="remove partial") as error:
        render_text_cards(valid_payload(), tmp_path, playwright_factory=Playwright)

    assert isinstance(error.value.__cause__, TextCardRenderError)
    assert "screenshot failed" in str(error.value.__cause__)
    assert (tmp_path / "01-cover.png").is_file()


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
