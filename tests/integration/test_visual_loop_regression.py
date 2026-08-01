"""Real-graph regression tests for the llm_scene_v3 visual-production loops.

These tests drive the REAL ``create_graph()`` (LangGraph state-merge, counter
persistence, and conditional-edge routing are all production) with the upstream
research/topic/writing nodes replaced by no-op fakes and the visual node under
test exercised through the real graph wiring. They guard two regressions that
unit tests missed because unit tests inject state directly instead of through
LangGraph:

* C1: the retry counters (``design_plan_qa_failures``, ``render_qa_failures``,
  ``visual_critic_round``) must be declared on ``AgentState`` or LangGraph
  drops the writes, producing non-terminating loops that only end on
  ``GraphRecursionError`` instead of the intended ``VisualProductionInterrupted``.
* I1: ``design_reviser`` must assemble a ``RevisionRequest`` from the QA/critic
  results already in state when one is not explicitly injected, or every
  failure route into the reviser crashes with ``ValueError``.

The fakes planted on the visual nodes mirror the real nodes' state-contract
(read the counter from state, increment, write back) so that a dropped counter
write surfaces as the original non-terminating loop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src import graph as graph_module
from src.nodes import node_p_design_reviser as design_reviser_module
from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.content_atoms import (
    ContentAtom,
    ContentAtomSet,
    ContentFragment,
    canonical_sha256,
    sha256_text,
)
from src.schemas.design_qa import DesignIssue, DesignPlanQAResult
from src.schemas.render_qa import RenderIssue, RenderQAResult
from src.schemas.scene_graph import (
    Box,
    CarouselDesignPlan,
    PageScene,
    ShapeElement,
    TextElement,
    TextStyle,
)
from src.schemas.visual_critique import VisualCritique, VisualCritiqueIssue
from src.schemas.visual_director import (
    AssetDirective,
    PageDirection,
    VisualDirectionPlan,
)
from src.visual_design.model_retry import VisualProductionInterrupted

# A roomy recursion limit so the 3-strike / 2-round terminations occur well
# before LangGraph's default ceiling; the bugs manifest as GraphRecursionError,
# so we must not conflate the two.
_RECURSION_LIMIT = 80


# ---------------------------------------------------------------------------
# Minimal valid visual fixtures (text-only carousel, no external assets).
# ---------------------------------------------------------------------------


def _atom_set(page_count: int = 5) -> ContentAtomSet:
    texts = [f"第{index}页内容重点。" for index in range(1, page_count + 1)]
    atoms = tuple(
        ContentAtom(
            atom_id=f"atom-{index}",
            text=text,
            role="paragraph",
            sha256=sha256_text(text),
        )
        for index, text in enumerate(texts, start=1)
    )
    return ContentAtomSet(
        atoms=atoms,
        canonical_sha256=canonical_sha256(
            [atom.model_dump(mode="json") for atom in atoms]
        ),
    )


def _fragments(atom_set: ContentAtomSet) -> tuple[ContentFragment, ...]:
    return tuple(
        ContentFragment(
            fragment_id=f"fragment-{index}",
            source_atom_id=atom.atom_id,
            start=0,
            end=len(atom.text),
            text=atom.text,
        )
        for index, atom in enumerate(atom_set.atoms, start=1)
    )


def _direction_plan(atom_set: ContentAtomSet) -> VisualDirectionPlan:
    fragments = _fragments(atom_set)
    return VisualDirectionPlan(
        template_family="pink_red",
        page_count=len(atom_set.atoms),
        content_atom_set_sha256=atom_set.canonical_sha256,
        art_direction="内容驱动的护肤编辑方向",
        palette=("#F4A7BF",),
        typography_direction={"display": "醒目", "body": "清晰"},
        motifs=("red underlines",),
        content_fragments=fragments,
        page_sequence=tuple(
            PageDirection(
                page_id=f"page-{index}",
                sequence=index,
                purpose=f"解释第{index}个重点",
                visual_job=f"visual-job-{index}",
                fragment_ids=(f"fragment-{index}",),
                asset_directive_ids=(),
            )
            for index in range(1, len(atom_set.atoms) + 1)
        ),
        asset_directives=(),
    )


def _asset_item() -> AssetManifestItem:
    return AssetManifestItem(
        asset_id="asset-2",
        directive_id="directive-2",
        page_id="page-2",
        source_kind="search",
        provider="pexels",
        license="Pexels License",
        local_path="/tmp/asset.png",
        width=1080,
        height=1440,
        sha256=sha256_text("asset-bytes"),
        subject_focal_point=(0.5, 0.5),
        crop_guidance="centered crop",
        security_status="approved",
        human_decision="pending",
        run_id="run-1",
        transaction_id="tx-1",
        internal_provenance={"provider": "pexels"},
    )


def _design_plan(
    direction_plan: VisualDirectionPlan,
    atom_set: ContentAtomSet,
    manifest: AssetManifest,
    *,
    revision: int = 0,
) -> CarouselDesignPlan:
    pages: list[PageScene] = []
    for direction_page in direction_plan.page_sequence:
        elements = [
            TextElement(
                element_id=f"text-{direction_page.page_id}",
                layer=1,
                box=Box(x=80, y=120, width=920, height=160),
                content_ref=direction_page.fragment_ids[0],
                style=TextStyle(
                    font_role="heading",
                    font_size=48,
                    line_height=1.3,
                    color="#1A1A1A",
                    align="left",
                    weight=700,
                ),
            )
        ]
        pages.append(
            PageScene(
                page_id=direction_page.page_id,
                sequence=direction_page.sequence,
                background="#FFFFFF",
                elements=tuple(elements),
            )
        )
    return CarouselDesignPlan(
        direction_plan_sha256=canonical_sha256(direction_plan),
        content_atom_set_sha256=atom_set.canonical_sha256,
        asset_manifest_sha256=canonical_sha256(manifest),
        revision=revision,
        pages=tuple(pages),
    )


def _visual_state(**overrides) -> dict:
    """Minimal state seed that the real visual nodes can run against."""
    atom_set = _atom_set()
    direction_plan = _direction_plan(atom_set)
    manifest = AssetManifest(items=(_asset_item(),))
    # Build a design plan whose hashes match the other fixtures so the real
    # design_reviser (I1 test) can validate bindings.
    design_plan = _design_plan(direction_plan, atom_set, manifest, revision=0)
    base = {
        "carousel_design_plan": design_plan,
        "visual_direction_plan": direction_plan,
        "content_atom_set": atom_set,
        "asset_manifest": manifest,
        "publish_package": {},
        "unresolved_optional_assets": [],
        "domain_context": {"domain": "beauty", "profile_version": "beauty-v1"},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Upstream no-op harness: replace the research/topic/writing chain so the real
# graph flows straight into the visual-production loop offline.
# ---------------------------------------------------------------------------


def _install_noop_upstream(monkeypatch) -> None:
    """Replace every pre-visual node with a passthrough that routes forward."""

    def passthrough(_state, **_kwargs):
        return {}

    pre_visual = (
        "domain_router_node",
        "domain_confirmation_node",
        "retrieve_memory_node",
        "topic_signal_collector_node",
        "creative_brief_builder_node",
        "topic_ideator_node",
        "topic_diversity_filter_node",
        "angle_strategist_node",
        "novelty_guard_node",
        "virality_scorer_node",
        "evidence_brief_node",
        "outline_architect_node",
        "draft_writer_node",
        "title_lab_node",
        "title_ranker_node",
        "hashtag_node",
        "assembler_node",
        "content_atomizer_node",
        "visual_director_node",
        "asset_resolver_node",
        "page_designer_node",
    )
    for node_name in pre_visual:
        monkeypatch.setattr(graph_module.nodes, node_name, passthrough)

    # decision_engine must publish a decision_output that routes to hashtag so
    # the chain proceeds into the visual-production path.
    def decision_route(_state):
        from src.schemas.decision import DecisionOutput, NormalizedInput

        return {
            "decision_output": DecisionOutput(
                next_node="HASHTAG_SEO",
                normalized_input=NormalizedInput(),
            )
        }

    monkeypatch.setattr(graph_module.nodes, "decision_engine_node", decision_route)


def _patch_visual_model(monkeypatch, model) -> None:
    """Force the lazy structured-model seam to return ``model``."""
    monkeypatch.setattr(graph_module, "_get_visual_model", lambda: model)
    # Reset the cached singleton so a prior build doesn't survive.
    monkeypatch.setattr(graph_module, "_VISUAL_MODEL", model)


class _NullModel:
    """Visual model stand-in for tests whose fakes never call the model."""

    def generate_json(self, *args, **kwargs):  # pragma: no cover - never called
        raise AssertionError("null model should not be invoked")


# ---------------------------------------------------------------------------
# C1 regression: design_plan_qa 3-strike terminates via interruption.
# ---------------------------------------------------------------------------


def test_design_plan_qa_three_strike_terminates_via_interruption(monkeypatch, tmp_path):
    """A persistently-failing design-plan QA must interrupt after exactly 3
    calls with the counter advancing 0->1->2->3. Before the AgentState fix the
    counter write is dropped and the loop only ends on GraphRecursionError."""
    monkeypatch.chdir(tmp_path)
    _install_noop_upstream(monkeypatch)
    _patch_visual_model(monkeypatch, _NullModel())

    observed_counters = []
    design_plan = _visual_state()["carousel_design_plan"]

    def failing_design_plan_qa(state):
        # Mirror the real node's state contract: read counter, increment,
        # write back. If LangGraph drops the write, the counter stays 0.
        prior = int(state.get("design_plan_qa_failures", 0))
        observed_counters.append(prior)
        failures = prior + 1
        if failures >= 3:
            raise VisualProductionInterrupted(
                stage="design_plan_qa",
                errors=["fake: persistent spacing failure"],
                raw_outputs=(),
            )
        result = DesignPlanQAResult(
            passed=False,
            issues=(
                DesignIssue(
                    rule="spacing",
                    message=f"page-1 spacing failure #{failures}",
                    repair_instruction="adjust spacing on page-1",
                    page_id="page-1",
                    element_id="text-page-1",
                ),
            ),
            design_plan_sha256=design_plan.direction_plan_sha256,
            content_coverage_attestation=False,
            family_attestation=True,
            asset_binding_attestation=True,
        )
        return {
            "design_plan_qa_result": result,
            "design_plan_qa_failures": failures,
            "current_node": "DESIGN_PLAN_QA",
        }

    def noop_reviser(state, *, model, style_profiles=None):
        # Routes back to design_plan_qa via visual_route_override=None.
        return {
            "carousel_design_plan": state.get("carousel_design_plan"),
            "current_node": "DESIGN_REVISER",
        }

    monkeypatch.setattr(graph_module.nodes, "design_plan_qa_node", failing_design_plan_qa)
    monkeypatch.setattr(graph_module.nodes, "design_reviser_node", noop_reviser)

    graph = graph_module.create_graph(checkpointer=InMemorySaver())
    config = {
        "configurable": {"thread_id": "dpj-3strike"},
        "recursion_limit": _RECURSION_LIMIT,
    }

    with pytest.raises(VisualProductionInterrupted) as excinfo:
        graph.invoke(_visual_state(), config=config)

    assert excinfo.value.stage == "design_plan_qa"
    # Exactly 3 QA calls, reading the counter 0, 1, 2 in sequence. If the
    # counter write were dropped, every call would read 0 and observe would
    # be [0, 0, 0, ...] until GraphRecursionError.
    assert observed_counters == [0, 1, 2]


# ---------------------------------------------------------------------------
# C1 regression: render_qa 3-strike terminates via interruption.
# ---------------------------------------------------------------------------


def test_render_qa_three_strike_terminates_via_interruption(monkeypatch, tmp_path):
    """A persistently-failing render QA must interrupt after exactly 3 calls."""
    monkeypatch.chdir(tmp_path)
    _install_noop_upstream(monkeypatch)
    _patch_visual_model(monkeypatch, _NullModel())

    observed_counters = []

    def passing_design_plan_qa(state):
        design_plan = state["carousel_design_plan"]
        return {
            "design_plan_qa_result": DesignPlanQAResult(
                passed=True,
                issues=(),
                design_plan_sha256=design_plan.direction_plan_sha256,
                content_coverage_attestation=True,
                family_attestation=True,
                asset_binding_attestation=True,
            ),
            "design_plan_qa_failures": 0,
            "current_node": "DESIGN_PLAN_QA",
        }

    def noop_renderer(_state):
        return {
            "render_manifest": {
                "pages": [],
                "contact_sheet_path": "/tmp/sheet.png",
            },
            "current_node": "GENERIC_SCENE_RENDERER",
        }

    def failing_render_qa(state):
        prior = int(state.get("render_qa_failures", 0))
        observed_counters.append(prior)
        failures = prior + 1
        if failures >= 3:
            raise VisualProductionInterrupted(
                stage="render_qa",
                errors=["fake: persistent geometry failure"],
                raw_outputs=(),
            )
        result = RenderQAResult(
            passed=False,
            issues=(
                RenderIssue(
                    rule="geometry",
                    message=f"page-1 box overflow #{failures}",
                    repair_instruction="resize page-1 box",
                    page_id="page-1",
                    element_id="text-page-1",
                ),
            ),
            render_manifest_sha256="0" * 64,
            content_attestation=False,
            geometry_attestation=False,
            asset_attestation=True,
        )
        return {
            "render_qa_result": result,
            "render_qa_failures": failures,
            "current_node": "RENDER_QA",
        }

    def noop_reviser(state, *, model, style_profiles=None):
        return {
            "carousel_design_plan": state.get("carousel_design_plan"),
            "current_node": "DESIGN_REVISER",
        }

    monkeypatch.setattr(graph_module.nodes, "design_plan_qa_node", passing_design_plan_qa)
    monkeypatch.setattr(graph_module.nodes, "generic_scene_renderer_node", noop_renderer)
    monkeypatch.setattr(graph_module.nodes, "render_qa_node", failing_render_qa)
    monkeypatch.setattr(graph_module.nodes, "design_reviser_node", noop_reviser)

    graph = graph_module.create_graph(checkpointer=InMemorySaver())
    config = {
        "configurable": {"thread_id": "rq-3strike"},
        "recursion_limit": _RECURSION_LIMIT,
    }

    with pytest.raises(VisualProductionInterrupted) as excinfo:
        graph.invoke(_visual_state(), config=config)

    assert excinfo.value.stage == "render_qa"
    assert observed_counters == [0, 1, 2]


# ---------------------------------------------------------------------------
# C1 regression: visual_critic round-2 routes to human_review.
# ---------------------------------------------------------------------------


class _HumanReviewReached(Exception):
    """Sentinel raised by the fake human_review to stop the graph cleanly."""

    def __init__(self, state) -> None:
        self.state = state


def test_visual_critic_round_two_routes_to_human_review(monkeypatch, tmp_path):
    """A persistently-failing critic must stop auto-redesign after round 2 and
    route to human_review with review_status=visual_needs_attention. Before
    the AgentState fix visual_critic_round is dropped so every critique stamps
    revision_round=0 and the loop never escalates."""
    monkeypatch.chdir(tmp_path)
    _install_noop_upstream(monkeypatch)
    _patch_visual_model(monkeypatch, _NullModel())

    observed_rounds = []

    def passing_design_plan_qa(state):
        design_plan = state["carousel_design_plan"]
        return {
            "design_plan_qa_result": DesignPlanQAResult(
                passed=True,
                issues=(),
                design_plan_sha256=design_plan.direction_plan_sha256,
                content_coverage_attestation=True,
                family_attestation=True,
                asset_binding_attestation=True,
            ),
            "design_plan_qa_failures": 0,
            "current_node": "DESIGN_PLAN_QA",
        }

    def noop_renderer(_state):
        return {
            "render_manifest": {
                "pages": [],
                "contact_sheet_path": "/tmp/sheet.png",
            },
            "current_node": "GENERIC_SCENE_RENDERER",
        }

    def passing_render_qa(state):
        return {
            "render_qa_result": RenderQAResult(
                passed=True,
                issues=(),
                render_manifest_sha256="0" * 64,
                content_attestation=True,
                geometry_attestation=True,
                asset_attestation=True,
            ),
            "render_qa_failures": 0,
            "current_node": "RENDER_QA",
        }

    def failing_visual_critic(state, *, model, style_profiles=None):
        # Mirror the real node: read the round counter from state, stamp the
        # critique with that round, then write round+1 back. If LangGraph
        # drops the write, round stays 0 forever and the terminal branch
        # (revision_round >= 2) is never taken.
        round_value = int(state.get("visual_critic_round", 0))
        observed_rounds.append(round_value)
        atom_set = state["content_atom_set"]
        direction = state["visual_direction_plan"]
        design_plan = state["carousel_design_plan"]
        critique = VisualCritique(
            content_atom_set_sha256=atom_set.canonical_sha256,
            direction_plan_sha256=canonical_sha256(direction),
            design_plan_sha256=canonical_sha256(design_plan),
            render_manifest_sha256="0" * 64,
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
        result = {
            "visual_critique": critique,
            "current_node": "VISUAL_CRITIC",
            "visual_critic_round": round_value + 1,
        }
        if not critique.passed and critique.revision_round >= 2:
            result["review_status"] = "visual_needs_attention"
        return result

    def noop_reviser(state, *, model, style_profiles=None):
        return {
            "carousel_design_plan": state.get("carousel_design_plan"),
            "current_node": "DESIGN_REVISER",
        }

    def human_review_recorder(state):
        raise _HumanReviewReached(state)

    monkeypatch.setattr(graph_module.nodes, "design_plan_qa_node", passing_design_plan_qa)
    monkeypatch.setattr(graph_module.nodes, "generic_scene_renderer_node", noop_renderer)
    monkeypatch.setattr(graph_module.nodes, "render_qa_node", passing_render_qa)
    monkeypatch.setattr(graph_module.nodes, "visual_critic_node", failing_visual_critic)
    monkeypatch.setattr(graph_module.nodes, "design_reviser_node", noop_reviser)
    monkeypatch.setattr(graph_module.nodes, "human_review_node", human_review_recorder)

    graph = graph_module.create_graph(checkpointer=InMemorySaver())
    config = {
        "configurable": {"thread_id": "vc-round2"},
        "recursion_limit": _RECURSION_LIMIT,
    }

    with pytest.raises(_HumanReviewReached) as excinfo:
        graph.invoke(_visual_state(), config=config)

    state = excinfo.value.state
    # The critic read the counter at 0, 1, 2 across three critiques (the
    # terminal third evaluation). Before the fix every read would be 0.
    assert observed_rounds == [0, 1, 2]
    critique = state["visual_critique"]
    assert critique.revision_round == 2
    assert state.get("review_status") == "visual_needs_attention"


# ---------------------------------------------------------------------------
# I1 regression: design_reviser assembles RevisionRequest from state.
# ---------------------------------------------------------------------------


class _ScriptedReviserModel:
    """Fake StructuredVisualModel that returns a pre-built revised plan."""

    def __init__(self, responses: Sequence[CarouselDesignPlan]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def generate_json(
        self,
        prompt: str,
        response_model: type,
        image_paths: Sequence[Path] = (),
    ):
        self.calls.append(
            {
                "prompt": prompt,
                "response_model": response_model,
                "image_paths": tuple(image_paths),
            }
        )
        return self.responses.pop(0)


def test_design_reviser_assembles_request_from_state_without_crashing(
    monkeypatch, tmp_path
):
    """When no explicit revision_request is injected, the real design_reviser
    must build one from design_plan_qa_result and produce a revised plan rather
    than raising ValueError. Before the I1 fix every failure route into the
    reviser crashed because no node writes revision_request."""
    monkeypatch.chdir(tmp_path)
    _install_noop_upstream(monkeypatch)

    state = _visual_state()
    before = state["carousel_design_plan"]
    # The loop cycles design_plan_qa -> design_reviser -> design_plan_qa; the
    # real reviser validates that the returned revision == current + 1, so we
    # pre-build one revised plan per expected reviser call, each bumping only
    # the revision (pages/hashes stay byte-equal so validate_revision +
    # validate_bindings pass).
    revised_plans = [
        before.model_copy(update={"revision": index}) for index in range(1, 5)
    ]
    model = _ScriptedReviserModel(revised_plans)
    _patch_visual_model(monkeypatch, model)

    qa_calls = []

    def failing_design_plan_qa(state):
        # Mirror the real node's 3-strike contract: read the persisted
        # counter, increment, raise VisualProductionInterrupted on the third
        # failure. The counter write persists because of the C1 fix.
        prior = int(state.get("design_plan_qa_failures", 0))
        qa_calls.append(prior)
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
                        message="page-1 needs wider margins",
                        repair_instruction="add a shape band on page-1",
                        page_id="page-1",
                        element_id="text-page-1",
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

    monkeypatch.setattr(graph_module.nodes, "design_plan_qa_node", failing_design_plan_qa)
    # design_reviser_node stays REAL; only the model is faked.

    graph = graph_module.create_graph(checkpointer=InMemorySaver())
    config = {
        "configurable": {"thread_id": "i1-reviser"},
        "recursion_limit": _RECURSION_LIMIT,
    }

    # The real reviser constructs a RevisionRequest from design_plan_qa_result,
    # calls the fake model, and returns a revised plan that routes back to
    # design_plan_qa. After 3 QA failures the loop interrupts (proving the
    # counter persisted across the reviser round-trip too).
    with pytest.raises(VisualProductionInterrupted) as excinfo:
        graph.invoke(state, config=config)

    assert excinfo.value.stage == "design_plan_qa"
    # The real reviser was invoked (model called) and did NOT raise
    # "design_reviser requires revision_request" -- before the I1 fix every
    # failure route into the reviser crashed because no node writes
    # revision_request. The revised plan was produced and the loop cycled.
    assert len(model.calls) >= 1, "real design_reviser never called the model"
    assert model.calls[0]["response_model"] is CarouselDesignPlan
    # The counter persisted across the reviser round-trip: QA read 0, 1, 2
    # across three calls. Before the C1 fix every read would be 0.
    assert qa_calls == [0, 1, 2]
    # The reviser ran twice (once per non-terminal QA failure).
    assert len(model.calls) == 2
    # revision_request is never injected; the real reviser assembled it from
    # design_plan_qa_result on every call.
    assert "revision_request" not in state
