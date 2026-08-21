from __future__ import annotations

from collections.abc import Mapping

import pytest

from tests.nodes.v4.test_layout import _direction_upstream
from src.nodes.v4.layout import aggregate_layout_plan
from src.schemas.assets import AssetManifest
from src.schemas.content_lock import ContentLock
from src.nodes.v4.design_qa import aggregate_design_qa, design_qa_node
from src.schemas.v4.content import canonical_sha256_v4
from src.schemas.v4.direction import AuthoringQAResultV4, AuthoringIssueV4
from src.schemas.v4.quality import (
    DesignMetricEvidenceV4,
    DesignMetricsQAResultV4,
    DesignQualityIssueV4,
)
from src.schemas.v4.semantic import SemanticIssueV4
from src.visual_design.v4.semantic_qa import evaluate_semantic_model
from src.visual_design.v4.tokens import get_family_tokens


def _fixture() -> dict[str, object]:
    atom_set, semantic_model, page_set, narrative, direction_plan, compiled = _direction_upstream()
    lock_payload = {
        "focus_keyword": "护肤",
        "topic": "护肤步骤",
        "topic_id": "topic-1",
        "angle": "按步骤判断",
        "angle_id": "angle-1",
        "target_group": "护肤人群",
        "core_pain": "不知道怎么做",
        "title": "护肤步骤",
        "cover_copy": "看完就会",
        "first_screen_promise": "照着做",
        "content": "页面内容",
        "hashtags": ("#护肤",),
        "content_atom_set_sha256": atom_set.canonical_sha256,
    }
    lock = ContentLock(**lock_payload, canonical_sha256=canonical_sha256_v4(lock_payload))
    q0 = evaluate_semantic_model(atom_set, semantic_model, content_lock=lock)
    q1_payload = {
        "passed": True,
        "issues": (),
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "content_lock_sha256": lock.canonical_sha256,
        "semantic_content_model_sha256": semantic_model.canonical_sha256,
        "narrative_sha256": direction_plan.narrative_sha256,
        "page_brief_set_sha256": page_set.canonical_sha256,
        "visual_direction_plan_sha256": direction_plan.canonical_sha256,
        "candidate_sha256": None,
    }
    q1 = AuthoringQAResultV4(
        **q1_payload,
        canonical_sha256=canonical_sha256_v4(q1_payload),
    )
    manifest = AssetManifest(items=())
    plan = aggregate_layout_plan(
        compiled,
        content_atom_set=atom_set,
        semantic_content_model=semantic_model,
        page_brief_set=page_set,
        asset_manifest=manifest,
        family_tokens=get_family_tokens("pink_red"),
        revision=1,
        run_id="run-a",
        candidate_id="candidate-a",
        visual_direction_plan=direction_plan,
    )
    return {
        "atom_set": atom_set,
        "semantic_model": semantic_model,
        "page_set": page_set,
        "lock": lock,
        "direction_plan": direction_plan,
        "manifest": manifest,
        "q0": q0,
        "q1": q1,
        "plan": plan,
    }


def _kwargs(fixture: Mapping[str, object], **updates: object) -> dict[str, object]:
    values = {
        "semantic_qa": fixture["q0"],
        "authoring_qa": fixture["q1"],
        "carousel_design_plan": fixture["plan"],
        "content_atom_set": fixture["atom_set"],
        "content_lock": fixture["lock"],
        "semantic_content_model": fixture["semantic_model"],
        "page_brief_set": fixture["page_set"],
        "visual_direction_plan": fixture["direction_plan"],
        "asset_manifest": fixture["manifest"],
        "family_tokens": get_family_tokens("pink_red"),
    }
    plan = fixture["plan"]
    values["page_metrics"] = tuple(
        __import__("src.visual_design.v4.design_metrics", fromlist=["evaluate_page_metrics"]).evaluate_page_metrics(
            page,
            page_brief_set=fixture["page_set"],
        )
        for page in plan.pages
    )
    values.update(updates)
    return values


def test_design_qa_orchestration_boundary_is_public() -> None:
    assert callable(aggregate_design_qa)
    assert callable(design_qa_node)


def test_failed_q0_or_q1_always_fails_aggregate() -> None:
    fixture = _fixture()
    q0 = fixture["q0"]
    q0_payload = q0.model_dump(mode="python")
    q0_payload["issues"] = (
        SemanticIssueV4(
            code="HASH_BINDING_MISMATCH",
            location="semantic_content_model",
            message="semantic binding failed",
        ),
    )
    q0_payload["passed"] = False
    q0_payload.pop("canonical_sha256", None)
    fixture["q0"] = type(q0)(**q0_payload, canonical_sha256=canonical_sha256_v4(q0_payload))
    result = aggregate_design_qa(**_kwargs(fixture))
    assert result.passed is False
    assert result.semantic_qa.passed is False

    fixture = _fixture()
    q1 = fixture["q1"]
    q1_payload = q1.model_dump(mode="python")
    q1_payload["issues"] = (
        AuthoringIssueV4(
            code="COMPOSITION_REPEATED",
            location="pages[1:2]",
            message="adjacent composition repeated",
        ),
    )
    q1_payload["passed"] = False
    q1_payload.pop("canonical_sha256", None)
    fixture["q1"] = AuthoringQAResultV4(
        **q1_payload,
        canonical_sha256=canonical_sha256_v4(q1_payload),
    )
    result = aggregate_design_qa(**_kwargs(fixture))
    assert result.passed is False
    assert result.authoring_qa.passed is False


