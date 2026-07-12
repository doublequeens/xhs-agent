from __future__ import annotations

from src.domain import find_policy_violations
from src.schemas import AgentState

_REQUIRED_PUBLISH_FIELDS = (
    "topic_id",
    "topic",
    "angle_id",
    "angle",
    "target_group",
    "core_pain",
    "title",
    "content",
    "hashtags",
)


def _coerce_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(str(item) for item in value if item is not None)
    return str(value)


def _required_field_issues(publish_package: dict) -> list[dict]:
    issues = []
    for field_name in _REQUIRED_PUBLISH_FIELDS:
        value = publish_package.get(field_name)
        if field_name == "hashtags":
            valid = (
                isinstance(value, list)
                and bool(value)
                and all(isinstance(item, str) and item.strip() for item in value)
            )
        else:
            valid = isinstance(value, str) and bool(value.strip())
        if not valid:
            issues.append(
                {
                    "rule_id": "missing_required_field",
                    "matched_text": field_name,
                    "message": f"Missing or invalid required publish_package field: {field_name}",
                    "location": f"publish_package.{field_name}",
                }
            )
    return issues


def _storyboard_visible_text(storyboards) -> list[str]:
    text_fragments = []
    for frame in list(storyboards or []):
        if not isinstance(frame, dict):
            text_fragments.append(str(frame))
            continue
        text_fragments.extend(
            _coerce_text(value)
            for key, value in frame.items()
            if key in {"kicker", "headline", "footer", "question"}
        )
        for field_name in ("wrong_items", "right_items", "checklist_items"):
            text_fragments.extend(_coerce_text(value) for value in frame.get(field_name) or [])
        for step in frame.get("steps") or []:
            if isinstance(step, dict):
                text_fragments.extend(_coerce_text(step.get(key)) for key in ("name", "hint"))
        for condition in frame.get("conditions") or []:
            if isinstance(condition, dict):
                text_fragments.extend(
                    _coerce_text(condition.get(key))
                    for key in ("situation", "recommendation")
                )
    return text_fragments


def final_policy_guard_node(state: AgentState) -> AgentState:
    publish_package = state.get("publish_package")
    if publish_package is None:
        raise ValueError("final_policy_guard_node requires `publish_package` in state.")

    issues = _required_field_issues(publish_package)
    combined_text = "\n".join(
        [
            _coerce_text(publish_package.get("title")),
            _coerce_text(publish_package.get("content")),
            _coerce_text(publish_package.get("cover_copy")),
            _coerce_text(publish_package.get("hashtags")),
            *_storyboard_visible_text(publish_package.get("storyboards")),
        ]
    )
    issues.extend(
        [
            issue.model_copy(update={"location": "publish_package"}).model_dump(mode="json")
            for issue in find_policy_violations(combined_text)
        ]
    )
    return {
        "final_policy_issues": issues,
        "current_node": "FINAL_POLICY_GUARD",
    }


def route_after_final_guard(state: AgentState) -> str:
    issues = state.get("final_policy_issues") or []
    return "human_review" if issues else "content_writer"
