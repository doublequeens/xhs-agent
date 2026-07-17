"""Offline visual-review renderer for the adaptive six-template workflow.

usage: render_adaptive_review.py --output DIR

Loads the six adaptive fixture IDs that map one-to-one to the six production
template families, drives the production ``render_carousel`` interface against
each, asserts that the family selected by the deterministic planner matches
the requested review family, and writes the rendered set under
``<output>/<family>/``.

Nothing is copied into ``outputs/publish/``: the renderer is given an explicit
output directory under ``--output`` for every family. The script exits nonzero
on any family mismatch, render failure, or output-path violation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "adaptive_editorial"

# Six fixture IDs mapped one-to-one to the six production template families.
# Each fixture's ``expected_template_family`` is the source of truth; this map
# is deliberately redundant so a fixture/family drift fails loudly here.
# The pair selection also ensures the review covers the 5/6/7-page content
# range: ``step_tutorial`` yields a 6-page deep_teal sheet and
# ``checklist_collection`` yields a 7-page green_catalog sheet (its top-level
# ``visible_copy.items`` anchor the dense checklist archetype).
FIXTURE_FAMILY_MAP = (
    ("cognitive_correction", "pink_red"),
    ("step_tutorial", "deep_teal"),
    ("diagnostic_qa", "soft_pink"),
    ("story_reversal", "coral_impact"),
    ("checklist_collection", "green_catalog"),
    ("reflective_editorial", "white_quote"),
)


def load_fixture(fixture_id: str) -> dict[str, Any]:
    fixture = json.loads(
        (FIXTURE_ROOT / f"{fixture_id}.json").read_text(encoding="utf-8")
    )
    assert fixture["fixture_id"] == fixture_id
    assert fixture["test_only"] is True
    assert fixture["intended_use"].startswith("synthetic regression input only")
    return fixture


def _storyboards_for_plan(fixture: dict[str, Any], visual_plan: Any) -> list[dict[str, Any]]:
    """Mirror the offline harness storyboard synthesizer."""

    visible = fixture.get("visible_copy") or {}
    save_headline = visible.get("save") or "保存本次合成回归卡"
    cover_headline = fixture["content_contract"]["first_screen_promise"]
    saveable_archetypes = {"save", "checklist", "comparison"}
    storyboards: list[dict[str, Any]] = []
    for frame in visual_plan.frame_plan:
        archetype = frame.page_archetype
        if archetype == "cover":
            headline = cover_headline
        elif archetype in saveable_archetypes:
            headline = save_headline
        else:
            headline = frame.purpose
        items = (
            visible.get("items")
            if archetype == "checklist" and "items" in visible
            else ["合成回归项一", "合成回归项二", "合成回归项三"]
        )
        block_type = {
            "checklist": "checklist",
            "comparison": "comparison",
            "steps": "steps",
            "diagnostic": "decision_tree",
            "qa": "text",
        }.get(archetype, "text")
        storyboards.append(
            {
                "frame_id": frame.frame_id,
                "role": frame.role,
                "page_archetype": archetype,
                "headline": headline[:80],
                "kicker": "合成回归",
                "content_blocks": [
                    {
                        "block_type": block_type,
                        "heading": headline[:80],
                        "body": frame.purpose,
                        "items": list(items),
                    }
                ],
                "emphasis": [],
                "visual_slots": [],
                "footer": "仅限合成回归",
            }
        )
    return storyboards


def _empty_asset_manifest() -> Any:
    from src.schemas.assets import AssetManifest

    return AssetManifest.model_validate(
        {
            "items": [],
            "search_report": {
                "search_triggered": False,
                "queries": [],
                "provider_reports": [],
                "selection_reasons": {},
            },
        }
    )


def render_fixture_family(
    fixture_id: str,
    requested_family: str,
    output_root: Path,
) -> Path:
    """Render one fixture's carousel under ``<output_root>/<family>/``.

    Returns the actual output directory. Raises ``SystemExit`` on any
    family mismatch or render error.
    """

    from src.editorial_carousel.planner import build_visual_plan
    from src.rendering.editorial.renderer import render_carousel
    from src.schemas.content_contract import ContentContract
    from src.schemas.narrative import NarrativePlan
    from src.schemas.storyboard import CarouselPayload

    fixture = load_fixture(fixture_id)
    contract = ContentContract.model_validate(fixture["content_contract"])
    narrative_plan = NarrativePlan.model_validate(fixture["narrative_plan"])
    package = fixture["package"]
    visual_plan = build_visual_plan(
        contract,
        narrative_plan,
        package,
        recent_signatures=[],
    )

    actual_family = visual_plan.template_family
    if actual_family != requested_family:
        raise SystemExit(
            f"{fixture_id}: requested family {requested_family!r} but planner "
            f"selected {actual_family!r}"
        )
    if actual_family != fixture["expected_template_family"]:
        raise SystemExit(
            f"{fixture_id}: planner selected {actual_family!r} but fixture "
            f"expected {fixture['expected_template_family']!r}"
        )

    storyboards = _storyboards_for_plan(fixture, visual_plan)
    payload = CarouselPayload.model_validate({"storyboards": storyboards})
    assets = _empty_asset_manifest()
    output_dir = output_root / requested_family / "images"
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = render_carousel(visual_plan, payload, assets, output_dir)
    if len(manifest.pages) < 5 or len(manifest.pages) > 7:
        raise SystemExit(
            f"{fixture_id}: rendered {len(manifest.pages)} pages; expected 5-7"
        )
    if not manifest.fonts.all_loaded:
        raise SystemExit(f"{fixture_id}: renderer reported fonts that did not load")

    return output_dir.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Render the six adaptive fixture families for visual review. "
            "Writes under <output>/<family>/ and never touches outputs/publish/."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Root directory to write per-family renders under.",
    )
    args = parser.parse_args(argv)

    output_root: Path = args.output.resolve()
    if not output_root.exists():
        output_root.mkdir(parents=True, exist_ok=True)
    publish_root = (REPOSITORY_ROOT / "outputs" / "publish").resolve()
    try:
        output_root.relative_to(publish_root)
        raise SystemExit(
            "--output must not live under outputs/publish/; adaptive review "
            "writes outside the production publish tree"
        )
    except ValueError:
        # output_root is not inside outputs/publish/ — proceed.
        pass

    rendered: list[tuple[str, str, Path]] = []
    for fixture_id, family in FIXTURE_FAMILY_MAP:
        try:
            family_dir = render_fixture_family(fixture_id, family, output_root)
        except SystemExit as exc:
            print(f"FAIL {fixture_id} -> {family}: {exc}", file=sys.stderr)
            return 1
        rendered.append((fixture_id, family, family_dir))
        print(
            f"OK   {fixture_id:<22} -> {family:<14} {len(list(family_dir.rglob('*.png')))} PNGs"
        )

    if len({family for _, family, _ in rendered}) != len(FIXTURE_FAMILY_MAP):
        print(
            "FAIL: rendered families are not unique one-to-one with fixtures",
            file=sys.stderr,
        )
        return 1

    print(f"\nRendered {len(rendered)} families under {output_root}")
    return 0


if __name__ == "__main__":  # pragma: no cover - manual visual review entry
    raise SystemExit(main())
