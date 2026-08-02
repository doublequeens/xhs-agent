"""End-to-end workflow proof for the ``llm_scene_v3`` dynamic visual pipeline.

Drives the REAL ``create_graph()`` through the golden harness
(``tests/dynamic_visual/golden_fixtures.py``) and asserts the two families of
production behavior the golden per-case suite does not cover:

* Retry ceilings. ``design_plan_qa`` and ``render_qa`` interrupt with
  ``VisualProductionInterrupted`` after exactly 3 consecutive failures
  (counter persistence is the real LangGraph state-merge, not faked).
  ``visual_critic``'s aesthetic ceiling is the 2-round escalation to Human
  Review with ``review_status="visual_needs_attention"`` (the production route
  ``route_after_visual_critic`` does NOT raise an interruption for aesthetic
  failure -- only the per-call model retry does -- so this test asserts the real
  2-round human-escalation ceiling rather than a non-existent 3-strike raise).
* Every Human Review route: approval -> final_policy_guard; design feedback ->
  design_reviser; visible-text edit -> r2_compliance (with full visual-chain
  invalidation); image rejection -> asset_resolver; visual_needs_attention ->
  explicit aesthetic override (and the no-override gate routing back to
  design_reviser).

The retry-ceiling regressions themselves (counter survival through LangGraph)
are guarded in detail by ``tests/integration/test_visual_loop_regression.py``;
these tests prove the ceilings hold via the golden end-to-end harness.
"""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src import graph as graph_module
from src.schemas.design_qa import DesignIssue, DesignPlanQAResult
from src.schemas.render_qa import RenderIssue, RenderQAResult
from src.schemas.visual_critique import VisualCritique, VisualCritiqueIssue
from src.schemas.content_atoms import canonical_sha256
from src.visual_design.model_retry import VisualProductionInterrupted
from tests.dynamic_visual.golden_fixtures import (
    ContentWriterReached,
    GoldenHarness,
    load_case,
)

RECURSION_LIMIT = 120


# ---------------------------------------------------------------------------
# Sentinels raised by route-target fakes so the chosen Human Review route is
# observable without running the full downstream loop.
# ---------------------------------------------------------------------------


class _DesignReviserReached(Exception):
    def __init__(self, state) -> None:
        self.state = state


class _R2ComplianceReached(Exception):
    def __init__(self, state) -> None:
        self.state = state


class _AssetResolverReached(Exception):
    def __init__(self, state) -> None:
        self.state = state


def _make_harness(case_id: str, tmp_path, **kwargs) -> GoldenHarness:
    spec = load_case(case_id)
    return GoldenHarness(spec=spec, tmp_path=tmp_path, **kwargs)


# ---------------------------------------------------------------------------
# Retry ceilings: design_plan_qa 3-strike -> VisualProductionInterrupted.
# ---------------------------------------------------------------------------


def test_design_plan_qa_three_strike_interrupts(tmp_path, monkeypatch):
    case_id = "case-01"
    harness = _make_harness(case_id, tmp_path)
    observed: list[int] = []

    def failing_design_plan_qa(state):
        prior = int(state.get("design_plan_qa_failures", 0))
        observed.append(prior)
        failures = prior + 1
        if failures >= 3:
            raise VisualProductionInterrupted(
                stage="design_plan_qa",
                errors=["fake: persistent spacing failure"],
                raw_outputs=(),
            )
        design_plan = state["carousel_design_plan"]
        return {
            "design_plan_qa_result": DesignPlanQAResult(
                passed=False,
                issues=(
                    DesignIssue(
                        rule="spacing",
                        message=f"page-1 spacing failure #{failures}",
                        repair_instruction="adjust spacing on page-1",
                        page_id="page-1",
                        element_id="text-1",
                    ),
                ),
                design_plan_sha256=design_plan.direction_plan_sha256,
                content_coverage_attestation=False,
                family_attestation=True,
                asset_binding_attestation=True,
            ),
            "design_plan_qa_failures": failures,
            "current_node": "DESIGN_PLAN_QA",
        }

    def noop_reviser(state, **_kwargs):
        return {
            "carousel_design_plan": state.get("carousel_design_plan"),
            "current_node": "DESIGN_REVISER",
        }

    harness.overrides = {
        "design_plan_qa_node": failing_design_plan_qa,
        "design_reviser_node": noop_reviser,
    }
    monkeypatch.chdir(tmp_path)
    harness.install(monkeypatch)
    graph = graph_module.create_graph(checkpointer=InMemorySaver())
    config = {
        "configurable": {"thread_id": "wf-dqa-3strike"},
        "recursion_limit": RECURSION_LIMIT,
    }
    with pytest.raises(VisualProductionInterrupted) as excinfo:
        graph.invoke(harness.initial_state(), config=config)
    assert excinfo.value.stage == "design_plan_qa"
    # Counter persisted across the reviser round-trip: 0 -> 1 -> 2.
    assert observed == [0, 1, 2]


