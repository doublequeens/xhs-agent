"""Task 15: unified dynamic-visual Human Review routing tests.

The ``llm_scene_v3`` Human Review is the single unified human gate after the
multimodal critic. It routes approvals / edits / rejections to one of four
registered nodes via ``state["review_route"]`` and clears the right downstream
visual artifacts for each route.
"""

from __future__ import annotations

import hashlib

import pytest
from types import SimpleNamespace

from src.nodes.node_q_human_review import (
    human_review_node,
    invalidated_visual_artifacts,
    route_after_human_review,
)
from src.schemas.assets import (
    AssetManifest,
    AssetManifestItem,
    UnresolvedOptionalAsset,
)
from src.schemas.content_atoms import ContentAtom, ContentAtomSet, sha256_text


# ---------------------------------------------------------------------------
# State fixtures
# ---------------------------------------------------------------------------

_ATOMS = (
    ContentAtom(atom_id="title-001", text="作息调整记录", role="title", sha256=sha256_text("作息调整记录")),
    ContentAtom(atom_id="cover-001", text="先看懂作息", role="cover", sha256=sha256_text("先看懂作息")),
    ContentAtom(atom_id="paragraph-001", text="记录每天的作息变化", role="paragraph", sha256=sha256_text("记录每天的作息变化")),
)
_ATOM_SET = ContentAtomSet(
    atoms=_ATOMS,
    canonical_sha256=__import__(
        "src.schemas.content_atoms", fromlist=["canonical_sha256"]
    ).canonical_sha256([atom.model_dump(mode="json") for atom in _ATOMS]),
)


def _directive(*, required: bool = True, directive_id: str = "dir-1"):
    return SimpleNamespace(directive_id=directive_id, required=required, page_id="page-1")


def _direction_plan(directives=(_directive(),)):
    """A lightweight direction-plan stub.

    Routing tests exercise the review node's routing/clearing logic, not the
    visual-contract validators (covered by Tasks 7-14). The node only reads
    ``asset_directives`` (for the required-asset gate) and a few summary
    fields, so a SimpleNamespace stub is sufficient and keeps these tests
    independent of the heavy VisualDirectionPlan contract.
    """
    return SimpleNamespace(
        template_family="soft_pink",
        page_count=5,
        art_direction="calm editorial",
        asset_directives=tuple(directives),
    )


def _asset_item(
    *,
    directive_id: str = "dir-1",
    security_status: str = "approved",
    human_decision: str = "pending",
    asset_id: str = "asset-1",
) -> AssetManifestItem:
    return AssetManifestItem(
        asset_id=asset_id,
        directive_id=directive_id,
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
        security_status=security_status,
        human_decision=human_decision,
        run_id="run-1",
        transaction_id="txn-1",
        internal_provenance={},
    )


def _narrative_plan() -> dict:
    beat = {
        "beat_id": "save",
        "kind": "summary",
        "purpose": "保存调整清单",
    }
    return {
        "narrative_form": "reflective_editorial",
        "beats": [
            {"beat_id": "hook", "kind": "hook", "purpose": "建立阅读承诺"},
            {"beat_id": "scene", "kind": "scene", "purpose": "呈现作息场景"},
            {"beat_id": "steps", "kind": "steps", "purpose": "给出调整步骤"},
            beat,
        ],
        "saveable_beat": beat,
        "closing_mode": "none",
    }


def _publish_package(**overrides) -> dict:
    package = {
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
        "subdomain": "skincare",
        "content_intent": "how_to",
        "risk_level": "low",
        "risk_flags": [],
        "profile_version": "beauty-v1",
        "narrative_plan": _narrative_plan(),
        "narrative_form": "reflective_editorial",
        "content_contract": {"first_screen_promise": "先看懂作息，再调整"},
    }
    package.update(overrides)
    return package


def _review_state(**overrides) -> dict:
    """A complete post-critic state arriving at Human Review."""
    base = {
        "publish_package": _publish_package(),
        "content_atom_set": _ATOM_SET,
        "visual_direction_plan": _direction_plan(),
        "asset_manifest": AssetManifest(items=(_asset_item(),)),
        "carousel_design_plan": object(),  # opaque; node passes through / clears
        "design_plan_qa_result": object(),
        "render_manifest": object(),
        "render_qa_result": object(),
        "visual_critique": object(),
        "unresolved_optional_assets": [],
        "review_status": None,
        "review_round": 0,
        "final_policy_issues": [],
        "domain_context": {"profile_version": "beauty-v1"},
    }
    base.update(overrides)
    return base


