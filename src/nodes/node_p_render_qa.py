from __future__ import annotations

import hashlib
import statistics
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image
from pydantic import ValidationError

from src.asset_resolver.lifecycle import ApprovedSafetyReview
from src.nodes.node_p_carousel_qa import _get_value, _selected_content_contract
from src.nodes.publish_patch import extract_storyboard_visible_text
from src.rendering.editorial.probes import EXPECTED_FONT_FAMILIES
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
from src.schemas.narrative import NarrativePlan
from src.schemas.render_qa import RenderQAIssue, RenderQAResult
SAVEABLE_ARCHETYPES = frozenset({"checklist", "save", "comparison"})


def _as_list(payload: Any, key: str) -> list[Any]:
    value = _get_value(payload, key, [])
    return list(value) if isinstance(value, (list, tuple)) else []


def _safety_review_is_resolved(item: Any) -> bool:
    try:
        ApprovedSafetyReview.model_validate(
            {
                "unresolved_safety_checks": _get_value(
                    item, "unresolved_safety_checks", []
                ),
                "safety_review_decisions": _get_value(
                    item, "safety_review_decisions", {}
                ),
                "safety_reviewed_at": _get_value(item, "safety_reviewed_at"),
                "review_status": _get_value(item, "review_status"),
                "review_disposition": _get_value(item, "review_disposition"),
            }
        )
    except ValidationError:
        return False
    return True


def _issue(
    rule_id: str,
    message: str,
    location_hint: str,
    *,
    frame_id: str | None = None,
) -> RenderQAIssue:
    return RenderQAIssue(
        rule_id=rule_id,
        message=message,
        location_hint=location_hint,
        frame_id=frame_id,
    )


def _png_snapshot(path: Path) -> tuple[str, tuple[int, int]] | None:
    try:
        data = path.read_bytes()
        with Image.open(BytesIO(data)) as image:
            if image.format != "PNG":
                return None
            image.verify()
        with Image.open(BytesIO(data)) as image:
            image.load()
            dimensions = image.size
    except (OSError, ValueError):
        return None
    return hashlib.sha256(data).hexdigest(), dimensions


def _png_dimensions(path: Path) -> tuple[int, int] | None:
    snapshot = _png_snapshot(path)
    return snapshot[1] if snapshot is not None else None


def _asset_snapshot(path: Path) -> tuple[str, tuple[int, int]] | None:
    try:
        data = path.read_bytes()
        if path.suffix.lower() == ".svg":
            root = ET.fromstring(data)
            dimensions = (
                int(float(root.attrib["width"])),
                int(float(root.attrib["height"])),
            )
        else:
            with Image.open(BytesIO(data)) as image:
                image.verify()
            with Image.open(BytesIO(data)) as image:
                image.load()
                dimensions = image.size
        return hashlib.sha256(data).hexdigest(), dimensions
    except (ET.ParseError, KeyError, OSError, ValueError):
        return None


def _expected_probe_text(frame: Any) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    kicker = _get_value(frame, "kicker")
    if kicker:
        values.append(("kicker", str(kicker)))
    headline = _get_value(frame, "headline")
    if headline:
        values.append(("headline", str(headline)))
    for block_index, block in enumerate(_as_list(frame, "content_blocks")):
        heading = _get_value(block, "heading")
        body = _get_value(block, "body")
        if heading:
            values.append((f"content_blocks[{block_index}].heading", str(heading)))
        if body:
            values.append((f"content_blocks[{block_index}].body", str(body)))
        values.extend(
            (f"content_blocks[{block_index}].items[{item_index}]", str(item))
            for item_index, item in enumerate(_as_list(block, "items"))
        )
    footer = _get_value(frame, "footer")
    if footer:
        values.append(("footer", str(footer)))
    return values


def _storyboard_slot_audit(
    frames: list[Any],
) -> tuple[
    list[RenderQAIssue],
    dict[str, list[tuple[int, int, Any, Any]]],
    set[str],
]:
    occurrences: dict[str, list[tuple[int, int, Any, Any]]] = {}
    for frame_index, frame in enumerate(frames):
        for slot_index, slot in enumerate(_as_list(frame, "visual_slots")):
            slot_id = str(_get_value(slot, "slot_id") or "")
            if not slot_id:
                continue
            occurrences.setdefault(slot_id, []).append(
                (frame_index, slot_index, frame, slot)
            )
    duplicate_ids = {
        slot_id for slot_id, values in occurrences.items() if len(values) > 1
    }
    issues = [
        _issue(
            "duplicate_storyboard_slot_id",
            "Storyboard slot IDs must be unique across the carousel before asset mapping.",
            f"storyboards[{frame_index}].visual_slots[{slot_index}].slot_id",
            frame_id=str(_get_value(frame, "frame_id") or "") or None,
        )
        for slot_id, values in occurrences.items()
        if slot_id in duplicate_ids
        for frame_index, slot_index, frame, _slot in values[1:]
    ]
    return issues, occurrences, duplicate_ids


