from __future__ import annotations

import re
import uuid
from html import escape
from pathlib import Path
from typing import Callable, Iterable, Sequence

from playwright.sync_api import sync_playwright

from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.render_manifest import FontLoadReport, RenderedPage, RenderManifest
from src.schemas.storyboard import CarouselFrame, CarouselPayload
from src.schemas.visual_plan import VisualPlan

from .design_system import BEAUTY_EDITORIAL_V1
from .layouts import LAYOUT_RENDERERS
from .probes import EXPECTED_FONT_FAMILIES, probe_fonts, probe_layout


class EditorialCarouselRenderError(RuntimeError):
    """Raised when a complete editorial carousel cannot be rendered locally."""


_ROLE_SEPARATOR = re.compile(r"[^a-z0-9]+")


def _font_css() -> str:
    paths = BEAUTY_EDITORIAL_V1.font_paths
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise EditorialCarouselRenderError(
            "font files are missing: " + ", ".join(missing)
        )
    return f"""
@font-face {{
  font-family: "Source Han Serif SC";
  src: url("{paths['display'].resolve().as_uri()}") format("opentype");
  font-style: normal; font-weight: 600; font-display: block;
}}
@font-face {{
  font-family: "Source Han Sans SC";
  src: url("{paths['body_regular'].resolve().as_uri()}") format("opentype");
  font-style: normal; font-weight: 400; font-display: block;
}}
@font-face {{
  font-family: "Source Han Sans SC";
  src: url("{paths['body_medium'].resolve().as_uri()}") format("opentype");
  font-style: normal; font-weight: 500; font-display: block;
}}
@font-face {{
  font-family: "Bodoni Moda";
  src: url("{paths['numeral'].resolve().as_uri()}") format("truetype");
  font-style: normal; font-weight: 400; font-display: block;
}}
"""


