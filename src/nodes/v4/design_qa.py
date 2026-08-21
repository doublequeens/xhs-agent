"""Narrow deterministic v4 Design Plan QA orchestration boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.schemas.assets import AssetManifest
from src.schemas.content_atoms import canonical_sha256 as canonical_sha256_v3
from src.schemas.content_lock import ContentLock
from src.schemas.v4.content import ContentAtomSetV4, canonical_sha256_v4
from src.schemas.v4.direction import PageBriefSetV4, VisualDirectionPlanV4
from src.schemas.v4.layout import CarouselDesignPlanV4, FamilyTokensV4
from src.schemas.v4.quality import (
    DesignMetricsQAResultV4,
    DesignPlanQAResultV4,
)
from src.schemas.v4.semantic import SemanticContentModelV4, SemanticQAResultV4
from src.visual_design.v4.design_metrics import (
    derive_page_role_v4,
    evaluate_page_metrics,
    get_quality_policy,
    threshold_for_metric_v4,
)
from src.visual_design.v4.tokens import get_family_tokens
from src.visual_design.v4.authoring_qa import AuthoringCandidatePreflightV4
from src.schemas.v4.direction import AuthoringQAResultV4


_ZERO_SHA256 = "0" * 64


class DesignPlanQAInvariantError(ValueError):
    """Structural/hash failure; metric misses are represented in a result."""


def _coerce(model_type, value: Any, name: str):
    try:
        raw = value.model_dump(mode="python") if isinstance(value, model_type) else value
        checked = model_type.model_validate(raw)
        if hasattr(checked, "validate_integrity"):
            checked.validate_integrity()
        return checked
    except Exception:
        raise DesignPlanQAInvariantError(f"{name} is stale or structurally invalid") from None


def _lock_hash(lock: ContentLock) -> str:
    try:
        payload = lock.model_dump(mode="json", exclude={"canonical_sha256"})
        expected = canonical_sha256_v4(payload)
    except Exception:
        raise DesignPlanQAInvariantError("content lock is not serializable") from None
    if lock.canonical_sha256 != expected:
        raise DesignPlanQAInvariantError("content lock canonical hash is stale")
    if not lock.content_atom_set_sha256:
        raise DesignPlanQAInvariantError("content lock atom binding is missing")
    return lock.canonical_sha256


def _authoring(value: Any) -> AuthoringQAResultV4:
    if isinstance(value, AuthoringCandidatePreflightV4):
        raise DesignPlanQAInvariantError("Q1 candidate preflight is not durable authoring evidence")
    return _coerce(AuthoringQAResultV4, value, "authoring QA result")


def _page_metrics(
    values: Sequence[DesignMetricsQAResultV4 | Mapping[str, Any]],
) -> tuple[DesignMetricsQAResultV4, ...]:
    checked: list[DesignMetricsQAResultV4] = []
    for value in values:
        checked.append(_coerce(DesignMetricsQAResultV4, value, "Q2 page result"))
    return tuple(checked)


def aggregate_design_qa(
    *,
    semantic: SemanticQAResultV4 | Mapping[str, Any] | None = None,
    semantic_qa: SemanticQAResultV4 | Mapping[str, Any] | None = None,
    q0: SemanticQAResultV4 | Mapping[str, Any] | None = None,
    authoring: AuthoringQAResultV4 | Mapping[str, Any] | None = None,
    authoring_qa: AuthoringQAResultV4 | Mapping[str, Any] | None = None,
    q1: AuthoringQAResultV4 | Mapping[str, Any] | None = None,
    metrics: Sequence[DesignMetricsQAResultV4 | Mapping[str, Any]] | None = None,
    page_metrics: Sequence[DesignMetricsQAResultV4 | Mapping[str, Any]] | None = None,
    design_metrics: Sequence[DesignMetricsQAResultV4 | Mapping[str, Any]] | None = None,
    design_plan: CarouselDesignPlanV4 | Mapping[str, Any] | None = None,
    carousel_design_plan: CarouselDesignPlanV4 | Mapping[str, Any] | None = None,
    content_atom_set: ContentAtomSetV4 | Mapping[str, Any] | None = None,
    content_lock: ContentLock | Mapping[str, Any] | None = None,
    semantic_content_model: SemanticContentModelV4 | Mapping[str, Any] | None = None,
    page_brief_set: PageBriefSetV4 | Mapping[str, Any] | None = None,
    visual_direction_plan: VisualDirectionPlanV4 | Mapping[str, Any] | None = None,
    asset_manifest: AssetManifest | Mapping[str, Any] | None = None,
    family_tokens: FamilyTokensV4 | str | None = None,
) -> DesignPlanQAResultV4:
    """Revalidate exact Q0/Q1/source inputs and aggregate canonical Q2 pages.

    This function performs no repair and invokes no renderer.  A deterministic
    metric miss returns a failed immutable result; missing or contradictory
    contracts raise at this boundary.
    """

    q0_value = semantic_qa if semantic_qa is not None else semantic if semantic is not None else q0
    q1_value = authoring_qa if authoring_qa is not None else authoring if authoring is not None else q1
    metric_values = page_metrics if page_metrics is not None else metrics if metrics is not None else design_metrics
    plan_value = carousel_design_plan if carousel_design_plan is not None else design_plan
    if any(value is None for value in (q0_value, q1_value, metric_values, plan_value, content_atom_set, content_lock, asset_manifest)):
        raise DesignPlanQAInvariantError("design QA requires complete Q0, Q1, Q2 and source contracts")

    q0_checked = _coerce(SemanticQAResultV4, q0_value, "semantic QA result")
    q1_checked = _authoring(q1_value)
    atom_set = _coerce(ContentAtomSetV4, content_atom_set, "content atom set")
    lock = _coerce(ContentLock, content_lock, "content lock")
    semantic_model = _coerce(SemanticContentModelV4, semantic_content_model, "semantic content model") if semantic_content_model is not None else None
    page_set = _coerce(PageBriefSetV4, page_brief_set, "page brief set") if page_brief_set is not None else None
    direction_plan = _coerce(VisualDirectionPlanV4, visual_direction_plan, "visual direction plan") if visual_direction_plan is not None else None
    manifest = _coerce(AssetManifest, asset_manifest, "asset manifest")
    plan = _coerce(CarouselDesignPlanV4, plan_value, "carousel design plan")
    if semantic_model is None or page_set is None or direction_plan is None:
        raise DesignPlanQAInvariantError("design QA requires exact semantic model, page briefs and direction plan")
    if isinstance(family_tokens, str):
        family = get_family_tokens(family_tokens)
    elif family_tokens is None:
        family = get_family_tokens(direction_plan.template_family)
    else:
        family = _coerce(FamilyTokensV4, family_tokens, "family tokens")
    if family.family != direction_plan.template_family:
        raise DesignPlanQAInvariantError("family tokens do not match visual direction plan")
    if family.canonical_sha256 != get_family_tokens(direction_plan.template_family).canonical_sha256:
        raise DesignPlanQAInvariantError("family tokens are not the canonical registry revision")

    lock_hash = _lock_hash(lock)
    asset_hash = canonical_sha256_v3(manifest)
    if semantic_model.content_atom_set_sha256 != atom_set.canonical_sha256:
        raise DesignPlanQAInvariantError("semantic model is not bound to supplied content atoms")
    if direction_plan.semantic_content_model_sha256 != semantic_model.canonical_sha256:
        raise DesignPlanQAInvariantError("visual direction plan is not bound to supplied semantic model")
    if direction_plan.page_brief_set_sha256 != page_set.canonical_sha256:
        raise DesignPlanQAInvariantError("visual direction plan is not bound to supplied page briefs")
    if direction_plan.content_atom_set_sha256 != atom_set.canonical_sha256:
        raise DesignPlanQAInvariantError("visual direction plan is not bound to supplied content atoms")
    if lock.content_atom_set_sha256 != atom_set.canonical_sha256:
        raise DesignPlanQAInvariantError("content lock is not bound to supplied content atoms")

    if q0_checked.content_atom_set_sha256 != atom_set.canonical_sha256:
        raise DesignPlanQAInvariantError("Q0 atom binding is stale")
    if q0_checked.content_lock_sha256 != lock_hash:
        raise DesignPlanQAInvariantError("Q0 content lock binding is stale")
    if q0_checked.semantic_content_model_sha256 != semantic_model.canonical_sha256:
        raise DesignPlanQAInvariantError("Q0 semantic model binding is stale")
    if q1_checked.candidate_sha256 is not None:
        raise DesignPlanQAInvariantError("Q1 candidate preflight cannot become durable QA evidence")
    q1_expected = {
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "content_lock_sha256": lock_hash,
        "semantic_content_model_sha256": semantic_model.canonical_sha256,
        "narrative_sha256": direction_plan.narrative_sha256,
        "page_brief_set_sha256": page_set.canonical_sha256,
        "visual_direction_plan_sha256": direction_plan.canonical_sha256,
    }
    for field, expected in q1_expected.items():
        if getattr(q1_checked, field) != expected:
            raise DesignPlanQAInvariantError(f"Q1 {field} binding is stale")

    plan_expected = {
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "semantic_content_model_sha256": semantic_model.canonical_sha256,
        "page_brief_set_sha256": page_set.canonical_sha256,
        "asset_manifest_sha256": asset_hash,
        "family_tokens_sha256": family.canonical_sha256,
        "visual_direction_plan_sha256": direction_plan.canonical_sha256,
    }
    for field, expected in plan_expected.items():
        if getattr(plan, field) != expected:
            raise DesignPlanQAInvariantError(f"design plan {field} binding is stale")
    plan.validate_integrity()
    if tuple(page.page_id for page in plan.pages) != tuple(page.page_id for page in page_set.pages):
        raise DesignPlanQAInvariantError("design plan pages do not match exact page brief order")
    for plan_page, brief in zip(plan.pages, page_set.pages):
        program = plan_page.layout_program
        provenance = plan_page.compiler_provenance
        if program.page_brief_sha256 != brief.canonical_sha256:
            raise DesignPlanQAInvariantError("compiled page is not bound to the exact page brief")
        if program.beat_ref != brief.beat_ref:
            raise DesignPlanQAInvariantError("compiled page beat binding does not match exact page brief")
        if program.carousel_narrative_sha256 != direction_plan.narrative_sha256:
            raise DesignPlanQAInvariantError("compiled page narrative binding is stale")
        if provenance.family_tokens_sha256 != family.canonical_sha256:
            raise DesignPlanQAInvariantError("compiled page family token binding is stale")

    checked_metrics = _page_metrics(metric_values)
    if len(checked_metrics) != len(plan.pages):
        raise DesignPlanQAInvariantError("Q2 page metrics must cover every compiled page exactly once")
    for metric, plan_page in zip(checked_metrics, plan.pages):
        if metric.page_id != plan_page.page_id or metric.sequence != plan_page.sequence:
            raise DesignPlanQAInvariantError("Q2 page metric identity does not match design plan")
        if metric.compiled_page_sha256 != plan_page.canonical_sha256:
            raise DesignPlanQAInvariantError("Q2 page metric is bound to a different compiled page")
        if metric.layout_program_sha256 != plan_page.layout_program.canonical_sha256:
            raise DesignPlanQAInvariantError("Q2 page metric is bound to a different layout program")
        if metric.grammar_id != plan_page.layout_program.grammar_id:
            raise DesignPlanQAInvariantError("Q2 page metric grammar is not plan-bound")
        expected_policy = get_quality_policy(
            metric.grammar_id,
            derive_page_role_v4(plan_page.layout_program.beat_task_kind),
            plan_page.layout_program.beat_task_kind,
        )
        if metric.policy_sha256 != expected_policy.canonical_sha256:
            raise DesignPlanQAInvariantError("Q2 page metric policy is not the canonical typed policy")
        for metric_evidence in metric.metrics:
            if metric_evidence.policy_sha256 != expected_policy.canonical_sha256:
                raise DesignPlanQAInvariantError("Q2 metric evidence policy binding is stale")
            expected_threshold = threshold_for_metric_v4(expected_policy, metric_evidence.metric)
            if abs(metric_evidence.threshold - expected_threshold) > 1e-9:
                raise DesignPlanQAInvariantError("Q2 metric threshold does not match canonical policy")
        if metric.content_atom_set_sha256 != atom_set.canonical_sha256 or metric.semantic_content_model_sha256 != semantic_model.canonical_sha256:
            raise DesignPlanQAInvariantError("Q2 page source binding is stale")
        if metric.page_brief_set_sha256 != page_set.canonical_sha256 or metric.visual_direction_plan_sha256 != direction_plan.canonical_sha256:
            raise DesignPlanQAInvariantError("Q2 page authoring binding is stale")
        if metric.asset_manifest_sha256 != asset_hash or metric.family_tokens_sha256 != family.canonical_sha256:
            raise DesignPlanQAInvariantError("Q2 page asset or family binding is stale")
    page_metrics_tuple = checked_metrics
    payload = {
        "passed": q0_checked.passed and q1_checked.passed and all(item.passed for item in page_metrics_tuple),
        "semantic_qa": q0_checked,
        "authoring_qa": q1_checked,
        "page_metrics": page_metrics_tuple,
        "carousel_design_plan": plan,
        "issues": (),
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "content_lock_sha256": lock_hash,
        "semantic_content_model_sha256": semantic_model.canonical_sha256,
        "narrative_sha256": direction_plan.narrative_sha256,
        "page_brief_set_sha256": page_set.canonical_sha256,
        "visual_direction_plan_sha256": direction_plan.canonical_sha256,
        "asset_manifest_sha256": asset_hash,
        "family_tokens_sha256": family.canonical_sha256,
        "candidate_id": plan.candidate_id,
        "revision": plan.revision,
        "run_id": plan.run_id,
    }
    return DesignPlanQAResultV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def design_qa_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate one complete v4 state and return no partial pass."""

    if not isinstance(state, Mapping):
        raise TypeError("v4 design QA node requires a state mapping")
    result = aggregate_design_qa(
        semantic_qa=state.get("semantic_qa", state.get("semantic_qa_result", state.get("semantic_qa_result_v4"))),
        authoring_qa=state.get("authoring_qa", state.get("authoring_qa_result", state.get("authoring_qa_result_v4"))),
        page_metrics=state.get("page_metrics", state.get("design_metrics_qa", state.get("design_metrics"))),
        carousel_design_plan=state.get("carousel_design_plan_v4", state.get("carousel_design_plan")),
        content_atom_set=state.get("content_atom_set", state.get("atom_set")),
        content_lock=state.get("content_lock"),
        semantic_content_model=state.get("semantic_content_model", state.get("semantic_model")),
        page_brief_set=state.get("page_brief_set", state.get("page_briefs")),
        visual_direction_plan=state.get("visual_direction_plan"),
        asset_manifest=state.get("asset_manifest", state.get("assets")),
        family_tokens=state.get("family_tokens"),
    )
    return {
        "design_plan_qa_result_v4": result,
        "design_plan_qa_result": result,
        "current_node": "V4_DESIGN_PLAN_QA",
        "route": "render" if result.passed else "design_reviser",
    }


evaluate_design_plan_qa = aggregate_design_qa
v4_design_qa_node = design_qa_node


__all__ = [
    "DesignPlanQAInvariantError",
    "aggregate_design_qa",
    "design_qa_node",
    "evaluate_design_plan_qa",
    "v4_design_qa_node",
]
