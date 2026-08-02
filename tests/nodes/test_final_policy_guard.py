"""Task 15: rebuilt Final Policy Guard tests for the ``llm_scene_v3`` path.

The Final Guard hard-gates on every QA / hash / asset-security / R2 /
ContentLock attestation. It may accept an aesthetic override (a human-overridden
``visual_needs_attention``) but NEVER a hard-QA override.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.nodes.node_q_01_final_policy_guard import (
    final_policy_guard_node,
    route_after_final_guard,
    validate_final_policy,
)
from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.content_atoms import ContentAtom, ContentAtomSet, sha256_text
from src.schemas.content_lock import ContentLock


# ---------------------------------------------------------------------------
# ContentLock schema (Task 15 Step 4)
# ---------------------------------------------------------------------------

_LOCK_FIELDS = {
    "focus_keyword": "分区护肤",
    "topic": "t", "topic_id": "tid", "angle": "a", "angle_id": "aid",
    "target_group": "tg", "core_pain": "cp",
    "title": "title", "cover_copy": "cc", "first_screen_promise": "fsc",
    "content": "content body",
    "hashtags": ["护肤", "通勤"],
    "content_atom_set_sha256": "a" * 64,
    "canonical_sha256": "b" * 64,
}


def test_content_lock_drops_storyboards_uses_tuple_hashtags_and_atom_hash():
    lock = ContentLock.model_validate(_LOCK_FIELDS)
    assert not hasattr(lock, "storyboards")
    assert isinstance(lock.hashtags, tuple)
    assert lock.hashtags == ("护肤", "通勤")
    assert lock.content_atom_set_sha256 == "a" * 64
    with pytest.raises(ValidationError):
        lock.title = "other"
    serialized = lock.model_dump(mode="json")
    assert isinstance(serialized["hashtags"], list)
    assert "storyboards" not in serialized


def test_content_lock_rejects_storyboards_extra_and_requires_atom_hash():
    with pytest.raises(ValidationError):
        ContentLock.model_validate({**_LOCK_FIELDS, "storyboards": []})
    broken = dict(_LOCK_FIELDS)
    del broken["content_atom_set_sha256"]
    with pytest.raises(ValidationError):
        ContentLock.model_validate(broken)


# ---------------------------------------------------------------------------
# Final Guard state fixtures
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
from src.schemas.content_atoms import canonical_sha256 as _canonical_sha256

_ATOM_SHA = _canonical_sha256([atom.model_dump(mode="json") for atom in _ATOMS])
_ATOM_SET = ContentAtomSet(atoms=_ATOMS, canonical_sha256=_ATOM_SHA)


def _asset_item(
    *,
    directive_id: str = "dir-1",
    security_status: str = "approved",
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
        human_decision="pending",
        run_id="run-1",
        transaction_id="txn-1",
        internal_provenance={},
    )


def _publish_package(**overrides) -> dict:
    package = {
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
    package.update(overrides)
    return package


def _design_qa(passed: bool = True, *, design_sha: str = _ATOM_SHA):
    return SimpleNamespace(
        passed=passed,
        issues=() if passed else (SimpleNamespace(rule="x", message="m", repair_instruction="r", page_id="page-1"),),
        design_plan_sha256=design_sha,
        content_coverage_attestation=True,
        family_attestation=True,
        asset_binding_attestation=True,
    )


def _render_qa(passed: bool = True, *, render_sha: str = _ATOM_SHA):
    return SimpleNamespace(
        passed=passed,
        issues=() if passed else (SimpleNamespace(rule="x", message="m", repair_instruction="r", page_id="page-1"),),
        render_manifest_sha256=render_sha,
        content_attestation=True,
        geometry_attestation=True,
        asset_attestation=True,
    )


def _visual_critique(*, passed: bool = True, atom_sha: str = _ATOM_SHA):
    return SimpleNamespace(
        passed=passed,
        content_atom_set_sha256=atom_sha,
        direction_plan_sha256=atom_sha,
        design_plan_sha256=atom_sha,
        render_manifest_sha256=atom_sha,
        revision_round=0 if passed else 2,
        revision_instructions=() if passed else ("fix composition",),
    )


def _complete_state(**overrides) -> dict:
    """A complete, approvable post-human-review state for the v3 path."""
    base = {
        "publish_package": _publish_package(),
        "review_status": "approved",
        "visual_aesthetic_override": None,
        "content_atom_set": _ATOM_SET,
        "visual_direction_plan": SimpleNamespace(
            template_family="soft_pink",
            content_atom_set_sha256=_ATOM_SHA,
            asset_directives=(SimpleNamespace(directive_id="dir-1", required=True),),
        ),
        "asset_manifest": AssetManifest(items=(_asset_item(),)),
        "carousel_design_plan": SimpleNamespace(content_atom_set_sha256=_ATOM_SHA),
        "design_plan_qa_result": _design_qa(),
        "render_manifest": SimpleNamespace(content_atom_set_sha256=_ATOM_SHA),
        "render_qa_result": _render_qa(),
        "visual_critique": _visual_critique(),
        "r2_output": SimpleNamespace(
            compliance_audit=SimpleNamespace(block_publish=False),
        ),
        "unresolved_optional_assets": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Approve path
# ---------------------------------------------------------------------------


def test_final_policy_guard_approves_complete_approved_state():
    result = final_policy_guard_node(_complete_state())
    assert result["final_policy_issues"] == []
    assert route_after_final_guard(result) == "content_writer"


def test_validate_final_policy_matches_node_output():
    state = _complete_state()
    assert validate_final_policy(state) == final_policy_guard_node(state)["final_policy_issues"]


def test_final_policy_guard_requires_publish_package():
    with pytest.raises(ValueError, match="publish_package"):
        final_policy_guard_node({})


# ---------------------------------------------------------------------------
# Human approval gate
# ---------------------------------------------------------------------------


def test_final_policy_guard_rejects_when_not_approved():
    state = _complete_state(review_status="pending")
    result = final_policy_guard_node(state)
    rules = {issue["rule_id"] for issue in result["final_policy_issues"]}
    assert "human_review_not_approved" in rules
    assert route_after_final_guard(result) == "human_review"


# ---------------------------------------------------------------------------
# Hard QA: design_plan_qa / render_qa (never overridable)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("override", [None, True])
def test_final_policy_guard_rejects_failed_design_plan_qa_even_with_override(override):
    state = _complete_state(
        design_plan_qa_result=_design_qa(passed=False),
        visual_aesthetic_override=override,
    )
    result = final_policy_guard_node(state)
    rules = {issue["rule_id"] for issue in result["final_policy_issues"]}
    assert "design_plan_qa_not_passed" in rules
    assert route_after_final_guard(result) == "human_review"


def test_final_policy_guard_rejects_missing_design_plan_qa():
    state = _complete_state(design_plan_qa_result=None)
    result = final_policy_guard_node(state)
    rules = {issue["rule_id"] for issue in result["final_policy_issues"]}
    assert "design_plan_qa_missing" in rules


@pytest.mark.parametrize("override", [None, True])
def test_final_policy_guard_rejects_failed_render_qa_even_with_override(override):
    state = _complete_state(
        render_qa_result=_render_qa(passed=False),
        visual_aesthetic_override=override,
    )
    result = final_policy_guard_node(state)
    rules = {issue["rule_id"] for issue in result["final_policy_issues"]}
    assert "render_qa_not_passed" in rules


def test_final_policy_guard_rejects_missing_render_qa():
    state = _complete_state(render_qa_result=None)
    result = final_policy_guard_node(state)
    rules = {issue["rule_id"] for issue in result["final_policy_issues"]}
    assert "render_qa_missing" in rules


# ---------------------------------------------------------------------------
# Content hash binding (ContentLock structural binding)
# ---------------------------------------------------------------------------


def test_final_policy_guard_rejects_missing_content_atom_set():
    state = _complete_state(content_atom_set=None)
    result = final_policy_guard_node(state)
    rules = {issue["rule_id"] for issue in result["final_policy_issues"]}
    assert "content_atom_set_missing" in rules


def test_final_policy_guard_rejects_content_hash_binding_mismatch():
    drifted = "c" * 64
    state = _complete_state(
        carousel_design_plan=SimpleNamespace(content_atom_set_sha256=drifted),
    )
    result = final_policy_guard_node(state)
    rules = {issue["rule_id"] for issue in result["final_policy_issues"]}
    assert "content_lock_binding_mismatch" in rules


# ---------------------------------------------------------------------------
# Asset security
# ---------------------------------------------------------------------------


def test_final_policy_guard_rejects_security_rejected_asset():
    state = _complete_state(
        asset_manifest=AssetManifest(items=(_asset_item(security_status="rejected"),))
    )
    result = final_policy_guard_node(state)
    rules = {issue["rule_id"] for issue in result["final_policy_issues"]}
    assert "asset_security_rejected" in rules


def test_final_policy_guard_rejects_unresolved_required_asset():
    state = _complete_state(asset_manifest=AssetManifest(items=()))
    result = final_policy_guard_node(state)
    rules = {issue["rule_id"] for issue in result["final_policy_issues"]}
    assert "required_asset_unresolved" in rules


# ---------------------------------------------------------------------------
# R2 attestation
# ---------------------------------------------------------------------------


def test_final_policy_guard_rejects_blocking_r2():
    state = _complete_state(
        r2_output=SimpleNamespace(
            compliance_audit=SimpleNamespace(block_publish=True)
        )
    )
    result = final_policy_guard_node(state)
    rules = {issue["rule_id"] for issue in result["final_policy_issues"]}
    assert "r2_compliance_blocked" in rules


def test_final_policy_guard_rejects_missing_r2():
    state = _complete_state(r2_output=None)
    result = final_policy_guard_node(state)
    rules = {issue["rule_id"] for issue in result["final_policy_issues"]}
    assert "r2_compliance_missing" in rules


# ---------------------------------------------------------------------------
# ContentLock attestation
# ---------------------------------------------------------------------------


def test_final_policy_guard_rejects_when_content_lock_cannot_be_built():
    state = _complete_state(
        publish_package=_publish_package(title="")  # missing required lock field
    )
    result = final_policy_guard_node(state)
    rules = {issue["rule_id"] for issue in result["final_policy_issues"]}
    assert "content_lock_invalid" in rules


# ---------------------------------------------------------------------------
# Aesthetic override rule (allowed) vs hard-QA override (never)
# ---------------------------------------------------------------------------


def test_final_policy_guard_accepts_aesthetic_override_for_failed_critique():
    state = _complete_state(
        visual_critique=_visual_critique(passed=False),
        visual_aesthetic_override=True,
    )
    result = final_policy_guard_node(state)
    rules = {issue["rule_id"] for issue in result["final_policy_issues"]}
    assert "visual_critique_not_overridden" not in rules
    assert route_after_final_guard(result) == "content_writer"


def test_final_policy_guard_rejects_failed_critique_without_override():
    state = _complete_state(
        visual_critique=_visual_critique(passed=False),
        visual_aesthetic_override=False,
    )
    result = final_policy_guard_node(state)
    rules = {issue["rule_id"] for issue in result["final_policy_issues"]}
    assert "visual_critique_not_overridden" in rules
    assert route_after_final_guard(result) == "human_review"


def test_final_policy_guard_hard_qa_failure_is_not_overridable_by_aesthetic():
    """Aesthetic override must not mask a hard-QA failure."""
    state = _complete_state(
        design_plan_qa_result=_design_qa(passed=False),
        render_qa_result=_render_qa(passed=False),
        visual_critique=_visual_critique(passed=False),
        visual_aesthetic_override=True,
    )
    result = final_policy_guard_node(state)
    rules = {issue["rule_id"] for issue in result["final_policy_issues"]}
    assert "design_plan_qa_not_passed" in rules
    assert "render_qa_not_passed" in rules
    # The aesthetic override did NOT silence the critique gate either when a
    # hard QA already failed (the whole state is rejected).
    assert route_after_final_guard(result) == "human_review"


# ---------------------------------------------------------------------------
# Policy text scan (retained)
# ---------------------------------------------------------------------------


def test_final_policy_guard_scans_unsafe_publish_copy():
    state = _complete_state(publish_package=_publish_package(title="保证立即见效"))
    result = final_policy_guard_node(state)
    rules = {issue["rule_id"] for issue in result["final_policy_issues"]}
    assert "guaranteed_outcome" in rules
    assert route_after_final_guard(result) == "human_review"
