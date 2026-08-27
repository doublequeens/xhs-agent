"""End-to-end v4 workflow integration: terminals, budget, review flow."""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.types import Command

from src.schemas.v4.revision import VisualExecutionInterrupted

from tests.integration.v4_harness import (
    HarnessStopped,
    V4Harness,
    resume_with_intent,
)


def test_shadow_terminal_never_reaches_content_writer(monkeypatch, tmp_path):
    harness = V4Harness(monkeypatch, tmp_path)
    graph, config = harness.run_until_review_interrupt(
        run_mode="shadow", critic_passes=True
    )
    state = graph.get_state(config)
    assert state.next == ("human_review",)

    values = resume_with_intent(graph, config, {"action": "APPROVE"})

    assert values["current_node"] == "SHADOW_ARTIFACT_WRITER"
    assert harness.content_writer_calls == []
    assert values["review_status"] == "approved"
    assert values["final_policy_guard_passed_v4"] is True
    bundle = Path(values["shadow_bundle_path"])
    assert bundle.parent == harness.shadow_root
    assert (bundle / "shadow-manifest.json").is_file()
    assert not harness.publish_root_sentinel.exists()


def test_production_terminal_reaches_content_writer_with_attestation(
    monkeypatch, tmp_path
):
    harness = V4Harness(monkeypatch, tmp_path)
    graph, config = harness.run_until_review_interrupt(
        run_mode="production", critic_passes=True
    )
    values = resume_with_intent(graph, config, {"action": "APPROVE"})

    assert len(harness.content_writer_calls) == 1
    assert values["current_node"] == "CONTENT_WRITER"
    assert values["final_policy_attestation_v4"].passed is True
    assert values["final_policy_attestation_v4"].action == "APPROVE"


def test_failed_q4_routes_to_revision_and_exhausts_budget_durable_across_resume(
    monkeypatch, tmp_path
):
    harness = V4Harness(monkeypatch, tmp_path)

    # Phase 1: one aesthetic failure consumes the single non-LAYOUT repair;
    # halt before the critic re-evaluates.
    harness._stop_after_failures = 1
    harness._install_stubs(critic_passes=False)
    graph = harness.build()
    config = harness.config()
    with pytest.raises(HarnessStopped):
        graph.invoke(harness.initial_state("shadow"), config)
    state = graph.get_state(config)
    assert len(state.values.get("revision_history_v4") or ()) == 1
    # The budget lives in checkpointed state: resuming must NOT reset it.
    assert state.next == ("visual_critic",)

    # Phase 2: resume on the same thread; the second identical fingerprint
    # exhausts the candidate through the REAL revision node (Task 14
    # semantics: non-LAYOUT layers get exactly one repair).
    harness._stop_after_failures = None
    with pytest.raises(VisualExecutionInterrupted) as exhausted:
        graph.invoke(None, config)
    assert exhausted.value.consumed_budget == 2
    final = graph.get_state(config)
    assert final.values["revision_history_v4"] is not None


def test_request_revision_action_loops_through_typed_revision(monkeypatch, tmp_path):
    harness = V4Harness(monkeypatch, tmp_path)
    graph, config = harness.run_until_review_interrupt(
        run_mode="shadow", critic_passes=True
    )
    # The passed-Q4 world can still receive a human revision request: the
    # typed revision boundary derives the AESTHETIC failure, appends one
    # durable event and re-routes to the critic.  The harness halts at the
    # critic's second evaluation — a real repair would re-render a new
    # revision before re-review.
    harness._stop_after_failures = 1
    with pytest.raises(HarnessStopped):
        resume_with_intent(
            graph,
            config,
            {"action": "REQUEST_REVISION", "feedback": "第二页节奏重复，需要重排。"},
        )
    state = graph.get_state(config)
    values = dict(state.values)
    assert state.next == ("visual_critic",)
    history = values["revision_history_v4"]
    assert len(history) == 1
    assert history[0].target_layer == "AESTHETIC"
    assert values["review_status"] == "revision_requested"
    assert values["route"] == "visual_critic"


def test_visible_copy_edit_routes_to_r2_compliance(monkeypatch, tmp_path):
    harness = V4Harness(monkeypatch, tmp_path)
    graph, config = harness.run_until_review_interrupt(
        run_mode="shadow", critic_passes=True
    )
    original_title = harness.inputs.content_lock.title
    with pytest.raises(HarnessStopped):
        resume_with_intent(
            graph,
            config,
            {
                "action": "VISIBLE_COPY_EDIT",
                "visible_copy_payload": '{"title": "全新标题"}',
            },
        )
    values = dict(graph.get_state(config).values)
    assert values["route"] == "r2_compliance"
    assert values["review_status"] == "needs_r2_recheck"
    assert values["publish_package"]["title"] == "全新标题"
    assert values["publish_package"]["title"] != original_title
