from __future__ import annotations

import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_FIXTURE_ROOT = REPOSITORY_ROOT / "tests/fixtures/editorial_carousel"
GOLDEN_FIXTURE_NAMES = (
    "zone_diagnosis",
    "ordered_routine",
    "multi_option_decision",
    "reference_checklist",
)
_FIXTURE_ENVELOPE_KEYS = frozenset(
    {
        "fixture_id",
        "test_only",
        "intended_use",
        "synthetic_title",
        "narrative_form",
        "narrative_plan",
        "expected_template_family",
        "expected_archetypes",
        "content_contract",
        "package",
        "visible_copy",
    }
)


def load_golden_fixture(name: str) -> dict:
    if name not in GOLDEN_FIXTURE_NAMES:
        raise ValueError(f"unknown editorial carousel golden fixture: {name}")
    fixture = json.loads(
        (GOLDEN_FIXTURE_ROOT / f"{name}.json").read_text(encoding="utf-8")
    )
    if set(fixture) != _FIXTURE_ENVELOPE_KEYS:
        raise ValueError(f"{name} has an invalid golden fixture envelope")
    if (
        fixture["fixture_id"] != name
        or fixture["test_only"] is not True
        or not fixture["intended_use"].startswith(
            "synthetic regression input only"
        )
    ):
        raise ValueError(f"{name} is not explicitly isolated test data")
    return fixture