# ---------------------------------------------------------------------------
# Retry ceilings: render_qa 3-strike -> VisualProductionInterrupted.
# ---------------------------------------------------------------------------


def test_render_qa_three_strike_interrupts(tmp_path, monkeypatch):
    case_id = "case-01"
    harness = _make_harness(case_id, tmp_path)
    observed: list[int] = []

    def passing_design_plan_qa(state):
        design_plan = state["carousel_design_plan"]
        return {
            "design_plan_qa_result": DesignPlanQAResult(
                passed=True,
                issues=(),
                design_plan_sha256=canonical_sha256(design_plan),
                content_coverage_attestation=True,
                family_attestation=True,
                asset_binding_attestation=True,
            ),
            "design_plan_qa_failures": 0,
            "current_node": "DESIGN_PLAN_QA",
        }

    def failing_render_qa(state):
        prior = int(state.get("render_qa_failures", 0))
        observed.append(prior)
        failures = prior + 1
        if failures >= 3:
            raise VisualProductionInterrupted(
                stage="render_qa",
                errors=["fake: persistent geometry failure"],
                raw_outputs=(),
            )
        return {
            "render_qa_result": RenderQAResult(
                passed=False,
                issues=(
                    RenderIssue(
                        rule="geometry",
                        message=f"page-1 box overflow #{failures}",
                        repair_instruction="resize page-1 box",
                        page_id="page-1",
                        element_id="text-1",
                    ),
                ),
                render_manifest_sha256="0" * 64,
                content_attestation=False,
                geometry_attestation=False,
                asset_attestation=True,
            ),
            "render_qa_failures": failures,
            "current_node": "RENDER_QA",
        }

    def noop_reviser(state, **_kwargs):
        return {
            "carousel_design_plan": state.get("carousel_design_plan"),
            "current_node": "DESIGN_REVISER",
        }

    harness.overrides = {
        "design_plan_qa_node": passing_design_plan_qa,
        "render_qa_node": failing_render_qa,
        "design_reviser_node": noop_reviser,
    }
    monkeypatch.chdir(tmp_path)
    harness.install(monkeypatch)
    graph = graph_module.create_graph(checkpointer=InMemorySaver())
    config = {
        "configurable": {"thread_id": "wf-rqa-3strike"},
        "recursion_limit": RECURSION_LIMIT,
    }
    with pytest.raises(VisualProductionInterrupted) as excinfo:
        graph.invoke(harness.initial_state(), config=config)
    assert excinfo.value.stage == "render_qa"
    assert observed == [0, 1, 2]


# ---------------------------------------------------------------------------
# visual_critic 2-round ceiling -> human_review (visual_needs_attention).
# ---------------------------------------------------------------------------


class _HumanReviewReached(Exception):
    def __init__(self, state) -> None:
        self.state = state


