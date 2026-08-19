"""Unified dynamic-visual Human Review node (Task 15).

In the ``llm_scene_v3`` graph Human Review is the single human gate after the
multimodal critic. It surfaces the complete rendered carousel, the visual
critique, asset provenance/decisions and every QA attestation, then routes the
human decision to one of four registered nodes through ``state["review_route"]``:

    direct approval       -> final_policy_guard
    visible-text edit      -> r2_compliance  (clears atoms + the whole visual chain)
    image rejection        -> asset_resolver (clears manifest/scene/render/critique,
                                               preserves atoms + direction)
    layout/color/spacing   -> design_reviser

A ``visual_needs_attention`` carousel (the critic's terminal round-2 failure)
cannot be approved without an explicit human aesthetic override. Human Review
can never approve a security-rejected asset or an unresolved required asset.
There is no asset-specific interrupt before this unified gate.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from langgraph.types import interrupt

from src.nodes.publish_patch import (
    enforce_publish_package_title_length,
    has_visible_publish_copy_edits,
    merge_publish_package,
)
from src.schemas import AgentState
from src.schemas.decision import (
    DecisionOutput,
    DecisionTrace,
    NormalizedInput,
    R2ContentSnapShoot,
    R2Input,
    RevisionMeta,
)
from src.utils import required_directive_ids as _required_directive_ids, _value


def invalidated_visual_artifacts() -> dict:
    """Clear the complete dynamic visual chain (used on a visible-text edit).

    A visible-text change re-runs R2 and then re-atomizes, so every downstream
    visual contract is stale: atoms, direction, asset manifest, design plan,
    design-plan QA, render manifest, render QA and the critique.
    """
    return {
        "content_atom_set": None,
        "visual_direction_plan": None,
        "asset_manifest": None,
        "carousel_design_plan": None,
        "design_plan_qa_result": None,
        "render_manifest": None,
        "render_qa_result": None,
        "visual_critique": None,
    }


def _invalidated_render_artifacts() -> dict:
    """Clear render-chain artifacts while preserving atoms + direction.

    Used on image rejection/replacement: the atoms and art direction are still
    valid, but the asset manifest, design plan, QA results, render manifest and
    critique must be rebuilt against the new assets.
    """
    return {
        "asset_manifest": None,
        "carousel_design_plan": None,
        "design_plan_qa_result": None,
        "render_manifest": None,
        "render_qa_result": None,
        "visual_critique": None,
    }


def route_after_human_review(
    state: AgentState,
) -> Literal["r2_compliance", "asset_resolver", "design_reviser", "final_policy_guard"]:
    """Route purely on the ``review_route`` the node wrote into state."""
    return state["review_route"]


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return dict(value)
    return value


def _has_visible_text_edits(previous: dict, current: dict) -> bool:
    return has_visible_publish_copy_edits(previous, current)


def _build_risk_context(state: Mapping[str, Any], publish_package: Mapping[str, Any]) -> dict:
    """Expose the policy context needed for an informed human decision."""
    domain_context = state.get("domain_context") or {}
    return {
        "domain": _value(publish_package, "domain"),
        "subdomain": _value(publish_package, "subdomain"),
        "content_intent": _value(publish_package, "content_intent"),
        "risk_level": _value(publish_package, "risk_level"),
        "risk_flags": list(_value(publish_package, "risk_flags", []) or []),
        "profile_version": _value(publish_package, "profile_version")
        or _value(domain_context, "profile_version"),
    }


def _matched_policy_rules(state: Mapping[str, Any]) -> list[Any]:
    """Serialize the R2 compliance audit's matched policy rules."""
    r2_output = state.get("r2_output")
    audit = _value(r2_output, "compliance_audit", {})
    rules = list(_value(audit, "matched_policy_rules", []) or [])
    return [_json_value(rule) for rule in rules]


def _serialized_evidence_items(state: Mapping[str, Any]) -> list[dict]:
    """Flatten evidence briefs into JSON-ready items for Human Review."""
    serialized = []
    for topic_id, brief in (state.get("evidence_briefs") or {}).items():
        for item in list(_value(brief, "items", []) or []):
            payload = _json_value(item)
            if not isinstance(payload, Mapping):
                payload = {"value": payload}
            serialized.append({"topic_id": topic_id, **dict(payload)})
    return serialized


def _validate_approval_asset_gate(state: Mapping[str, Any]) -> None:
    """Forbid approving a security-rejected or unresolved required asset."""
    asset_manifest = state.get("asset_manifest")
    items = list(_value(asset_manifest, "items", ()) or ()) if asset_manifest is not None else []
    for item in items:
        if _value(item, "security_status") == "rejected":
            raise ValueError(
                "Human Review cannot approve a security-rejected asset; "
                "reject or replace it first."
            )
        if _value(item, "human_decision") == "rejected":
            raise ValueError(
                "Human Review cannot approve a human-rejected asset; "
                "reject or replace it first."
            )
    required_ids = _required_directive_ids(state.get("visual_direction_plan"))
    if required_ids:
        covered = {
            str(_value(item, "directive_id"))
            for item in items
            if _value(item, "directive_id")
        }
        missing = sorted(required_ids - covered)
        if missing:
            raise ValueError(
                "Human Review cannot approve with an unresolved required asset: "
                + ", ".join(missing)
            )