_CARD_CSS = """
* { box-sizing: border-box; }
:root {
  --ivory: #F7F2EA;
  --ink: #292625;
  --mauve: #9A707B;
  --coral: #D45D4C;
  --sage: #78805E;
  --safe-margin: 84px;
}
html, body { margin: 0; width: 1080px; height: 1440px; overflow: hidden; }
body { background: var(--ivory); color: var(--ink); font-family: "Source Han Sans SC"; font-weight: 400; }
.card {
  position: relative; isolation: isolate; width: 1080px; height: 1440px;
  overflow: hidden; padding: var(--safe-margin); background: var(--ivory);
  display: grid; grid-template-rows: auto minmax(0, 1fr) auto; gap: 34px;
}
.card::before { content: ""; position: absolute; inset: 26px; z-index: -2; border: 1px solid rgba(41,38,37,.14); }
.card::after { content: ""; position: absolute; right: -130px; top: -100px; z-index: -1; width: 430px; height: 430px; border-radius: 50%; background: rgba(154,112,123,.11); }
.font-probes { position: absolute; left: 0; top: 0; opacity: 0; pointer-events: none; font-size: 16px; }
.font-probe-display { font-family: "Source Han Serif SC"; font-weight: 600; }
.font-probe-body { font-family: "Source Han Sans SC"; font-weight: 400; }
.font-probe-numeral, .numeral { font-family: "Bodoni Moda"; font-weight: 400; }
.editorial-header { display: grid; gap: 14px; min-width: 0; }
.kicker { color: var(--mauve); font-size: 25px; line-height: 1.3; font-weight: 500; letter-spacing: .14em; }
.headline { margin: 0; max-width: 900px; color: var(--ink); font-family: "Source Han Serif SC"; font-size: 64px; line-height: 1.17; font-weight: 600; letter-spacing: -.035em; overflow-wrap: anywhere; }
.layout-body { min-width: 0; min-height: 0; overflow: hidden; }
.content-block { min-width: 0; display: grid; gap: 11px; align-content: start; }
.block-heading { margin: 0; color: var(--mauve); font-size: 27px; line-height: 1.3; font-weight: 500; }
.block-body { margin: 0; font-size: 29px; line-height: 1.55; }
.block-items { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
.block-item { min-width: 0; display: grid; grid-template-columns: 42px minmax(0, 1fr); gap: 11px; align-items: baseline; }
.item-marker { color: var(--coral); font-size: 20px; line-height: 1; }
.item-copy { min-width: 0; font-size: 26px; line-height: 1.45; overflow-wrap: anywhere; }
.asset-gallery { min-width: 0; min-height: 0; display: grid; gap: 14px; place-items: center; }
.asset-figure { width: 100%; height: 100%; min-height: 0; margin: 0; display: grid; place-items: center; overflow: hidden; }
.asset-figure img { display: block; max-width: 100%; max-height: 100%; object-fit: contain; }
.asset-placeholder { width: 75%; aspect-ratio: 1; border-radius: 50% 44% 52% 38%; background: linear-gradient(145deg, rgba(154,112,123,.28), rgba(212,93,76,.08)); }
.editorial-footer { min-width: 0; border-top: 1px solid rgba(41,38,37,.28); padding-top: 17px; display: flex; align-items: baseline; justify-content: space-between; gap: 24px; }
.footer-copy { min-width: 0; color: var(--sage); font-size: 22px; line-height: 1.35; font-weight: 500; }
.page-number { flex: 0 0 auto; color: var(--mauve); font-size: 27px; }
.layout-editorial-cover { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(280px, .85fr); gap: 46px; align-items: stretch; }
.cover-copy { align-self: end; display: grid; gap: 25px; padding-bottom: 36px; }
.cover-rule { width: 112px; height: 9px; background: var(--coral); }
.cover-visual { border-radius: 280px 280px 36px 36px; padding: 24px; background: rgba(154,112,123,.14); }
.layout-texture-baseline { display: grid; grid-template-columns: minmax(340px, .9fr) minmax(0, 1.1fr); gap: 44px; align-items: stretch; }
.texture-visual { border: 1px solid rgba(154,112,123,.45); padding: 42px; background: rgba(255,255,255,.32); }
.baseline-notes { display: grid; gap: 22px; align-content: center; }
.baseline-notes .content-block { border-bottom: 1px solid rgba(41,38,37,.18); padding-bottom: 18px; }
.layout-front-face-zone, .layout-three-quarter-face-zone { display: grid; grid-template-columns: minmax(430px, 1.08fr) minmax(0, .92fr); gap: 42px; align-items: stretch; }
.layout-three-quarter-face-zone { grid-template-columns: minmax(0, .9fr) minmax(460px, 1.1fr); }
.zone-visual { position: relative; min-height: 0; border-radius: 48% 48% 42% 42%; border: 1px solid rgba(154,112,123,.38); padding: 32px; }
.zone-three-quarter { transform: translateX(12px); }
.zone-marker { position: absolute; width: 68px; height: 68px; border: 3px solid var(--coral); border-radius: 50%; }
.marker-one { top: 26%; left: 24%; }
.marker-two { top: 50%; right: 22%; }
.zone-bracket { position: absolute; inset: 20% 10% 18% 48%; border-right: 3px solid var(--coral); border-top: 3px solid var(--coral); border-bottom: 3px solid var(--coral); }
.zone-notes { display: grid; gap: 22px; align-content: center; }
.layout-step-timeline { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(250px, .65fr); gap: 38px; }
.timeline-rail { display: grid; gap: 18px; align-content: center; border-left: 3px solid var(--mauve); padding-left: 30px; }
.timeline-rail .content-block { position: relative; padding: 17px 20px; background: rgba(255,255,255,.3); }
.timeline-rail .content-block::before { content: ""; position: absolute; left: -42px; top: 30px; width: 20px; height: 20px; border-radius: 50%; background: var(--coral); }
.timeline-visual { padding: 38px 10px; }
.layout-morning-evening-flow { display: grid; grid-template-columns: 1fr 2px 1fr; gap: 28px; position: relative; }
.flow-panel { min-width: 0; display: grid; gap: 20px; align-content: center; padding: 28px; }
.morning-panel { background: rgba(212,93,76,.08); }
.evening-panel { background: rgba(120,128,94,.10); }
.flow-divider { background: rgba(41,38,37,.22); }
.flow-label { color: var(--mauve); font-size: 40px; }
.flow-visual { display: none; }
.layout-left-right-comparison { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; position: relative; }
.comparison-panel { min-width: 0; padding: 30px; display: grid; gap: 20px; align-content: center; border: 2px solid rgba(154,112,123,.45); }
.comparison-right { border-color: rgba(120,128,94,.58); background: rgba(120,128,94,.07); }
.panel-label { color: var(--mauve); font-size: 23px; font-weight: 500; letter-spacing: .16em; }
.comparison-visual { display: none; }
.layout-three-state-diagnostic { display: grid; grid-template-columns: minmax(0, 1fr) 230px; gap: 32px; }
.state-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; align-content: center; }
.state-grid .content-block { min-height: 330px; padding: 24px 18px; border-top: 9px solid var(--mauve); background: rgba(255,255,255,.34); }
.state-grid .content-block:nth-child(2) { border-color: var(--coral); }
.state-grid .content-block:nth-child(3) { border-color: var(--sage); }
.diagnostic-visual { padding: 44px 10px; }
.layout-decision-tree { display: grid; grid-template-columns: 116px minmax(0, 1fr) 190px; gap: 26px; align-items: center; }
.tree-root { display: grid; place-items: center; width: 110px; height: 110px; border-radius: 50%; background: var(--ink); color: var(--ivory); font-size: 31px; }
.tree-branches { display: grid; gap: 16px; border-left: 2px solid var(--mauve); padding-left: 30px; }
.tree-branches .content-block { padding: 17px 22px; border: 1px solid rgba(154,112,123,.42); background: rgba(255,255,255,.35); }
.tree-visual { padding: 30px 0; }
.layout-saveable-checklist { position: relative; display: grid; grid-template-columns: minmax(0, 1fr) 210px; gap: 30px; border: 2px solid rgba(41,38,37,.24); padding: 48px 42px 36px; background: rgba(255,255,255,.30); }
.save-label { position: absolute; top: -17px; left: 40px; padding: 5px 14px; background: var(--coral); color: var(--ivory); font-size: 18px; letter-spacing: .13em; }
.checklist-sheet { display: grid; gap: 15px; align-content: center; }
.checklist-sheet .content-block { padding: 15px 18px 15px 54px; border-bottom: 1px solid rgba(41,38,37,.20); }
.checklist-sheet .content-block::before { content: "✓"; position: absolute; margin-left: -36px; color: var(--sage); font-size: 26px; }
.checklist-visual { padding: 30px 0; }
.layout-saveable-reference { display: grid; grid-template-columns: 74px minmax(0, 1fr) 230px; gap: 26px; border-top: 10px solid var(--mauve); padding-top: 32px; }
.reference-index { color: var(--coral); font-size: 35px; line-height: 2.15; border-right: 1px solid rgba(41,38,37,.24); }
.reference-sheet { display: grid; gap: 18px; align-content: center; }
.reference-sheet .content-block { padding-bottom: 16px; border-bottom: 1px solid rgba(41,38,37,.18); }
.reference-visual { padding: 34px 0; }
"""