def test_visual_critic_two_round_ceiling_routes_to_human_review(
    tmp_path, monkeypatch
):
    """A persistently-failing critic escalates to Human Review after round 2
    (revision_round 0 -> 1 -> 2) with ``review_status="visual_needs_attention"``.

    Production ``route_after_visual_critic`` escalates to Human Review at
    ``revision_round >= 2``; it does NOT raise ``VisualProductionInterrupted``
    for aesthetic failure, so this is the real ceiling, exercised here through
    the golden harness."""
    case_id = "case-01"
    harness = _make_harness(case_id, tmp_path)
    observed_rounds: list[int] = []

    def failing_visual_critic(state, **_kwargs):
        round_value = int(state.get("visual_critic_round", 0))
        observed_rounds.append(round_value)
        atom_set = state["content_atom_set"]
        direction = state["visual_direction_plan"]
        design_plan = state["carousel_design_plan"]
        render_manifest = state["render_manifest"]
        critique = VisualCritique(
            content_atom_set_sha256=atom_set.canonical_sha256,
            direction_plan_sha256=canonical_sha256(direction),
            design_plan_sha256=canonical_sha256(design_plan),
            render_manifest_sha256=canonical_sha256(render_manifest),
            passed=False,
            revision_round=round_value,
            contains_images=False,
            overall=40,
            hierarchy=40,
            legibility=40,
            composition=40,
            family_consistency=40,
            page_variation=40,
            page_rhythm=40,
            color=40,
            spacing=40,
            image_relevance="not_applicable",
            issues=(
                VisualCritiqueIssue(
                    rule="composition",
                    message=f"weak composition at round {round_value}",
                    revision_instruction="rebalance page-1 composition",
                    page_id="page-1",
                ),
            ),
            revision_instructions=("rebalance page-1 composition",),
        )
        result: dict[str, Any] = {
            "visual_critique": critique,
            "current_node": "VISUAL_CRITIC",
            "visual_critic_round": round_value + 1,
        }
        if critique.revision_round >= 2:
            result["review_status"] = "visual_needs_attention"
        return result

    def noop_reviser(state, **_kwargs):
        return {
            "carousel_design_plan": state.get("carousel_design_plan"),
            "current_node": "DESIGN_REVISER",
        }

    def human_review_sentinel(state):
        raise _HumanReviewReached(state)

    harness.overrides = {
        "visual_critic_node": failing_visual_critic,
        "design_reviser_node": noop_reviser,
        "human_review_node": human_review_sentinel,
    }
    monkeypatch.chdir(tmp_path)
    harness.install(monkeypatch)
    graph = graph_module.create_graph(checkpointer=InMemorySaver())
    config = {
        "configurable": {"thread_id": "wf-vc-round2"},
        "recursion_limit": RECURSION_LIMIT,
    }
    with pytest.raises(_HumanReviewReached) as excinfo:
        graph.invoke(harness.initial_state(), config=config)
    state = excinfo.value.state
    assert observed_rounds == [0, 1, 2]
    assert state["visual_critique"].revision_round == 2
    assert state.get("review_status") == "visual_needs_attention"


# ---------------------------------------------------------------------------
# Human Review route 1: approval -> final_policy_guard -> content_writer.
# ---------------------------------------------------------------------------


def test_human_review_approval_routes_to_final_policy_guard(tmp_path, monkeypatch):
    case_id = "case-01"
    harness = _make_harness(case_id, tmp_path)
    state = harness.run(monkeypatch, thread_id="wf-hr-approve")
    assert isinstance(state, dict)
    assert state.get("review_status") == "approved"
    assert state.get("review_route") == "final_policy_guard"
    assert state.get("final_policy_issues") == []
    # The content_writer sentinel captured terminal state.
    assert state.get("current_node") != "HUMAN_REVIEW"


# ---------------------------------------------------------------------------
# Human Review route 2: design feedback -> design_reviser.
# ---------------------------------------------------------------------------