def _atom_set_summary(atom_set: Any) -> dict | None:
    if atom_set is None:
        return None
    atoms = _value(atom_set, "atoms", ()) or ()
    return {
        "canonical_sha256": _value(atom_set, "canonical_sha256"),
        "atom_count": len(atoms),
    }


def _visual_direction_summary(direction_plan: Any) -> dict | None:
    if direction_plan is None:
        return None
    return {
        "template_family": _value(direction_plan, "template_family"),
        "page_count": _value(direction_plan, "page_count"),
        "art_direction": _value(direction_plan, "art_direction"),
    }


def _review_artifacts(state: Mapping[str, Any], publish_package: dict) -> dict:
    return {
        "publish_package": publish_package,
        "final_policy_issues": list(state.get("final_policy_issues") or []),
        "risk_context": _build_risk_context(state, publish_package),
        "matched_policy_rules": _matched_policy_rules(state),
        "evidence_items": _serialized_evidence_items(state),
        "render_manifest": _json_value(state.get("render_manifest")),
        "asset_manifest": _json_value(state.get("asset_manifest")),
        "visual_critique": _json_value(state.get("visual_critique")),
        "design_plan_qa_result": _json_value(state.get("design_plan_qa_result")),
        "render_qa_result": _json_value(state.get("render_qa_result")),
        "unresolved_optional_assets": list(state.get("unresolved_optional_assets") or []),
        "review_status": state.get("review_status"),
        "visual_direction_summary": _visual_direction_summary(state.get("visual_direction_plan")),
        "content_atom_set_summary": _atom_set_summary(state.get("content_atom_set")),
    }


def _build_r2_recheck_decision(
    state: Mapping[str, Any], publish_package: dict, review_round: int
) -> DecisionOutput:
    r2_output = state.get("r2_output")
    previous_snapshot = getattr(r2_output, "content_snapshot", None)
    previous_revision_meta = getattr(r2_output, "revision_meta", None)

    decision_output = state.get("decision_output")
    if previous_snapshot is None and decision_output is not None:
        normalized_input = getattr(decision_output, "normalized_input", None)
        previous_r2_input = getattr(normalized_input, "r2_input", None)
        previous_snapshot = getattr(previous_r2_input, "content_snapshot", None)
        previous_revision_meta = (
            getattr(previous_r2_input, "revision_meta", None)
            or previous_revision_meta
        )

    draft_id = (
        getattr(previous_snapshot, "draft_id", None)
        or publish_package.get("draft_id")
        or "human_review_edit"
    )
    previous_revision_id = (
        getattr(previous_revision_meta, "revision_id", None) or "human_review_edit"
    )
    previous_round = getattr(previous_revision_meta, "round", 0) or 0
    previous_diff_summary = list(getattr(previous_revision_meta, "diff_summary", []) or [])

    return DecisionOutput(
        next_node="R2_COMPLIANCE",
        normalized_input=NormalizedInput(
            r2_input=R2Input(
                content_snapshot=R2ContentSnapShoot(
                    draft_id=draft_id,
                    revised_title=str(publish_package.get("title") or ""),
                    revised_md=str(publish_package.get("content") or ""),
                    topic_id=str(publish_package.get("topic_id") or ""),
                    topic=str(publish_package.get("topic") or ""),
                    angle_id=str(publish_package.get("angle_id") or ""),
                    angle=str(publish_package.get("angle") or ""),
                    target_group=str(publish_package.get("target_group") or ""),
                    core_pain=str(publish_package.get("core_pain") or ""),
                    best_cover_copy=str(publish_package.get("cover_copy") or ""),
                    narrative_plan=publish_package.get("narrative_plan"),
                ),
                revision_meta=RevisionMeta(
                    revision_id=previous_revision_id,
                    round=previous_round + 1,
                    diff_summary=previous_diff_summary
                    + [f"human_review_round_{review_round}_edited_visible_text"],
                    next_actions=["rerun_r2_compliance_after_human_edit"],
                ),
                decision_trace=DecisionTrace(
                    source_node="HUMAN_REVIEW",
                    why_this_route=[
                        "Visible text changed during human review; rerun R2 compliance."
                    ],
                ),
            )
        ),
    )


def _design_revision_request(feedback: str | None, revision_request: Any) -> dict:
    """Normalize a design-feedback revision request for the design reviser."""
    if isinstance(revision_request, Mapping):
        request = dict(revision_request)
    else:
        request = {}
    if feedback and "feedback" not in request:
        request["feedback"] = feedback
    return request


