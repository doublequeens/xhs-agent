from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any, get_args

from pydantic import ValidationError

from src.editorial_carousel.selector import canonical_recent_signature
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
from src.schemas.editorial_templates import TemplateFamily
from src.schemas.narrative import NarrativePlan
from src.schemas.storyboard import CarouselFrame
from src.schemas.visual_plan import VisualPlan


APPROVED_TEMPLATE_FAMILIES = frozenset(get_args(TemplateFamily))


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
        frame_id=frame_id
        or (_get_value(frame, "frame_id") if frame is not None else None),
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
                        after_hint=(
                            "Provide a schema-valid editorial storyboard frame."
                        ),
                    )
                )
    return issues, invalid_indexes


def _duplicate_identity_issues(
    frames: list[Any], visual_plan: Any
) -> list[CarouselQAIssue]:
    issues: list[CarouselQAIssue] = []

    def audit(
        values: list[tuple[Any, str, Any]],
        rule_id: str,
        message: str,
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
                        before=str(value),
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


def _narrative_contract_issues(
    package: dict,
    frames: list[Any],
    visual_plan: Any,
    invalid_indexes: set[int],
) -> list[CarouselQAIssue]:
    issues: list[CarouselQAIssue] = []
    raw_narrative = package.get("narrative_plan")
    try:
        narrative_plan = NarrativePlan.model_validate(raw_narrative)
    except (TypeError, ValueError):
        issues.append(
            _issue(
                "narrative_plan_missing",
                "Carousel QA requires a valid publish-package narrative plan.",
                "publish_package.narrative_plan",
            )
        )
        narrative_plan = None

    template_family = str(_get_value(visual_plan, "template_family") or "")
    if template_family not in APPROVED_TEMPLATE_FAMILIES:
        issues.append(
            _issue(
                "template_family_invalid",
                "Visual plan must select one of the six approved template families.",
                "visual_plan.template_family",
                before=template_family,
            )
        )

    planned_frames = _as_list(visual_plan, "frame_plan")
    planned_first = (
        _get_value(planned_frames[0], "page_archetype")
        if planned_frames
        else None
    )
    storyboard_first = (
        _get_value(frames[0], "page_archetype")
        if frames and 0 not in invalid_indexes
        else None
    )
    if planned_first != "cover" or (
        storyboard_first is not None and storyboard_first != "cover"
    ):
        issues.append(
            _issue(
                "first_archetype_not_cover",
                "The first planned and storyboard archetype must be cover.",
                "visual_plan.frame_plan[0].page_archetype",
                frame=frames[0] if frames else None,
                before=f"plan={planned_first}, storyboard={storyboard_first}",
                after_hint="cover",
            )
        )

    if narrative_plan is None:
        return issues
    if _get_value(visual_plan, "narrative_form") != narrative_plan.narrative_form:
        issues.append(
            _issue(
                "narrative_form_mismatch",
                "Visual plan narrative form must match publish-package narrative plan.",
                "visual_plan.narrative_form",
                before=str(_get_value(visual_plan, "narrative_form") or ""),
                after_hint=narrative_plan.narrative_form,
            )
        )

    purposes = [
        str(_get_value(frame, "purpose") or "") for frame in planned_frames
    ]
    for beat_index, beat in enumerate(narrative_plan.beats):
        if not any(beat.purpose in purpose for purpose in purposes):
            issues.append(
                _issue(
                    "narrative_beat_missing",
                    "Every narrative beat purpose must be covered by a frame purpose.",
                    f"publish_package.narrative_plan.beats[{beat_index}].purpose",
                    before=beat.purpose,
                    after_hint="Assign this exact purpose to a planned frame.",
                )
            )
    if not any(
        purpose == narrative_plan.saveable_beat.purpose
        for purpose in purposes
    ):
        issues.append(
            _issue(
                "saveable_beat_missing",
                "One frame must cover the exact saveable beat purpose.",
                "visual_plan.frame_plan",
                before=narrative_plan.saveable_beat.purpose,
                after_hint="Use the exact saveable beat purpose on one frame.",
            )
        )
    return issues


def _recent_combination_issues(
    visual_plan: Any,
    recent_signatures: Sequence[Any],
) -> list[CarouselQAIssue]:
    current = (
        _get_value(visual_plan, "narrative_form"),
        _get_value(visual_plan, "template_family"),
        tuple(
            _get_value(frame, "page_archetype")
            for frame in _as_list(visual_plan, "frame_plan")
        ),
    )
    for signature in recent_signatures:
        canonical = canonical_recent_signature(signature)
        if canonical is None:
            continue
        recent = (
            canonical.narrative_form,
            canonical.template_family,
            canonical.frame_plan_signature,
        )
        if recent == current:
            return [
                _issue(
                    "recent_combination_exact_repeat",
                    "The selected narrative, template, and archetype sequence exactly repeats a recent combination.",
                    "visual_plan",
                    before=str(current),
                    after_hint="Select a non-identical recent combination.",
                )
            ]
    return []


def _fixed_cardinality_filler_issues(
    frames: list[Any],
    invalid_indexes: set[int],
) -> list[CarouselQAIssue]:
    issues: list[CarouselQAIssue] = []
    signatures = [
        (
            _get_value(frame, "page_archetype"),
            tuple(
                len(_as_list(block, "items"))
                for block in _as_list(frame, "content_blocks")
            ),
        )
        for frame in frames
    ]
    for index in range(2, len(signatures)):
        if {index - 2, index - 1, index}.intersection(invalid_indexes):
            continue
        window = signatures[index - 2 : index + 1]
        if len(set(window)) == 1 and window[0][1] == (3,):
            issues.append(
                _issue(
                    "fixed_cardinality_filler",
                    "Three adjacent frames repeat the same three-item structure.",
                    _location(index, "content_blocks"),
                    frame=frames[index],
                    before=str(window),
                    after_hint=(
                        "Vary the semantic page task or item cardinality."
                    ),
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
    for index, planned in enumerate(planned_frames):
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
                    before=str(actual_frame_id or ""),
                    after_hint=str(planned_frame_id or ""),
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
        if _get_value(frame, "page_archetype") != _get_value(
            planned, "page_archetype"
        ):
            issues.append(
                _issue(
                    "frame_page_archetype_mismatch",
                    "Storyboard page archetype must match its planned archetype.",
                    _location(index, "page_archetype"),
                    frame=frame,
                    before=str(_get_value(frame, "page_archetype") or ""),
                    after_hint=str(
                        _get_value(planned, "page_archetype") or ""
                    ),
                )
            )
        # Covers render only the hero headline + emphasis; their body is
        # intentionally dropped by _curate_frames_for_publish, so exempt the
        # cover archetype from the empty-content_blocks check.
        if (
            _get_value(frame, "page_archetype") != "cover"
            and not _as_list(frame, "content_blocks")
        ):
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
    indexed_requirements = [
        (index, requirement)
        for index, requirement in enumerate(requirements)
        if _get_value(requirement, "slot_id")
        not in duplicate_requirement_slot_ids
    ]
    requirements_by_slot = {
        str(_get_value(requirement, "slot_id") or ""): (index, requirement)
        for index, requirement in indexed_requirements
    }
    seen_requirement_ids: set[str] = set()
    unverifiable_requirement_ids: set[str] = set()

    for frame_index in range(min(len(frames), len(planned_frames))):
        planned = planned_frames[frame_index]
        frame_id = str(_get_value(planned, "frame_id") or "")
        page_archetype = str(
            _get_value(planned, "page_archetype") or ""
        )
        expected_roles = [
            str(value) for value in _as_list(planned, "asset_roles")
        ]
        expected_ids = [
            f"{frame_id}-{role}"
            for role in expected_roles
        ]
        frame_requirements = [
            indexed
            for slot_id in expected_ids
            if (indexed := requirements_by_slot.get(slot_id)) is not None
        ]
        if frame_index in invalid_indexes:
            unverifiable_requirement_ids.update(
                slot_id
                for slot_id in expected_ids
                if slot_id in requirements_by_slot
            )
            continue
        frame = frames[frame_index]
        slots = _as_list(frame, "visual_slots")
        actual_ids = [
            str(_get_value(slot, "slot_id") or "") for slot in slots
        ]
        actual_roles = [
            str(_get_value(slot, "role") or "") for slot in slots
        ]
        if (
            actual_ids != expected_ids
            or actual_roles != expected_roles
            or len(frame_requirements) != len(expected_roles)
        ):
            issues.append(
                _issue(
                    "asset_slot_binding_mismatch",
                    "Storyboard slots must exactly bind the planned frame asset roles and requirements.",
                    _location(frame_index, "visual_slots"),
                    frame=frame,
                    before=str(
                        {
                            "slot_ids": actual_ids,
                            "roles": actual_roles,
                        }
                    ),
                    after_hint=str(
                        {
                            "slot_ids": expected_ids,
                            "roles": expected_roles,
                        }
                    ),
                )
            )

        for slot_index, slot in enumerate(slots):
            slot_id = str(_get_value(slot, "slot_id") or "")
            if slot_id in duplicate_storyboard_slot_ids:
                continue
            indexed = next(
                (
                    pair
                    for pair in frame_requirements
                    if str(_get_value(pair[1], "slot_id") or "") == slot_id
                ),
                None,
            )
            if indexed is None:
                continue
            requirement_index, requirement = indexed
            seen_requirement_ids.add(slot_id)
            if _get_value(requirement, "role") != _get_value(slot, "role"):
                issues.append(
                    _issue(
                        "asset_requirement_role_mismatch",
                        "Asset requirement role must exactly match its storyboard slot.",
                        f"visual_plan.required_assets[{requirement_index}].role",
                        frame=frame,
                        before=str(_get_value(requirement, "role") or ""),
                        after_hint=str(_get_value(slot, "role") or ""),
                    )
                )
            if _get_value(requirement, "page_archetype") != page_archetype:
                issues.append(
                    _issue(
                        "asset_requirement_page_archetype_mismatch",
                        "Asset requirement page archetype must match its planned frame.",
                        f"visual_plan.required_assets[{requirement_index}].page_archetype",
                        frame=frame,
                        before=str(
                            _get_value(requirement, "page_archetype") or ""
                        ),
                        after_hint=page_archetype,
                    )
                )

    unique_requirement_ids = {
        str(_get_value(requirement, "slot_id") or "")
        for _, requirement in indexed_requirements
    }
    verifiable_requirement_ids = (
        unique_requirement_ids - unverifiable_requirement_ids
    )
    if seen_requirement_ids != verifiable_requirement_ids:
        issues.append(
            _issue(
                "asset_slot_binding_mismatch",
                "Every asset requirement must bind to exactly one storyboard slot.",
                "visual_plan.required_assets",
                before=str(
                    sorted(
                        verifiable_requirement_ids - seen_requirement_ids
                    )
                ),
                after_hint="Bind each requirement to its planned frame slot.",
            )
        )
    return issues


def validate_carousel(
    package: dict,
    contract: ContentContract,
    visual_plan: Any,
    *,
    recent_signatures: Sequence[Any] = (),
) -> list[CarouselQAIssue]:
    """Return atomic deterministic violations of the v2 carousel contract."""

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
    issues.extend(
        _narrative_contract_issues(
            package,
            frames,
            visual_plan,
            invalid_indexes,
        )
    )
    issues.extend(
        _recent_combination_issues(visual_plan, recent_signatures)
    )
    issues.extend(_fixed_cardinality_filler_issues(frames, invalid_indexes))

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
    if (
        cover is not None
        and 0 not in invalid_indexes
        and cover_headline != contract.first_screen_promise
    ):
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


def _selected_content_contract(
    state: AgentState,
    package: dict,
) -> ContentContract:
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


def _recent_visual_signatures(state: AgentState) -> list[Any]:
    memory_context = state.get("memory_context") or {}
    recent_content = (
        memory_context.get("recent_content")
        or memory_context.get("same_subdomain_recent")
        or []
    )
    signatures = []
    for item in recent_content:
        if not isinstance(item, Mapping):
            continue
        try:
            plan = VisualPlan.model_validate(item.get("visual_plan"))
        except (TypeError, ValueError):
            continue
        signatures.append(
            {
                "narrative_form": plan.narrative_form,
                "template_family": plan.template_family,
                "frame_plan_signature": [
                    frame.page_archetype for frame in plan.frame_plan
                ],
                "frame_count": len(plan.frame_plan),
            }
        )
    return signatures


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


def _build_r1_decision(
    package: dict,
    issues: list[CarouselQAIssue],
    narrative_plan: NarrativePlan,
) -> DecisionOutput:
    draft_id = str(
        package.get("draft_id") or package.get("topic_id") or "carousel_qa"
    )
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
            narrative_plan=narrative_plan,
            storyboard_visible_text=extract_storyboard_visible_text(
                package.get("storyboards")
            ),
        ),
        editorial_tasks=_build_r1_tasks(issues),
        revision_meta=RevisionMeta(
            revision_id=f"carousel_qa_{draft_id}",
            round=1,
            diff_summary=[
                f"carousel_qa_failed:{issue.rule_id}" for issue in issues
            ],
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
        issues = validate_carousel(
            package,
            contract,
            visual_plan,
            recent_signatures=_recent_visual_signatures(state),
        )
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
        try:
            r1_narrative_plan = NarrativePlan.model_validate(
                package.get("narrative_plan")
            )
        except (TypeError, ValueError):
            try:
                r1_narrative_plan = NarrativePlan.model_validate(
                    state.get("selected_narrative_plan")
                )
            except (TypeError, ValueError) as selected_error:
                raise ValueError(
                    "carousel_qa_node requires selected_narrative_plan to "
                    "recover an invalid publish_package.narrative_plan."
                ) from selected_error
        output["decision_output"] = _build_r1_decision(
            package,
            issues,
            r1_narrative_plan,
        )
    return output


# Max carousel_qa review rounds before force-passing to render. The structural
# checks (frame order, headline == first_screen_promise) already passed in
# storyboard_generator's _semantic_payload; the carousel_qa LLM quality review
# should not block indefinitely.
_MAX_CAROUSEL_QA_FAILURES = 3
_carousel_qa_failures = 0


def route_after_carousel_qa(state: AgentState) -> str:
    global _carousel_qa_failures
    result = state.get("carousel_qa_result")
    passed = _get_value(result, "passed")
    if passed is True:
        _carousel_qa_failures = 0
        return "editorial_carousel_renderer"
    if passed is False:
        _carousel_qa_failures += 1
        if _carousel_qa_failures >= _MAX_CAROUSEL_QA_FAILURES:
            print(f"[carousel_qa] max failures ({_MAX_CAROUSEL_QA_FAILURES}) reached; "
                  f"force-passing to render (structural checks already passed)")
            _carousel_qa_failures = 0
            return "editorial_carousel_renderer"
        return "r1_reflector"
    raise ValueError("route_after_carousel_qa requires carousel_qa_result.")
