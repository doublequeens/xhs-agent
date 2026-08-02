"""Real-graph regression tests for the Task 15 Human Review state channels.

These tests drive the REAL ``create_graph()`` so that LangGraph's production
state-merge (the TypedDict channel-filtering) is exercised end-to-end. They
guard two regressions that the direct-node-call unit tests in
``tests/nodes/test_dynamic_visual_human_review.py`` could not catch:

* C1: ``human_review_node`` writes ``visual_aesthetic_override: True`` on the
  approval-with-override path, but the key was undeclared on ``AgentState``.
  LangGraph silently drops any key absent from the TypedDict from a node's
  return dict, so ``final_policy_guard`` always read ``None`` and emitted
  ``visual_critique_not_overridden``, routing back to ``human_review`` forever.
  A ``visual_needs_attention`` carousel could never be approved.
* I1: ``human_review_node`` writes ``rejected_asset_decisions`` on the
  image-rejection route; it was likewise undeclared and dropped, silently
  losing the human's rejection rationale before any downstream
  asset-resolver consumer could read it.

The bug is in LangGraph's state-merge layer, NOT in the node return values, so
the assertions verify cross-node key survival through the real graph wiring
(upstream + visual nodes replaced by no-op passthrough fakes at the
``graph_module.nodes`` registration seam, exactly like
``tests/integration/test_visual_loop_regression.py``).
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src import graph as graph_module
from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.content_atoms import (
    ContentAtom,
    ContentAtomSet,
    canonical_sha256,
    sha256_text,
)
from src.schemas.visual_critique import VisualCritique, VisualCritiqueIssue

# Roomy recursion limit so the intended terminations occur well before
# LangGraph's default ceiling; the C1 bug manifests as a non-terminating
# human_review <-> final_policy_guard loop, which must not be conflated with
# GraphRecursionError.
_RECURSION_LIMIT = 80


# ---------------------------------------------------------------------------
# Minimal final-guard-ready fixtures.
# ---------------------------------------------------------------------------

_ATOMS = (
    ContentAtom(atom_id="title-001", text="作息调整记录", role="title", sha256=sha256_text("作息调整记录")),
    ContentAtom(atom_id="cover-001", text="先看懂作息", role="cover", sha256=sha256_text("先看懂作息")),
    ContentAtom(
        atom_id="paragraph-001",
        text="记录每天的作息变化",
        role="paragraph",
        sha256=sha256_text("记录每天的作息变化"),
    ),
)
_ATOM_SHA = canonical_sha256([atom.model_dump(mode="json") for atom in _ATOMS])
_ATOM_SET = ContentAtomSet(atoms=_ATOMS, canonical_sha256=_ATOM_SHA)


def _asset_item() -> AssetManifestItem:
    return AssetManifestItem(
        asset_id="asset-1",
        directive_id="dir-1",
        page_id="page-1",
        source_kind="catalog",
        provider="local",
        license="project_internal",
        local_path="/assets/active/a.svg",
        width=16,
        height=16,
        sha256=hashlib.sha256(b"a").hexdigest(),
        subject_focal_point=(0.5, 0.5),
        crop_guidance="center",
        security_status="approved",
        human_decision="pending",
        run_id="run-1",
        transaction_id="txn-1",
        internal_provenance={},
    )


def _publish_package() -> dict:
    """A publish package that satisfies every Final Guard required-field and
    ContentLock attestation, so the visual-critique override rule is the
    SOLE determinant of the guard's verdict."""
    return {
        "focus_keyword": "分区护肤",
        "topic_id": "tp_001",
        "topic": "睡眠改善",
        "angle_id": "ag_001",
        "angle": "作息调整",
        "target_group": "上班族",
        "core_pain": "熬夜后疲惫",
        "title": "作息调整记录",
        "content": "记录每天的作息变化。",
        "cover_copy": "先看懂作息",
        "hashtags": ["#作息", "#睡眠"],
        "domain": "beauty",
        "content_contract": {"first_screen_promise": "先看懂作息，再调整"},
    }


