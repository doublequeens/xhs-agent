"""Critic calibration and the predeclared G4 release gate.

The calibration gate runs a critic (repeatedly) over the immutable
quality-manifest corpus and requires:

- every human-rated positive cover passes (missed positives fail closed);
- the known negative inner pages do not ALL pass (a scripted
  pass-everything critic lists every negative as a false pass and fails);
- zero critical human regressions (a negative page the human rates
  unpublishable that the critic waved through);
- stable repeated final decisions per page across runs.

The release gate additionally aggregates the predeclared campaign
thresholds declared in the manifest's ``campaign`` section.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class CalibrationResult:
    gate_passed: bool
    missed_positive_pages: tuple[str, ...]
    false_passed_negative_pages: tuple[str, ...]
    critical_regressions: tuple[str, ...]
    unstable_pages: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ReleaseGateResult:
    gate_passed: bool
    calibration: CalibrationResult
    reasons: tuple[str, ...]


def load_quality_manifest(
    path: Path, *, expect_sha256: str | None = None
) -> dict[str, Any]:
    raw = Path(path).read_bytes()
    if expect_sha256 is not None and hashlib.sha256(raw).hexdigest() != expect_sha256:
        raise ValueError("quality manifest bytes differ from the expected corpus hash")
    manifest = json.loads(raw.decode("utf-8"))
    if not isinstance(manifest.get("cases"), list) or not manifest["cases"]:
        raise ValueError("quality manifest requires a non-empty case corpus")
    for case in manifest["cases"]:
        labels = {page["label"] for page in case["pages"]}
        if "positive" not in labels or "negative" not in labels:
            raise ValueError(
                f"quality case {case.get('case_id')!r} must carry positive and negative labels"
            )
    return manifest


def _final_decision(runs: Sequence[Mapping[str, bool]], page_id: str) -> bool:
    votes = [run[page_id] for run in runs]
    return sum(votes) * 2 > len(votes)


def evaluate_calibration(
    manifest: Mapping[str, Any],
    critic_runs: Sequence[Mapping[str, bool]],
    *,
    human_regressions: Sequence[str] = (),
) -> CalibrationResult:
    if not critic_runs:
        raise ValueError("calibration requires at least one critic run")
    positives: list[str] = []
    negatives: list[str] = []
    for case in manifest["cases"]:
        for page in case["pages"]:
            (positives if page["label"] == "positive" else negatives).append(page["page_id"])
    all_pages = set(positives) | set(negatives)
    for run in critic_runs:
        missing = all_pages - set(run)
        if missing:
            raise ValueError(f"critic run is missing page decisions: {sorted(missing)[:3]}")

    missed = tuple(dict.fromkeys(p for p in positives if not _final_decision(critic_runs, p)))
    false_passed = tuple(dict.fromkeys(p for p in negatives if _final_decision(critic_runs, p)))
    regressions = tuple(p for p in human_regressions if p in false_passed)
    unstable = tuple(
        sorted(
            page
            for page in all_pages
            if len({run[page] for run in critic_runs}) > 1
        )
    )
    reasons: list[str] = []
    if missed:
        reasons.append(f"missed positive covers: {list(missed)}")
    if false_passed and len(false_passed) == len(negatives):
        reasons.append("every known negative page passed: the critic cannot catch known-bad design")
    elif false_passed:
        reasons.append(f"false-passed negative pages: {list(false_passed)}")
    if regressions:
        reasons.append(f"critical human regressions waved through: {list(regressions)}")
    if unstable:
        reasons.append(f"unstable repeated decisions: {list(unstable)}")
    return CalibrationResult(
        gate_passed=not reasons,
        missed_positive_pages=missed,
        false_passed_negative_pages=false_passed,
        critical_regressions=regressions,
        unstable_pages=unstable,
        reasons=tuple(reasons),
    )


def evaluate_release_gate(
    manifest: Mapping[str, Any],
    critic_runs: Sequence[Mapping[str, bool]],
    *,
    better_or_equal_ratio: float,
    topics: int,
    pages: int,
    max_attempts_per_candidate: int,
    max_request_ms: int,
    human_regressions: Sequence[str] = (),
) -> ReleaseGateResult:
    campaign = manifest.get("campaign", {})
    thresholds = {
        "min_topics": int(campaign.get("min_topics", 10)),
        "min_pages": int(campaign.get("min_pages", 75)),
        "min_better_or_equal_ratio": float(campaign.get("min_better_or_equal_ratio", 0.80)),
        "max_attempts_per_candidate": int(campaign.get("max_attempts_per_candidate", 14)),
        "max_aesthetic_revisions": int(campaign.get("max_aesthetic_revisions", 2)),
        "max_request_ms": int(campaign.get("max_request_ms", 60_000)),
    }
    calibration = evaluate_calibration(manifest, critic_runs, human_regressions=human_regressions)
    reasons = list(calibration.reasons)
    if topics < thresholds["min_topics"]:
        reasons.append(f"campaign covered {topics} topics; requires {thresholds['min_topics']}")
    if pages < thresholds["min_pages"]:
        reasons.append(f"campaign covered {pages} pages; requires {thresholds['min_pages']}")
    if better_or_equal_ratio < thresholds["min_better_or_equal_ratio"]:
        reasons.append(
            f"better-or-equal ratio {better_or_equal_ratio:.3f} below the predeclared "
            f"{thresholds['min_better_or_equal_ratio']:.2f}"
        )
    if max_attempts_per_candidate > thresholds["max_attempts_per_candidate"]:
        reasons.append(
            f"candidate used {max_attempts_per_candidate} attempts; "
            f"budget is {thresholds['max_attempts_per_candidate']}"
        )
    if max_request_ms > thresholds["max_request_ms"]:
        reasons.append(
            f"request took {max_request_ms}ms; deadline budget is {thresholds['max_request_ms']}ms"
        )
    return ReleaseGateResult(
        gate_passed=not reasons,
        calibration=calibration,
        reasons=tuple(reasons),
    )
