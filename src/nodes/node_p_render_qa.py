from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.nodes.node_p_carousel_qa import _get_value, _selected_content_contract
from src.nodes.node_p_text_card_renderer import PUBLISH_ROOT
from src.nodes.publish_patch import extract_storyboard_visible_text
from src.rendering.text_cards import CANVAS, output_paths
from src.schemas.agent_state import AgentState
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
from src.schemas.render_qa import RenderQAIssue, RenderQAResult
from src.schemas.text_card import TextCardPayload


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
EXPECTED_FILENAMES = tuple(path.name for path in output_paths(Path(".")))


def _issue(rule_id: str, message: str, location_hint: str) -> RenderQAIssue:
    return RenderQAIssue(
        rule_id=rule_id,
        message=message,
        location_hint=location_hint,
    )


def _png_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        header = path.read_bytes()[:24]
    except OSError:
        return None
    if len(header) < 24 or header[:8] != PNG_SIGNATURE:
        return None
    length, chunk_type, width, height = struct.unpack(">I4sII", header[8:24])
    if length != 13 or chunk_type != b"IHDR":
        return None
    return width, height


def _payload_issues(package: dict, state: AgentState) -> list[RenderQAIssue]:
    issues: list[RenderQAIssue] = []
    raw_storyboards = package.get("storyboards")
    try:
        payload = TextCardPayload.model_validate({"storyboards": raw_storyboards})
    except ValidationError as exc:
        issues.append(
            _issue(
                "text_card_schema_invalid",
                f"Rendered cards require schema-valid text-card storyboards: {exc.errors()[0]['msg']}",
                "publish_package.storyboards",
            )
        )
        payload = None

    frames = raw_storyboards if isinstance(raw_storyboards, list) else []
    cover = frames[0] if frames else None
    cover_headline = str(_get_value(cover, "headline") or "")
    contract = _selected_content_contract(state, package)
    if cover_headline != contract.first_screen_promise:
        issues.append(
            _issue(
                "first_screen_promise_mismatch",
                "The cover headline must exactly equal the selected first-screen promise.",
                "publish_package.storyboards[0].headline",
            )
        )

    templates = [_get_value(frame, "template") for frame in frames]
    if "saveable_checklist" not in templates:
        issues.append(
            _issue(
                "missing_saveable_checklist",
                "Rendered cards must include the saveable_checklist frame.",
                "publish_package.storyboards[3].template",
            )
        )
    return issues


def validate_rendered_images(package: dict, state: AgentState) -> list[RenderQAIssue]:
    """Return every deterministic generated-file and content-contract violation."""
    issues = _payload_issues(package, state)
    render_error = package.get("render_error")
    if render_error:
        issues.append(
            _issue(
                "local_render_failed",
                f"Local text-card rendering failed: {render_error}",
                "publish_package.rendered_image_paths",
            )
        )

    raw_paths: Any = package.get("rendered_image_paths")
    paths = raw_paths if isinstance(raw_paths, list) else []
    if len(paths) != len(EXPECTED_FILENAMES):
        issues.append(
            _issue(
                "rendered_image_count_invalid",
                "Local rendering must produce exactly six PNG files.",
                "publish_package.rendered_image_paths",
            )
        )

    publish_root = PUBLISH_ROOT.resolve()
    resolved_paths: list[Path | None] = []
    for index, raw_path in enumerate(paths):
        location_hint = f"publish_package.rendered_image_paths[{index}]"
        try:
            path = Path(raw_path).resolve()
        except (OSError, TypeError, ValueError) as exc:
            issues.append(
                _issue(
                    "png_path_invalid",
                    f"Generated PNG path cannot be resolved: {exc}",
                    location_hint,
                )
            )
            resolved_paths.append(None)
            continue
        if not path.is_relative_to(publish_root):
            issues.append(
                _issue(
                    "png_outside_publish_root",
                    "Generated PNG must remain inside outputs/publish.",
                    location_hint,
                )
            )
            resolved_paths.append(None)
            continue
        resolved_paths.append(path)

    for index, expected_name in enumerate(EXPECTED_FILENAMES):
        if index >= len(paths):
            issues.append(
                _issue(
                    "png_missing",
                    f"Missing generated PNG {expected_name}.",
                    f"publish_package.rendered_image_paths[{index}]",
                )
            )
            continue
        path = resolved_paths[index]
        if path is None:
            continue
        if path.name != expected_name:
            issues.append(
                _issue(
                    "png_filename_order_invalid",
                    f"Generated PNG {index + 1} must be named {expected_name}.",
                    f"publish_package.rendered_image_paths[{index}]",
                )
            )
        if not path.is_file():
            issues.append(
                _issue(
                    "png_missing",
                    f"Generated PNG is missing: {path.name or expected_name}.",
                    f"publish_package.rendered_image_paths[{index}]",
                )
            )
            continue
        dimensions = _png_dimensions(path)
        if dimensions is None:
            issues.append(
                _issue(
                    "png_signature_or_ihdr_invalid",
                    f"Generated file {path.name} is not a PNG with a valid IHDR header.",
                    f"publish_package.rendered_image_paths[{index}]",
                )
            )
        elif dimensions != (CANVAS["width"], CANVAS["height"]):
            issues.append(
                _issue(
                    "png_dimensions_invalid",
                    f"Generated PNG {path.name} must be {CANVAS['width']}x{CANVAS['height']}; got {dimensions[0]}x{dimensions[1]}.",
                    f"publish_package.rendered_image_paths[{index}]",
                )
            )
    return issues


def _build_r1_decision(package: dict, issues: list[RenderQAIssue]) -> DecisionOutput:
    draft_id = str(package.get("draft_id") or package.get("topic_id") or "render_qa")
    tasks = EditorialTasks(
        mandatory=[
            SingleTask(
                task_id=f"render_qa_{issue.rule_id}_{index:03d}",
                source="render_qa",
                instruction=issue.message,
                severity="high",
                location_hint=issue.location_hint,
                rationale="Generated-file QA blocked human review.",
            )
            for index, issue in enumerate(issues, start=1)
        ],
        optional=[],
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
            storyboard_visible_text=extract_storyboard_visible_text(package.get("storyboards")),
        ),
        editorial_tasks=tasks,
        revision_meta=RevisionMeta(
            revision_id=f"render_qa_{draft_id}",
            round=1,
            diff_summary=[f"render_qa_failed:{issue.rule_id}" for issue in issues],
            next_actions=["repair_render_qa_issues", "rerun_text_card_renderer"],
        ),
        decision_trace=DecisionTrace(
            source_node="RENDER_QA",
            why_this_route=["Generated-file QA found violations; return to R1."],
        ),
    )
    return DecisionOutput(
        next_node="R1_REFLECTOR",
        normalized_input=NormalizedInput(r1_input=r1_input),
    )


def render_qa_node(state: AgentState) -> dict:
    package = state.get("publish_package")
    if not isinstance(package, dict):
        raise ValueError("render_qa_node requires publish_package as a dict.")

    issues = validate_rendered_images(package, state)
    result = RenderQAResult(passed=not issues, issues=issues)
    output = {"render_qa_result": result, "current_node": "RENDER_QA"}
    if issues:
        output["decision_output"] = _build_r1_decision(package, issues)
    return output


def route_after_render_qa(state: AgentState) -> str:
    result = state.get("render_qa_result")
    passed = _get_value(result, "passed")
    if passed is True:
        return "human_review"
    if passed is False:
        return "r1_reflector"
    raise ValueError("route_after_render_qa requires render_qa_result.")
