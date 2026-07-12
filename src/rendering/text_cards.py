from __future__ import annotations

from html import escape
from pathlib import Path
from types import MappingProxyType
from typing import Callable

from playwright.sync_api import sync_playwright

from src.schemas.text_card import TextCardFrame, TextCardPayload


THEMES = MappingProxyType(
    {
        "warm_neutral": MappingProxyType(
            {"background": "#F7F2EB", "ink": "#292622", "accent": "#B85C56"}
        ),
        "cool_sage": MappingProxyType(
            {"background": "#EEF2ED", "ink": "#243128", "accent": "#607A69"}
        ),
    }
)
CANVAS = MappingProxyType({"width": 1080, "height": 1440, "padding": 84})

_OUTPUT_FILENAMES = (
    "01-cover.png",
    "02-wrong-vs-right.png",
    "03-timeline.png",
    "04-checklist.png",
    "05-decision.png",
    "06-question.png",
)


class TextCardRenderError(RuntimeError):
    """Raised when a text card cannot be rendered into a complete PNG set."""


_CSS = """
* { box-sizing: border-box; }
html, body { margin: 0; width: 1080px; height: 1440px; overflow: hidden; }
body { font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; }
.card {
  width: 1080px; height: 1440px; overflow: hidden; padding: 84px;
  color: var(--ink); background: var(--background);
  display: grid; grid-template-rows: auto 1fr auto; gap: 42px;
}
.card-header { display: grid; min-width: 0; gap: 18px; align-content: start; }
.kicker { color: var(--accent); font-size: 30px; font-weight: 700; letter-spacing: 0.16em; }
.headline { min-width: 0; margin: 0; padding-bottom: 1px; font-size: 70px; line-height: 96px; letter-spacing: -0.04em; font-weight: 800; }
.card-content { min-height: 0; align-self: stretch; }
[data-card-copy] { overflow-wrap: anywhere; word-break: break-word; }
.footer { border-top: 2px solid color-mix(in srgb, var(--accent) 40%, transparent); padding-top: 22px; font-size: 28px; font-weight: 600; }
.cover-content { display: grid; place-items: center start; }
.cover-rule { width: 144px; height: 14px; background: var(--accent); }
.cover-message { display: grid; gap: 34px; font-size: 44px; line-height: 64px; font-weight: 700; }
.comparison-grid { height: 100%; display: grid; grid-template-columns: 1fr 1fr; gap: 28px; }
.comparison-column { min-width: 0; border: 3px solid var(--accent); padding: 32px; display: grid; align-content: start; gap: 26px; }
.comparison-label { font-size: 34px; font-weight: 800; color: var(--accent); }
.comparison-list { display: grid; gap: 22px; }
.comparison-item { min-width: 0; font-size: 35px; line-height: 48px; font-weight: 650; }
.timeline { height: 100%; display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; align-items: center; }
.timeline-step { min-width: 0; min-height: 310px; border-top: 12px solid var(--accent); padding: 28px 10px 0; display: grid; align-content: start; gap: 24px; }
.step-number { font-size: 28px; color: var(--accent); font-weight: 800; }
.step-name { padding-bottom: 1px; font-size: 48px; line-height: 64px; font-weight: 800; }
.step-hint { font-size: 30px; line-height: 41px; font-weight: 600; }
.checklist { height: 100%; display: grid; grid-template-columns: repeat(2, 1fr); gap: 22px; align-content: center; }
.checklist-row { min-width: 0; min-height: 154px; border: 2px solid var(--accent); padding: 28px; display: grid; grid-template-columns: 42px 1fr; gap: 16px; align-items: center; }
.checkmark { color: var(--accent); font-size: 38px; font-weight: 900; }
.checklist-copy { padding-bottom: 1px; font-size: 36px; line-height: 48px; font-weight: 700; }
.decision { height: 100%; display: grid; grid-template-rows: 1fr auto 1fr; gap: 28px; align-items: center; }
.decision-row { min-width: 0; min-height: 240px; padding: 38px; border-left: 12px solid var(--accent); display: grid; align-content: center; gap: 18px; background: color-mix(in srgb, var(--accent) 8%, transparent); }
.decision-label { font-size: 30px; font-weight: 800; color: var(--accent); letter-spacing: 0.1em; }
.decision-copy { padding-bottom: 1px; font-size: 46px; line-height: 64px; font-weight: 800; }
.decision-arrow { color: var(--accent); font-size: 62px; text-align: center; font-weight: 800; }
.question { height: 100%; display: grid; align-content: center; gap: 38px; }
.question-copy { font-size: 58px; line-height: 76px; font-weight: 800; border-bottom: 10px solid var(--accent); padding-bottom: 32px; }
.question-note { font-size: 36px; line-height: 51px; font-weight: 650; }
"""


def output_paths(output_dir: Path) -> list[Path]:
    """Return the exact six-file publish sequence for an output directory."""
    return [Path(output_dir) / filename for filename in _OUTPUT_FILENAMES]


def _copy(role: str, value: str, class_name: str, tag: str = "div") -> str:
    return (
        f'<{tag} class="{class_name}" data-card-copy data-copy-role="{role}">'
        f"{escape(value, quote=True)}</{tag}>"
    )


def _shared_header(frame: TextCardFrame) -> str:
    return "".join(
        (
            '<header class="card-header">',
            _copy("kicker", frame.kicker, "kicker"),
            _copy("headline", frame.headline, "headline", "h1"),
            "</header>",
        )
    )


