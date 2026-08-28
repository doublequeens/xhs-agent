#!/usr/bin/env python
"""Render blind v4-vs-v3 shadow review evidence from the quality corpus.

Offline mode (default) composes the blind A/B contact sheets for the two
immutable quality-manifest cases and writes the anonymized blind payload
plus the private identity mapping side-by-side for the local reviewer.

The full G4 campaign (--campaign) additionally drives real shadow runs and
requires explicit credentials/approval; it is intentionally manual and is
not exercised by the offline test suite.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.evaluation.v4_calibration import load_quality_manifest  # noqa: E402
from src.evaluation.v4_comparison import (  # noqa: E402
    VariantBundle,
    VariantPage,
    build_blind_report,
    compose_contact_sheets,
)

MANIFEST_PATH = ROOT / "tests" / "fixtures" / "llm_scene_v4" / "quality_manifest.json"


def build_case_bundles(manifest: dict, case: dict) -> tuple[VariantBundle, VariantBundle]:
    corpus_root = MANIFEST_PATH.parent
    v3_pages = []
    v4_pages = []
    for page in case["pages"]:
        path = corpus_root / case["case_id"] / page["path"]
        # Offline corpus pages are the historical v3 renders; the v4 side of
        # the offline sheet is the same reviewed page served as the blind
        # counterpart placeholder until a real shadow run replaces it.
        passed = page["label"] == "positive"
        v3_pages.append(
            VariantPage(
                page_id=page["page_id"],
                image_path=path,
                hard_qa_passed=passed,
                evidence={"corpus_label": page["label"], "human_issues": page["human_issues"]},
            )
        )
        v4_pages.append(
            VariantPage(
                page_id=page["page_id"],
                image_path=path,
                hard_qa_passed=passed,
                evidence={"corpus_label": page["label"], "human_issues": page["human_issues"]},
            )
        )
    critic = case["critic"]
    return (
        VariantBundle(
            workflow_version="llm_scene_v3",
            topic=case["case_id"],
            pages=tuple(v3_pages),
            attempts=int(critic.get("revision_round", 0)) + 1,
            latency_ms=0,
            revision_rounds=int(critic.get("revision_round", 0)),
        ),
        VariantBundle(
            workflow_version="llm_scene_v4",
            topic=case["case_id"],
            pages=tuple(v4_pages),
            attempts=int(critic.get("revision_round", 0)) + 1,
            latency_ms=0,
            revision_rounds=int(critic.get("revision_round", 0)),
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render blind v4 shadow review evidence")
    parser.add_argument("--cases", type=int, default=10, help="number of campaign cases (manual mode)")
    parser.add_argument("--output", type=Path, default=Path("outputs/review/llm_scene_v4"))
    parser.add_argument("--campaign", action="store_true", help="run the credential-backed G4 campaign (manual)")
    args = parser.parse_args(argv)

    manifest = load_quality_manifest(MANIFEST_PATH)
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    if args.campaign:
        print(
            "G4 campaign mode requires explicit credentials and human approval; "
            "run it manually with the documented provider flags.",
            file=sys.stderr,
        )
        return 2

    index = []
    for case in manifest["cases"]:
        v3, v4 = build_case_bundles(manifest, case)
        report = build_blind_report(v3, v4, seed=case["case_id"])
        sheets = compose_contact_sheets(report, output / case["case_id"] / "sheets")
        (output / case["case_id"] / "blind-payload.json").write_text(
            report.public_payload_json(), encoding="utf-8"
        )
        # The identity mapping is review-local evidence; it never enters the
        # blind payload handed to a reviewer.
        (output / case["case_id"] / "identity.private.json").write_text(
            json.dumps(dict(report.identity), ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        index.append(
            {
                "case_id": case["case_id"],
                "sheets": len(sheets),
                "labels": dict(report.identity),
            }
        )
    (output / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {len(index)} blind case packages under {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
