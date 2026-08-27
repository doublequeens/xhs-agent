"""The v4 Human Review node exposes only the bounded intent seam."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.review.v4_decisions import HumanReviewDecisionError
from src.review.v4_workspace import build_review_workspace
from src.schemas.v4.review import HumanReviewIntentV4

from tests.review.test_v4_workspace import _inputs


def _state(inputs, workspace, *, package=None):
    return {
        "review_workspace_inputs_v4": inputs,
        "review_workspace": workspace,
        "publish_package": package or inputs.content_lock.model_dump(mode="python"),
        # A caller cannot steer this node by presenting a stale route/status.
        "route": "asset_resolver",
        "review_status": "approved",
    }


def test_node_interrupt_payload_is_bounded_and_approval_route_is_derived(tmp_path, monkeypatch):
    from src.nodes.v4 import human_review as module

    inputs = _inputs(tmp_path)
    workspace = build_review_workspace(inputs)
    captured = {}

    def fake_interrupt(payload):
        captured.update(payload)
        return {"action": "APPROVE"}

    monkeypatch.setattr(module, "interrupt", fake_interrupt)
    result = module.human_review_node(
        _state(inputs, workspace),
        clock=lambda: "2026-08-26T00:00:00Z",
        decision_id_factory=lambda: "node-decision",
    )

    assert result["route"] == "final_policy_guard"
    assert result["review_route"] == "final_policy_guard"
    assert captured["kind"] == "v4_human_review"
    assert captured["workspace_index"] == "review/index.html"
    assert captured["q4"]["passed"] is True
    assert "route" not in captured
    assert all("/" not in asset_id for asset_id in captured["asset_ids"])


def test_node_rejects_untrusted_path_only_or_missing_external_reference(tmp_path, monkeypatch):
    from src.nodes.v4 import human_review as module

    inputs = _inputs(tmp_path)
    workspace = build_review_workspace(inputs)
    monkeypatch.setattr(module, "interrupt", lambda payload: {"action": "APPROVE"})
    with pytest.raises(HumanReviewDecisionError, match="reference"):
        module.human_review_node(
            _state(inputs, replace(workspace, reference=None)),
            clock=lambda: "2026-08-26T00:00:00Z",
            decision_id_factory=lambda: "missing-ref",
        )
    with pytest.raises(HumanReviewDecisionError, match="reference"):
        module.human_review_node(
            {
                "artifact_paths": inputs.artifact_paths,
                "review_inputs_v4": inputs,
            },
            clock=lambda: "2026-08-26T00:00:00Z",
            decision_id_factory=lambda: "path-only",
        )


def test_node_visible_copy_resume_returns_r2_patch_and_clears_lock(tmp_path, monkeypatch):
    from src.nodes.v4 import human_review as module

    inputs = _inputs(tmp_path)
    workspace = build_review_workspace(inputs)
    package = inputs.content_lock.model_dump(mode="python")
    monkeypatch.setattr(
        module,
        "interrupt",
        lambda payload: {
            "action": "VISIBLE_COPY_EDIT",
            "visible_copy_payload": '{"title":"节点编辑后的标题"}',
        },
    )
    result = module.human_review_node(
        _state(inputs, workspace, package=package),
        clock=lambda: "2026-08-26T00:00:00Z",
        decision_id_factory=lambda: "node-copy-edit",
    )
    assert result["route"] == "r2_compliance"
    assert result["publish_package"]["title"] == "节点编辑后的标题"
    assert result["content_lock"] is None
    assert result["content_atom_set"] is None


def test_node_source_has_no_v3_human_review_import_or_mutable_route_trust():
    from pathlib import Path

    source = Path(__file__).resolve().parents[3] / "src" / "nodes" / "v4" / "human_review.py"
    text = source.read_text(encoding="utf-8")
    assert "node_q_human_review" not in text
    assert "review_status" not in text
    assert "state.get(\"route\")" not in text
