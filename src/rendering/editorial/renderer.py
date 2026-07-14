from __future__ import annotations

import hashlib
import re
import shutil
import uuid
import warnings
from io import BytesIO
from html import escape
from pathlib import Path
from typing import Callable, Iterable, Sequence

from PIL import Image
from pydantic import ValidationError
from playwright.sync_api import sync_playwright

from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.render_manifest import (
    FontLoadReport,
    PageProbeAttestation,
    RenderedPage,
    RenderManifest,
)
from src.schemas.storyboard import CarouselFrame, CarouselPayload
from src.schemas.visual_plan import VisualPlan

from .design_system import BEAUTY_EDITORIAL_V1
from .layouts import LAYOUT_RENDERERS
from .probes import EXPECTED_FONT_FAMILIES, probe_fonts, probe_layout


class EditorialCarouselRenderError(RuntimeError):
    """Raised when a complete editorial carousel cannot be rendered locally."""


_ROLE_SEPARATOR = re.compile(r"[^a-z0-9]+")
_RENDERED_PAGE_NAME = re.compile(r"^\d{2}-.+\.png$")


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
.block-body { margin: 0; font-size: 29px; line-height: 1.45; }
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
.flow-visual {
  position: absolute; right: 22px; bottom: 22px; width: 170px; height: 170px;
  z-index: 1; padding: 14px; border-radius: 50%; background: rgba(247,242,234,.92);
}
.layout-left-right-comparison { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; position: relative; }
.comparison-panel { min-width: 0; padding: 30px; display: grid; gap: 20px; align-content: center; border: 2px solid rgba(154,112,123,.45); }
.comparison-right { border-color: rgba(120,128,94,.58); background: rgba(120,128,94,.07); }
.panel-label { color: var(--mauve); font-size: 23px; font-weight: 500; letter-spacing: .16em; }
.comparison-visual {
  position: absolute; left: 50%; bottom: 22px; width: 170px; height: 170px;
  z-index: 1; transform: translateX(-50%); padding: 14px; border-radius: 50%;
  background: rgba(247,242,234,.94); border: 1px solid rgba(154,112,123,.32);
}
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
    resolved: list[AssetManifestItem] = []
    for slot in frame.visual_slots:
        matches = [item for item in items if item.slot_id == slot.slot_id]
        if not matches:
            raise EditorialCarouselRenderError(
                f"{frame.frame_id} asset slot {slot.slot_id} is missing"
            )
        if len(matches) != 1:
            raise EditorialCarouselRenderError(
                f"{frame.frame_id} asset slot {slot.slot_id} is ambiguous"
            )
        item = matches[0]
        if item.layout != frame.layout:
            raise EditorialCarouselRenderError(
                f"{frame.frame_id} asset slot {slot.slot_id} does not match "
                "the declared frame layout"
            )
        path = Path(item.path)
        if "://" in item.path or not path.is_absolute() or not path.is_file():
            raise EditorialCarouselRenderError(
                f"{frame.frame_id} asset slot {slot.slot_id} is not a resolved local file"
            )
        actual_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_sha256 != item.sha256:
            raise EditorialCarouselRenderError(
                f"{frame.frame_id} asset slot {slot.slot_id} sha256 does not match file bytes"
            )
        resolved.append(item)
    return resolved


def _resolve_storyboard_assets(
    storyboard: CarouselPayload, assets: AssetManifest
) -> tuple[dict[str, list[AssetManifestItem]], dict[str, str]]:
    by_frame: dict[str, list[AssetManifestItem]] = {}
    used_hashes: dict[str, str] = {}
    for frame in storyboard.storyboards:
        frame_items = _frame_assets(frame, assets.items)
        by_frame[frame.frame_id] = frame_items
        for item in frame_items:
            used_hashes[item.slot_id] = item.sha256
    return by_frame, used_hashes


