from __future__ import annotations

import hashlib
from typing import Any

from pydantic import ValidationError

from src.editorial_carousel.strategy import ASSET_ADAPTER, LAYOUT_FAMILY
from src.nodes.publish_patch import extract_storyboard_visible_text
from src.schemas.agent_state import AgentState
from src.schemas.carousel_qa import CarouselQAIssue, CarouselQAResult
from src.schemas.content_contract import ContentContract
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
from src.schemas.storyboard import CarouselFrame


SAVEABLE_LAYOUTS = frozenset({"saveable_checklist", "saveable_reference"})


def _get_value(payload: Any, key: str, default=None):
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


def _as_list(payload: Any, key: str) -> list[Any]:
    value = _get_value(payload, key, [])
    return list(value) if isinstance(value, (list, tuple)) else []


def _location(index: int, field_name: str) -> str:
    return f"storyboards[{index}].{field_name}"


def _issue(
    rule_id: str,
    message: str,
    location_hint: str,
    *,
    frame: Any = None,
    frame_id: str | None = None,
    before: str | None = None,
    after_hint: str | None = None,
) -> CarouselQAIssue:
    return CarouselQAIssue(
        rule_id=rule_id,
        message=message,
        location_hint=location_hint,
        frame_id=frame_id or (_get_value(frame, "frame_id") if frame is not None else None),
        before=before,
        after_hint=after_hint,
    )


def _schema_location(index: int, location: tuple[Any, ...]) -> str:
    result = f"storyboards[{index}]"
    for segment in location:
        if isinstance(segment, int):
            result += f"[{segment}]"
        else:
            result += f".{segment}"
    return result


def _editorial_schema_audit(
    raw_frames: Any,
) -> tuple[list[CarouselQAIssue], set[int]]:
    if not isinstance(raw_frames, list):
        return (
            [
                _issue(
                    "storyboard_schema_invalid",
                    "Editorial storyboards must be a list of structured frames.",
                    "storyboards",
                    before=str(raw_frames),
                    after_hint="Provide a list of schema-valid CarouselFrame values.",
                )
            ],
            set(),
        )

    issues: list[CarouselQAIssue] = []
    invalid_indexes: set[int] = set()
    for index, raw_frame in enumerate(raw_frames):
        try:
            CarouselFrame.model_validate(raw_frame)
        except ValidationError as exc:
            invalid_indexes.add(index)
            for error in exc.errors():
                issues.append(
                    _issue(
                        "storyboard_schema_invalid",
                        f"Storyboard schema validation failed: {error['msg']}",
                        _schema_location(index, tuple(error["loc"])),
                        frame=raw_frame,
                        before=str(error.get("input") or ""),
                        after_hint="Provide a schema-valid editorial storyboard frame.",
                    )
                )
    return issues, invalid_indexes


def _duplicate_identity_issues(
    frames: list[Any], visual_plan: Any
) -> list[CarouselQAIssue]:
    issues: list[CarouselQAIssue] = []

    def audit(
        values: list[tuple[Any, str, Any]], rule_id: str, message: str
    ) -> None:
        seen: set[Any] = set()
        for value, location, owner in values:
            if value in {None, ""}:
                continue
            if value in seen:
                issues.append(
                    _issue(
                        rule_id,
                        message,
                        location,
                        frame=owner,
                        before=str(value or ""),
                    )
                )
            else:
                seen.add(value)

    planned = _as_list(visual_plan, "frame_plan")
    audit(
        [
            (
                _get_value(frame, "frame_id"),
                f"visual_plan.frame_plan[{index}].frame_id",
                frame,
            )
            for index, frame in enumerate(planned)
        ],
        "duplicate_plan_frame_id",
        "Visual-plan frame IDs must be unique.",
    )
    audit(
        [
            (
                _get_value(frame, "frame_id"),
                _location(index, "frame_id"),
                frame,
            )
            for index, frame in enumerate(frames)
        ],
        "duplicate_storyboard_frame_id",
        "Storyboard frame IDs must be unique.",
    )
    audit(
        [
            (
                _get_value(slot, "slot_id"),
                _location(frame_index, f"visual_slots[{slot_index}].slot_id"),
                frame,
            )
            for frame_index, frame in enumerate(frames)
            for slot_index, slot in enumerate(_as_list(frame, "visual_slots"))
        ],
        "duplicate_storyboard_slot_id",
        "Storyboard visual-slot IDs must be unique across the carousel.",
    )
    audit(
        [
            (
                _get_value(requirement, "slot_id"),
                f"visual_plan.required_assets[{index}].slot_id",
                None,
            )
            for index, requirement in enumerate(
                _as_list(visual_plan, "required_assets")
            )
        ],
        "duplicate_asset_requirement_slot_id",
        "Visual-plan asset requirement slot IDs must be unique.",
    )
    return issues


