"""Static contract tests for the hand-authored template mockups.

These mockups are HUMAN VISUAL REFERENCES ONLY. They are standalone HTML files
under ``examples/templates-mockup/`` and are NOT produced by the production
renderer. No mockup string may be imported by production Python or prompts.

The tests here are deliberately offline (no Chromium): they only assert that
each mockup HTML honours the production canvas (1080x1440), carries the
``data-page`` selectors the deterministic render script expects, drops the
fixed-count sample copy that would imply a production page count, and that the
README states the sample count is non-binding.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


MOCKUP_ROOT = Path("examples/templates-mockup")

TEMPLATE_HTML_PATHS = [
    MOCKUP_ROOT / "set1-pink-red" / "template.html",
    MOCKUP_ROOT / "set2-teal" / "template.html",
    MOCKUP_ROOT / "set3-soft-pink" / "template.html",
    MOCKUP_ROOT / "set4-coral-promo" / "template.html",
    MOCKUP_ROOT / "set5-green-favorites" / "template.html",
    MOCKUP_ROOT / "set6-white-quote" / "template.html",
]

# This map MUST stay in sync with examples/templates-mockup/render_mockups.py.
EXPECTED_SETS = {
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

# Sample copy that would imply a fixed production page count. None of these may
# appear in any mockup: the mockup page count is a non-binding reference.
FORBIDDEN_FIXED_COUNT_PATTERNS = [
    "1080×1350",
    "1080x1350",
    "03 / 03",
    "02 / 03",
    "01 / 03",
    "STEP 01",
    "STEP 02",
    "STEP 03",
    "N°01",
    "N°02",
    "N°03",
    "FOLLOW FOR MORE",
    "follow for more",
]


@pytest.mark.parametrize("template_path", TEMPLATE_HTML_PATHS)
def test_mockup_templates_use_production_canvas_and_no_fixed_count_copy(
    template_path: Path,
) -> None:
    html = template_path.read_text(encoding="utf-8")
    assert "width:1080px" in html
    assert "height:1440px" in html
    for forbidden in FORBIDDEN_FIXED_COUNT_PATTERNS:
        assert forbidden not in html, f"{forbidden!r} present in {template_path}"


@pytest.mark.parametrize("template_path", TEMPLATE_HTML_PATHS)
def test_mockup_templates_have_at_least_three_non_cover_pages(
    template_path: Path,
) -> None:
    html = template_path.read_text(encoding="utf-8")
    # Count page blocks via the data-page attribute that the render script uses.
    page_selectors = re.findall(r'data-page="([^"]+)"', html)
    non_cover = [sel for sel in page_selectors if sel != "cover"]
    assert len(page_selectors) >= 4, (
        f"{template_path}: expected >=4 page archetypes (cover + >=3 others), "
        f"got {page_selectors}"
    )
    assert len(non_cover) >= 3, (
        f"{template_path}: expected >=3 non-cover archetypes, got {non_cover}"
    )


@pytest.mark.parametrize("set_name, selectors", EXPECTED_SETS.items())
def test_mockup_template_carries_expected_data_page_selectors(
    set_name: str, selectors: list[str]
) -> None:
    template_path = MOCKUP_ROOT / set_name / "template.html"
    html = template_path.read_text(encoding="utf-8")
    page_selectors = re.findall(r'data-page="([^"]+)"', html)
    # Every selector the render script will screenshot must be present, in order.
    assert page_selectors == selectors, (
        f"{set_name}: data-page selectors {page_selectors} != expected {selectors}"
    )


def test_mockup_templates_include_sparse_and_dense_examples() -> None:
    """Each set must demonstrate both sparse and dense archetype density."""
    all_selectors = []
    for set_name in EXPECTED_SETS:
        template_path = MOCKUP_ROOT / set_name / "template.html"
        html = template_path.read_text(encoding="utf-8")
        all_selectors.extend(re.findall(r'data-page="([^"]+)"', html))
    assert any(sel.endswith("-sparse") for sel in all_selectors), (
        "no sparse archetype found across mockup sets"
    )
    assert any(sel.endswith("-dense") for sel in all_selectors), (
        "no dense archetype found across mockup sets"
    )


def test_mockup_readme_states_reference_count_is_not_production_count() -> None:
    readme = (MOCKUP_ROOT / "README.md").read_text(encoding="utf-8")
    assert "样张图片数量不等于生产套图页数" in readme
    assert "5–7" in readme


def test_render_mockups_script_defines_expected_sets_map() -> None:
    script = (MOCKUP_ROOT / "render_mockups.py").read_text(encoding="utf-8")
    # The render script must define a SETS dict whose keys match the mockup sets
    # and whose selector lists match the contract above.
    for set_name, selectors in EXPECTED_SETS.items():
        assert f'"{set_name}"' in script, f"{set_name} missing from render_mockups.py SETS"
        for selector in selectors:
            assert f'"{selector}"' in script, (
                f"selector {selector!r} for {set_name} missing from render_mockups.py"
            )