def _document_html(card_html: str) -> str:
    return "".join(
        (
            '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=1080, initial-scale=1">',
            f"<style>{_font_css()}{_CARD_CSS}</style>",
            "</head><body>",
            card_html,
            "<script>window.__editorialFontsReady = document.fonts.ready;</script>",
            "</body></html>",
        )
    )


def _sanitize_role(role: str) -> str:
    sanitized = _ROLE_SEPARATOR.sub("-", role.lower()).strip("-")
    return sanitized or "frame"


def _output_paths(frames: Sequence[CarouselFrame], output_dir: Path) -> list[Path]:
    return [
        output_dir
        / (
            "01-cover.png"
            if index == 1
            else f"{index:02d}-{_sanitize_role(frame.role)}.png"
        )
        for index, frame in enumerate(frames, start=1)
    ]


def _frame_assets(
    frame: CarouselFrame, items: Sequence[AssetManifestItem]
) -> list[AssetManifestItem]:
    slot_ids = {slot.slot_id for slot in frame.visual_slots}
    exact = [item for item in items if item.slot_id in slot_ids]
    if exact:
        return exact
    return [item for item in items if item.layout == frame.layout]


def _assert_plan_matches_storyboard(
    visual_plan: VisualPlan, storyboard: CarouselPayload
) -> None:
    planned = [
        (frame.frame_id, frame.role, frame.layout) for frame in visual_plan.frame_plan
    ]
    rendered = [
        (frame.frame_id, frame.role, frame.layout) for frame in storyboard.storyboards
    ]
    if planned != rendered:
        raise EditorialCarouselRenderError(
            "visual plan does not match storyboard frame order"
        )


