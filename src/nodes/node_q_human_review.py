from langgraph.types import interrupt

from src.schemas import DecisionOutput, DecisionTrace, NormalizedInput, R2ContentSnapShoot, R2Input, RevisionMeta
from src.schemas import AgentState
from src.nodes.publish_patch import (
    enforce_publish_package_title_length,
    extract_storyboard_visible_text,
    merge_publish_package,
)


def _get_value(payload, key, default=None):
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


def _build_risk_context(state: AgentState, publish_package: dict) -> dict:
    domain_context = state.get("domain_context", {}) or {}
    return {
        "domain": publish_package.get("domain"),
        "subdomain": publish_package.get("subdomain"),
        "content_intent": publish_package.get("content_intent"),
        "risk_level": publish_package.get("risk_level"),
        "risk_flags": list(publish_package.get("risk_flags") or []),
        "profile_version": publish_package.get("profile_version") or domain_context.get("profile_version"),
    }


def _matched_policy_rules(state: AgentState) -> list[str]:
    r2_output = state.get("r2_output")
    audit = _get_value(r2_output, "compliance_audit", {})
    return list(_get_value(audit, "matched_policy_rules", []) or [])


def _serialized_evidence_items(state: AgentState) -> list[dict]:
    serialized = []
    for topic_id, brief in (state.get("evidence_briefs") or {}).items():
        for item in list(_get_value(brief, "items", []) or []):
            payload = (
                item.model_dump(mode="json")
                if hasattr(item, "model_dump")
                else dict(item)
            )
            serialized.append({"topic_id": topic_id, **payload})
    return serialized


def _storyboard_signature(storyboards) -> list[dict]:
    return extract_storyboard_visible_text(storyboards)


def _visible_text_signature(publish_package: dict) -> dict:
    return {
        "title": str(publish_package.get("title") or ""),
        "content": str(publish_package.get("content") or ""),
        "cover_copy": str(publish_package.get("cover_copy") or ""),
        "hashtags": [str(item) for item in list(publish_package.get("hashtags") or [])],
        "storyboards": _storyboard_signature(publish_package.get("storyboards")),
    }


def _has_visible_text_edits(previous_package: dict, current_package: dict) -> bool:
    return _visible_text_signature(previous_package) != _visible_text_signature(current_package)


def _build_r2_recheck_decision(state: AgentState, publish_package: dict, review_round: int) -> DecisionOutput:
    r2_output = state.get("r2_output")
    previous_snapshot = getattr(r2_output, "content_snapshot", None)
    previous_revision_meta = getattr(r2_output, "revision_meta", None)

    decision_output = state.get("decision_output")
    if previous_snapshot is None and decision_output is not None:
        normalized_input = getattr(decision_output, "normalized_input", None)
        previous_r2_input = getattr(normalized_input, "r2_input", None)
        previous_snapshot = getattr(previous_r2_input, "content_snapshot", None)
        previous_revision_meta = getattr(previous_r2_input, "revision_meta", None) or previous_revision_meta

    draft_id = (
        getattr(previous_snapshot, "draft_id", None)
        or publish_package.get("draft_id")
        or "human_review_edit"
    )
    previous_revision_id = getattr(previous_revision_meta, "revision_id", None) or "human_review_edit"
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
                    storyboard_visible_text=extract_storyboard_visible_text(
                        publish_package.get("storyboards")
                    ),
                ),
                revision_meta=RevisionMeta(
                    revision_id=previous_revision_id,
                    round=previous_round + 1,
                    diff_summary=previous_diff_summary + [f"human_review_round_{review_round}_edited_visible_text"],
                    next_actions=["rerun_r2_compliance_after_human_edit"],
                ),
                decision_trace=DecisionTrace(
                    source_node="HUMAN_REVIEW",
                    why_this_route=["Visible text changed during human review; rerun R2 compliance."],
                ),
            )
        ),
    )


def route_after_human_review(state: AgentState) -> str:
    review_status = state.get("review_status")
    if review_status == "needs_r2_recheck":
        return "r2_compliance"
    if review_status == "approved":
        return "final_policy_guard"
    raise ValueError("route_after_human_review requires an approved review or R2 recheck.")


def human_review_node(state: AgentState) -> AgentState:
    """
    Pause after assembler so a human can review or edit publish_package.
    Execution continues only after the human explicitly approves it.
    """
    publish_package = state.get("publish_package")
    if not publish_package:
        raise ValueError("human_review_node requires `publish_package` in state.")
    publish_package = enforce_publish_package_title_length(publish_package)

    review_round = state.get("review_round", 0) or 0
    final_policy_issues = list(state.get("final_policy_issues") or [])
    risk_context = _build_risk_context(state, publish_package)
    visible_text_edited = False
    pending_patch = dict(state.get("pending_human_publish_patch") or {})
    pending_replace_storyboards = bool(state.get("pending_human_replace_storyboards"))

    while True:
        review_result = interrupt(
            {
                "kind": "publish_review",
                "message": "请审核 assembler 的结果。只有输入 yes 才会继续进入最终策略守门；若仍有风险会返回这里继续修改。",
                "publish_package": publish_package,
                "final_policy_issues": final_policy_issues,
                "risk_context": risk_context,
                "matched_policy_rules": _matched_policy_rules(state),
                "evidence_items": _serialized_evidence_items(state),
                "review_round": review_round + 1,
            }
        )

        if not isinstance(review_result, dict):
            raise ValueError("Human review resume payload must be a dict.")

        prior_publish_package = publish_package
        edited_publish_package = review_result.get("edited_publish_package")
        if edited_publish_package is not None:
            replace_storyboards = review_result.get("replace_storyboards") is True
            publish_package = merge_publish_package(
                publish_package,
                edited_publish_package,
                replace_storyboards=replace_storyboards,
            )
            publish_package = enforce_publish_package_title_length(publish_package)
            pending_patch = merge_publish_package(
                pending_patch,
                edited_publish_package,
                replace_storyboards=replace_storyboards,
            )
            pending_patch = enforce_publish_package_title_length(pending_patch)
            pending_replace_storyboards = pending_replace_storyboards or replace_storyboards
            visible_text_edited = visible_text_edited or _has_visible_text_edits(
                prior_publish_package,
                publish_package,
            )
            risk_context = _build_risk_context(state, publish_package)

        approved = review_result.get("approved", False)
        feedback = review_result.get("feedback")
        review_round += 1

        if approved:
            if visible_text_edited:
                return {
                    "publish_package": publish_package,
                    "review_status": "needs_r2_recheck",
                    "review_feedback": feedback,
                    "review_round": review_round,
                    "final_policy_issues": [],
                    "pending_human_publish_patch": pending_patch,
                    "pending_human_replace_storyboards": pending_replace_storyboards,
                    "decision_output": _build_r2_recheck_decision(state, publish_package, review_round),
                    "current_node": "HUMAN_REVIEW",
                }
            return {
                "publish_package": publish_package,
                "review_status": "approved",
                "review_feedback": feedback,
                "review_round": review_round,
                "current_node": "HUMAN_REVIEW",
            }