def _duplicates(values: list[Any]) -> set[Any]:
    seen: set[Any] = set()
    duplicates: set[Any] = set()
    for value in values:
        if value in {None, ""}:
            continue
        if value in seen:
            duplicates.add(value)
        else:
            seen.add(value)
    return duplicates


def _frame_count_issues(frames: list[Any]) -> list[CarouselQAIssue]:
    if 5 <= len(frames) <= 7:
        return []
    return [
        _issue(
            "frame_count_out_of_range",
            "An editorial carousel must contain five to seven frames.",
            "storyboards",
            before=str(len(frames)),
            after_hint="Provide five to seven ordered editorial frames.",
        )
    ]


def _composition_issues(
    frames: list[Any], invalid_indexes: set[int]
) -> list[CarouselQAIssue]:
    issues: list[CarouselQAIssue] = []
    layouts = [str(_get_value(frame, "layout") or "") for frame in frames]
    valid_layouts = [
        layout for index, layout in enumerate(layouts) if index not in invalid_indexes
    ]
    if not invalid_indexes and len(set(valid_layouts)) < 3:
        issues.append(
            _issue(
                "insufficient_layout_variety",
                "An editorial carousel must use at least three distinct layouts.",
                "storyboards",
                before=", ".join(layouts),
                after_hint="Use at least three layout families without changing frame tasks.",
            )
        )

    for index in range(1, len(layouts)):
        if (
            index not in invalid_indexes
            and index - 1 not in invalid_indexes
            and layouts[index]
            and layouts[index] == layouts[index - 1]
        ):
            issues.append(
                _issue(
                    "consecutive_layout_repeat",
                    "Adjacent frames must not repeat the same layout.",
                    _location(index, "layout"),
                    frame=frames[index],
                    before=layouts[index],
                    after_hint="Choose a compatible layout for the same planned task.",
                )
            )

    if not invalid_indexes and not SAVEABLE_LAYOUTS.intersection(valid_layouts):
        issues.append(
            _issue(
                "missing_saveable_frame",
                "The carousel needs at least one standalone saveable frame.",
                "storyboards",
                after_hint="Use saveable_checklist or saveable_reference for one frame.",
            )
        )
    return issues


def _plan_contract_issues(
    frames: list[Any],
    visual_plan: Any,
    invalid_indexes: set[int],
    duplicate_plan_frame_ids: set[Any],
    duplicate_storyboard_frame_ids: set[Any],
) -> list[CarouselQAIssue]:
    issues: list[CarouselQAIssue] = []
    planned_frames = _as_list(visual_plan, "frame_plan")
    allowed_families = {
        str(_get_value(visual_plan, "primary_visual_family") or ""),
        *(str(value) for value in _as_list(visual_plan, "supporting_families")),
    }

    for index, planned in enumerate(planned_frames):
        frame_id = str(_get_value(planned, "frame_id") or "") or None
        layout = _get_value(planned, "layout")
        family = LAYOUT_FAMILY.get(layout)
        if family is not None and family not in allowed_families:
            issues.append(
                _issue(
                    "layout_family_mismatch",
                    f"Layout {layout} belongs to undeclared visual family {family}.",
                    f"visual_plan.frame_plan[{index}].layout",
                    frame_id=frame_id,
                    before=str(layout or ""),
                    after_hint="Declare the family or select a layout from a declared family.",
                )
            )

        if index >= len(frames) or index in invalid_indexes:
            continue
        frame = frames[index]
        actual_frame_id = _get_value(frame, "frame_id")
        planned_frame_id = _get_value(planned, "frame_id")
        if (
            actual_frame_id not in duplicate_storyboard_frame_ids
            and planned_frame_id not in duplicate_plan_frame_ids
            and actual_frame_id != planned_frame_id
        ):
            issues.append(
                _issue(
                    "frame_id_mismatch",
                    "Storyboard frame ID must match the visual plan order.",
                    _location(index, "frame_id"),
                    frame=frame,
                    before=str(_get_value(frame, "frame_id") or ""),
                    after_hint=str(_get_value(planned, "frame_id") or ""),
                )
            )
        if _get_value(frame, "role") != _get_value(planned, "role"):
            issues.append(
                _issue(
                    "frame_role_mismatch",
                    "Each frame must retain its one planned semantic task.",
                    _location(index, "role"),
                    frame=frame,
                    before=str(_get_value(frame, "role") or ""),
                    after_hint=str(_get_value(planned, "role") or ""),
                )
            )
        if _get_value(frame, "layout") != _get_value(planned, "layout"):
            issues.append(
                _issue(
                    "frame_layout_mismatch",
                    "Storyboard frame layout must match its planned layout.",
                    _location(index, "layout"),
                    frame=frame,
                    before=str(_get_value(frame, "layout") or ""),
                    after_hint=str(_get_value(planned, "layout") or ""),
                )
            )
        blocks = _as_list(frame, "content_blocks")
        if not blocks:
            issues.append(
                _issue(
                    "frame_task_missing",
                    "Each frame must contain content for its one planned task.",
                    _location(index, "content_blocks"),
                    frame=frame,
                    after_hint=str(_get_value(planned, "purpose") or ""),
                )
            )

    return issues


