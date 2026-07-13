from __future__ import annotations

import hashlib
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from PIL import Image
from pydantic import ValidationError

from src.editorial_carousel.strategy import ASSET_ADAPTER
from src.nodes.node_p_carousel_qa import _get_value, _selected_content_contract
from src.nodes.node_p_text_card_renderer import PUBLISH_ROOT
from src.nodes.publish_patch import extract_storyboard_visible_text
from src.rendering.editorial.probes import EXPECTED_FONT_FAMILIES
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
SAVEABLE_LAYOUTS = frozenset({"saveable_checklist", "saveable_reference"})


def _as_list(payload: Any, key: str) -> list[Any]:
    value = _get_value(payload, key, [])
    return list(value) if isinstance(value, (list, tuple)) else []


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


def _asset_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        if path.suffix.lower() == ".svg":
            root = ET.parse(path).getroot()
            return int(float(root.attrib["width"])), int(float(root.attrib["height"]))
        with Image.open(path) as image:
            return image.size
    except (ET.ParseError, KeyError, OSError, ValueError):
        return None


def _page_has_exact_dimensions(page: Any) -> bool:
    raw_path = _get_value(page, "path")
    try:
        path = Path(raw_path)
    except TypeError:
        return False
    return (
        bool(raw_path)
        and _png_dimensions(path) == (1080, 1440)
        and _get_value(page, "width") == 1080
        and _get_value(page, "height") == 1440
    )


def _visible_text(frame: Any) -> list[str]:
    values: list[str] = []
    kicker = _get_value(frame, "kicker")
    if kicker:
        values.append(str(kicker))
    headline = _get_value(frame, "headline")
    if headline:
        values.append(str(headline))
    for block in _as_list(frame, "content_blocks"):
        heading = _get_value(block, "heading")
        body = _get_value(block, "body")
        if heading:
            values.append(str(heading))
        if body:
            values.append(str(body))
        values.extend(str(item) for item in _as_list(block, "items"))
    footer = _get_value(frame, "footer")
    if footer:
        values.append(str(footer))
    return values