def _write_html(path: Path, html: str) -> None:
    path.write_text(html, encoding="utf-8")


def _validate_font_report(report: dict, frame_id: str) -> FontLoadReport:
    all_loaded = report.get("all_loaded") is True
    families = report.get("computed_families")
    if not isinstance(families, list) or any(
        not isinstance(family, str) for family in families
    ):
        raise EditorialCarouselRenderError(
            f"{frame_id} font probe returned invalid computed families"
        )
    if not all_loaded or set(families) != EXPECTED_FONT_FAMILIES:
        raise EditorialCarouselRenderError(
            f"{frame_id} font probe failed without the exact repo font families"
        )
    return FontLoadReport(all_loaded=True, computed_families=families)


def _remove_paths(paths: Iterable[Path]) -> None:
    failures: list[str] = []
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            failures.append(f"{path}: {exc}")
    if failures:
        raise EditorialCarouselRenderError(
            "could not remove partial editorial render outputs: "
            + "; ".join(failures)
        )


def _cleanup_failure(
    png_paths: Sequence[Path],
    html_paths: Sequence[Path],
    render_error: EditorialCarouselRenderError,
) -> None:
    try:
        _remove_paths([*png_paths, *html_paths])
    except EditorialCarouselRenderError as cleanup_error:
        raise cleanup_error from render_error


def _contact_sheet_html(page_paths: Sequence[Path]) -> str:
    cells = "".join(
        '<figure class="contact-cell">'
        f'<img src="{escape(path.resolve().as_uri(), quote=True)}" alt="rendered page {index}">'
        f'<figcaption class="numeral">{index:02d}</figcaption>'
        "</figure>"
        for index, path in enumerate(page_paths, start=1)
    )
    return "".join(
        (
            '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
            "<style>",
            _font_css(),
            "*{box-sizing:border-box}html,body{margin:0;background:#292625}"
            '.contact-sheet{width:1320px;padding:42px;display:grid;grid-template-columns:repeat(3,1fr);gap:28px;background:#292625}'
            '.contact-cell{position:relative;margin:0;padding:12px;background:#F7F2EA}'
            '.contact-cell img{display:block;width:100%;height:auto}'
            '.contact-cell figcaption{position:absolute;right:22px;bottom:20px;padding:5px 10px;background:#F7F2EA;color:#9A707B;font-size:22px}'
            '.font-probes{position:absolute;opacity:0}.font-probe-display{font-family:"Source Han Serif SC"}'
            '.font-probe-body{font-family:"Source Han Sans SC"}.font-probe-numeral,.numeral{font-family:"Bodoni Moda"}',
            "</style></head><body>",
            '<div class="font-probes" aria-hidden="true"><span class="font-probe-display">字</span><span class="font-probe-body">字</span><span class="font-probe-numeral">01</span></div>',
            f'<main class="contact-sheet">{cells}</main>',
            "<script>window.__editorialFontsReady = document.fonts.ready;</script>",
            "</body></html>",
        )
    )