def _slot_contract_issues(
    frames: list[Any],
    visual_plan: Any,
    invalid_indexes: set[int],
    duplicate_storyboard_slot_ids: set[Any],
    duplicate_requirement_slot_ids: set[Any],
) -> list[CarouselQAIssue]:
    issues: list[CarouselQAIssue] = []
    planned_frames = _as_list(visual_plan, "frame_plan")
    requirements = _as_list(visual_plan, "required_assets")
    requirements_by_slot = {
        _get_value(requirement, "slot_id"): (index, requirement)
        for index, requirement in enumerate(requirements)
        if _get_value(requirement, "slot_id")
        not in duplicate_requirement_slot_ids
    }

    for frame_index in range(min(len(frames), len(planned_frames))):
        if frame_index in invalid_indexes:
            continue
        frame = frames[frame_index]
        planned = planned_frames[frame_index]
        frame_id = str(_get_value(frame, "frame_id") or "") or None
        layout = _get_value(planned, "layout")
        expected_roles = [str(value) for value in _as_list(planned, "asset_roles")]
        slots = _as_list(frame, "visual_slots")
        actual_roles = [str(_get_value(slot, "role") or "") for slot in slots]

        for slot_index, slot in enumerate(slots):
            semantic_role = str(_get_value(slot, "role") or "")
            location = _location(frame_index, f"visual_slots[{slot_index}].role")
            if slot_index >= len(expected_roles) or semantic_role != expected_roles[slot_index]:
                issues.append(
                    _issue(
                        "semantic_slot_role_mismatch",
                        "Storyboard visual slots must keep semantic roles from the frame plan.",
                        location,
                        frame_id=frame_id,
                        before=semantic_role,
                        after_hint=(
                            expected_roles[slot_index]
                            if slot_index < len(expected_roles)
                            else "Remove the unplanned visual slot."
                        ),
                    )
                )
                continue

            adapter = ASSET_ADAPTER.get((layout, semantic_role))
            if adapter is None:
                issues.append(
                    _issue(
                        "asset_adapter_missing",
                        "No approved semantic-to-catalog asset adapter exists for this slot.",
                        location,
                        frame_id=frame_id,
                        before=f"{layout}:{semantic_role}",
                    )
                )
                continue

            slot_id = _get_value(slot, "slot_id")
            if (
                slot_id in duplicate_storyboard_slot_ids
                or slot_id in duplicate_requirement_slot_ids
            ):
                continue
            indexed_requirement = requirements_by_slot.get(slot_id)
            if indexed_requirement is None:
                issues.append(
                    _issue(
                        "asset_requirement_missing",
                        "Every semantic visual slot needs one plan asset requirement with the same slot_id.",
                        _location(frame_index, f"visual_slots[{slot_index}].slot_id"),
                        frame_id=frame_id,
                        before=str(slot_id or ""),
                    )
                )
                continue

            requirement_index, requirement = indexed_requirement
            expected_concrete_role = adapter[0]
            if _get_value(requirement, "role") != expected_concrete_role:
                issues.append(
                    _issue(
                        "asset_requirement_role_mismatch",
                        "The plan requirement must use the adapter's concrete catalog role and frame layout.",
                        f"visual_plan.required_assets[{requirement_index}].role",
                        frame_id=frame_id,
                        before=str(_get_value(requirement, "role") or ""),
                        after_hint=expected_concrete_role,
                    )
                )
            if _get_value(requirement, "layout") != layout:
                issues.append(
                    _issue(
                        "asset_requirement_layout_mismatch",
                        "The plan requirement layout must match its storyboard frame layout.",
                        f"visual_plan.required_assets[{requirement_index}].layout",
                        frame_id=frame_id,
                        before=str(_get_value(requirement, "layout") or ""),
                        after_hint=str(layout or ""),
                    )
                )

        if len(actual_roles) < len(expected_roles):
            for missing_index in range(len(actual_roles), len(expected_roles)):
                issues.append(
                    _issue(
                        "semantic_slot_role_mismatch",
                        "Storyboard frame is missing a planned semantic visual slot.",
                        _location(
                            frame_index,
                            f"visual_slots[{missing_index}].missing_role[{expected_roles[missing_index]}]",
                        ),
                        frame_id=frame_id,
                        after_hint=expected_roles[missing_index],
                    )
                )
    return issues


