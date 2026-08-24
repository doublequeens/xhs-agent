from __future__ import annotations

import pytest

from src.schemas.v4.quality import (
    DesignMetricEvidenceV4,
    DesignMetricsQAResultV4,
    DesignQualityIssueV4,
    DesignPlanQAResultV4,
    QUALITY_METRIC_KINDS_V4,
    LINE_LENGTH_METRIC_UNIT_V4,
    LINE_LENGTH_METRIC_VERSION_V4,
    QUALITY_METRIC_UNIT_V4,
    QUALITY_METRIC_VERSION_V4,
)
from src.schemas.v4.content import canonical_sha256_v4


def test_quality_contracts_are_frozen_and_reject_unknown_fields() -> None:
    assert DesignMetricsQAResultV4.model_config["frozen"] is True
    assert DesignPlanQAResultV4.model_config["extra"] == "forbid"
    with pytest.raises(Exception):
        DesignMetricsQAResultV4.model_validate({"x": 1})


@pytest.mark.parametrize("metric", QUALITY_METRIC_KINDS_V4)
def test_every_metric_evidence_derives_a_passing_and_failing_boundary(metric: str) -> None:
    def build(actual: float, threshold: float, passed: bool) -> DesignMetricEvidenceV4:
        payload = {
            "metric": metric,
            "page_id": "page-1",
            "actual": actual,
            "threshold": threshold,
            "comparator": "gte",
            "passed": passed,
            "metric_unit": (
                LINE_LENGTH_METRIC_UNIT_V4
                if metric == "line_length"
                else QUALITY_METRIC_UNIT_V4
            ),
            "metric_version": (
                LINE_LENGTH_METRIC_VERSION_V4
                if metric == "line_length"
                else QUALITY_METRIC_VERSION_V4
            ),
            "policy_sha256": "1" * 64,
            "region_id": None,
            "element_id": None,
            "fragment_ref": None,
        }
        return DesignMetricEvidenceV4(
            **payload,
            canonical_sha256=canonical_sha256_v4(payload),
        )

    assert build(1.0, 1.0, True).passed is True
    assert build(0.0, 1.0, False).passed is False


def test_quality_issue_is_closed_actionable_and_sanitized() -> None:
    payload = {
        "code": "WHITESPACE_RATIO",
        "metric": "whitespace_ratio",
        "page_id": "page-1",
        "actual": 0.1,
        "threshold": 0.4,
        "comparator": "gte",
        "revision_target": "layout_reflow",
        "message": "whitespace ratio is below the typed threshold",
        "region_id": "hero",
        "element_id": "v4-text-title-1",
        "fragment_ref": "fragment-1",
        "policy_sha256": "1" * 64,
    }
    issue = DesignQualityIssueV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )
    assert issue.revision_target == "layout_reflow"
    for sentinel in ("provider-secret", "/Users/private/file.png", "prompt: add text"):
        bad = {**payload, "message": sentinel}
        with pytest.raises(ValueError):
            DesignQualityIssueV4(
                **bad,
                canonical_sha256=canonical_sha256_v4(bad),
            )

    for bad_ref, field_name in (("provider-secret", "element_id"), ("/private/path", "fragment_ref")):
        bad = {**payload, field_name: bad_ref}
        with pytest.raises(ValueError):
            DesignQualityIssueV4(
                **bad,
                canonical_sha256=canonical_sha256_v4(bad),
            )

    bad = {**payload, "message": "用户原文可见复制"}
    with pytest.raises(ValueError):
        DesignQualityIssueV4(
            **bad,
            canonical_sha256=canonical_sha256_v4(bad),
        )
