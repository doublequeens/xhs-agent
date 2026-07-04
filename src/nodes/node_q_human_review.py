from langgraph.types import interrupt

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

        edited_publish_package = review_result.get("edited_publish_package")
        if edited_publish_package is not None:
            publish_package = edited_publish_package
            risk_context = _build_risk_context(state, publish_package)

        approved = review_result.get("approved", False)
        feedback = review_result.get("feedback")
        review_round += 1

        if approved:
            return {
                "publish_package": publish_package,
                "review_status": "approved",
                "review_feedback": feedback,
                "review_round": review_round,
                "current_node": "HUMAN_REVIEW",
            }