def _frame_by_slot(frames: list[Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for frame in frames:
        for slot in _as_list(frame, "visual_slots"):
            slot_id = _get_value(slot, "slot_id")
            if isinstance(slot_id, str) and slot_id:
                result[slot_id] = frame
    return result


def _manifest_page_issues(
    frames: list[Any], render_manifest: Any
) -> list[RenderQAIssue]:
    issues: list[RenderQAIssue] = []
    pages = _as_list(render_manifest, "pages")
    if len(pages) != len(frames):
        issues.append(
            _issue(
                "rendered_page_count_mismatch",
                "Render manifest page count must match the storyboard frame count.",
                "render_manifest.pages",
            )
        )

    missing_page = False
    for index, frame in enumerate(frames):
        frame_id = str(_get_value(frame, "frame_id") or "") or None
        if index >= len(pages):
            missing_page = True
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
        expected = (
            _get_value(frame, "frame_id"),
            _get_value(frame, "role"),
            _get_value(frame, "layout"),
        )
        actual = (
            _get_value(page, "frame_id"),
            _get_value(page, "role"),
            _get_value(page, "layout"),
        )
        if actual != expected:
            issues.append(
                _issue(
                    "rendered_page_order_mismatch",
                    "Rendered page identity, role, and layout must match storyboard order.",
                    f"render_manifest.pages[{index}]",
                    frame_id=frame_id,
                )
            )

        raw_path = _get_value(page, "path")
        try:
            path = Path(raw_path)
        except TypeError:
            path = Path("")
        if not raw_path or not path.is_file():
            missing_page = True
            issues.append(
                _issue(
                    "rendered_page_missing",
                    "Rendered page file is missing.",
                    f"render_manifest.pages[{index}].path",
                    frame_id=frame_id,
                )
            )
            continue

        dimensions = _png_dimensions(path)
        if dimensions is None:
            issues.append(
                _issue(
                    "png_signature_invalid",
                    "Rendered page must be a PNG with a valid IHDR header.",
                    f"render_manifest.pages[{index}].path",
                    frame_id=frame_id,
                )
            )
        elif not _page_has_exact_dimensions(page):
            issues.append(
                _issue(
                    "png_dimensions_invalid",
                    f"Rendered page must be 1080x1440; got {dimensions[0]}x{dimensions[1]}.",
                    f"render_manifest.pages[{index}].path",
                    frame_id=frame_id,
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
    if missing_page:
        issues.append(
            _issue(
                "partial_render_output",
                "The renderer left a partial output set; rerender the complete carousel.",
                "render_manifest.pages",
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


def _diagnostic_issues(package: dict) -> list[RenderQAIssue]:
    issues: list[RenderQAIssue] = []
    diagnostics = package.get("render_diagnostics")
    if diagnostics is None:
        return issues
    if not isinstance(diagnostics, list):
        return [
            _issue(
                "render_diagnostics_invalid",
                "Render diagnostics must be a list of deterministic probe findings.",
                "publish_package.render_diagnostics",
            )
        ]
    overflow_kinds = {
        "overflow",
        "ink_clip",
        "layout_clip",
        "hidden_copy",
        "headline_lines",
    }
    for index, diagnostic in enumerate(diagnostics):
        kind = str(_get_value(diagnostic, "kind") or "")
        frame_id = str(_get_value(diagnostic, "frame_id") or "") or None
        role = str(_get_value(diagnostic, "role") or "unknown")
        if kind in overflow_kinds:
            issues.append(
                _issue(
                    "text_overflow",
                    f"Rendered copy failed the {kind} probe at {role}.",
                    f"publish_package.render_diagnostics[{index}]",
                    frame_id=frame_id,
                )
            )
        elif kind:
            issues.append(
                _issue(
                    "render_token_violation",
                    f"Rendered page failed deterministic {kind} token validation.",
                    f"publish_package.render_diagnostics[{index}]",
                    frame_id=frame_id,
                )
            )
    return issues


def _visible_text_issues(package: dict, frames: list[Any]) -> list[RenderQAIssue]:
    rendered = package.get("rendered_visible_text")
    if rendered is None:
        # The Task 6 renderer creates pages directly from the storyboard and only
        # returns a manifest after its copy probes pass. Task 8 may additionally
        # persist the explicit audit mapping handled below.
        return []
    if not isinstance(rendered, dict):
        return [
            _issue(
                "rendered_visible_text_invalid",
                "Rendered visible-text audit must be keyed by frame_id.",
                "publish_package.rendered_visible_text",
            )
        ]
    issues: list[RenderQAIssue] = []
    for frame in frames:
        frame_id = str(_get_value(frame, "frame_id") or "")
        actual = rendered.get(frame_id)
        expected = _visible_text(frame)
        if actual != expected:
            issues.append(
                _issue(
                    "rendered_visible_text_mismatch",
                    "Rendered visible text must exactly equal the storyboard strings.",
                    f"publish_package.rendered_visible_text.{frame_id}",
                    frame_id=frame_id or None,
                )
            )
    return issues


def _asset_issues(
    frames: list[Any], asset_manifest: Any, render_manifest: Any
) -> list[RenderQAIssue]:
    issues: list[RenderQAIssue] = []
    items = _as_list(asset_manifest, "items")
    item_by_slot = {_get_value(item, "slot_id"): item for item in items}
    frame_by_slot = _frame_by_slot(frames)
    rendered_hashes = _get_value(render_manifest, "source_asset_sha256", {})
    if not isinstance(rendered_hashes, dict):
        rendered_hashes = {}

    for index, item in enumerate(items):
        slot_id = str(_get_value(item, "slot_id") or "")
        frame = frame_by_slot.get(slot_id)
        frame_id = str(_get_value(frame, "frame_id") or "") or None
        location = f"asset_manifest.items[{index}]"
        if not _get_value(item, "source_type") or not _get_value(item, "license"):
            issues.append(
                _issue(
                    "asset_provenance_missing",
                    "Every rendered asset needs explicit source type and license provenance.",
                    location,
                    frame_id=frame_id,
                )
            )
        source_type = str(_get_value(item, "source_type") or "")
        if source_type not in {"local", "local_catalog"} and not all(
            _get_value(item, field) for field in ("provider", "source_url", "author")
        ):
            issues.append(
                _issue(
                    "asset_provenance_missing",
                    "External assets need provider, source URL, and author provenance.",
                    location,
                    frame_id=frame_id,
                )
            )

        raw_path = _get_value(item, "path")
        try:
            path = Path(raw_path)
        except TypeError:
            path = Path("")
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

        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
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
        if rendered_hashes.get(slot_id) != declared_hash:
            issues.append(
                _issue(
                    "rendered_asset_hash_mismatch",
                    "Rendered source hash must match the active AssetManifest item.",
                    f"render_manifest.source_asset_sha256.{slot_id}",
                    frame_id=frame_id,
                )
            )

        intrinsic = _asset_dimensions(path)
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

    for slot_id, frame in frame_by_slot.items():
        frame_id = str(_get_value(frame, "frame_id") or "") or None
        item = item_by_slot.get(slot_id)
        if item is None:
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
        semantic_role = _get_value(slot, "role")
        layout = _get_value(frame, "layout")
        adapter = ASSET_ADAPTER.get((layout, semantic_role))
        if adapter is None or _get_value(item, "role") != adapter[0]:
            issues.append(
                _issue(
                    "asset_catalog_role_mismatch",
                    "Manifest role must equal the adapter's concrete catalog role for this semantic slot.",
                    f"asset_manifest.items.{slot_id}.role",
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
    if raw_path and path.is_file() and _png_dimensions(path) is not None:
        return []
    return [
        _issue(
            "contact_sheet_missing",
            "Render QA requires a generated PNG contact sheet.",
            "render_manifest.contact_sheet_path",
        )
    ]


def validate_render(
    package: dict,
    asset_manifest: Any,
    render_manifest: Any,
) -> list[RenderQAIssue]:
    """Return atomic deterministic editorial render violations."""

    raw_frames = package.get("storyboards")
    frames = raw_frames if isinstance(raw_frames, list) else []
    issues: list[RenderQAIssue] = []
    issues.extend(_manifest_page_issues(frames, render_manifest))
    issues.extend(_font_issues(render_manifest))
    issues.extend(_diagnostic_issues(package))
    issues.extend(_visible_text_issues(package, frames))
    issues.extend(_asset_issues(frames, asset_manifest, render_manifest))
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
    package: dict, asset_manifest: Any, render_manifest: Any
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

    category_facts: list[bool] = []
    for frame in frames:
        for slot in _as_list(frame, "visual_slots"):
            adapter = ASSET_ADAPTER.get(
                (_get_value(frame, "layout"), _get_value(slot, "role"))
            )
            item = item_by_slot.get(_get_value(slot, "slot_id"))
            category_facts.append(
                adapter is not None
                and item is not None
                and _get_value(item, "role") == adapter[0]
            )
    beauty_category_fit = _score(category_facts)

    page_identity_facts = [
        index < len(pages)
        and (
            _get_value(page, "frame_id"),
            _get_value(page, "role"),
            _get_value(page, "layout"),
        )
        == (
            _get_value(frame, "frame_id"),
            _get_value(frame, "role"),
            _get_value(frame, "layout"),
        )
        for index, frame in enumerate(frames)
        for page in [pages[index] if index < len(pages) else None]
    ]
    page_dimension_facts = [_page_has_exact_dimensions(page) for page in pages]
    hashes = _get_value(render_manifest, "source_asset_sha256", {})
    hash_fact = isinstance(hashes, dict) and all(
        hashes.get(_get_value(item, "slot_id")) == _get_value(item, "sha256")
        for item in items
    )
    cross_page_consistency = _score(
        [font_fact, hash_fact, *page_identity_facts, *page_dimension_facts]
    )

    cover = frames[0] if frames else None
    visual_hierarchy = _score(
        [
            _get_value(cover, "layout") == "editorial_cover",
            bool(_get_value(cover, "headline")),
            font_fact,
            bool(page_dimension_facts) and all(page_dimension_facts),
        ]
    )
    saveability = 100 if any(
        _get_value(frame, "layout") in SAVEABLE_LAYOUTS for frame in frames
    ) else 0

    layouts = [str(_get_value(frame, "layout") or "") for frame in frames]
    repeats = sum(
        layouts[index] == layouts[index - 1]
        for index in range(1, len(layouts))
    )
    template_stiffness = round(100 * repeats / max(1, len(layouts) - 1))
    editorial_quality = round(
        (
            beauty_category_fit
            + visual_hierarchy
            + saveability
            + cross_page_consistency
            + (100 - template_stiffness)
        )
        / 5
    )
    return {
        "editorial_quality": editorial_quality,
        "beauty_category_fit": beauty_category_fit,
        "visual_hierarchy": visual_hierarchy,
        "saveability": saveability,
        "cross_page_consistency": cross_page_consistency,
        "template_stiffness": template_stiffness,
    }


def _legacy_payload_issues(package: dict, state: AgentState) -> list[RenderQAIssue]:
    issues: list[RenderQAIssue] = []
    raw_storyboards = package.get("storyboards")
    try:
        TextCardPayload.model_validate({"storyboards": raw_storyboards})
    except ValidationError as exc:
        issues.append(
            _issue(
                "text_card_schema_invalid",
                f"Rendered cards require schema-valid text-card storyboards: {exc.errors()[0]['msg']}",
                "publish_package.storyboards",
            )
        )
    frames = raw_storyboards if isinstance(raw_storyboards, list) else []
    cover = frames[0] if frames else None
    contract = _selected_content_contract(state, package)
    if str(_get_value(cover, "headline") or "") != contract.first_screen_promise:
        issues.append(
            _issue(
                "first_screen_promise_mismatch",
                "The cover headline must exactly equal the selected first-screen promise.",
                "publish_package.storyboards[0].headline",
            )
        )
    return issues


def validate_rendered_images(package: dict, state: AgentState) -> list[RenderQAIssue]:
    """Checkpoint-only validation for the pre-Task-8 fixed-card graph."""

    issues = _legacy_payload_issues(package, state)
    if package.get("render_error"):
        issues.append(
            _issue(
                "local_render_failed",
                f"Local text-card rendering failed: {package['render_error']}",
                "publish_package.rendered_image_paths",
            )
        )
    raw_paths = package.get("rendered_image_paths")
    paths = raw_paths if isinstance(raw_paths, list) else []
    if len(paths) != len(EXPECTED_FILENAMES):
        issues.append(
            _issue(
                "rendered_image_count_invalid",
                "Legacy local rendering must produce exactly six PNG files.",
                "publish_package.rendered_image_paths",
            )
        )
    publish_root = PUBLISH_ROOT.resolve()
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
        try:
            path = Path(paths[index]).resolve()
        except (OSError, TypeError, ValueError):
            issues.append(
                _issue(
                    "png_path_invalid",
                    "Generated PNG path cannot be resolved.",
                    f"publish_package.rendered_image_paths[{index}]",
                )
            )
            continue
        if not path.is_relative_to(publish_root):
            issues.append(
                _issue(
                    "png_outside_publish_root",
                    "Generated PNG must remain inside outputs/publish.",
                    f"publish_package.rendered_image_paths[{index}]",
                )
            )
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
                    f"Generated PNG is missing: {expected_name}.",
                    f"publish_package.rendered_image_paths[{index}]",
                )
            )
            continue
        dimensions = _png_dimensions(path)
        if dimensions is None:
            issues.append(
                _issue(
                    "png_signature_or_ihdr_invalid",
                    f"Generated file {path.name} is not a valid PNG.",
                    f"publish_package.rendered_image_paths[{index}]",
                )
            )
        elif dimensions != (CANVAS["width"], CANVAS["height"]):
            issues.append(
                _issue(
                    "png_dimensions_invalid",
                    f"Generated PNG {path.name} has invalid dimensions.",
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
    if asset_manifest is not None and render_manifest is not None:
        issues = validate_render(package, asset_manifest, render_manifest)
        metrics = _quality_proxy_metrics(package, asset_manifest, render_manifest)
    else:
        issues = validate_rendered_images(package, state)
        metrics = {}
    result = RenderQAResult(passed=not issues, issues=issues, **metrics)
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