def test_one_failed_page_fails_whole_carousel() -> None:
    fixture = _fixture()
    metrics = list(_kwargs(fixture)["page_metrics"])
    first = metrics[0]
    evidence = first.metrics[0]
    evidence_payload = evidence.model_dump(mode="python")
    evidence_payload.update({"actual": 0.0, "passed": False})
    evidence_payload.pop("canonical_sha256", None)
    failed_evidence = DesignMetricEvidenceV4(
        **evidence_payload,
        canonical_sha256=canonical_sha256_v4(evidence_payload),
    )
    issue_payload = {
        "code": "SAFE_MARGIN_NONCOMPLIANT",
        "metric": "safe_margin_compliance",
        "page_id": first.page_id,
        "actual": 0.0,
        "threshold": evidence.threshold,
        "comparator": "gte",
        "revision_target": "layout_reflow",
        "message": "safe margin compliance is below the typed quality threshold",
        "region_id": None,
        "element_id": None,
        "fragment_ref": None,
        "policy_sha256": first.policy_sha256,
    }
    issue = DesignQualityIssueV4(
        **issue_payload,
        canonical_sha256=canonical_sha256_v4(issue_payload),
    )
    page_payload = first.model_dump(mode="python")
    page_payload["metrics"] = (failed_evidence, *first.metrics[1:])
    page_payload["issues"] = (issue,)
    page_payload["passed"] = False
    page_payload.pop("canonical_sha256", None)
    metrics[0] = DesignMetricsQAResultV4(
        **page_payload,
        canonical_sha256=canonical_sha256_v4(page_payload),
    )
    result = aggregate_design_qa(**_kwargs(fixture, page_metrics=tuple(metrics)))
    assert result.passed is False
    assert result.page_metrics[0].passed is False
    assert all(page.passed for page in result.page_metrics[1:])


def test_stale_and_self_consistent_rehashed_q0_fail_closed() -> None:
    fixture = _fixture()
    q0 = fixture["q0"]
    stale = q0.model_copy(update={"semantic_content_model_sha256": "2" * 64})
    with pytest.raises(ValueError):
        aggregate_design_qa(**_kwargs(fixture, semantic_qa=stale))
    raw = q0.model_dump(mode="python")
    raw["semantic_content_model_sha256"] = "2" * 64
    raw.pop("canonical_sha256", None)
    recanonicalized = type(q0)(**raw, canonical_sha256=canonical_sha256_v4(raw))
    with pytest.raises(ValueError, match="Q0 semantic model"):
        aggregate_design_qa(**_kwargs(fixture, semantic_qa=recanonicalized))


def test_self_consistent_easier_q2_threshold_is_rejected() -> None:
    fixture = _fixture()
    metrics = list(_kwargs(fixture)["page_metrics"])
    first = metrics[0]
    original = first.metrics[4]  # whitespace_ratio
    metric_payload = original.model_dump(mode="python")
    metric_payload["threshold"] = 0.01
    metric_payload.pop("canonical_sha256", None)
    easier = DesignMetricEvidenceV4(
        **metric_payload,
        canonical_sha256=canonical_sha256_v4(metric_payload),
    )
    page_payload = first.model_dump(mode="python")
    page_payload["metrics"] = (*first.metrics[:4], easier, *first.metrics[5:])
    page_payload.pop("canonical_sha256", None)
    metrics[0] = DesignMetricsQAResultV4(
        **page_payload,
        canonical_sha256=canonical_sha256_v4(page_payload),
    )
    with pytest.raises(ValueError, match="policy|threshold"):
        aggregate_design_qa(**_kwargs(fixture, page_metrics=tuple(metrics)))


def test_candidate_preflight_is_not_durable_q1() -> None:
    fixture = _fixture()
    from src.visual_design.v4.authoring_qa import AuthoringCandidatePreflightV4

    preflight = AuthoringCandidatePreflightV4(candidate_sha256="3" * 64, issues=())
    with pytest.raises(ValueError, match="candidate preflight"):
        aggregate_design_qa(**_kwargs(fixture, authoring_qa=preflight))


def test_repeated_aggregation_is_deep_frozen_and_byte_deterministic() -> None:
    fixture = _fixture()
    first = aggregate_design_qa(**_kwargs(fixture))
    second = aggregate_design_qa(**_kwargs(fixture))
    assert first.canonical_sha256 == second.canonical_sha256
    assert first.model_dump_json() == second.model_dump_json()
    assert isinstance(first.page_metrics, tuple)
    with pytest.raises(TypeError):
        first.page_metrics[0] = first.page_metrics[0]  # type: ignore[index]


def test_design_qa_node_returns_hard_gate_route_without_renderer() -> None:
    fixture = _fixture()
    values = _kwargs(fixture)
    state = {
        "semantic_qa_result": values.pop("semantic_qa"),
        "authoring_qa_result": values.pop("authoring_qa"),
        "carousel_design_plan": values.pop("carousel_design_plan"),
        **values,
    }
    result = design_qa_node(state)
    assert result["design_plan_qa_result_v4"].passed is True
    assert result["route"] == "render"