def _probe_attestation_issues(
    frame: Any,
    page: Any,
    page_index: int,
    duplicate_storyboard_slot_ids: set[str],
) -> list[RenderQAIssue]:
    issues: list[RenderQAIssue] = []
    frame_id = str(_get_value(frame, "frame_id") or "") or None
    probe = _get_value(page, "probe")
    base = f"render_manifest.pages[{page_index}].probe"
    if probe is None:
        return [
            _issue(
                "page_probe_missing",
                "Every rendered page requires persisted probe attestation.",
                base,
                frame_id=frame_id,
            )
        ]

    if (
        _get_value(probe, "canvas_width") != 1080
        or _get_value(probe, "canvas_height") != 1440
    ):
        issues.append(
            _issue(
                "probe_canvas_geometry_mismatch",
                "Persisted probe canvas must be exactly 1080x1440.",
                f"{base}.canvas_width",
                frame_id=frame_id,
            )
        )
    if float(_get_value(probe, "safe_margin") or 0) != 84.0:
        issues.append(
            _issue(
                "probe_safe_margin_mismatch",
                "Persisted probe safe margin must equal the 84px design token.",
                f"{base}.safe_margin",
                frame_id=frame_id,
            )
        )

    texts = _as_list(probe, "text_results")
    actual_text = [
        (str(_get_value(text, "role") or ""), str(_get_value(text, "text") or ""))
        for text in texts
    ]
    if actual_text != _expected_probe_text(frame):
        issues.append(
            _issue(
                "rendered_visible_text_mismatch",
                "Persisted rendered visible text must exactly equal storyboard strings.",
                f"{base}.text_results",
                frame_id=frame_id,
            )
        )
    for text_index, text in enumerate(texts):
        text_location = f"{base}.text_results[{text_index}]"
        role = str(_get_value(text, "role") or "")
        if (
            _get_value(text, "visible") is not True
            or _get_value(text, "overflow") is True
            or _get_value(text, "ink_clipped") is True
            or _get_value(text, "layout_clipped") is True
        ):
            issues.append(
                _issue(
                    "text_overflow",
                    "Persisted probe found hidden, overflowing, or clipped copy.",
                    text_location,
                    frame_id=frame_id,
                )
            )
        expected_family = (
            "Source Han Serif SC" if role == "headline" else "Source Han Sans SC"
        )
        if _get_value(text, "font_family") != expected_family:
            issues.append(
                _issue(
                    "text_font_family_mismatch",
                    "Persisted text must use the exact role-specific repository font.",
                    f"{text_location}.font_family",
                    frame_id=frame_id,
                )
            )
        font_size = float(_get_value(text, "font_size") or 0)
        if role == "headline" and not 40 <= font_size <= 72:
            issues.append(
                _issue(
                    "text_font_size_token_invalid",
                    "Headline font size is outside the approved editorial token range.",
                    f"{text_location}.font_size",
                    frame_id=frame_id,
                )
            )
        if (role.endswith(".body") or ".items[" in role) and font_size:
            ratio = float(_get_value(text, "line_height") or 0) / font_size
            if not 1.4 <= ratio <= 1.5:
                issues.append(
                    _issue(
                        "body_line_height_invalid",
                        "Body copy line height must remain between 1.4 and 1.5.",
                        f"{text_location}.line_height",
                        frame_id=frame_id,
                    )
                )
        if role == "headline" and int(_get_value(text, "line_count") or 0) > 2:
            issues.append(
                _issue(
                    "headline_line_count_invalid",
                    "Headline must render in at most two lines.",
                    f"{text_location}.line_count",
                    frame_id=frame_id,
                )
            )
        x = float(_get_value(text, "x") or 0)
        y = float(_get_value(text, "y") or 0)
        width = float(_get_value(text, "width") or 0)
        height = float(_get_value(text, "height") or 0)
        if x < 0 or y < 0 or x + width > 1080 or y + height > 1440:
            issues.append(
                _issue(
                    "text_geometry_out_of_canvas",
                    "Persisted text geometry must remain inside the exact canvas.",
                    text_location,
                    frame_id=frame_id,
                )
            )

    for issue_index, finding in enumerate(_as_list(probe, "issues")):
        issues.append(
            _issue(
                "render_token_violation",
                f"Persisted page probe failed: {finding}.",
                f"{base}.issues[{issue_index}]",
                frame_id=frame_id,
            )
        )

    asset_results = _as_list(probe, "asset_results")
    result_occurrences: dict[str, list[tuple[int, Any]]] = {}
    for result_index, result in enumerate(asset_results):
        slot_id = str(_get_value(result, "slot_id") or "")
        result_occurrences.setdefault(slot_id, []).append((result_index, result))
    duplicate_probe_ids = {
        slot_id
        for slot_id, values in result_occurrences.items()
        if len(values) > 1
    }
    for slot_id, values in result_occurrences.items():
        if slot_id not in duplicate_probe_ids:
            continue
        for result_index, _result in values[1:]:
            issues.append(
                _issue(
                    "duplicate_probe_asset_slot_id",
                    "Page probe asset slot IDs must be unique.",
                    f"{base}.asset_results[{result_index}].slot_id",
                    frame_id=frame_id,
                )
            )

    expected_ids = {
        str(_get_value(slot, "slot_id") or "")
        for slot in _as_list(frame, "visual_slots")
        if str(_get_value(slot, "slot_id") or "")
        not in duplicate_storyboard_slot_ids
    }
    actual_unique_ids = set(result_occurrences) - duplicate_probe_ids
    for slot_id in sorted(expected_ids - actual_unique_ids - duplicate_probe_ids):
        issues.append(
            _issue(
                "probe_asset_slot_missing",
                "Page probe is missing the storyboard asset slot.",
                f"{base}.asset_results.{slot_id}",
                frame_id=frame_id,
            )
        )
    for result_index, result in enumerate(asset_results):
        slot_id = str(_get_value(result, "slot_id") or "")
        if slot_id not in expected_ids and slot_id not in duplicate_storyboard_slot_ids:
            issues.append(
                _issue(
                    "unexpected_probe_asset_slot",
                    "Page probe contains an asset slot absent from the storyboard frame.",
                    f"{base}.asset_results[{result_index}].slot_id",
                    frame_id=frame_id,
                )
            )

    for slot_id in sorted(expected_ids & actual_unique_ids):
        result_index, result = result_occurrences[slot_id][0]
        result_location = f"{base}.asset_results[{result_index}]"
        natural_ratio = float(_get_value(result, "natural_width")) / float(
            _get_value(result, "natural_height")
        )
        rendered_ratio = float(_get_value(result, "rendered_width")) / float(
            _get_value(result, "rendered_height")
        )
        recomputed_error = abs(rendered_ratio - natural_ratio) / natural_ratio
        claimed_error = float(_get_value(result, "aspect_ratio_error") or 0)
        if abs(claimed_error - recomputed_error) > 1e-6:
            issues.append(
                _issue(
                    "asset_aspect_ratio_attestation_mismatch",
                    "Persisted aspect-ratio error must match raw measured geometry.",
                    f"{result_location}.aspect_ratio_error",
                    frame_id=frame_id,
                )
            )
        expected_cropped = _get_value(result, "object_fit") == "cover"
        if _get_value(result, "cropped") is not expected_cropped:
            issues.append(
                _issue(
                    "asset_crop_attestation_mismatch",
                    "Persisted crop flag must match the raw object-fit token.",
                    f"{result_location}.cropped",
                    frame_id=frame_id,
                )
            )
        if (
            recomputed_error > 0.01
            or _get_value(result, "object_fit") != "contain"
            or expected_cropped
        ):
            issues.append(
                _issue(
                    "asset_render_stretched",
                    "Raw DOM geometry indicates crop or aspect-ratio distortion.",
                    result_location,
                    frame_id=frame_id,
                )
            )
    return issues


