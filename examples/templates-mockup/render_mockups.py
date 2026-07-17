"""Deterministic renderer for the six hand-authored template mockups.

These mockups are HUMAN VISUAL REFERENCES ONLY -- standalone HTML files under
``examples/templates-mockup/`` that visually represent each production template
family. They are NOT produced by the production renderer and no mockup string
is imported by production Python or prompts.

This script:

* defines the ``SETS`` selector map (set directory -> ordered list of
  ``data-page`` selectors to screenshot);
* for each selector, takes a 1080x1440 screenshot with Playwright (after
  waiting for ``document.fonts.ready``);
* refuses unknown selectors (every selector in ``SETS`` must exist as a
  ``data-page`` attribute in the corresponding ``template.html``);
* builds each set's ``contact-sheet.png`` from its screenshots via Pillow;
* builds ``gallery-all-6.png`` from the six cover screenshots.

Run from the repository root::

    python examples/templates-mockup/render_mockups.py

The script is intentionally self-contained and writes only to
``examples/templates-mockup/``. It does not export a production page count.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright


# Ordered selector map. Each list is the sequence of ``data-page`` values the
# script will screenshot for that set. Keep this in sync with the
# ``EXPECTED_SETS`` constant in ``tests/examples/test_template_mockups.py``.
SETS: dict[str, list[str]] = {
    "set1-pink-red": ["cover", "steps-standard", "comparison-dense", "save"],
    "set2-teal": ["cover", "explanation-standard", "checklist-dense", "qa"],
    "set3-soft-pink": ["cover", "scene-sparse", "diagnostic-standard", "save"],
    "set4-coral-promo": ["cover", "story-beat", "steps-dense", "boundary"],
    "set5-green-favorites": [
        "cover",
        "collection-standard",
        "collection-dense",
        "comparison",
        "save",
    ],
    "set6-white-quote": [
        "cover",
        "quote-sparse",
        "explanation-standard",
        "checklist-dense",
        "boundary",
    ],
}

CANVAS_W = 1080
CANVAS_H = 1440

# Contact-sheet layout: 2 columns, computed row count per set.
SHEET_COLS = 2
SHEET_PAD = 24
SHEET_BG = (34, 34, 34)


def _read_selectors(template_html: Path) -> list[str]:
    html = template_html.read_text(encoding="utf-8")
    return re.findall(r'data-page="([^"]+)"', html)


def _validate_sets(root: Path) -> None:
    """Refuse unknown selectors: every SETS entry must exist in its template."""
    for set_name, selectors in SETS.items():
        template_html = root / set_name / "template.html"
        if not template_html.exists():
            raise FileNotFoundError(f"missing template: {template_html}")
        present = _read_selectors(template_html)
        for selector in selectors:
            if selector not in present:
                raise ValueError(
                    f"selector {selector!r} for {set_name} not found in "
                    f"{template_html}; available selectors: {present}"
                )


def _screenshot_selector(
    page, template_html: Path, selector: str, out_path: Path
) -> None:
    page.goto(template_html.resolve().as_uri(), wait_until="load")
    # Wait for web fonts so the rendered text matches the design.
    page.evaluate("document.fonts.ready")
    locator = page.locator(f'div.page[data-page="{selector}"]')
    locator.screenshot(path=str(out_path))


def _build_contact_sheet(set_dir: Path, shot_paths: list[Path]) -> Path:
    """Tile the set's screenshots into a 2-column contact sheet."""
    images = [Image.open(p).convert("RGB") for p in shot_paths]
    n = len(images)
    rows = (n + SHEET_COLS - 1) // SHEET_COLS
    sheet_w = SHEET_COLS * CANVAS_W + (SHEET_COLS + 1) * SHEET_PAD
    sheet_h = rows * CANVAS_H + (rows + 1) * SHEET_PAD
    sheet = Image.new("RGB", (sheet_w, sheet_h), SHEET_BG)
    for idx, img in enumerate(images):
        r, c = divmod(idx, SHEET_COLS)
        x = SHEET_PAD + c * (CANVAS_W + SHEET_PAD)
        y = SHEET_PAD + r * (CANVAS_H + SHEET_PAD)
        sheet.paste(img, (x, y))
    out_path = set_dir / "contact-sheet.png"
    sheet.save(out_path)
    return out_path


def _build_gallery(root: Path, cover_paths: list[Path]) -> Path:
    """Tile the six cover screenshots into a 2x3 gallery."""
    images = [Image.open(p).convert("RGB") for p in cover_paths]
    n = len(images)
    cols = 2
    rows = (n + cols - 1) // cols
    sheet_w = cols * CANVAS_W + (cols + 1) * SHEET_PAD
    sheet_h = rows * CANVAS_H + (rows + 1) * SHEET_PAD
    sheet = Image.new("RGB", (sheet_w, sheet_h), SHEET_BG)
    for idx, img in enumerate(images):
        r, c = divmod(idx, cols)
        x = SHEET_PAD + c * (CANVAS_W + SHEET_PAD)
        y = SHEET_PAD + r * (CANVAS_H + SHEET_PAD)
        sheet.paste(img, (x, y))
    out_path = root / "gallery-all-6.png"
    sheet.save(out_path)
    return out_path


def render(root: Path) -> dict[str, list[str]]:
    """Render every set; return a per-set list of written PNG paths."""
    _validate_sets(root)
    written: dict[str, list[str]] = {}
    cover_paths: list[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": CANVAS_W, "height": CANVAS_H},
            device_scale_factor=1,
        )
        try:
            for set_name, selectors in SETS.items():
                set_dir = root / set_name
                shot_paths: list[Path] = []
                for selector in selectors:
                    out_path = set_dir / f"{selector}.png"
                    _screenshot_selector(
                        page, set_dir / "template.html", selector, out_path
                    )
                    shot_paths.append(out_path)
                    if selector == "cover":
                        cover_paths.append(out_path)
                sheet_path = _build_contact_sheet(set_dir, shot_paths)
                written[set_name] = [str(p) for p in shot_paths + [sheet_path]]
        finally:
            browser.close()
    if len(cover_paths) != len(SETS):
        raise RuntimeError(
            f"expected {len(SETS)} cover screenshots, got {len(cover_paths)}"
        )
    gallery = _build_gallery(root, cover_paths)
    written["__gallery__"] = [str(gallery)]
    return written


def main() -> int:
    root = Path(__file__).resolve().parent
    written = render(root)
    for set_name, paths in written.items():
        label = "gallery" if set_name == "__gallery__" else set_name
        print(f"[{label}]")
        for path in paths:
            print(f"  {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