def validate_carousel(
    package: dict,
    contract: ContentContract,
    visual_plan: Any,
) -> list[CarouselQAIssue]:
    """Return atomic deterministic violations of the editorial carousel contract."""

    raw_frames = package.get("storyboards")
    frames = raw_frames if isinstance(raw_frames, list) else []
    issues, invalid_indexes = _editorial_schema_audit(raw_frames)
    issues.extend(_frame_count_issues(frames))
    planned_frames = _as_list(visual_plan, "frame_plan")
    if len(planned_frames) != len(frames):
        issues.append(
            _issue(
                "frame_plan_count_mismatch",
                "Visual-plan and storyboard frame counts must match before traversal.",
                "visual_plan.frame_plan",
                before=str(len(planned_frames)),
                after_hint=str(len(frames)),
            )
        )

    identity_issues = _duplicate_identity_issues(frames, visual_plan)
    issues.extend(identity_issues)
    issues.extend(_composition_issues(frames, invalid_indexes))

    duplicate_plan_frame_ids = _duplicates(
        [_get_value(frame, "frame_id") for frame in planned_frames]
    )
    duplicate_storyboard_frame_ids = _duplicates(
        [_get_value(frame, "frame_id") for frame in frames]
    )
    duplicate_storyboard_slot_ids = _duplicates(
        [
            _get_value(slot, "slot_id")
            for frame in frames
            for slot in _as_list(frame, "visual_slots")
        ]
    )
    duplicate_requirement_slot_ids = _duplicates(
        [
            _get_value(requirement, "slot_id")
            for requirement in _as_list(visual_plan, "required_assets")
        ]
    )

    cover = frames[0] if frames else None
    cover_headline = str(_get_value(cover, "headline") or "")
    if 0 not in invalid_indexes and cover_headline != contract.first_screen_promise:
        issues.append(
            _issue(
                "first_screen_promise_mismatch",
                "The cover headline must exactly equal the first-screen promise.",
                _location(0, "headline"),
                frame=cover,
                before=cover_headline,
                after_hint=contract.first_screen_promise,
            )
        )

    issues.extend(
        _plan_contract_issues(
            frames,
            visual_plan,
            invalid_indexes,
            duplicate_plan_frame_ids,
            duplicate_storyboard_frame_ids,
        )
    )
    issues.extend(
        _slot_contract_issues(
            frames,
            visual_plan,
            invalid_indexes,
            duplicate_storyboard_slot_ids,
            duplicate_requirement_slot_ids,
        )
    )
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
    return (
        contract
        if isinstance(contract, ContentContract)
        else ContentContract.model_validate(contract)
    )


def _build_r1_tasks(issues: list[CarouselQAIssue]) -> EditorialTasks:
    def task_id(issue: CarouselQAIssue) -> str:
        identity = "|".join(
            (
                "carousel_qa",
                issue.rule_id,
                issue.frame_id or "",
                issue.location_hint,
            )
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
        return f"carousel_qa_{issue.rule_id}_{digest}"

    return EditorialTasks(
        mandatory=[
            SingleTask(
                task_id=task_id(issue),
                source="carousel_qa",
                instruction=issue.message,
                severity="high",
                location_hint=issue.location_hint,
                rationale="Deterministic carousel QA blocked human review.",
                before=issue.before,
                after_hint=issue.after_hint,
            )
            for issue in issues
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
            storyboard_visible_text=extract_storyboard_visible_text(
                package.get("storyboards")
            ),
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
    visual_plan = state.get("visual_plan")
    if visual_plan is None:
        issues = [
            _issue(
                "visual_plan_missing",
                "Editorial carousel QA requires the persisted visual plan.",
                "visual_plan",
            )
        ]
    else:
        issues = validate_carousel(package, contract, visual_plan)
        package_contract = package.get("content_contract")
        try:
            matches_authoritative = (
                package_contract is not None
                and ContentContract.model_validate(package_contract).model_dump(
                    mode="json"
                )
                == contract.model_dump(mode="json")
            )
        except ValidationError:
            matches_authoritative = False
        if not matches_authoritative:
            issues.insert(
                0,
                _issue(
                    "content_contract_mismatch",
                    "Publish-package content contract must match the selected topic contract.",
                    "publish_package.content_contract",
                ),
            )
    result = CarouselQAResult(passed=not issues, issues=issues)
    output = {"carousel_qa_result": result, "current_node": "CAROUSEL_QA"}
    if issues:
        output["decision_output"] = _build_r1_decision(package, issues)
    return output


def route_after_carousel_qa(state: AgentState) -> str:
    result = state.get("carousel_qa_result")
    passed = _get_value(result, "passed")
    if passed is True:
        return "editorial_carousel_renderer"
    if passed is False:
        return "r1_reflector"
    raise ValueError("route_after_carousel_qa requires carousel_qa_result.")