def _manifest_page_issues(
    frames: list[Any],
    render_manifest: Any,
    duplicate_storyboard_slot_ids: set[str],
) -> list[RenderQAIssue]:
    issues: list[RenderQAIssue] = []
    pages = _as_list(render_manifest, "pages")
    for index, frame in enumerate(frames):
        frame_id = str(_get_value(frame, "frame_id") or "") or None
        if index >= len(pages):
            issues.append(
                _issue(
                    "rendered_page_missing",
                    "A storyboard frame has no rendered page entry.",
                    f"render_manifest.pages[{index}]",
                    frame_id=frame_id,
                )
            )
            continue

        page = pages[index]
        for field, rule_id in (
            ("frame_id", "rendered_page_frame_id_mismatch"),
            ("role", "rendered_page_role_mismatch"),
            ("page_archetype", "rendered_page_archetype_mismatch"),
        ):
            if _get_value(page, field) != _get_value(frame, field):
                issues.append(
                    _issue(
                        rule_id,
                        f"Rendered page {field} must match storyboard order.",
                        f"render_manifest.pages[{index}].{field}",
                        frame_id=frame_id,
                    )
                )

        raw_path = _get_value(page, "path")
        try:
            path = Path(raw_path)
        except TypeError:
            path = Path("")
        if not raw_path or not path.is_file():
            issues.append(
                _issue(
                    "rendered_page_missing",
                    "Rendered page file is missing.",
                    f"render_manifest.pages[{index}].path",
                    frame_id=frame_id,
                )
            )
            continue

        snapshot = _png_snapshot(path)
        if snapshot is None:
            issues.append(
                _issue(
                    "rendered_page_corrupt",
                    "Rendered page must be a completely decodable PNG.",
                    f"render_manifest.pages[{index}].path",
                    frame_id=frame_id,
                )
            )
        else:
            actual_sha256, dimensions = snapshot
            if dimensions != (1080, 1440) or (
                _get_value(page, "width"), _get_value(page, "height")
            ) != (1080, 1440):
                issues.append(
                    _issue(
                        "png_dimensions_invalid",
                        f"Rendered page must be 1080x1440; got {dimensions[0]}x{dimensions[1]}.",
                        f"render_manifest.pages[{index}].path",
                        frame_id=frame_id,
                    )
                )
            if actual_sha256 != _get_value(page, "sha256"):
                issues.append(
                    _issue(
                        "rendered_page_hash_mismatch",
                        "Rendered page hash does not match its current PNG bytes.",
                        f"render_manifest.pages[{index}].sha256",
                        frame_id=frame_id,
                    )
                )

        issues.extend(
            _probe_attestation_issues(
                frame, page, index, duplicate_storyboard_slot_ids
            )
        )

    if len(pages) > len(frames):
        for index in range(len(frames), len(pages)):
            issues.append(
                _issue(
                    "unexpected_rendered_page",
                    "Render manifest contains a page with no storyboard frame.",
                    f"render_manifest.pages[{index}]",
                    frame_id=str(_get_value(pages[index], "frame_id") or "") or None,
                )
            )
    return issues