def human_review_node(state: AgentState) -> AgentState:
    """Pause for unified human review, then route via ``state["review_route"]``."""
    publish_package = state.get("publish_package")
    if not isinstance(publish_package, Mapping):
        raise ValueError("human_review_node requires `publish_package` in state.")
    publish_package = enforce_publish_package_title_length(dict(publish_package))

    review_round = int(state.get("review_round", 0) or 0)
    review_status = state.get("review_status")
    needs_attention = review_status == "visual_needs_attention"
    pending_patch = dict(state.get("pending_human_publish_patch") or {})

    visible_text_edited = False

    while True:
        review_result = interrupt(
            {
                "kind": "publish_review",
                "message": (
                    "请审核完整的动态视觉产出。批准后进入最终策略守门；修改可见文字会回到 R2；"
                    "拒绝图片会回到素材解析；布局/配色/间距反馈会回到设计修订。"
                    + (
                        " 视觉批评两轮未通过，需要明确的视觉放行才能批准。"
                        if needs_attention
                        else ""
                    )
                ),
                "review_round": review_round + 1,
                **_review_artifacts(state, publish_package),
            }
        )

        if not isinstance(review_result, Mapping):
            raise ValueError("Human review resume payload must be a dict.")

        # --- apply edits ---
        edited_publish_package = review_result.get("edited_publish_package")
        if edited_publish_package:
            prior_publish_package = publish_package
            publish_package = enforce_publish_package_title_length(
                merge_publish_package(publish_package, dict(edited_publish_package))
            )
            visible_text_edited = visible_text_edited or _has_visible_text_edits(
                prior_publish_package, publish_package
            )
            pending_patch = merge_publish_package(
                pending_patch, dict(edited_publish_package)
            )

        feedback = review_result.get("feedback")
        reject_assets = review_result.get("reject_assets") or None
        revision_request = review_result.get("revision_request") or None
        approved = review_result.get("approved", False)
        aesthetic_override = review_result.get("aesthetic_override", False) is True
        review_round += 1

        # --- route precedence ---

        # 1. A visible-text edit re-runs the whole chain (R2 -> atomizer -> ...).
        if visible_text_edited:
            return {
                "publish_package": publish_package,
                **invalidated_visual_artifacts(),
                "review_status": "needs_r2_recheck",
                "review_route": "r2_compliance",
                "review_feedback": feedback,
                "review_round": review_round,
                "final_policy_issues": [],
                "pending_human_publish_patch": pending_patch,
                "visual_aesthetic_override": None,
                "decision_output": _build_r2_recheck_decision(
                    state, publish_package, review_round
                ),
                "current_node": "HUMAN_REVIEW",
            }

        # 2. Image rejection/replacement -> asset resolver (atoms + direction kept).
        if reject_assets:
            return {
                "publish_package": publish_package,
                **_invalidated_render_artifacts(),
                "review_status": "pending",
                "review_route": "asset_resolver",
                "review_feedback": feedback,
                "review_round": review_round,
                "final_policy_issues": [],
                "rejected_asset_decisions": dict(reject_assets),
                "visual_aesthetic_override": None,
                "current_node": "HUMAN_REVIEW",
            }

        # 3. Layout/color/image/spacing feedback -> design reviser.
        if revision_request:
            return {
                "publish_package": publish_package,
                "review_status": "pending",
                "review_route": "design_reviser",
                "review_feedback": feedback,
                "review_round": review_round,
                "revision_request": _design_revision_request(feedback, revision_request),
                "final_policy_issues": [],
                "visual_aesthetic_override": None,
                "current_node": "HUMAN_REVIEW",
            }

        # 4. Approval (gated).
        if approved:
            _validate_approval_asset_gate(state)
            if needs_attention and not aesthetic_override:
                # Cannot approve a needs-attention carousel without an
                # explicit aesthetic override; route back to the design
                # reviser instead.
                return {
                    "publish_package": publish_package,
                    "review_status": "visual_needs_attention",
                    "review_route": "design_reviser",
                    "review_feedback": feedback or "visual_needs_attention requires explicit override",
                    "review_round": review_round,
                    "revision_request": _design_revision_request(
                        feedback or "visual_needs_attention requires explicit override",
                        None,
                    ),
                    "final_policy_issues": [],
                    "visual_aesthetic_override": None,
                    "current_node": "HUMAN_REVIEW",
                }
            result = {
                "publish_package": publish_package,
                "review_status": "approved",
                "review_route": "final_policy_guard",
                "review_feedback": feedback,
                "review_round": review_round,
                "final_policy_issues": [],
                "pending_human_publish_patch": pending_patch,
                "current_node": "HUMAN_REVIEW",
            }
            if needs_attention and aesthetic_override:
                result["visual_aesthetic_override"] = True
            else:
                result["visual_aesthetic_override"] = None
            return result

        # Not approved and no specific action -> re-loop for another review pass.
        continue