def _failed_critique() -> VisualCritique:
    """A FAILED visual critique (passed=False, revision_round=2).

    ``revision_round=2`` makes ``route_after_visual_critic`` escalate to
    ``human_review`` and ``passed=False`` makes Final Guard's override rule
    the deciding attestation. The real ``VisualCritique`` schema is used so
    the state is checkpoint-serializable and ``route_after_visual_critic`` can
    read the ``.passed`` / ``.revision_round`` attributes it depends on.
    """
    return VisualCritique(
        content_atom_set_sha256=_ATOM_SHA,
        direction_plan_sha256=_ATOM_SHA,
        design_plan_sha256=_ATOM_SHA,
        render_manifest_sha256=_ATOM_SHA,
        passed=False,
        revision_round=2,
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


def _passed_critique() -> VisualCritique:
    return VisualCritique(
        content_atom_set_sha256=_ATOM_SHA,
        direction_plan_sha256=_ATOM_SHA,
        design_plan_sha256=_ATOM_SHA,
        render_manifest_sha256=_ATOM_SHA,
        passed=True,
        revision_round=0,
        contains_images=False,
        overall=90,
        hierarchy=90,
        legibility=90,
        composition=90,
        family_consistency=90,
        page_variation=90,
        page_rhythm=90,
        color=90,
        spacing=90,
        image_relevance="not_applicable",
    )


def _complete_visual_state(**overrides) -> dict:
    """A post-critic state that passes every Final Guard attestation EXCEPT
    the critique-override rule when the critique is failed.

    The artifact stand-ins are plain dicts (plus the real ``VisualCritique``
    and real ``AssetManifest`` / ``ContentAtomSet``) so the state is
    msgpack-serializable for ``InMemorySaver``. The dict payloads carry just
    the keys the real routing functions and Final Guard read (``passed`` for
    QA routing, ``content_atom_set_sha256`` for the ContentLock binding,
    ``asset_directives`` for the required-asset gate). The REAL
    ``human_review_node`` and ``final_policy_guard_node`` run against this
    state unchanged.
    """
    base: dict[str, Any] = {
        "publish_package": _publish_package(),
        "content_atom_set": _ATOM_SET,
        # visual_direction_plan: Final Guard reads asset_directives
        # (required-asset gate) and content_atom_set_sha256 (binding).
        "visual_direction_plan": {
            "template_family": "soft_pink",
            "content_atom_set_sha256": _ATOM_SHA,
            "asset_directives": ({"directive_id": "dir-1", "required": True},),
        },
        "asset_manifest": AssetManifest(items=(_asset_item(),)),
        "carousel_design_plan": {"content_atom_set_sha256": _ATOM_SHA},
        "render_manifest": {"content_atom_set_sha256": _ATOM_SHA},
        # QA results as dicts: route_after_design_plan_qa / route_after_render_qa
        # accept a Mapping, and Final Guard reads .get("passed").
        "design_plan_qa_result": {"passed": True},
        "render_qa_result": {"passed": True},
        "visual_critique": _failed_critique(),
        "r2_output": {"compliance_audit": {"block_publish": False}},
        "unresolved_optional_assets": [],
        "review_round": 0,
        "final_policy_issues": [],
        "domain_context": {"domain": "beauty", "profile_version": "beauty-v1"},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# No-op harness: replace the research/topic/writing + visual chain so the
# REAL human_review and final_policy_guard nodes are reached offline. The
# passthroughs preserve the seeded visual artifacts (they return {} so the
# conditional-edge routers read the seeded values).
# ---------------------------------------------------------------------------


def _passthrough(_state, **_kwargs):
    return {}


def _install_noop_chain(monkeypatch) -> None:
    """Replace every node except human_review / final_policy_guard with a
    passthrough, so the seeded state flows through the real conditional edges
    into the two nodes under test."""

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
        "design_plan_qa_node",
        "generic_scene_renderer_node",
        "render_qa_node",
        "visual_critic_node",
        "design_reviser_node",
    )
    for node_name in pre_visual:
        monkeypatch.setattr(graph_module.nodes, node_name, _passthrough)

    # decision_engine must route into the visual chain.
    def decision_route(_state):
        from src.schemas.decision import DecisionOutput, NormalizedInput

        return {
            "decision_output": DecisionOutput(
                next_node="HASHTAG_SEO",
                normalized_input=NormalizedInput(),
            )
        }

    monkeypatch.setattr(graph_module.nodes, "decision_engine_node", decision_route)


def _build_graph(monkeypatch) -> Any:
    return graph_module.create_graph(checkpointer=InMemorySaver())


# ---------------------------------------------------------------------------
# Sentinels raised by fakes to prove a specific node was reached (and to stop
# the graph cleanly instead of running the real DB-writing content_writer).
# ---------------------------------------------------------------------------


class _ContentWriterReached(Exception):
    def __init__(self, state) -> None:
        self.state = state


class _HumanReviewReached(Exception):
    """Final Guard routed back to human_review (the no-override gate held)."""


class _AssetResolverReached(Exception):
    def __init__(self, state) -> None:
        self.state = state


def _content_writer_sentinel(state):
    raise _ContentWriterReached(state)


# ---------------------------------------------------------------------------
# C1 regression: visual_aesthetic_override survives human_review -> Final Guard.
# ---------------------------------------------------------------------------


def test_visual_aesthetic_override_survives_into_final_guard(monkeypatch, tmp_path):
    """C1 override round-trip through the REAL graph.

    A failed-critique carousel flagged ``visual_needs_attention`` reaches
    human_review; the human approves with ``aesthetic_override=True``. The
    override MUST survive LangGraph's state-merge into Final Guard's state, so
    Final Guard sees ``True`` (not ``None``), omits
    ``visual_critique_not_overridden``, and routes to ``content_writer``.

    Before the ``AgentState`` declaration, LangGraph dropped the override key
    from human_review's return dict; Final Guard read ``None``, emitted
    ``visual_critique_not_overridden`` and routed back to human_review in an
    infinite loop (the carousel could never be approved).
    """
    monkeypatch.chdir(tmp_path)
    _install_noop_chain(monkeypatch)
    monkeypatch.setattr(graph_module.nodes, "content_writer_node", _content_writer_sentinel)

    # human_review interrupts exactly once per node entry. The first entry
    # returns the human approval-with-override payload. A second entry means
    # Final Guard routed BACK to human_review instead of forward to
    # content_writer -- i.e. the override was dropped and the gate blocked.
    # The sentinel stops the graph cleanly so the loop is observable without
    # waiting on GraphRecursionError.
    interrupt_calls = {"count": 0}

    def resume_payload(_payload):
        interrupt_calls["count"] += 1
        if interrupt_calls["count"] == 1:
            return {"approved": True, "aesthetic_override": True, "feedback": "accept look"}
        raise _HumanReviewReached()

    monkeypatch.setattr("src.nodes.node_q_human_review.interrupt", resume_payload)

    graph = _build_graph(monkeypatch)
    config = {
        "configurable": {"thread_id": "c1-override"},
        "recursion_limit": _RECURSION_LIMIT,
    }

    state = _complete_visual_state(review_status="visual_needs_attention")

    # GREEN: the override survives, Final Guard omits
    # ``visual_critique_not_overridden`` and routes to content_writer, so the
    # content_writer sentinel fires. RED (before the AgentState declaration):
    # the override is dropped, Final Guard re-emits the issue and routes back
    # to human_review, so ``_HumanReviewReached`` fires on the second entry
    # instead and this assertion fails.
    with pytest.raises(_ContentWriterReached) as excinfo:
        graph.invoke(state, config=config)

    terminal_state = excinfo.value.state
    # The override survived across the human_review -> final_policy_guard edge:
    final_issues = terminal_state.get("final_policy_issues") or []
    rule_ids = {issue.get("rule_id") for issue in final_issues}
    assert "visual_critique_not_overridden" not in rule_ids, (
        f"override was dropped: Final Guard saw visual_aesthetic_override="
        f"{terminal_state.get('visual_aesthetic_override')!r} and emitted "
        f"visual_critique_not_overridden; issues={final_issues}"
    )
    # And the graph terminated at content_writer rather than looping back.
    assert terminal_state.get("visual_aesthetic_override") is True


def test_failed_critique_without_override_loops_back_to_human_review(
    monkeypatch, tmp_path
):
    """C1 no-override gate still holds.

    The same failed-critique carousel approved WITHOUT an aesthetic override
    MUST NOT reach content_writer: Final Guard emits
    ``visual_critique_not_overridden`` (override is ``None``) and routes back
    to human_review. Declaring the channel on ``AgentState`` must not bypass
    this gate.
    """
    monkeypatch.chdir(tmp_path)
    _install_noop_chain(monkeypatch)
    monkeypatch.setattr(graph_module.nodes, "content_writer_node", _content_writer_sentinel)

    # First human_review entry: approve without override (routes to
    # final_policy_guard). Second entry: raise a sentinel to prove Final Guard
    # routed back, and to stop the graph before GraphRecursionError.
    interrupt_calls = {"count": 0}

    def resume_payload(_payload):
        interrupt_calls["count"] += 1
        if interrupt_calls["count"] == 1:
            return {"approved": True, "feedback": "ship it"}  # no override
        raise _HumanReviewReached()

    monkeypatch.setattr("src.nodes.node_q_human_review.interrupt", resume_payload)

    graph = _build_graph(monkeypatch)
    config = {
        "configurable": {"thread_id": "c1-no-override"},
        "recursion_limit": _RECURSION_LIMIT,
    }

    # review_status=None (not needs_attention) so human_review releases the
    # carousel to Final Guard without requiring an override; the FAILED
    # critique then makes Final Guard the blocking gate.
    state = _complete_visual_state(review_status=None)

    with pytest.raises(_HumanReviewReached):
        graph.invoke(state, config=config)

    # The graph re-entered human_review (Final Guard routed back) and never
    # reached content_writer. If the override channel declaration had
    # accidentally satisfied the gate with a stale/default value, the graph
    # would have terminated at content_writer instead.


# ---------------------------------------------------------------------------
# I1 regression: rejected_asset_decisions survives human_review -> asset_resolver.
# ---------------------------------------------------------------------------


def test_rejected_asset_decisions_survive_into_asset_resolver(monkeypatch, tmp_path):
    """I1 round-trip through the REAL graph.

    On the image-rejection route human_review writes
    ``rejected_asset_decisions``. The key MUST survive LangGraph's state-merge
    so a downstream asset-resolver consumer can read the human's rejection
    rationale. Before the ``AgentState`` declaration the write was dropped and
    the resolver read ``None``.
    """
    monkeypatch.chdir(tmp_path)
    _install_noop_chain(monkeypatch)

    rejection = {"asset-1": {"reason": "wrong composition", "page_id": "page-1"}}
    monkeypatch.setattr(
        "src.nodes.node_q_human_review.interrupt",
        lambda _payload: {"reject_assets": rejection, "feedback": "bad image"},
    )

    # asset_resolver is traversed twice: once during the normal visual chain
    # (before human_review, where the key is absent) and once after human_review
    # routes back via reject_assets (where the key MUST be present). Capture
    # the key on each call and stop the graph on the second call.
    captures: list[dict] = []

    def asset_resolver_capture(state, **_kwargs):
        captures.append({"rejected_asset_decisions": state.get("rejected_asset_decisions")})
        if len(captures) == 2:
            raise _AssetResolverReached(state)
        return {}

    monkeypatch.setattr(graph_module.nodes, "asset_resolver_node", asset_resolver_capture)

    graph = _build_graph(monkeypatch)
    config = {
        "configurable": {"thread_id": "i1-rejection"},
        "recursion_limit": _RECURSION_LIMIT,
    }

    # Passing critique so the override rule is irrelevant; human_review reaches
    # the reject_assets branch regardless of critique status.
    state = _complete_visual_state(
        review_status=None,
        visual_critique=_passed_critique(),
    )

    with pytest.raises(_AssetResolverReached):
        graph.invoke(state, config=config)

    # The pre-human-review traversal saw no rejection decisions (key absent on
    # the first pass). The post-human-review traversal received the exact dict
    # human_review wrote -- before the declaration this read back as None.
    assert len(captures) == 2
    assert captures[0]["rejected_asset_decisions"] is None
    assert captures[1]["rejected_asset_decisions"] == rejection