def _font_issues(render_manifest: Any) -> list[RenderQAIssue]:
    fonts = _get_value(render_manifest, "fonts")
    families = set(str(value) for value in _as_list(fonts, "computed_families"))
    if _get_value(fonts, "all_loaded") is True and families == EXPECTED_FONT_FAMILIES:
        return []
    return [
        _issue(
            "font_family_mismatch",
            "Every page must use the three exact project-local font families without fallback.",
            "render_manifest.fonts",
        )
    ]


def _asset_issues(
    frames: list[Any],
    asset_manifest: Any,
    render_manifest: Any,
    visual_plan: Any = None,
    storyboard_slot_occurrences: dict[
        str, list[tuple[int, int, Any, Any]]
    ] | None = None,
    duplicate_storyboard_slot_ids: set[str] | None = None,
    *,
    allow_pending_external: bool = False,
) -> list[RenderQAIssue]:
    issues: list[RenderQAIssue] = []
    items = _as_list(asset_manifest, "items")
    storyboard_slot_occurrences = storyboard_slot_occurrences or {}
    duplicate_storyboard_slot_ids = duplicate_storyboard_slot_ids or set()
    item_occurrences: dict[str, list[tuple[int, Any]]] = {}
    for item_index, item in enumerate(items):
        slot_id = str(_get_value(item, "slot_id") or "")
        item_occurrences.setdefault(slot_id, []).append((item_index, item))
    duplicate_item_slot_ids = {
        slot_id for slot_id, values in item_occurrences.items() if len(values) > 1
    }
    for slot_id, values in item_occurrences.items():
        if slot_id not in duplicate_item_slot_ids:
            continue
        for index, _item in values[1:]:
            issues.append(
                _issue(
                    "duplicate_asset_manifest_slot_id",
                    "AssetManifest slot IDs must be unique before asset mapping.",
                    f"asset_manifest.items[{index}].slot_id",
                )
            )
    auditable_items = list(enumerate(items))
    item_by_slot = {
        slot_id: values[0][1]
        for slot_id, values in item_occurrences.items()
        if slot_id not in duplicate_item_slot_ids
    }
    frame_by_slot = {
        slot_id: values[0][2]
        for slot_id, values in storyboard_slot_occurrences.items()
        if slot_id not in duplicate_storyboard_slot_ids
    }
    rendered_hashes = _get_value(render_manifest, "source_asset_sha256", {})
    if not isinstance(rendered_hashes, dict):
        rendered_hashes = {}
    storyboard_slot_ids = set(frame_by_slot)
    manifest_slot_ids = set(item_by_slot)
    if storyboard_slot_ids != manifest_slot_ids:
        issues.append(
            _issue(
                "asset_manifest_slot_set_mismatch",
                "AssetManifest slot IDs must exactly equal the declared storyboard slot IDs.",
                "asset_manifest.items",
            )
        )

    for index, item in auditable_items:
        slot_id = str(_get_value(item, "slot_id") or "")
        frame = frame_by_slot.get(slot_id)
        frame_id = str(_get_value(frame, "frame_id") or "") or None
        location = f"asset_manifest.items[{index}]"
        for field, rule_id in (
            ("source_type", "asset_source_type_provenance_missing"),
            ("license", "asset_license_provenance_missing"),
        ):
            if _get_value(item, field):
                continue
            issues.append(
                _issue(
                    rule_id,
                    f"Every rendered asset needs explicit {field} provenance.",
                    f"{location}.{field}",
                    frame_id=frame_id,
                )
            )
        source_type = str(_get_value(item, "source_type") or "")
        is_reviewable_pending = (
            allow_pending_external
            and _get_value(item, "status") == "pending_external"
            and bool(_get_value(item, "pending_id"))
            and bool(_get_value(item, "metadata_path"))
        )
        if source_type and source_type not in {"local", "local_catalog"}:
            for field, rule_id in (
                ("provider", "asset_provider_provenance_missing"),
                ("source_url", "asset_source_url_provenance_missing"),
                ("author", "asset_author_provenance_missing"),
            ):
                if not _get_value(item, field):
                    issues.append(
                        _issue(
                            rule_id,
                            f"External assets need {field} provenance.",
                            f"{location}.{field}",
                            frame_id=frame_id,
                        )
                    )
            if (
                not is_reviewable_pending
                and _get_value(item, "review_status") != "approved"
            ):
                issues.append(
                    _issue(
                        "asset_publishing_review_not_approved",
                        "External assets need an approved publishing-safety review.",
                        f"{location}.review_status",
                        frame_id=frame_id,
                    )
                )
            if (
                not is_reviewable_pending
                and _get_value(item, "review_disposition")
                != "approved_for_publishing"
            ):
                issues.append(
                    _issue(
                        "asset_publishing_disposition_not_approved",
                        "External assets must be explicitly approved for publishing.",
                        f"{location}.review_disposition",
                        frame_id=frame_id,
                    )
                )
        if (
            not is_reviewable_pending
            and (
                source_type not in {"", "local", "local_catalog"}
                or bool(_as_list(item, "unresolved_safety_checks"))
                or bool(_get_value(item, "safety_review_decisions", {}))
                or bool(_get_value(item, "safety_reviewed_at"))
                or bool(_get_value(item, "review_status"))
                or bool(_get_value(item, "review_disposition"))
            )
            and not _safety_review_is_resolved(item)
        ):
            issues.append(
                _issue(
                    "asset_safety_checks_unresolved",
                    "Rendered assets cannot retain unresolved publishing-safety checks.",
                    f"{location}.unresolved_safety_checks",
                    frame_id=frame_id,
                )
            )

        raw_path = _get_value(item, "path")
        try:
            path = Path(raw_path)
        except TypeError:
            path = Path("")
        if raw_path and ("://" in str(raw_path) or not path.is_absolute()):
            issues.append(
                _issue(
                    "asset_path_not_local",
                    "Rendered asset sources must use absolute local file paths.",
                    f"{location}.path",
                    frame_id=frame_id,
                )
            )
            continue
        if not raw_path or not path.is_file():
            issues.append(
                _issue(
                    "asset_file_missing",
                    "Rendered asset source file is missing.",
                    f"{location}.path",
                    frame_id=frame_id,
                )
            )
            continue

        snapshot = _asset_snapshot(path)
        if snapshot is None:
            issues.append(
                _issue(
                    "asset_file_corrupt",
                    "Rendered asset source must be completely decodable.",
                    f"{location}.path",
                    frame_id=frame_id,
                )
            )
            continue
        actual_hash, intrinsic = snapshot
        declared_hash = str(_get_value(item, "sha256") or "")
        if actual_hash != declared_hash:
            issues.append(
                _issue(
                    "asset_source_hash_mismatch",
                    "Asset manifest hash does not match the current source bytes.",
                    f"{location}.sha256",
                    frame_id=frame_id,
                )
            )
        if (
            slot_id not in duplicate_item_slot_ids
            and rendered_hashes.get(slot_id) != actual_hash
        ):
            issues.append(
                _issue(
                    "rendered_asset_hash_mismatch",
                    "Rendered source hash must match the active AssetManifest item.",
                    f"render_manifest.source_asset_sha256.{slot_id}",
                    frame_id=frame_id,
                )
            )

        declared_dimensions = (
            _get_value(item, "width"),
            _get_value(item, "height"),
        )
        if intrinsic is None or intrinsic != declared_dimensions:
            issues.append(
                _issue(
                    "asset_stretching_detected",
                    "Asset intrinsic dimensions must match manifest geometry before rendering.",
                    f"{location}.width",
                    frame_id=frame_id,
                )
            )

        if visual_plan is not None:
            matching_requirements = [
                requirement
                for requirement in _as_list(visual_plan, "required_assets")
                if _get_value(requirement, "slot_id") == slot_id
            ]
            if len(matching_requirements) == 1:
                requirement = matching_requirements[0]
                if intrinsic[0] < int(_get_value(requirement, "min_width") or 0) or intrinsic[
                    1
                ] < int(_get_value(requirement, "min_height") or 0):
                    issues.append(
                        _issue(
                            "asset_min_dimensions_unmet",
                            "Asset source snapshot does not meet VisualPlan minimum dimensions.",
                            f"{location}.width",
                            frame_id=frame_id,
                        )
                    )

        frame_index = (
            storyboard_slot_occurrences[slot_id][0][0]
            if slot_id in storyboard_slot_occurrences
            and slot_id not in duplicate_storyboard_slot_ids
            else None
        )
        pages = _as_list(render_manifest, "pages")
        if (
            slot_id not in duplicate_item_slot_ids
            and frame_index is not None
            and frame_index < len(pages)
        ):
            probe = _get_value(pages[frame_index], "probe")
            probe_assets = [
                (result_index, result)
                for result_index, result in enumerate(
                    _as_list(probe, "asset_results")
                )
                if _get_value(result, "slot_id") == slot_id
            ]
            if len(probe_assets) == 1:
                result_index, result = probe_assets[0]
                natural = (
                    _get_value(result, "natural_width"),
                    _get_value(result, "natural_height"),
                )
                if natural != intrinsic:
                    issues.append(
                        _issue(
                            "asset_probe_natural_dimensions_mismatch",
                            "Persisted DOM natural dimensions must match decoded source bytes.",
                            f"render_manifest.pages[{frame_index}].probe.asset_results[{result_index}].natural_width",
                            frame_id=frame_id,
                        )
                    )

    for slot_id, frame in frame_by_slot.items():
        frame_id = str(_get_value(frame, "frame_id") or "") or None
        item = item_by_slot.get(slot_id)
        if item is None:
            if slot_id in duplicate_item_slot_ids:
                continue
            issues.append(
                _issue(
                    "asset_manifest_slot_missing",
                    "Every rendered storyboard slot needs one AssetManifest item.",
                    f"asset_manifest.items.{slot_id}",
                    frame_id=frame_id,
                )
            )
            continue
        slot = next(
            slot
            for slot in _as_list(frame, "visual_slots")
            if _get_value(slot, "slot_id") == slot_id
        )
        if (
            _get_value(item, "role") != _get_value(slot, "role")
            or _get_value(item, "page_archetype")
            != _get_value(frame, "page_archetype")
        ):
            issues.append(
                _issue(
                    "asset_slot_binding_mismatch",
                    "Manifest role and page_archetype must exactly match the storyboard slot binding.",
                    f"asset_manifest.items.{slot_id}",
                    frame_id=frame_id,
                )
            )
    return issues


