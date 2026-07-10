from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from src.nodes.publish_patch import extract_storyboard_visible_text
from src.schemas.agent_state import AgentState
from src.schemas.carousel_qa import CarouselQAIssue, CarouselQAResult
from src.schemas.content_contract import ContentContract
from src.schemas.storyboard import StoryboardPayload
from src.schemas.decision import (
    ContentCandidate,
    DecisionOutput,
    DecisionTrace,
    EditorialTasks,
    NormalizedInput,
    R1Input,
    RevisionMeta,
    SingleTask,
)


DECORATIVE_TEXT_FIELDS = (
    "visual_description",
    "scene_background",
    "composition",
    "text_area",
    "image_prompt_cn",
    "image_prompt_en",
)
BANNED_DECORATIVE_TERMS = (
    "卡通",
    "动漫",
    "吉祥物",
    "虚构角色",
    "小蝾螈",
    "装饰插画",
    "ai插画",
    "decorative ai illustration",
    "cartoon",
    "mascot",
)


def _get_value(payload: Any, key: str, default=None):
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


def _location(index: int, field_name: str) -> str:
    return f"storyboards[{index}].{field_name}"


def _issue(
    rule_id: str,
    message: str,
    location_hint: str,
    *,
    frame: Any = None,
    before: str | None = None,
    after_hint: str | None = None,
) -> CarouselQAIssue:
    return CarouselQAIssue(
        rule_id=rule_id,
        message=message,
        location_hint=location_hint,
        frame_id=_get_value(frame, "frame_id") if frame is not None else None,
        before=before,
        after_hint=after_hint,
    )


