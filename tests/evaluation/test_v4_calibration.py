"""Critic calibration gate over the immutable quality-manifest corpus."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.evaluation.v4_calibration import (
    evaluate_calibration,
    evaluate_release_gate,
    load_quality_manifest,
)

MANIFEST = Path(__file__).resolve().parents[1] / "fixtures" / "llm_scene_v4" / "quality_manifest.json"


def quality_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def scripted_critic_that_passes_all(manifest: dict) -> list[dict]:
    return [{page["page_id"]: True for case in manifest["cases"] for page in case["pages"]}] * 2


def honest_critic(manifest: dict) -> list[dict]:
    run = {
        page["page_id"]: page["label"] == "positive"
        for case in manifest["cases"]
        for page in case["pages"]
    }
    return [dict(run), dict(run)]


def test_release_gate_rejects_known_negative_false_passes():
    manifest = quality_manifest()
    result = evaluate_calibration(manifest, scripted_critic_that_passes_all(manifest))
    assert result.gate_passed is False
    assert result.false_passed_negative_pages
    # Corpus page ids repeat across the two cases; after dedup every
    # distinct known-negative id must appear as a false pass.
    assert len(result.false_passed_negative_pages) >= 8


def test_honest_critic_passes_the_calibration_gate():
    manifest = quality_manifest()
    result = evaluate_calibration(manifest, honest_critic(manifest))
    assert result.gate_passed is True
    assert result.false_passed_negative_pages == ()
    assert result.missed_positive_pages == ()
    assert result.unstable_pages == ()


def test_missed_positive_cover_fails_closed():
    manifest = quality_manifest()
    runs = honest_critic(manifest)
    positive_id = next(
        page["page_id"] for case in manifest["cases"] for page in case["pages"] if page["label"] == "positive"
    )
    for run in runs:
        run[positive_id] = False
    result = evaluate_calibration(manifest, runs)
    assert result.gate_passed is False
    assert result.missed_positive_pages == (positive_id,)


def test_unstable_repeated_decisions_fail_the_gate():
    manifest = quality_manifest()
    runs = honest_critic(manifest)
    negative_id = next(
        page["page_id"] for case in manifest["cases"] for page in case["pages"] if page["label"] == "negative"
    )
    runs[1][negative_id] = True
    result = evaluate_calibration(manifest, runs)
    assert result.gate_passed is False
    assert negative_id in result.unstable_pages


def test_critical_human_regression_fails_the_gate():
    manifest = quality_manifest()
    negative_id = next(
        page["page_id"] for case in manifest["cases"] for page in case["pages"] if page["label"] == "negative"
    )
    runs = honest_critic(manifest)
    for run in runs:
        run[negative_id] = True  # critic waved an unpublishable page through
    result = evaluate_calibration(manifest, runs, human_regressions=(negative_id,))
    assert result.gate_passed is False
    assert result.critical_regressions == (negative_id,)


def test_release_gate_aggregates_predeclared_campaign_thresholds():
    manifest = quality_manifest()
    runs = honest_critic(manifest)
    result = evaluate_release_gate(
        manifest,
        runs,
        better_or_equal_ratio=0.85,
        topics=10,
        pages=80,
        max_attempts_per_candidate=9,
        max_request_ms=30_000,
    )
    assert result.gate_passed is True
    failing = evaluate_release_gate(
        manifest,
        runs,
        better_or_equal_ratio=0.5,
        topics=10,
        pages=80,
        max_attempts_per_candidate=9,
        max_request_ms=30_000,
    )
    assert failing.gate_passed is False
    assert failing.reasons


def test_load_quality_manifest_verifies_corpus_integrity():
    loaded = load_quality_manifest(MANIFEST)
    assert loaded is not None
    with pytest.raises(Exception):
        load_quality_manifest(MANIFEST, expect_sha256="0" * 64)