def _template_content(frame: TextCardFrame) -> str:
    if frame.template == "cover_statement":
        return "".join(
            (
                '<section class="card-content cover-content">',
                '<div class="cover-message">',
                '<div class="cover-rule" aria-hidden="true"></div>',
                _copy("headline", frame.headline, "cover-headline"),
                "</div></section>",
            )
        )
    if frame.template == "wrong_vs_right":
        wrong_items = "".join(
            _copy(f"wrong_items[{index}]", item, "comparison-item")
            for index, item in enumerate(frame.wrong_items)
        )
        right_items = "".join(
            _copy(f"right_items[{index}]", item, "comparison-item")
            for index, item in enumerate(frame.right_items)
        )
        return f"""
<section class="card-content comparison-grid template-wrong-vs-right">
  <div class="comparison-column"><div class="comparison-label">错误顺序</div><div class="comparison-list">{wrong_items}</div></div>
  <div class="comparison-column"><div class="comparison-label">正确顺序</div><div class="comparison-list">{right_items}</div></div>
</section>"""
    if frame.template == "step_timeline":
        steps = "".join(
            "".join(
                (
                    '<div class="timeline-step">',
                    f'<div class="step-number">0{index + 1}</div>',
                    _copy(f"steps[{index}].name", step.name, "step-name"),
                    _copy(f"steps[{index}].hint", step.hint, "step-hint"),
                    "</div>",
                )
            )
            for index, step in enumerate(frame.steps)
        )
        return f'<section class="card-content timeline">{steps}</section>'
    if frame.template == "saveable_checklist":
        rows = "".join(
            "".join(
                (
                    '<div class="checklist-row">',
                    '<div class="checkmark" aria-hidden="true">✓</div>',
                    _copy(f"checklist_items[{index}]", item, "checklist-copy"),
                    "</div>",
                )
            )
            for index, item in enumerate(frame.checklist_items)
        )
        return f'<section class="card-content checklist">{rows}</section>'
    if frame.template == "decision_rule":
        return "".join(
            (
                '<section class="card-content decision">',
                '<div class="decision-row"><div class="decision-label">当</div>',
                _copy("condition", frame.condition, "decision-copy"),
                "</div><div class=\"decision-arrow\" aria-hidden=\"true\">↓</div>",
                '<div class="decision-row"><div class="decision-label">就</div>',
                _copy("recommendation", frame.recommendation, "decision-copy"),
                "</div></section>",
            )
        )
    if frame.template == "question_closer":
        return "".join(
            (
                '<section class="card-content question">',
                _copy("question", frame.question, "question-copy"),
                _copy("footer", frame.footer, "question-note"),
                "</section>",
            )
        )
    raise TextCardRenderError(f"unsupported text card template: {frame.template}")


def render_card_html(frame: TextCardFrame) -> str:
    """Render one schema-valid frame into a standalone 1080 by 1440 document."""
    try:
        theme = THEMES[frame.theme]
    except KeyError as exc:
        raise TextCardRenderError(f"unsupported text card theme: {frame.theme}") from exc

    return "".join(
        (
            "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">",
            "<meta name=\"viewport\" content=\"width=1080, initial-scale=1\">",
            f"<style>{_CSS}</style></head><body>",
            f'<main class="card template-{frame.template.replace("_", "-")}" '
            f'style="--background: {theme["background"]}; --ink: {theme["ink"]}; --accent: {theme["accent"]};">',
            _shared_header(frame),
            _template_content(frame),
            _copy("footer", frame.footer, "footer", "footer"),
            "</main></body></html>",
        )
    )


def _assert_no_overflow(page, frame_id: str) -> None:
    overflowing = page.locator("[data-card-copy]").evaluate_all(
        "elements => elements.filter(e => e.scrollHeight > e.clientHeight || e.scrollWidth > e.clientWidth).map(e => e.dataset.copyRole)"
    )
    if overflowing:
        raise TextCardRenderError(f"{frame_id} text overflow: {', '.join(overflowing)}")


def _remove_partial_outputs(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            continue


def render_text_cards(
    payload: TextCardPayload,
    output_dir: Path,
    *,
    playwright_factory: Callable = sync_playwright,
) -> list[Path]:
    """Capture all six text-card documents using one local Chromium session."""
    output_dir = Path(output_dir)
    paths = output_paths(output_dir)
    attempted_paths: list[Path] = []
    written_paths: list[Path] = []
    browser = None

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise TextCardRenderError(f"could not create text-card output directory: {exc}") from exc

    try:
        with playwright_factory() as playwright:
            try:
                try:
                    browser = playwright.chromium.launch()
                    page = browser.new_page()
                    page.set_viewport_size({"width": CANVAS["width"], "height": CANVAS["height"]})
                except Exception as exc:
                    raise TextCardRenderError(f"could not start local Chromium: {exc}") from exc

                for frame, path in zip(payload.storyboards, paths, strict=True):
                    try:
                        page.set_content(render_card_html(frame), wait_until="load")
                        _assert_no_overflow(page, frame.frame_id)
                    except TextCardRenderError:
                        raise
                    except Exception as exc:
                        raise TextCardRenderError(f"{frame.frame_id} browser render failed: {exc}") from exc

                    attempted_paths.append(path)
                    try:
                        page.locator(".card").screenshot(path=str(path))
                    except Exception as exc:
                        raise TextCardRenderError(f"{frame.frame_id} screenshot failed: {exc}") from exc
                    written_paths.append(path)
            finally:
                if browser is not None:
                    browser.close()
    except TextCardRenderError:
        _remove_partial_outputs(attempted_paths)
        raise
    except Exception as exc:
        _remove_partial_outputs(attempted_paths)
        raise TextCardRenderError(f"local text-card rendering failed: {exc}") from exc

    return written_paths