def _assert_plan_matches_storyboard(
    visual_plan: VisualPlan, storyboard: CarouselPayload
) -> None:
    seen_plan_ids: set[str] = set()
    for frame in visual_plan.frame_plan:
        if frame.frame_id in seen_plan_ids:
            raise EditorialCarouselRenderError(
                f"visual plan has duplicate frame_id: {frame.frame_id}"
            )
        seen_plan_ids.add(frame.frame_id)

    seen_storyboard_ids: set[str] = set()
    for frame in storyboard.storyboards:
        if frame.frame_id in seen_storyboard_ids:
            raise EditorialCarouselRenderError(
                f"storyboard has duplicate frame_id: {frame.frame_id}"
            )
        seen_storyboard_ids.add(frame.frame_id)

        seen_slot_ids: set[str] = set()
        for slot in frame.visual_slots:
            if slot.slot_id in seen_slot_ids:
                raise EditorialCarouselRenderError(
                    f"{frame.frame_id} has duplicate visual slot_id: {slot.slot_id}"
                )
            seen_slot_ids.add(slot.slot_id)

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


def _expected_copy(frame: CarouselFrame) -> list[tuple[str, str]]:
    expected: list[tuple[str, str]] = []
    if frame.kicker:
        expected.append(("kicker", frame.kicker))
    expected.append(("headline", frame.headline))
    for block_index, block in enumerate(frame.content_blocks):
        if block.heading:
            expected.append(
                (f"content_blocks[{block_index}].heading", block.heading)
            )
        if block.body:
            expected.append((f"content_blocks[{block_index}].body", block.body))
        expected.extend(
            (f"content_blocks[{block_index}].items[{item_index}]", item)
            for item_index, item in enumerate(block.items)
        )
    if frame.footer:
        expected.append(("footer", frame.footer))
    return expected


def _probe_issue_label(issue: object) -> str:
    if not isinstance(issue, dict):
        return str(issue)
    kind = str(issue.get("kind", "unknown"))
    identity = issue.get("role", issue.get("slot_id"))
    return f"{kind}:{identity}" if identity else kind


def _validate_layout_report(
    report: dict, frame: CarouselFrame
) -> PageProbeAttestation:
    try:
        attestation = PageProbeAttestation.model_validate(
            {
                "canvas_width": report.get("canvas", {}).get("width"),
                "canvas_height": report.get("canvas", {}).get("height"),
                "safe_margin": report.get("safe_margin"),
                "text_results": report.get("texts"),
                "asset_results": report.get("assets"),
                "issues": [
                    _probe_issue_label(issue) for issue in report.get("issues", [])
                ],
            }
        )
    except (AttributeError, TypeError, ValidationError) as exc:
        raise EditorialCarouselRenderError(
            f"{frame.frame_id} layout probe returned invalid evidence: {exc}"
        ) from exc

    actual_copy = [(item.role, item.text) for item in attestation.text_results]
    if actual_copy != _expected_copy(frame):
        raise EditorialCarouselRenderError(
            f"{frame.frame_id} layout probe visible text does not match storyboard"
        )
    if attestation.issues or any(
        not item.visible
        or item.overflow
        or item.ink_clipped
        or item.layout_clipped
        for item in attestation.text_results
    ):
        raise EditorialCarouselRenderError(
            f"{frame.frame_id} layout probe failed: {attestation.issues}"
        )
    for item in attestation.text_results:
        expected_family = (
            "Source Han Serif SC"
            if item.role == "headline"
            else "Source Han Sans SC"
        )
        if item.font_family != expected_family:
            raise EditorialCarouselRenderError(
                f"{frame.frame_id} layout probe used an unexpected font for {item.role}"
            )
    expected_slots = [slot.slot_id for slot in frame.visual_slots]
    actual_slots = [asset.slot_id for asset in attestation.asset_results]
    if actual_slots != expected_slots:
        raise EditorialCarouselRenderError(
            f"{frame.frame_id} layout probe asset slots do not match storyboard"
        )
    return attestation


