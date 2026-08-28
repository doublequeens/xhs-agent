"""Blind shadow comparison and Critic calibration for the v4 evaluation."""

from .v4_calibration import (
    CalibrationResult,
    ReleaseGateResult,
    evaluate_calibration,
    evaluate_release_gate,
    load_quality_manifest,
)
from .v4_comparison import (
    BlindComparisonReport,
    VariantBundle,
    VariantPage,
    build_blind_report,
    compose_contact_sheets,
)

__all__ = [
    "BlindComparisonReport",
    "CalibrationResult",
    "ReleaseGateResult",
    "VariantBundle",
    "VariantPage",
    "build_blind_report",
    "compose_contact_sheets",
    "evaluate_calibration",
    "evaluate_release_gate",
    "load_quality_manifest",
]
