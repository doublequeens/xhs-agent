"""Blind A/B comparison: anonymized payload, private identity, contact sheets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.evaluation.v4_comparison import (
    BlindComparisonReport,
    VariantBundle,
    VariantPage,
    build_blind_report,
    compose_contact_sheets,
)


def _bundle(version: str, *, topic: str, passed: bool = True) -> VariantBundle:
    return VariantBundle(
        workflow_version=version,
        topic=topic,
        pages=(
            VariantPage(
                page_id="page-1",
                image_path=Path(f"/tmp/{version}-1.png"),
                hard_qa_passed=passed,
                evidence={"q3_passed": passed, "attempts": 2, "revision_rounds": 1},
            ),
        ),
        attempts=2,
        latency_ms=1200,
        revision_rounds=1,
    )


def _pair() -> tuple[VariantBundle, VariantBundle]:
    return _bundle("llm_scene_v3", topic="早C晚A"), _bundle("llm_scene_v4", topic="早C晚A")


def test_blind_report_hides_variant_identity():
    v3, v4 = _pair()
    report = build_blind_report(v3, v4, seed="case-1")
    assert set(report.variants) == {"A", "B"}
    public = report.public_payload_json()
    assert "llm_scene_v3" not in public
    assert "llm_scene_v4" not in public
    assert "早C晚A" not in public  # topic stays private too
    parsed = json.loads(public)
    for payload in parsed["variants"].values():
        assert set(payload) >= {"pages", "attempts", "latency_ms", "revision_rounds"}
        assert payload["pages"][0]["hard_qa_passed"] is True


def test_identity_is_private_and_seed_deterministic():
    v3, v4 = _pair()
    first = build_blind_report(v3, v4, seed="case-1")
    second = build_blind_report(v3, v4, seed="case-1")
    assert first.identity == second.identity
    assert set(first.identity.values()) == {"llm_scene_v3", "llm_scene_v4"}
    flipped = build_blind_report(v3, v4, seed="case-2")
    swapped = {"A": first.identity["B"], "B": first.identity["A"]}
    assert flipped.identity in (first.identity, swapped)
    # The identity mapping lives on a separate object, never in the payload.
    assert "llm_scene_v3" not in first.public_payload_json()


def test_contact_sheets_compose_side_by_side(tmp_path):
    from PIL import Image

    for name in ("v3", "v4"):
        Image.new("RGB", (60, 80), "#FF0000" if name == "v3" else "#00FF00").save(
            tmp_path / f"{name}.png"
        )
    v3 = _bundle("llm_scene_v3", topic="t")
    v4 = _bundle("llm_scene_v4", topic="t")
    v3 = VariantBundle(**{**v3.__dict__, "pages": (VariantPage(page_id="page-1", image_path=tmp_path / "v3.png", hard_qa_passed=True),)})
    v4 = VariantBundle(**{**v4.__dict__, "pages": (VariantPage(page_id="page-1", image_path=tmp_path / "v4.png", hard_qa_passed=True),)})
    report = build_blind_report(v3, v4, seed="s")
    out = compose_contact_sheets(report, tmp_path / "sheets")
    assert len(out) == 1
    sheet = Image.open(out[0])
    assert sheet.size == (120, 80)
    left = sheet.crop((0, 0, 60, 80)).getpixel((30, 40))
    right = sheet.crop((60, 0, 120, 80)).getpixel((30, 40))
    assert {left, right} == {(255, 0, 0), (0, 255, 0)}
