from __future__ import annotations

import hashlib
from pathlib import Path

from src.domain import find_policy_violations
from src.editorial_carousel.legacy import is_legacy_editorial_checkpoint
from src.rendering.editorial.design_system import ASSET_ROOT
from src.schemas import AgentState


ASSET_ACTIVE_ROOT = ASSET_ROOT / "active"

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


def _value(payload, key, default=None):
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


def _as_list(payload, key) -> list:
    value = _value(payload, key, [])
    return list(value) if isinstance(value, (list, tuple)) else []


def _artifact_issue(rule_id: str, message: str, location: str) -> dict:
    return {
        "rule_id": rule_id,
        "matched_text": location,
        "message": message,
        "location": location,
    }


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _editorial_artifact_issues(state: AgentState, package: dict) -> list[dict]:
    issues: list[dict] = []
    if state.get("review_status") != "approved":
        issues.append(
            _artifact_issue(
                "human_review_not_approved",
                "Final policy guard requires explicit human approval.",
                "review_status",
            )
        )
    for state_key, rule_id in (
        ("carousel_qa_result", "carousel_qa_not_passed"),
        ("render_qa_result", "render_qa_not_passed"),
    ):
        if _value(state.get(state_key), "passed") is not True:
            issues.append(
                _artifact_issue(
                    rule_id,
                    f"Final policy guard requires passed {state_key}.",
                    f"{state_key}.passed",
                )
            )

    visual_plan = state.get("visual_plan")
    asset_manifest = state.get("asset_manifest")
    render_manifest = state.get("render_manifest")
    for value, name in (
        (visual_plan, "visual_plan"),
        (asset_manifest, "asset_manifest"),
        (render_manifest, "render_manifest"),
    ):
        if value is None:
            issues.append(
                _artifact_issue(
                    f"{name}_missing",
                    f"Final policy guard requires persisted {name}.",
                    name,
                )
            )
    if asset_manifest is None or render_manifest is None:
        return issues

    active_root = Path(ASSET_ACTIVE_ROOT).resolve()
    current_asset_hashes: dict[str, str] = {}
    for index, item in enumerate(_as_list(asset_manifest, "items")):
        location = f"asset_manifest.items[{index}]"
        slot_id = str(_value(item, "slot_id") or "")
        status = _value(item, "status")
        if status == "pending_external":
            issues.append(
                _artifact_issue(
                    "pending_asset_not_approved",
                    "Pending external assets cannot pass Final Policy Guard.",
                    f"{location}.status",
                )
            )
        elif status not in {"active", "fallback"}:
            issues.append(
                _artifact_issue(
                    "asset_status_invalid",
                    "Every final asset must be active or an explicit fallback.",
                    f"{location}.status",
                )
            )
        try:
            path = Path(_value(item, "path")).resolve()
        except (OSError, TypeError, ValueError):
            path = Path("")
        if not path.is_relative_to(active_root):
            issues.append(
                _artifact_issue(
                    "asset_path_not_active",
                    "Final assets must resolve inside the approved active catalog.",
                    f"{location}.path",
                )
            )
            continue
        actual = _sha256(path)
        if actual is None:
            issues.append(
                _artifact_issue(
                    "asset_file_missing",
                    "Final asset file is missing or unreadable.",
                    f"{location}.path",
                )
            )
            continue
        if actual != _value(item, "sha256"):
            issues.append(
                _artifact_issue(
                    "asset_file_hash_mismatch",
                    "Final asset bytes no longer match AssetManifest.",
                    f"{location}.sha256",
                )
            )
        if slot_id:
            current_asset_hashes[slot_id] = actual

    rendered_source_hashes = _value(
        render_manifest, "source_asset_sha256", {}
    )
    if rendered_source_hashes != current_asset_hashes:
        issues.append(
            _artifact_issue(
                "render_source_hash_binding_mismatch",
                "RenderManifest source hashes must exactly bind current active assets.",
                "render_manifest.source_asset_sha256",
            )
        )

    pages = _as_list(render_manifest, "pages")
    plan_frames = _as_list(visual_plan, "frame_plan")
    plan_frame_ids = [str(_value(frame, "frame_id") or "") for frame in plan_frames]
    storyboard_frame_ids = [
        str(_value(frame, "frame_id") or "")
        for frame in list(package.get("storyboards") or [])
    ]
    rendered_frame_ids = [str(_value(page, "frame_id") or "") for page in pages]
    if (
        rendered_frame_ids != plan_frame_ids
        or rendered_frame_ids != storyboard_frame_ids
    ):
        issues.append(
            _artifact_issue(
                "rendered_page_order_mismatch",
                "Rendered page order must match the visual plan and storyboard frame order.",
                "render_manifest.pages",
            )
        )
    page_paths = [str(_value(page, "path") or "") for page in pages]
    package_paths = package.get("rendered_image_paths")
    expected_count = len(plan_frames)
    if (
        not 5 <= len(pages) <= 7
        or (expected_count and len(pages) != expected_count)
        or len(set(page_paths)) != len(page_paths)
        or not isinstance(package_paths, list)
        or package_paths != page_paths
    ):
        issues.append(
            _artifact_issue(
                "rendered_image_paths_incomplete",
                "Publish package must contain every ordered final rendered PNG path.",
                "publish_package.rendered_image_paths",
            )
        )

    actual_page_hashes: list[str | None] = []
    for index, page in enumerate(pages):
        raw_path = _value(page, "path")
        try:
            path = Path(raw_path)
        except TypeError:
            path = Path("")
        actual = _sha256(path) if path.suffix.lower() == ".png" else None
        actual_page_hashes.append(actual)
        if actual is None:
            issues.append(
                _artifact_issue(
                    "rendered_page_missing",
                    "Every final rendered page must be a readable PNG.",
                    f"render_manifest.pages[{index}].path",
                )
            )
        elif actual != _value(page, "sha256"):
            issues.append(
                _artifact_issue(
                    "rendered_page_hash_mismatch",
                    "Rendered page bytes no longer match RenderManifest.",
                    f"render_manifest.pages[{index}].sha256",
                )
            )

    if _as_list(render_manifest, "contact_sheet_page_sha256") != actual_page_hashes:
        issues.append(
            _artifact_issue(
                "contact_sheet_page_hash_binding_mismatch",
                "Contact-sheet page binding must match current rendered PNG hashes.",
                "render_manifest.contact_sheet_page_sha256",
            )
        )
    try:
        contact_path = Path(_value(render_manifest, "contact_sheet_path"))
    except TypeError:
        contact_path = Path("")
    contact_hash = _sha256(contact_path)
    if contact_hash is None:
        issues.append(
            _artifact_issue(
                "contact_sheet_missing",
                "Human-review contact sheet is missing or unreadable.",
                "render_manifest.contact_sheet_path",
            )
        )
    elif contact_hash != _value(render_manifest, "contact_sheet_sha256"):
        issues.append(
            _artifact_issue(
                "contact_sheet_hash_mismatch",
                "Contact-sheet bytes no longer match RenderManifest.",
                "render_manifest.contact_sheet_sha256",
            )
        )
    return issues


def final_policy_guard_node(state: AgentState) -> AgentState:
    publish_package = state.get("publish_package")
    if publish_package is None:
        raise ValueError("final_policy_guard_node requires `publish_package` in state.")

    issues = _required_field_issues(publish_package)
    if not is_legacy_editorial_checkpoint(state):
        issues.extend(_editorial_artifact_issues(state, publish_package))
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