def _resume(monkeypatch, payload):
    """Monkeypatch the langgraph interrupt with a fixed resume payload."""
    monkeypatch.setattr(
        "src.nodes.node_q_human_review.interrupt", lambda _payload: payload
    )


# ---------------------------------------------------------------------------
# invalidated_visual_artifacts + route_after_human_review
# ---------------------------------------------------------------------------


def test_invalidated_visual_artifacts_clears_the_complete_visual_chain():
    cleared = invalidated_visual_artifacts()

    assert cleared == {
        "content_atom_set": None,
        "visual_direction_plan": None,
        "asset_manifest": None,
        "carousel_design_plan": None,
        "design_plan_qa_result": None,
        "render_manifest": None,
        "render_qa_result": None,
        "visual_critique": None,
    }


def test_route_after_human_review_returns_state_review_route():
    assert route_after_human_review({"review_route": "final_policy_guard"}) == "final_policy_guard"
    assert route_after_human_review({"review_route": "asset_resolver"}) == "asset_resolver"
    assert route_after_human_review({"review_route": "design_reviser"}) == "design_reviser"
    assert route_after_human_review({"review_route": "r2_compliance"}) == "r2_compliance"


# ---------------------------------------------------------------------------
# Step 1: direct approval -> final_policy_guard
# ---------------------------------------------------------------------------


def test_direct_approval_routes_to_final_policy_guard(monkeypatch):
    _resume(monkeypatch, {"approved": True, "feedback": "ok"})
    result = human_review_node(_review_state())

    assert result["review_status"] == "approved"
    assert result["review_route"] == "final_policy_guard"
    assert route_after_human_review(result) == "final_policy_guard"


# ---------------------------------------------------------------------------
# Step 1: layout/color/spacing feedback -> design_reviser
# ---------------------------------------------------------------------------


def test_design_feedback_routes_to_design_reviser(monkeypatch):
    _resume(
        monkeypatch,
        {
            "approved": False,
            "revision_request": {"focus": "spacing", "note": "tighten page 2"},
            "feedback": "fix spacing",
        },
    )
    result = human_review_node(_review_state())

    assert result["review_route"] == "design_reviser"
    assert result["revision_request"]["focus"] == "spacing"
    assert route_after_human_review(result) == "design_reviser"


# ---------------------------------------------------------------------------
# Step 1: visible-text edit -> r2_compliance, clear atoms + visual chain
# ---------------------------------------------------------------------------


def test_visible_text_edit_routes_to_r2_and_clears_all_visual_artifacts(monkeypatch):
    _resume(
        monkeypatch,
        {
            "approved": True,
            "edited_publish_package": {"content": "更新后的可见正文。"},
            "feedback": "edited body",
        },
    )
    state = _review_state()
    result = human_review_node(state)

    assert result["review_route"] == "r2_compliance"
    assert result["review_status"] == "needs_r2_recheck"
    assert route_after_human_review(result) == "r2_compliance"
    # The whole visual chain (atoms + direction + manifest + design + QA +
    # render + critique) is cleared.
    assert result["content_atom_set"] is None
    assert result["visual_direction_plan"] is None
    assert result["asset_manifest"] is None
    assert result["carousel_design_plan"] is None
    assert result["design_plan_qa_result"] is None
    assert result["render_manifest"] is None
    assert result["render_qa_result"] is None
    assert result["visual_critique"] is None
    # The human-edited publish copy is preserved as R2 input.
    assert result["publish_package"]["content"] == "更新后的可见正文。"
    decision = result["decision_output"]
    snapshot = decision.normalized_input.r2_input.content_snapshot
    assert snapshot.revised_md == "更新后的可见正文。"


def test_visible_text_edit_takes_precedence_over_image_rejection(monkeypatch):
    """A text change re-runs the whole chain (including assets), so it wins."""
    _resume(
        monkeypatch,
        {
            "approved": True,
            "edited_publish_package": {"title": "新的标题"},
            "reject_assets": {"asset-1": "replacement"},
        },
    )
    result = human_review_node(_review_state())

    assert result["review_route"] == "r2_compliance"


# ---------------------------------------------------------------------------
# Step 1: image rejection -> asset_resolver, preserve atoms + direction
# ---------------------------------------------------------------------------