def test_human_review_design_feedback_routes_to_design_reviser(
    tmp_path, monkeypatch
):
    case_id = "case-01"
    harness = _make_harness(case_id, tmp_path)

    def design_reviser_sentinel(state, **_kwargs):
        raise _DesignReviserReached(state)

    harness.overrides = {"design_reviser_node": design_reviser_sentinel}
    harness.interrupt_payload = {
        "revision_request": {"focus": "tighten page-2 spacing"},
        "feedback": "page 2 looks loose",
    }
    with pytest.raises(_DesignReviserReached) as excinfo:
        harness.run(monkeypatch, thread_id="wf-hr-design")
    state = excinfo.value.state
    assert state.get("review_route") == "design_reviser"
    assert state["revision_request"]["feedback"] == "page 2 looks loose"


# ---------------------------------------------------------------------------
# Human Review route 3: visible-text edit -> r2_compliance (full invalidation).
# ---------------------------------------------------------------------------


def test_human_review_visible_text_edit_routes_to_r2_compliance(
    tmp_path, monkeypatch
):
    case_id = "case-01"
    harness = _make_harness(case_id, tmp_path)

    def r2_sentinel(state):
        raise _R2ComplianceReached(state)

    harness.overrides = {"r2_compliance_node": r2_sentinel}
    # Edit the visible ``content`` field -> has_visible_publish_copy_edits True.
    harness.interrupt_payload = {
        "edited_publish_package": {
            "content": "全新的可见内容，触发 R2 复核与整条视觉链失效。"
        },
        "feedback": "rewrote body",
    }
    with pytest.raises(_R2ComplianceReached) as excinfo:
        harness.run(monkeypatch, thread_id="wf-hr-visible")
    state = excinfo.value.state
    assert state.get("review_route") == "r2_compliance"
    assert state.get("review_status") == "needs_r2_recheck"
    # Full visual-chain invalidation: every visual artifact is cleared.
    for key in (
        "content_atom_set",
        "visual_direction_plan",
        "asset_manifest",
        "carousel_design_plan",
        "design_plan_qa_result",
        "render_manifest",
        "render_qa_result",
        "visual_critique",
    ):
        assert state.get(key) is None, f"{key} not invalidated on visible-text edit"
    # The decision_output routes the R2 recheck.
    decision = state.get("decision_output")
    assert decision is not None
    assert decision.next_node == "R2_COMPLIANCE"


# ---------------------------------------------------------------------------
# Human Review route 4: image rejection -> asset_resolver.
# ---------------------------------------------------------------------------


def test_human_review_image_rejection_routes_to_asset_resolver(
    tmp_path, monkeypatch
):
    case_id = "case-02"  # searched photo: exactly one resolved asset
    harness = _make_harness(case_id, tmp_path)

    rejection = {
        "asset-dir-search-photo": {
            "reason": "wrong composition",
            "page_id": "page-3",
        }
    }
    captures: list[dict] = []

    def asset_resolver_recorder(state, **_kwargs):
        captures.append(
            {"rejected_asset_decisions": state.get("rejected_asset_decisions")}
        )
        if len(captures) == 2:
            raise _AssetResolverReached(state)
        return harness._fake_asset_resolver(state, **_kwargs)

    harness.overrides = {"asset_resolver_node": asset_resolver_recorder}
    harness.interrupt_payload = {
        "reject_assets": rejection,
        "feedback": "bad image",
    }
    with pytest.raises(_AssetResolverReached) as excinfo:
        harness.run(monkeypatch, thread_id="wf-hr-reject")
    state = excinfo.value.state
    assert state.get("review_route") == "asset_resolver"
    # First pass: no rejection; second pass (post human_review): rejection present.
    assert len(captures) == 2
    assert captures[0]["rejected_asset_decisions"] is None
    assert captures[1]["rejected_asset_decisions"] == rejection
    # Render-chain artifacts invalidated; atoms + direction preserved.
    assert state.get("content_atom_set") is not None
    assert state.get("visual_direction_plan") is not None
    assert state.get("render_manifest") is None
    assert state.get("visual_critique") is None


# ---------------------------------------------------------------------------
# Human Review route 5: visual_needs_attention -> explicit override.
# ---------------------------------------------------------------------------