def _contact_sheet_issues(render_manifest: Any) -> list[RenderQAIssue]:
    raw_path = _get_value(render_manifest, "contact_sheet_path")
    try:
        path = Path(raw_path)
    except TypeError:
        path = Path("")
    location = "render_manifest.contact_sheet_path"
    if not raw_path or not path.is_file():
        return [
            _issue(
                "contact_sheet_missing",
                "Render QA requires a generated PNG contact sheet.",
                location,
            )
        ]
    snapshot = _png_snapshot(path)
    if snapshot is None:
        return [
            _issue(
                "contact_sheet_corrupt",
                "Contact sheet must be a completely decodable PNG.",
                location,
            )
        ]
    issues: list[RenderQAIssue] = []
    actual_sha256, _ = snapshot
    if actual_sha256 != _get_value(render_manifest, "contact_sheet_sha256"):
        issues.append(
            _issue(
                "contact_sheet_hash_mismatch",
                "Contact-sheet hash does not match its current PNG bytes.",
                "render_manifest.contact_sheet_sha256",
            )
        )
    ordered_page_hashes = [
        _get_value(page, "sha256") for page in _as_list(render_manifest, "pages")
    ]
    if _as_list(render_manifest, "contact_sheet_page_sha256") != ordered_page_hashes:
        issues.append(
            _issue(
                "contact_sheet_page_binding_mismatch",
                "Contact sheet must bind the ordered rendered-page hashes.",
                "render_manifest.contact_sheet_page_sha256",
            )
        )
    return issues


