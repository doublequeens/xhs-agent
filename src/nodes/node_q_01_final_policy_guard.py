from __future__ import annotations

from src.domain import find_policy_violations
from src.schemas import AgentState


def _coerce_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(str(item) for item in value if item is not None)
    return str(value)


def final_policy_guard_node(state: AgentState) -> AgentState:
    publish_package = state.get("publish_package")
    if not publish_package:
        raise ValueError("final_policy_guard_node requires `publish_package` in state.")

    combined_text = "\n".join(
        [
            _coerce_text(publish_package.get("title")),
            _coerce_text(publish_package.get("content")),
            _coerce_text(publish_package.get("cover_copy")),
            _coerce_text(publish_package.get("hashtags")),
        ]
    )
    issues = [
        issue.model_copy(update={"location": "publish_package"}).model_dump(mode="json")
        for issue in find_policy_violations(combined_text)
    ]
    return {
        "final_policy_issues": issues,
        "current_node": "FINAL_POLICY_GUARD",
    }


def route_after_final_guard(state: AgentState) -> str:
    issues = state.get("final_policy_issues") or []
    return "human_review" if issues else "content_writer"
