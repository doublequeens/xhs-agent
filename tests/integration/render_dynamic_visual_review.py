"""Render-review script for the 24-case dynamic-visual golden set.

Renders EVERY golden case through the REAL production graph end-to-end (real
``create_graph()``, scripted fakes only for the four structured-model visual
nodes; the REAL Chromium renderer renders the scripted ``CarouselDesignPlan``
into actual 1080x1440 PNGs) and produces, under a Git-excluded review tree:

* one contact sheet per case (the renderer's own all-pages grid);
* one family contact sheet per family (a grid of every case's cover page in
  that family) so a human can inspect family coherence at a glance;
* a machine-readable ``summary.json`` with per-case dimensions / page count /
  QA verdicts / asset mode / PNG + contact-sheet paths, and per-family contact
  sheet paths.

It never touches the canonical ``outputs/publish`` packages: every artifact is
written under ``outputs/review/dynamic_visual/<timestamp>/`` (``outputs/`` is
gitignored, so the review tree is never committed).

Run from the repo root:

    python tests/integration/render_dynamic_visual_review.py

This is a SLOW, real-browser artifact generator (not a pytest); it is the
"Step 6" surface a human inspects. The deterministic golden TESTS live in
``tests/dynamic_visual/test_golden_set.py`` and never launch a browser.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Bootstrap the repo root onto sys.path so the script is runnable directly
# (``python tests/integration/render_dynamic_visual_review.py``) without the
# pytest ``pythonpath = .`` injection.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image

import pytest

from src.schemas.content_atoms import canonical_sha256  # noqa: F401  (kept for summary hash use)
from tests.dynamic_visual.golden_fixtures import (
    ContentWriterReached,
    GoldenHarness,
    all_case_ids,
    load_case,
    load_manifest,
)

REVIEW_ROOT = REPO_ROOT / "outputs" / "review" / "dynamic_visual"

# Thumbnail geometry for the family cover-grid contact sheets.
_COVER_THUMB_W = 360
_COVER_THUMB_H = 480
_GRID_PADDING = 16
_GRID_BG = (245, 245, 245)


def _run_case(case_id: str, review_dir: Path) -> dict:
    """Render one case through the real Chromium path; return a result record."""
    mp = pytest.MonkeyPatch()
    try:
        tmp_path = Path(tempfile.mkdtemp(prefix=f"golden-review-{case_id}-"))
        spec = load_case(case_id)
        harness = GoldenHarness(
            spec=spec, tmp_path=tmp_path, deterministic_render=False
        )
        try:
            state = harness.run(mp)
        except ContentWriterReached as captured:
            state = captured.state

        record: dict = {
            "case_id": case_id,
            "family": spec.family,
            "page_count": spec.page_count,
            "density": spec.density,
            "copy_shape": spec.copy_shape,
            "asset_mode": spec.asset_mode,
            "note": spec.note,
        }

        if not state or state.get("render_manifest") is None:
            record["status"] = "no_render_manifest"
            record["final_policy_issues"] = state.get("final_policy_issues") if state else None
            return record

        render_manifest = state["render_manifest"]
        dqa = state.get("design_plan_qa_result")
        rqa = state.get("render_qa_result")
        record.update(
            {
                "status": "rendered",
                "design_plan_qa_passed": bool(dqa and dqa.passed),
                "render_qa_passed": bool(rqa and rqa.passed),
                "review_status": state.get("review_status"),
                "final_policy_issues": state.get("final_policy_issues") or [],
                "page_count_rendered": len(render_manifest.pages),
                "page_dimensions": {
                    "width": render_manifest.pages[0].width,
                    "height": render_manifest.pages[0].height,
                },
                "page_files": [],
                "contact_sheet": None,
            }
        )
        # Copy the rendered pages + per-case contact sheet into the review tree.
        case_dir = review_dir / "cases" / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        page_paths = []
        for page in render_manifest.pages:
            src = Path(page.path)
            dst = case_dir / f"{page.sequence:02d}-{page.page_id}.png"
            if src.is_file():
                shutil.copyfile(src, dst)
            page_paths.append(str(dst.relative_to(REPO_ROOT)))
        record["page_files"] = page_paths

        sheet_src = Path(render_manifest.contact_sheet_path)
        sheet_dst = case_dir / "contact-sheet.png"
        if sheet_src.is_file():
            shutil.copyfile(sheet_src, sheet_dst)
            record["contact_sheet"] = str(sheet_dst.relative_to(REPO_ROOT))
            record["cover_page"] = page_paths[0] if page_paths else None
        return record
    except Exception as exc:  # pragma: no cover - review-only, best effort
        return {
            "case_id": case_id,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        mp.undo()


def _build_family_contact_sheets(records: list[dict], family_dir: Path) -> dict:
    """One cover-page grid per family. Returns ``{family: contact_sheet_path}``."""
    by_family: dict[str, list[dict]] = {}
    for record in records:
        if record.get("cover_page"):
            by_family.setdefault(record["family"], []).append(record)

    result: dict[str, str] = {}
    for family, members in sorted(by_family.items()):
        members.sort(key=lambda r: r["case_id"])
        covers = [REPO_ROOT / r["cover_page"] for r in members]
        valid = [path for path in covers if path.is_file()]
        if not valid:
            continue
        cols = len(valid)
        canvas_w = cols * (_COVER_THUMB_W + _GRID_PADDING) + _GRID_PADDING
        canvas_h = _COVER_THUMB_H + 2 * _GRID_PADDING
        sheet = Image.new("RGB", (canvas_w, canvas_h), _GRID_BG)
        for index, path in enumerate(valid):
            with Image.open(path) as img:
                thumb = img.resize((_COVER_THUMB_W, _COVER_THUMB_H))
                x = _GRID_PADDING + index * (_COVER_THUMB_W + _GRID_PADDING)
                sheet.paste(thumb, (x, _GRID_PADDING))
        out_path = family_dir / f"{family}-cover-grid.png"
        sheet.save(out_path)
        result[family] = str(out_path.relative_to(REPO_ROOT))
    return result


def main() -> int:
    # Guard: the review tree MUST live under a Git-excluded path (``outputs/``
    # is gitignored), so review artifacts are never committed alongside the
    # canonical publish packages.
    try:
        REVIEW_ROOT.relative_to(REPO_ROOT / "outputs")
    except ValueError as exc:
        raise SystemExit(
            f"refusing to write review output outside outputs/: {REVIEW_ROOT}"
        ) from exc

    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    review_dir = REVIEW_ROOT / timestamp
    review_dir.mkdir(parents=True, exist_ok=True)

    case_ids = all_case_ids()
    print(f"Rendering {len(case_ids)} golden cases through real Chromium into:")
    print(f"  {review_dir}")
    records: list[dict] = []
    for case_id in case_ids:
        print(f"  - {case_id} ...", flush=True)
        record = _run_case(case_id, review_dir)
        records.append(record)
        print(f"      -> {record.get('status')}")

    family_dir = review_dir / "families"
    family_dir.mkdir(parents=True, exist_ok=True)
    family_sheets = _build_family_contact_sheets(records, family_dir)

    manifest = load_manifest()
    summary = {
        "generated_at": timestamp,
        "review_dir": str(review_dir.relative_to(REPO_ROOT)),
        "matrix_axes": manifest["matrix_axes"],
        "case_count": len(records),
        "rendered_count": sum(1 for r in records if r.get("status") == "rendered"),
        "error_count": sum(1 for r in records if r.get("status") in ("error", "no_render_manifest")),
        "family_contact_sheets": family_sheets,
        "cases": records,
    }
    summary_path = review_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print()
    print("=== dynamic visual golden review ===")
    print(f"rendered: {summary['rendered_count']}/{summary['case_count']}")
    print(f"errors:   {summary['error_count']}")
    print(f"summary:  {summary_path.relative_to(REPO_ROOT)}")
    print("family contact sheets (for human visual inspection):")
    for family, path in sorted(family_sheets.items()):
        print(f"  {family:14s} -> {path}")
    return 0 if summary["error_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