def validate_render(
    package: dict,
    asset_manifest: Any,
    render_manifest: Any,
    visual_plan: Any = None,
    *,
    allow_pending_external: bool = False,
) -> list[RenderQAIssue]:
    """Return atomic deterministic editorial render violations."""

    raw_frames = package.get("storyboards")
    frames = raw_frames if isinstance(raw_frames, list) else []
    (
        storyboard_slot_issues,
        storyboard_slot_occurrences,
        duplicate_storyboard_slot_ids,
    ) = _storyboard_slot_audit(frames)
    issues: list[RenderQAIssue] = list(storyboard_slot_issues)
    issues.extend(
        _manifest_page_issues(
            frames, render_manifest, duplicate_storyboard_slot_ids
        )
    )
    issues.extend(_font_issues(render_manifest))
    issues.extend(
        _asset_issues(
            frames,
            asset_manifest,
            render_manifest,
            visual_plan,
            storyboard_slot_occurrences,
            duplicate_storyboard_slot_ids,
            allow_pending_external=allow_pending_external,
        )
    )
    issues.extend(_contact_sheet_issues(render_manifest))
    render_error = package.get("render_error")
    if render_error:
        issues.append(
            _issue(
                "local_render_failed",
                f"Editorial rendering failed: {render_error}",
                "publish_package.render_error",
            )
        )
    return issues


