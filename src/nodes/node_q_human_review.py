from langgraph.types import interrupt

from src.schemas import DecisionOutput, DecisionTrace, NormalizedInput, R2ContentSnapShoot, R2Input, RevisionMeta
from src.schemas import AgentState


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


def _merge_publish_package(base: dict, patch: dict, *, replace_storyboards: bool = False) -> dict:
    merged = dict(base)
    for key, value in patch.items():
        if key == "storyboards" and replace_storyboards:
            merged[key] = value
        elif key == "storyboards" and isinstance(value, list) and isinstance(merged.get(key), list):
            merged[key] = _merge_storyboards(merged[key], value)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_publish_package(merged[key], value)
        else:
            merged[key] = value
    return merged


def _merge_storyboards(base: list, patch: list) -> list:
    merged = list(base)
    index_by_frame_id = {
        frame.get("frame_id"): index
        for index, frame in enumerate(merged)
        if isinstance(frame, dict) and frame.get("frame_id")
    }

    for patch_index, patch_frame in enumerate(patch):
        frame_id = patch_frame.get("frame_id") if isinstance(patch_frame, dict) else None
        if frame_id:
            target_index = index_by_frame_id.get(frame_id)
        else:
            target_index = patch_index if patch_index < len(merged) else None

        if target_index is None:
            if frame_id:
                index_by_frame_id[frame_id] = len(merged)
            merged.append(patch_frame)
        elif isinstance(merged[target_index], dict) and isinstance(patch_frame, dict):
            merged[target_index] = _merge_publish_package(merged[target_index], patch_frame)
        else:
            merged[target_index] = patch_frame

    return merged


def _storyboard_signature(storyboards) -> list[tuple[str, str, str]]:
    signature = []
    for frame in list(storyboards or []):
        if not isinstance(frame, dict):
            signature.append((str(frame), "", ""))
            continue
        signature.append(
            (
                str(frame.get("frame_title") or ""),
                str(frame.get("on_image_copy") or ""),
                str(frame.get("narration") or ""),
            )
        )
    return signature


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

    review_round = state.get("review_round", 0) or 0
    final_policy_issues = list(state.get("final_policy_issues") or [])
    risk_context = _build_risk_context(state, publish_package)
    visible_text_edited = False

    while True:
        review_result = interrupt(
            {
                "kind": "publish_review",
                "message": "请审核 assembler 的结果。只有输入 yes 才会继续进入最终策略守门；若仍有风险会返回这里继续修改。",
                "publish_package": publish_package,
                "final_policy_issues": final_policy_issues,
                "risk_context": risk_context,
                "review_round": review_round + 1,
            }
        )

        if not isinstance(review_result, dict):
            raise ValueError("Human review resume payload must be a dict.")

        prior_publish_package = publish_package
        edited_publish_package = review_result.get("edited_publish_package")
        if edited_publish_package is not None:
            publish_package = _merge_publish_package(
                publish_package,
                edited_publish_package,
                replace_storyboards=review_result.get("replace_storyboards") is True,
            )
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
