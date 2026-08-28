"""Blind A/B shadow comparison with a private identity mapping.

The public blind-review payload carries only anonymized variants ("A"/"B"
assigned deterministically from a seed), per-page hard-QA evidence, attempt,
latency and revision counters.  Workflow versions and topics stay in a
separate identity object that never serializes into the public payload, so a
blind reviewer can never learn which variant is which.  Image paths are
private for the same reason: a path can name the workflow through its
location.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class VariantPage:
    page_id: str
    image_path: Path
    hard_qa_passed: bool
    evidence: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VariantBundle:
    workflow_version: str
    topic: str
    pages: tuple[VariantPage, ...]
    attempts: int
    latency_ms: int
    revision_rounds: int


@dataclass(frozen=True)
class BlindComparisonReport:
    """Public anonymized payload plus the deliberately separate identity."""

    variants: Mapping[str, dict[str, Any]]
    identity: Mapping[str, str]  # private: label -> workflow_version
    seed: str
    image_paths: Mapping[str, tuple[Path, ...]] = field(default_factory=dict)

    def public_payload_json(self) -> str:
        payload = {
            "kind": "blind_comparison_v1",
            "seed": self.seed,
            "variants": {label: dict(value) for label, value in self.variants.items()},
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _assign_labels(seed: str, versions: tuple[str, str]) -> dict[str, str]:
    digest = hashlib.sha256(
        f"{seed}:{'/'.join(sorted(versions))}".encode("utf-8")
    ).hexdigest()
    first, second = versions
    if int(digest[:8], 16) % 2 == 0:
        return {"A": first, "B": second}
    return {"A": second, "B": first}


def _public_variant(bundle: VariantBundle) -> dict[str, Any]:
    return {
        "pages": [
            {
                "page_id": f"p{index + 1:02d}",
                "hard_qa_passed": page.hard_qa_passed,
                "evidence": dict(page.evidence),
            }
            for index, page in enumerate(bundle.pages)
        ],
        "attempts": bundle.attempts,
        "latency_ms": bundle.latency_ms,
        "revision_rounds": bundle.revision_rounds,
    }


def build_blind_report(
    v3_bundle: VariantBundle,
    v4_bundle: VariantBundle,
    *,
    seed: str,
) -> BlindComparisonReport:
    if not seed:
        raise ValueError("blind comparison requires a non-empty seed")
    if v3_bundle.workflow_version == v4_bundle.workflow_version:
        raise ValueError("blind comparison requires two distinct workflow versions")
    identity = _assign_labels(seed, (v3_bundle.workflow_version, v4_bundle.workflow_version))
    by_version = {
        v3_bundle.workflow_version: v3_bundle,
        v4_bundle.workflow_version: v4_bundle,
    }
    variants = {
        label: _public_variant(by_version[version]) for label, version in identity.items()
    }
    image_paths = {
        label: tuple(page.image_path for page in by_version[version].pages)
        for label, version in identity.items()
    }
    return BlindComparisonReport(
        variants=variants,
        identity=identity,
        seed=seed,
        image_paths=image_paths,
    )


def compose_contact_sheets(
    report: BlindComparisonReport,
    out_dir: Path,
) -> tuple[Path, ...]:
    """Write one side-by-side contact sheet per page index (label A left, B right)."""

    from PIL import Image

    out_dir.mkdir(parents=True, exist_ok=True)
    paths_a = report.image_paths.get("A", ())
    paths_b = report.image_paths.get("B", ())
    count = min(len(paths_a), len(paths_b))
    sheets: list[Path] = []
    for index in range(count):
        left = Image.open(paths_a[index]).convert("RGB")
        right = Image.open(paths_b[index]).convert("RGB")
        height = max(left.height, right.height)
        if left.height != height:
            left = left.crop((0, 0, left.width, height))
        if right.height != height:
            right = right.crop((0, 0, right.width, height))
        sheet = Image.new("RGB", (left.width + right.width, height), "#FFFFFF")
        sheet.paste(left, (0, 0))
        sheet.paste(right, (left.width, 0))
        path = out_dir / f"sheet-{index + 1:02d}.png"
        sheet.save(path, format="PNG")
        sheets.append(path)
    return tuple(sheets)