def _png_snapshot(
    path: Path, *, expected_size: tuple[int, int] | None = None
) -> tuple[str, tuple[int, int]]:
    try:
        data = path.read_bytes()
        with Image.open(BytesIO(data)) as image:
            if image.format != "PNG":
                raise ValueError(f"unexpected image format {image.format}")
            image.verify()
        with Image.open(BytesIO(data)) as image:
            image.load()
            size = image.size
    except (OSError, ValueError) as exc:
        raise EditorialCarouselRenderError(
            f"rendered PNG is corrupt at {path}: {exc}"
        ) from exc
    if expected_size is not None and size != expected_size:
        raise EditorialCarouselRenderError(
            f"rendered PNG at {path} has size {size}, expected {expected_size}"
        )
    return hashlib.sha256(data).hexdigest(), size


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


def _discard_staging(
    staging_dir: Path, render_error: EditorialCarouselRenderError
) -> None:
    try:
        shutil.rmtree(staging_dir)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise EditorialCarouselRenderError(
            f"could not remove editorial render staging directory: {exc}"
        ) from render_error


def _is_renderer_owned_name(name: str) -> bool:
    return (
        name == "contact-sheet.png"
        or _RENDERED_PAGE_NAME.fullmatch(name) is not None
    )


def _preserve_unrelated_entries(output_dir: Path, staging_dir: Path) -> None:
    if not output_dir.exists():
        return
    if not output_dir.is_dir():
        raise EditorialCarouselRenderError(
            f"editorial output path is not a directory: {output_dir}"
        )
    for source in output_dir.iterdir():
        if _is_renderer_owned_name(source.name):
            continue
        destination = staging_dir / source.name
        if destination.exists() or destination.is_symlink():
            raise EditorialCarouselRenderError(
                f"preserved output entry would overwrite staged render: {source.name}"
            )
        try:
            if source.is_symlink():
                destination.symlink_to(
                    source.readlink(), target_is_directory=source.is_dir()
                )
            elif source.is_dir():
                shutil.copytree(source, destination, symlinks=True)
            elif source.is_file():
                shutil.copy2(source, destination, follow_symlinks=False)
            else:
                raise EditorialCarouselRenderError(
                    f"cannot safely preserve special output entry: {source}"
                )
        except EditorialCarouselRenderError:
            raise
        except OSError as exc:
            raise EditorialCarouselRenderError(
                f"could not preserve output entry {source}: {exc}"
            ) from exc