def test_image_rejection_routes_to_asset_resolver_and_preserves_atoms(monkeypatch):
    _resume(
        monkeypatch,
        {
            "approved": False,
            "reject_assets": {"asset-1": "wrong tone"},
            "feedback": "replace image",
        },
    )
    direction_plan = _direction_plan()
    state = _review_state(
        content_atom_set=_ATOM_SET, visual_direction_plan=direction_plan
    )
    result = human_review_node(state)

    assert result["review_route"] == "asset_resolver"
    assert route_after_human_review(result) == "asset_resolver"
    # Atoms and direction are preserved (the node does NOT write them back, so
    # they are absent from the return dict and LangGraph keeps the state value).
    assert "content_atom_set" not in result
    assert "visual_direction_plan" not in result
    # Manifest / design / render / critique are cleared.
    assert result["asset_manifest"] is None
    assert result["carousel_design_plan"] is None
    assert result["design_plan_qa_result"] is None
    assert result["render_manifest"] is None
    assert result["render_qa_result"] is None
    assert result["visual_critique"] is None


# ---------------------------------------------------------------------------
# Step 1: visual_needs_attention requires explicit aesthetic override
# ---------------------------------------------------------------------------


def test_visual_needs_attention_blocks_approval_without_override(monkeypatch):
    _resume(monkeypatch, {"approved": True, "feedback": "ship it"})
    state = _review_state(review_status="visual_needs_attention")
    result = human_review_node(state)

    # No explicit override -> cannot approve; route back to design_reviser.
    assert result["review_route"] == "design_reviser"
    assert result["review_status"] != "approved"


def test_visual_needs_attention_approves_with_explicit_override(monkeypatch):
    _resume(
        monkeypatch,
        {"approved": True, "aesthetic_override": True, "feedback": "accept look"},
    )
    state = _review_state(review_status="visual_needs_attention")
    result = human_review_node(state)

    assert result["review_route"] == "final_policy_guard"
    assert result["review_status"] == "approved"
    assert result["visual_aesthetic_override"] is True


# ---------------------------------------------------------------------------
# Step 1: cannot approve security-rejected or unresolved required asset
# ---------------------------------------------------------------------------


def test_cannot_approve_security_rejected_asset(monkeypatch):
    _resume(monkeypatch, {"approved": True, "feedback": "ok"})
    state = _review_state(
        asset_manifest=AssetManifest(
            items=(_asset_item(security_status="rejected"),)
        )
    )
    with pytest.raises(ValueError, match="security.*reject"):
        human_review_node(state)


def test_cannot_approve_unresolved_required_asset(monkeypatch):
    _resume(monkeypatch, {"approved": True, "feedback": "ok"})
    # Required directive present, but manifest does not cover it.
    state = _review_state(
        visual_direction_plan=_direction_plan(directives=(_directive(required=True),)),
        asset_manifest=AssetManifest(items=()),
    )
    with pytest.raises(ValueError, match="unresolved.*required"):
        human_review_node(state)


def test_optional_unresolved_asset_does_not_block_approval(monkeypatch):
    _resume(monkeypatch, {"approved": True, "feedback": "ok"})
    state = _review_state(
        unresolved_optional_assets=[
            UnresolvedOptionalAsset(
                directive_id="dir-opt",
                page_id="page-1",
                reason="no candidate",
            ).model_dump(mode="json")
        ]
    )
    result = human_review_node(state)

    assert result["review_route"] == "final_policy_guard"
    assert result["review_status"] == "approved"


# ---------------------------------------------------------------------------
# Step 1: Human Review is the unified gate (no asset-specific interrupt)
# ---------------------------------------------------------------------------


def test_human_review_interrupt_is_the_unified_gate(monkeypatch):
    """The node interrupts exactly once with a publish_review payload that
    surfaces the full visual + asset + critique context (no per-asset gate)."""
    captured = {}

    def fake_interrupt(payload):
        captured.update(payload)
        return {"approved": True}

    monkeypatch.setattr("src.nodes.node_q_human_review.interrupt", fake_interrupt)
    human_review_node(_review_state())

    assert captured["kind"] == "publish_review"
    # The unified payload surfaces every artifact the human needs to decide.
    for key in (
        "publish_package",
        "render_manifest",
        "asset_manifest",
        "visual_critique",
        "design_plan_qa_result",
        "render_qa_result",
        "unresolved_optional_assets",
        "review_status",
    ):
        assert key in captured, f"unified review payload missing {key}"