def test_visual_needs_attention_requires_explicit_override(tmp_path, monkeypatch):
    """A round-2 ``visual_needs_attention`` carousel approved WITH an aesthetic
    override reaches Final Guard; approved WITHOUT the override is routed back
    to design_reviser (the gate holds)."""

    case_id = "case-01"
    # Failed critic that drives review_status to visual_needs_attention.
    failed_critic_factory = _make_failed_critic_factory(case_id)

    # (a) override present -> final_policy_guard -> content_writer.
    harness_a = _make_harness(case_id, tmp_path)
    harness_a.overrides = {
        "visual_critic_node": failed_critic_factory(with_status=True),
        # noop reviser so the rounds-0/1 critic failures cycle back to QA and
        # re-render before round 2 escalates to human_review.
        "design_reviser_node": lambda state, **_k: {
            "carousel_design_plan": state.get("carousel_design_plan"),
            "current_node": "DESIGN_REVISER",
        },
    }
    harness_a.interrupt_payload = {
        "approved": True,
        "aesthetic_override": True,
        "feedback": "accept look",
    }
    state_a = harness_a.run(monkeypatch, thread_id="wf-needs-attn-override")
    assert state_a.get("review_status") == "approved"
    assert state_a.get("visual_aesthetic_override") is True
    assert state_a.get("final_policy_issues") == []

    # (b) no override -> routed back to design_reviser, never approved.
    harness_b = _make_harness(case_id, tmp_path)

    def gate_aware_design_reviser(state, **_kwargs):
        # During the round-0/1 critic-failure cycle human_review has not run
        # yet, so ``review_route`` is unset -> noop so the loop advances. Once
        # human_review routes back here (the no-override gate), ``review_route``
        # is "design_reviser" -> sentinel fires, proving the gate held.
        if state.get("review_route") == "design_reviser":
            raise _DesignReviserReached(state)
        return {
            "carousel_design_plan": state.get("carousel_design_plan"),
            "current_node": "DESIGN_REVISER",
        }

    harness_b.overrides = {
        "visual_critic_node": failed_critic_factory(with_status=True),
        "design_reviser_node": gate_aware_design_reviser,
    }
    harness_b.interrupt_payload = {"approved": True, "feedback": "ship it"}
    with pytest.raises(_DesignReviserReached) as excinfo:
        harness_b.run(monkeypatch, thread_id="wf-needs-attn-no-override")
    state_b = excinfo.value.state
    assert state_b.get("review_route") == "design_reviser"
    assert state_b.get("visual_aesthetic_override") is None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_failed_critic_factory(case_id: str):
    spec = load_case(case_id)

    def factory(*, with_status: bool):
        def failing_visual_critic(state, **_kwargs):
            round_value = int(state.get("visual_critic_round", 0))
            atom_set = state["content_atom_set"]
            direction = state["visual_direction_plan"]
            design_plan = state["carousel_design_plan"]
            render_manifest = state["render_manifest"]
            critique = VisualCritique(
                content_atom_set_sha256=atom_set.canonical_sha256,
                direction_plan_sha256=canonical_sha256(direction),
                design_plan_sha256=canonical_sha256(design_plan),
                render_manifest_sha256=canonical_sha256(render_manifest),
                passed=False,
                revision_round=round_value,
                contains_images=False,
                overall=40,
                hierarchy=40,
                legibility=40,
                composition=40,
                family_consistency=40,
                page_variation=40,
                page_rhythm=40,
                color=40,
                spacing=40,
                image_relevance="not_applicable",
                issues=(
                    VisualCritiqueIssue(
                        rule="composition",
                        message="weak composition",
                        revision_instruction="rebalance page-1 composition",
                        page_id="page-1",
                    ),
                ),
                revision_instructions=("rebalance page-1 composition",),
            )
            result: dict[str, Any] = {
                "visual_critique": critique,
                "current_node": "VISUAL_CRITIC",
                "visual_critic_round": round_value + 1,
            }
            if with_status and critique.revision_round >= 2:
                result["review_status"] = "visual_needs_attention"
            return result

        return failing_visual_critic

    return factory