def _score(values: list[bool]) -> int:
    return round(100 * sum(values) / len(values)) if values else 0


def _quality_proxy_metrics(
    package: dict,
    asset_manifest: Any,
    render_manifest: Any,
    visual_plan: Any = None,
) -> dict[str, int]:
    frames = package.get("storyboards")
    frames = frames if isinstance(frames, list) else []
    pages = _as_list(render_manifest, "pages")
    items = _as_list(asset_manifest, "items")
    item_by_slot = {_get_value(item, "slot_id"): item for item in items}
    fonts = _get_value(render_manifest, "fonts")
    font_fact = (
        _get_value(fonts, "all_loaded") is True
        and set(str(value) for value in _as_list(fonts, "computed_families"))
        == EXPECTED_FONT_FAMILIES
    )

    requirements = {
        _get_value(requirement, "slot_id"): requirement
        for requirement in _as_list(visual_plan, "required_assets")
    }
    probe_assets = {
        _get_value(result, "slot_id"): result
        for page in pages
        for result in _as_list(_get_value(page, "probe"), "asset_results")
    }
    category_scores: list[float] = []
    for frame in frames:
        for slot in _as_list(frame, "visual_slots"):
            item = item_by_slot.get(_get_value(slot, "slot_id"))
            role_fit = (
                item is not None
                and _get_value(item, "role") == _get_value(slot, "role")
                and _get_value(item, "page_archetype")
                == _get_value(frame, "page_archetype")
            )
            requirement = requirements.get(_get_value(slot, "slot_id"))
            measured = probe_assets.get(_get_value(slot, "slot_id"))
            headroom = 0.0
            if requirement is not None and measured is not None:
                width_ratio = float(_get_value(measured, "natural_width") or 0) / max(
                    1, float(_get_value(requirement, "min_width") or 1)
                )
                height_ratio = float(_get_value(measured, "natural_height") or 0) / max(
                    1, float(_get_value(requirement, "min_height") or 1)
                )
                headroom = min(1.0, max(0.0, min(width_ratio, height_ratio) - 1.0))
            category_scores.append((70.0 if role_fit else 0.0) + 30.0 * headroom)
    beauty_category_fit = round(statistics.mean(category_scores)) if category_scores else 0

    page_identity_facts = [
        index < len(pages)
        and (
            _get_value(page, "frame_id"),
            _get_value(page, "role"),
            _get_value(page, "page_archetype"),
        )
        == (
            _get_value(frame, "frame_id"),
            _get_value(frame, "role"),
            _get_value(frame, "page_archetype"),
        )
        for index, frame in enumerate(frames)
        for page in [pages[index] if index < len(pages) else None]
    ]
    hashes = _get_value(render_manifest, "source_asset_sha256", {})
    hash_fact = isinstance(hashes, dict) and all(
        hashes.get(_get_value(item, "slot_id")) == _get_value(item, "sha256")
        for item in items
    )
    headline_sizes = [
        float(_get_value(text, "font_size") or 0)
        for page in pages
        for text in _as_list(_get_value(page, "probe"), "text_results")
        if _get_value(text, "role") == "headline"
    ]
    if headline_sizes and statistics.mean(headline_sizes) > 0:
        coefficient = statistics.pstdev(headline_sizes) / statistics.mean(
            headline_sizes
        )
        type_consistency = max(0, round(100 * (1 - min(1.0, coefficient * 4))))
    else:
        type_consistency = 0
    page_binding_fact = _as_list(
        render_manifest, "contact_sheet_page_sha256"
    ) == [_get_value(page, "sha256") for page in pages]
    cross_page_consistency = round(
        statistics.mean(
            [
                type_consistency,
                100 if font_fact else 0,
                100 if hash_fact else 0,
                100 if page_binding_fact else 0,
                _score(page_identity_facts),
            ]
        )
    )

    cover = frames[0] if frames else None
    hierarchy_scores: list[float] = []
    for page in pages:
        texts = _as_list(_get_value(page, "probe"), "text_results")
        headlines = [
            float(_get_value(text, "font_size") or 0)
            for text in texts
            if _get_value(text, "role") == "headline"
        ]
        bodies = [
            float(_get_value(text, "font_size") or 0)
            for text in texts
            if ".body" in str(_get_value(text, "role") or "")
            or ".items[" in str(_get_value(text, "role") or "")
        ]
        if headlines and bodies and statistics.mean(bodies) > 0:
            separation = headlines[0] / statistics.mean(bodies)
            hierarchy_scores.append(min(100.0, max(0.0, (separation - 1.0) * 80)))
    scale_hierarchy = (
        statistics.mean(hierarchy_scores) if hierarchy_scores else 0.0
    )
    visual_hierarchy = round(
        0.8 * scale_hierarchy
        + 10 * (_get_value(cover, "page_archetype") == "cover")
        + 10 * bool(_get_value(cover, "headline"))
    )
    saveable_item_counts = [
        sum(len(_as_list(block, "items")) for block in _as_list(frame, "content_blocks"))
        for frame in frames
        if _get_value(frame, "page_archetype") in SAVEABLE_ARCHETYPES
    ]
    saveability = min(100, 20 * max(saveable_item_counts, default=0))

    archetypes = [
        str(_get_value(frame, "page_archetype") or "") for frame in frames
    ]
    template_stiffness = round(
        100
        * (len(archetypes) - len(set(archetypes)))
        / max(1, len(archetypes))
    )
    visible_character_counts = [
        sum(
            len(str(_get_value(text, "text") or ""))
            for text in _as_list(_get_value(page, "probe"), "text_results")
        )
        for page in pages
    ]
    text_density_score = (
        max(0, round(100 - statistics.mean(visible_character_counts) * 0.7))
        if visible_character_counts
        else 0
    )
    editorial_quality = round(
        (
            beauty_category_fit
            + visual_hierarchy
            + saveability
            + cross_page_consistency
            + (100 - template_stiffness)
            + text_density_score
        )
        / 6
    )
    return {
        "editorial_quality": editorial_quality,
        "beauty_category_fit": beauty_category_fit,
        "visual_hierarchy": visual_hierarchy,
        "saveability": saveability,
        "cross_page_consistency": cross_page_consistency,
        "template_stiffness": template_stiffness,
    }