def _publish_staging(staging_dir: Path, output_dir: Path, invocation: str) -> None:
    backup_dir = output_dir.parent / (
        f".{output_dir.name}.editorial-{invocation}.backup"
    )
    quarantine_dir = output_dir.parent / (
        f".{output_dir.name}.editorial-{invocation}.quarantine"
    )
    previous_moved = False
    try:
        if output_dir.exists():
            output_dir.replace(backup_dir)
            previous_moved = True
        staging_dir.replace(output_dir)
    except OSError as exc:
        if previous_moved and not output_dir.exists() and backup_dir.exists():
            backup_dir.replace(output_dir)
        raise EditorialCarouselRenderError(
            f"could not atomically publish editorial render: {exc}"
        ) from exc

    if not previous_moved:
        return
    try:
        backup_dir.replace(quarantine_dir)
    except OSError as exc:
        warnings.warn(
            "editorial publication committed, but previous output could not be moved "
            f"to quarantine and remains at {backup_dir}: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        return
    try:
        shutil.rmtree(quarantine_dir)
    except OSError as exc:
        warnings.warn(
            "editorial publication committed; partial previous output remains in "
            f"quarantine at {quarantine_dir}: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )


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
    frame_assets, used_asset_hashes = _resolve_storyboard_assets(storyboard, assets)

    output_dir = Path(output_dir).resolve()
    invocation = uuid.uuid4().hex
    staging_dir = output_dir.parent / (
        f".{output_dir.name}.editorial-{invocation}.staging"
    )
    try:
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        staging_dir.mkdir()
    except OSError as exc:
        raise EditorialCarouselRenderError(
            f"could not create editorial staging directory: {exc}"
        ) from exc

    frames = storyboard.storyboards
    final_page_paths = _output_paths(frames, output_dir)
    staged_page_paths = _output_paths(frames, staging_dir)
    final_contact_sheet_path = output_dir / "contact-sheet.png"
    staged_contact_sheet_path = staging_dir / "contact-sheet.png"
    temporary_html: list[Path] = []
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
                for index, (frame, staged_path, final_path) in enumerate(
                    zip(frames, staged_page_paths, final_page_paths, strict=True),
                    start=1,
                ):
                    html_path = staging_dir / f"page-{index:02d}.html"
                    temporary_html.append(html_path)
                    try:
                        renderer = LAYOUT_RENDERERS[frame.layout]
                        card = renderer(frame, frame_assets[frame.frame_id])
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
                        layout_report = _validate_layout_report(
                            probe_layout(page), frame
                        )
                    except Exception as exc:
                        if isinstance(exc, EditorialCarouselRenderError):
                            raise
                        raise EditorialCarouselRenderError(
                            f"{frame.frame_id} layout probe failed: {exc}"
                        ) from exc

                    try:
                        page.locator(".card").screenshot(path=str(staged_path))
                    except Exception as exc:
                        raise EditorialCarouselRenderError(
                            f"{frame.frame_id} screenshot failed: {exc}"
                        ) from exc
                    page_sha256, _ = _png_snapshot(
                        staged_path, expected_size=BEAUTY_EDITORIAL_V1.canvas
                    )
                    rendered_pages.append(
                        RenderedPage(
                            frame_id=frame.frame_id,
                            role=frame.role,
                            layout=frame.layout,
                            path=str(final_path),
                            width=1080,
                            height=1440,
                            sha256=page_sha256,
                            probe=layout_report,
                        )
                    )

                contact_html_path = (
                    staging_dir / "contact-sheet.html"
                )
                temporary_html.append(contact_html_path)
                try:
                    _write_html(
                        contact_html_path, _contact_sheet_html(staged_page_paths)
                    )
                    page.set_viewport_size({"width": 1404, "height": 3200})
                    page.goto(
                        contact_html_path.resolve().as_uri(), wait_until="load"
                    )
                    _validate_font_report(probe_fonts(page), "contact-sheet")
                    page.locator(".contact-sheet").screenshot(
                        path=str(staged_contact_sheet_path)
                    )
                    contact_sheet_sha256, _ = _png_snapshot(
                        staged_contact_sheet_path
                    )
                except EditorialCarouselRenderError:
                    raise
                except Exception as exc:
                    raise EditorialCarouselRenderError(
                        f"contact sheet screenshot failed: {exc}"
                    ) from exc
            finally:
                if browser is not None:
                    try:
                        browser.close()
                    except Exception as exc:
                        raise EditorialCarouselRenderError(
                            f"browser close failed: {exc}"
                        ) from exc

        _remove_paths(temporary_html)

        if font_report is None:
            raise EditorialCarouselRenderError("font probe did not run")
        manifest = RenderManifest(
            pages=rendered_pages,
            fonts=font_report,
            contact_sheet_path=str(final_contact_sheet_path),
            contact_sheet_sha256=contact_sheet_sha256,
            contact_sheet_page_sha256=[page.sha256 for page in rendered_pages],
            source_asset_sha256=used_asset_hashes,
        )
        _preserve_unrelated_entries(output_dir, staging_dir)
        _publish_staging(staging_dir, output_dir, invocation)
        return manifest
    except EditorialCarouselRenderError as render_error:
        _discard_staging(staging_dir, render_error)
        raise
    except Exception as exc:
        render_error = EditorialCarouselRenderError(
            f"editorial carousel rendering failed: {exc}"
        )
        _discard_staging(staging_dir, render_error)
        raise render_error from exc