def render_carousel(
    visual_plan: VisualPlan,
    storyboard: CarouselPayload,
    assets: AssetManifest,
    output_dir: Path,
    *,
    playwright_factory: Callable = sync_playwright,
) -> RenderManifest:
    """Render one strict editorial carousel as a complete local Chromium set."""
    _assert_plan_matches_storyboard(visual_plan, storyboard)
    if visual_plan.design_system != BEAUTY_EDITORIAL_V1.name:
        raise EditorialCarouselRenderError(
            f"unsupported design system: {visual_plan.design_system}"
        )

    output_dir = Path(output_dir)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise EditorialCarouselRenderError(
            f"could not create editorial output directory: {exc}"
        ) from exc

    frames = storyboard.storyboards
    page_paths = _output_paths(frames, output_dir)
    contact_sheet_path = output_dir / "contact-sheet.png"
    invocation = uuid.uuid4().hex
    temporary_html: list[Path] = []
    created_pngs: list[Path] = []
    rendered_pages: list[RenderedPage] = []
    font_report: FontLoadReport | None = None
    browser = None

    try:
        with playwright_factory() as playwright:
            try:
                browser = playwright.chromium.launch()
                page = browser.new_page()
                page.set_viewport_size(
                    {
                        "width": BEAUTY_EDITORIAL_V1.canvas[0],
                        "height": BEAUTY_EDITORIAL_V1.canvas[1],
                    }
                )
            except Exception as exc:
                raise EditorialCarouselRenderError(
                    f"could not start local Chromium: {exc}"
                ) from exc

            try:
                for index, (frame, page_path) in enumerate(
                    zip(frames, page_paths, strict=True), start=1
                ):
                    html_path = output_dir / f".editorial-{invocation}-{index:02d}.html"
                    temporary_html.append(html_path)
                    try:
                        renderer = LAYOUT_RENDERERS[frame.layout]
                        card = renderer(frame, _frame_assets(frame, assets.items))
                        document = _document_html(card)
                        _write_html(html_path, document)
                        page.goto(html_path.resolve().as_uri(), wait_until="load")
                    except EditorialCarouselRenderError:
                        raise
                    except Exception as exc:
                        raise EditorialCarouselRenderError(
                            f"{frame.frame_id} browser render failed: {exc}"
                        ) from exc

                    try:
                        current_font_report = _validate_font_report(
                            probe_fonts(page), frame.frame_id
                        )
                    except EditorialCarouselRenderError:
                        raise
                    except Exception as exc:
                        raise EditorialCarouselRenderError(
                            f"{frame.frame_id} font probe failed: {exc}"
                        ) from exc
                    if font_report is None:
                        font_report = current_font_report

                    try:
                        issues = probe_layout(page)
                    except Exception as exc:
                        raise EditorialCarouselRenderError(
                            f"{frame.frame_id} layout probe failed: {exc}"
                        ) from exc
                    if issues:
                        raise EditorialCarouselRenderError(
                            f"{frame.frame_id} layout probe failed: {issues}"
                        )

                    created_pngs.append(page_path)
                    try:
                        page.locator(".card").screenshot(path=str(page_path))
                    except Exception as exc:
                        raise EditorialCarouselRenderError(
                            f"{frame.frame_id} screenshot failed: {exc}"
                        ) from exc
                    rendered_pages.append(
                        RenderedPage(
                            frame_id=frame.frame_id,
                            role=frame.role,
                            layout=frame.layout,
                            path=str(page_path),
                            width=1080,
                            height=1440,
                        )
                    )

                contact_html_path = (
                    output_dir / f".editorial-{invocation}-contact-sheet.html"
                )
                temporary_html.append(contact_html_path)
                try:
                    _write_html(contact_html_path, _contact_sheet_html(page_paths))
                    page.set_viewport_size({"width": 1404, "height": 3200})
                    page.goto(
                        contact_html_path.resolve().as_uri(), wait_until="load"
                    )
                    _validate_font_report(probe_fonts(page), "contact-sheet")
                    created_pngs.append(contact_sheet_path)
                    page.locator(".contact-sheet").screenshot(
                        path=str(contact_sheet_path)
                    )
                except EditorialCarouselRenderError:
                    raise
                except Exception as exc:
                    raise EditorialCarouselRenderError(
                        f"contact sheet screenshot failed: {exc}"
                    ) from exc
            finally:
                if browser is not None:
                    browser.close()

        try:
            _remove_paths(temporary_html)
        except EditorialCarouselRenderError as cleanup_error:
            _cleanup_failure(created_pngs, temporary_html, cleanup_error)
            raise
    except EditorialCarouselRenderError as render_error:
        _cleanup_failure(created_pngs, temporary_html, render_error)
        raise
    except Exception as exc:
        render_error = EditorialCarouselRenderError(
            f"editorial carousel rendering failed: {exc}"
        )
        _cleanup_failure(created_pngs, temporary_html, render_error)
        raise render_error from exc

    if font_report is None:
        raise EditorialCarouselRenderError("font probe did not run")
    return RenderManifest(
        pages=rendered_pages,
        fonts=font_report,
        contact_sheet_path=str(contact_sheet_path),
        source_asset_sha256={item.slot_id: item.sha256 for item in assets.items},
    )