def _normalized_copy(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _schema_location(location: tuple[Any, ...]) -> str:
    result = ""
    for segment in location:
        if isinstance(segment, int):
            result += f"[{segment}]"
        elif result:
            result += f".{segment}"
        else:
            result = str(segment)
    return result or "storyboards"


def _schema_issues(raw_frames: Any) -> list[CarouselQAIssue]:
    try:
        StoryboardPayload.model_validate({"storyboards": raw_frames})
    except ValidationError as exc:
        issues = []
        for error in exc.errors():
            location = tuple(error["loc"])
            if (
                location == ("storyboards",)
                and error["type"] in {"too_short", "too_long"}
            ):
                # The deterministic card-count rule below produces the more
                # actionable task for this same condition.
                continue
            frame = None
            if (
                isinstance(raw_frames, list)
                and len(location) > 1
                and isinstance(location[1], int)
                and location[1] < len(raw_frames)
            ):
                frame = raw_frames[location[1]]
            issues.append(
                _issue(
                    "storyboard_schema_invalid",
                    f"Storyboard schema validation failed: {error['msg']}",
                    _schema_location(location),
                    frame=frame,
                    before=str(error.get("input") or ""),
                    after_hint="Provide a schema-valid storyboard frame or carousel payload.",
                )
            )
        return issues
    return []


def validate_carousel(
    package: dict,
    contract: ContentContract,
    creator_profile: Any = None,
) -> list[CarouselQAIssue]:
    """Return deterministic, independently actionable carousel contract violations."""
    raw_frames = package.get("storyboards")
    issues = _schema_issues(raw_frames)
    frames = raw_frames if isinstance(raw_frames, list) else []

    allowed_visual_modes = _get_value(creator_profile, "visual_modes")
    if allowed_visual_modes is not None and contract.visual_mode not in allowed_visual_modes:
        issues.append(
            _issue(
                "creator_profile_visual_mode_mismatch",
                "The content contract visual mode is not allowed by the active creator profile.",
                _location(0, "visual_mode"),
                before=contract.visual_mode,
                after_hint="Use a visual mode allowed by the active creator profile.",
            )
        )

    if not 6 <= len(frames) <= 8:
        issues.append(
            _issue(
                "card_count_out_of_range",
                "A carousel must contain six to eight cards.",
                _location(0, "frame_id"),
                before=str(len(frames)),
                after_hint="Provide between 6 and 8 cards.",
            )
        )

    cover = frames[0] if frames else None
    if _get_value(cover, "card_role") != "cover":
        issues.append(
            _issue(
                "cover_role_missing",
                "The first carousel card must have card_role == 'cover'.",
                _location(0, "card_role"),
                frame=cover,
                before=str(_get_value(cover, "card_role") or ""),
                after_hint="Set the first card role to cover.",
            )
        )
    cover_copy = str(_get_value(cover, "on_image_copy") or "")
    if cover_copy != contract.first_screen_promise:
        issues.append(
            _issue(
                "first_screen_promise_mismatch",
                "The first card on-image copy must exactly equal the first-screen promise.",
                _location(0, "on_image_copy"),
                frame=cover,
                before=cover_copy,
                after_hint=contract.first_screen_promise,
            )
        )

    if not any(bool(_get_value(frame, "is_screenshot_asset")) for frame in frames):
        issues.append(
            _issue(
                "missing_screenshot_asset",
                "At least one card must be marked as a screenshot asset.",
                _location(0, "is_screenshot_asset"),
                after_hint="Mark the card that presents the contract screenshot asset.",
            )
        )

    seen_copies: dict[str, int] = {}
    for index, frame in enumerate(frames):
        frame_visual_mode = _get_value(frame, "visual_mode")
        if frame_visual_mode != contract.visual_mode:
            issues.append(
                _issue(
                    "visual_mode_mismatch",
                    "Every card visual mode must match the content contract.",
                    _location(index, "visual_mode"),
                    frame=frame,
                    before=str(frame_visual_mode or ""),
                    after_hint=contract.visual_mode,
                )
            )

        for field_name in DECORATIVE_TEXT_FIELDS:
            field_value = str(_get_value(frame, field_name) or "")
            normalized_field_value = field_value.casefold()
            matched_term = next(
                (term for term in BANNED_DECORATIVE_TERMS if term in normalized_field_value),
                None,
            )
            if matched_term:
                issues.append(
                    _issue(
                        "banned_decorative_term",
                        f"Banned decorative term `{matched_term}` appears in carousel output.",
                        _location(index, field_name),
                        frame=frame,
                        before=field_value,
                        after_hint="Use a text-led information card or a real proof asset instead.",
                    )
                )

        copy = str(_get_value(frame, "on_image_copy") or "")
        normalized_copy = _normalized_copy(copy)
        if normalized_copy:
            first_index = seen_copies.get(normalized_copy)
            if first_index is not None:
                issues.append(
                    _issue(
                        "duplicate_on_image_copy",
                        f"On-image copy duplicates card {first_index + 1}.",
                        _location(index, "on_image_copy"),
                        frame=frame,
                        before=copy,
                        after_hint="Replace with distinct on-image copy.",
                    )
                )
            else:
                seen_copies[normalized_copy] = index

    return issues


def _selected_content_contract(state: AgentState, package: dict) -> ContentContract:
    topic_id = package.get("topic_id")
    matches = [
        topic
        for topic in state.get("trends") or []
        if _get_value(topic, "topic_id") == topic_id
    ]
    if not matches:
        raise ValueError(f"Unknown topic_id: {topic_id}")
    if len(matches) > 1:
        raise ValueError(f"Duplicate topic_id: {topic_id}")

    contract = _get_value(matches[0], "content_contract")
    if contract is None:
        raise ValueError(f"Selected topic {topic_id} requires content_contract")
    return contract if isinstance(contract, ContentContract) else ContentContract.model_validate(contract)


def _build_r1_tasks(issues: list[CarouselQAIssue]) -> EditorialTasks:
    return EditorialTasks(
        mandatory=[
            SingleTask(
                task_id=f"carousel_qa_{issue.rule_id}_{index:03d}",
                source="carousel_qa",
                instruction=issue.message,
                severity="high",
                location_hint=issue.location_hint,
                rationale="Deterministic carousel QA blocked human review.",
                before=issue.before,
                after_hint=issue.after_hint,
            )
            for index, issue in enumerate(issues, start=1)
        ],
        optional=[],
    )


def _build_r1_decision(package: dict, issues: list[CarouselQAIssue]) -> DecisionOutput:
    draft_id = str(package.get("draft_id") or package.get("topic_id") or "carousel_qa")
    r1_input = R1Input(
        content_candidate=ContentCandidate(
            draft_id=draft_id,
            draft_md=str(package.get("content") or ""),
            best_title=str(package.get("title") or ""),
            best_title_id=None,
            safer_title=None,
            safer_title_id=None,
            best_cover_copy=str(package.get("cover_copy") or ""),
            why_win=None,
            topic_id=str(package.get("topic_id") or ""),
            topic=str(package.get("topic") or ""),
            angle_id=str(package.get("angle_id") or ""),
            angle=str(package.get("angle") or ""),
            target_group=str(package.get("target_group") or ""),
            core_pain=str(package.get("core_pain") or ""),
            storyboard_visible_text=extract_storyboard_visible_text(package.get("storyboards")),
        ),
        editorial_tasks=_build_r1_tasks(issues),
        revision_meta=RevisionMeta(
            revision_id=f"carousel_qa_{draft_id}",
            round=1,
            diff_summary=[f"carousel_qa_failed:{issue.rule_id}" for issue in issues],
            next_actions=["repair_carousel_qa_issues", "rerun_carousel_qa"],
        ),
        decision_trace=DecisionTrace(
            source_node="CAROUSEL_QA",
            why_this_route=[
                "Deterministic carousel QA found contract violations; return to R1."
            ],
        ),
    )
    return DecisionOutput(
        next_node="R1_REFLECTOR",
        normalized_input=NormalizedInput(r1_input=r1_input),
    )


def carousel_qa_node(state: AgentState) -> dict:
    package = state.get("publish_package")
    if not isinstance(package, dict):
        raise ValueError("carousel_qa_node requires publish_package as a dict.")

    contract = _selected_content_contract(state, package)
    issues = validate_carousel(package, contract, state.get("creator_profile"))
    result = CarouselQAResult(passed=not issues, issues=issues)
    output = {"carousel_qa_result": result, "current_node": "CAROUSEL_QA"}
    if issues:
        output["decision_output"] = _build_r1_decision(package, issues)
    return output


def route_after_carousel_qa(state: AgentState) -> str:
    result = state.get("carousel_qa_result")
    passed = _get_value(result, "passed")
    if passed is True:
        return "human_review"
    if passed is False:
        return "r1_reflector"
    raise ValueError("route_after_carousel_qa requires carousel_qa_result.")