def _build_r1_decision(
    package: dict,
    issues: list[RenderQAIssue],
    narrative_plan: NarrativePlan | None = None,
) -> DecisionOutput:
    draft_id = str(package.get("draft_id") or package.get("topic_id") or "render_qa")
    authoritative_narrative = narrative_plan or NarrativePlan.model_validate(
        package.get("narrative_plan")
    )

    def task_id(issue: RenderQAIssue) -> str:
        identity = "|".join(
            (
                "render_qa",
                issue.rule_id,
                issue.frame_id or "",
                issue.location_hint,
            )
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
        return f"render_qa_{issue.rule_id}_{digest}"

    tasks = EditorialTasks(
        mandatory=[
            SingleTask(
                task_id=task_id(issue),
                source="render_qa",
                instruction=issue.message,
                severity="high",
                location_hint=issue.location_hint,
                rationale="Generated-file QA blocked human review.",
            )
            for issue in issues
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
            narrative_plan=authoritative_narrative,
            storyboard_visible_text=extract_storyboard_visible_text(
                package.get("storyboards")
            ),
        ),
        editorial_tasks=tasks,
        revision_meta=RevisionMeta(
            revision_id=f"render_qa_{draft_id}",
            round=1,
            diff_summary=[f"render_qa_failed:{issue.rule_id}" for issue in issues],
            next_actions=["repair_render_qa_issues", "rerun_editorial_renderer"],
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

    asset_manifest = state.get("asset_manifest")
    render_manifest = state.get("render_manifest")
    visual_plan = state.get("visual_plan")
    issues = []
    if visual_plan is None:
        issues.append(
            _issue(
                "visual_plan_missing",
                "Editorial render QA requires the persisted VisualPlan.",
                "visual_plan",
            )
        )
    if asset_manifest is None:
        issues.append(
            _issue(
                "asset_manifest_missing",
                "Editorial render QA requires the persisted AssetManifest.",
                "asset_manifest",
            )
        )
    if render_manifest is None:
        issues.append(
            _issue(
                "render_manifest_missing",
                "Editorial render QA requires the persisted RenderManifest.",
                "render_manifest",
            )
        )
    if not issues:
        issues = validate_render(
            package,
            asset_manifest,
            render_manifest,
            visual_plan,
            allow_pending_external=state.get("review_status") != "approved",
        )
        metrics = (
            {
                "metrics_available": True,
                **_quality_proxy_metrics(
                    package, asset_manifest, render_manifest, visual_plan
                ),
            }
            if not issues
            else {}
        )
    else:
        metrics = {}
    result = RenderQAResult(passed=not issues, issues=issues, **metrics)
    output = {"render_qa_result": result, "current_node": "RENDER_QA"}
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
                    "render_qa_node requires selected_narrative_plan to "
                    "recover an invalid publish_package.narrative_plan."
                ) from selected_error
        output["decision_output"] = _build_r1_decision(
            package,
            issues,
            r1_narrative_plan,
        )
    return output


def route_after_render_qa(state: AgentState) -> str:
    result = state.get("render_qa_result")
    passed = _get_value(result, "passed")
    if passed is True:
        return "human_review"
    if passed is False:
        return "r1_reflector"
    raise ValueError("route_after_render_qa requires render_qa_result.")
