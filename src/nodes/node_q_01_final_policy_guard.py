from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from src.asset_resolver.catalog import load_catalog_bytes
from src.asset_resolver.eligibility import entry_satisfies_requirement
from src.asset_resolver.lifecycle import PendingAuditRecord
from src.asset_resolver.resolver import requirement_fingerprint
from src.domain import find_policy_violations
from src.rendering.editorial.design_system import ASSET_ROOT
from src.schemas import AgentState
from src.schemas.assets import AssetRequirement
from src.nodes.publish_patch import extract_storyboard_visible_text
from src.nodes.node_p_editorial_carousel_renderer import PUBLISH_ROOT


ASSET_ACTIVE_ROOT = ASSET_ROOT / "active"
RENDER_OUTPUT_ROOT = PUBLISH_ROOT

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
_URL_PATTERN = re.compile(r"https?://[^\s，。！？、；：)\]}>\"']+")


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
    for frame in extract_storyboard_visible_text(storyboards):
        text_fragments.extend(
            _coerce_text(value)
            for value in dict(frame.get("text_blocks") or {}).values()
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


def _secure_file_snapshot(path_value, trusted_root: Path):
    directory_descriptors: list[int] = []
    directory_bindings: list[tuple[int, str, tuple[int, int]]] = []
    descriptor: int | None = None
    try:
        raw_path = Path(path_value)
        root = Path(os.path.abspath(trusted_root))
        lexical_path = Path(
            os.path.abspath(raw_path if raw_path.is_absolute() else root / raw_path)
        )
        if not lexical_path.is_relative_to(root):
            return None
        relative_parts = lexical_path.relative_to(root).parts
        if not relative_parts or any(part in {"", ".", ".."} for part in relative_parts):
            return None
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | nofollow
        directory_descriptors.append(os.open(root.anchor, directory_flags))
        for component in root.parts[1:]:
            parent_descriptor = directory_descriptors[-1]
            child_descriptor = os.open(
                component,
                directory_flags,
                dir_fd=parent_descriptor,
            )
            opened_directory = os.fstat(child_descriptor)
            named_directory = os.stat(
                component,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISDIR(opened_directory.st_mode)
                or (opened_directory.st_dev, opened_directory.st_ino)
                != (named_directory.st_dev, named_directory.st_ino)
            ):
                os.close(child_descriptor)
                raise OSError("trusted root component identity changed")
            directory_bindings.append(
                (
                    parent_descriptor,
                    component,
                    (opened_directory.st_dev, opened_directory.st_ino),
                )
            )
            directory_descriptors.append(child_descriptor)
        for component in relative_parts[:-1]:
            parent_descriptor = directory_descriptors[-1]
            child_descriptor = os.open(
                component,
                directory_flags,
                dir_fd=parent_descriptor,
            )
            opened_directory = os.fstat(child_descriptor)
            named_directory = os.stat(
                component,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISDIR(opened_directory.st_mode)
                or (opened_directory.st_dev, opened_directory.st_ino)
                != (named_directory.st_dev, named_directory.st_ino)
            ):
                os.close(child_descriptor)
                raise OSError("artifact directory component identity changed")
            directory_bindings.append(
                (
                    parent_descriptor,
                    component,
                    (opened_directory.st_dev, opened_directory.st_ino),
                )
            )
            directory_descriptors.append(child_descriptor)
        descriptor = os.open(
            relative_parts[-1],
            os.O_RDONLY | nofollow,
            dir_fd=directory_descriptors[-1],
        )
    except (OSError, TypeError, ValueError):
        if descriptor is not None:
            os.close(descriptor)
        for directory_descriptor in reversed(directory_descriptors):
            os.close(directory_descriptor)
        return None
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            return None
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
        try:
            current = os.stat(
                relative_parts[-1],
                dir_fd=directory_descriptors[-1],
                follow_symlinks=False,
            )
        except OSError:
            return None
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            return None
        for parent_descriptor, component, identity in directory_bindings:
            try:
                current_directory = os.stat(
                    component,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except OSError:
                return None
            if (
                current_directory.st_dev,
                current_directory.st_ino,
            ) != identity:
                return None
        return (
            lexical_path,
            (opened.st_dev, opened.st_ino),
            hashlib.sha256(data).hexdigest(),
            data,
        )
    finally:
        if descriptor is not None:
            os.close(descriptor)
        for directory_descriptor in reversed(directory_descriptors):
            os.close(directory_descriptor)


def _secure_png_snapshot(path_value, trusted_root: Path):
    snapshot = _secure_file_snapshot(path_value, trusted_root)
    if snapshot is None:
        return None
    canonical, identity, digest, data = snapshot
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
            if image.format != "PNG":
                return None
    except (OSError, ValueError):
        return None
    return canonical, identity, digest


def _approved_audit_matches_canonical(
    item,
    entry,
    *,
    catalog_root: Path,
) -> bool:
    provenance = entry.provenance
    if provenance is None:
        return True
    incoming_root = (
        catalog_root / "incoming" / "external" / provenance.run_id
    )
    if not incoming_root.is_dir():
        return False
    matching_audits = []
    for metadata_path in incoming_root.glob("*.json"):
        snapshot = _secure_file_snapshot(metadata_path, incoming_root)
        if snapshot is None:
            continue
        try:
            audit = PendingAuditRecord.model_validate_json(
                snapshot[3],
                strict=True,
            )
        except (TypeError, ValueError):
            continue
        if (
            audit.review_status == "approved"
            and Path(str(audit.approved_path)) == entry.path
            and audit.pending_id
            and audit.provider == provenance.provider
            and audit.provider_asset_id == provenance.provider_asset_id
        ):
            matching_audits.append(audit)
    if len(matching_audits) != 1:
        return False
    audit = matching_audits[0]
    return (
        audit.sha256 == entry.sha256 == _value(item, "sha256")
        and audit.approved_sha256 == entry.sha256
        and audit.role == entry.role
        and audit.layout in entry.allowed_layouts
        and audit.layout == _value(item, "page_archetype")
        and audit.width == entry.width == _value(item, "width")
        and audit.height == entry.height == _value(item, "height")
        and tuple(audit.tags) == entry.tags
        and tuple(audit.fallback_roles) == entry.fallback_roles
        and audit.run_id == provenance.run_id == _value(item, "run_id")
        and audit.license == entry.license == _value(item, "license")
        and audit.source_type
        == provenance.source_type
        == _value(item, "source_type")
        and audit.provider == provenance.provider == _value(item, "provider")
        and audit.provider_asset_id
        == provenance.provider_asset_id
        == _value(item, "provider_asset_id")
        and audit.source_url == provenance.source_url == _value(item, "source_url")
        and audit.source_file_url
        == provenance.source_file_url
        == _value(item, "source_file_url")
        and audit.author == provenance.author == _value(item, "author")
        and audit.provider_attribution
        == dict(provenance.provider_attribution)
        == (_value(item, "provider_attribution", {}) or {})
        and audit.license_snapshot
        == provenance.license_snapshot
        == _value(item, "license_snapshot")
        and audit.license_snapshot_sha256
        == provenance.license_snapshot_sha256
        == _value(item, "license_snapshot_sha256")
        and audit.license_terms_url
        == provenance.license_terms_url
        == _value(item, "license_terms_url")
        and audit.acquired_at == provenance.acquired_at == _value(item, "acquired_at")
        and audit.average_hash
        == provenance.average_hash
        == _value(item, "average_hash")
        and audit.requirement_fingerprint
        == provenance.requirement_fingerprint
        == _value(item, "requirement_fingerprint")
        and list(audit.unresolved_safety_checks)
        == list(provenance.unresolved_safety_checks)
        == list(_value(item, "unresolved_safety_checks", []) or [])
        and audit.safety_review_decisions
        == dict(provenance.safety_review_decisions)
        == (_value(item, "safety_review_decisions", {}) or {})
        and audit.safety_reviewed_at
        == provenance.safety_reviewed_at
        == _value(item, "safety_reviewed_at")
        and audit.review_disposition
        == provenance.review_disposition
        == _value(item, "review_disposition")
        and _value(item, "review_status") == "approved"
    )


def _asset_item_matches_canonical(
    item,
    entry,
    *,
    catalog_root: Path,
    canonical_path: Path,
) -> bool:
    if (
        _value(item, "asset_id") != entry.asset_id
        or Path(os.path.abspath(_value(item, "path"))) != canonical_path
        or _value(item, "sha256") != entry.sha256
        or _value(item, "license") != entry.license
    ):
        return False
    provenance = entry.provenance
    if provenance is None:
        return (
            entry.ownership == "project_original"
            and entry.usage == "production"
            and bool(entry.tags)
            and _value(item, "page_archetype") in entry.allowed_layouts
            and _value(item, "width") == entry.width
            and _value(item, "height") == entry.height
            and (
                (_value(item, "status") == "active" and _value(item, "role") == entry.role)
                or _value(item, "status") == "fallback"
            )
            and _value(item, "source_type") == "local"
            and _value(item, "pending_id") is None
            and _value(item, "metadata_path") is None
            and _value(item, "candidate_rank") is None
            and _value(item, "attempt_number") is None
            and _value(item, "provider") is None
            and _value(item, "provider_asset_id") is None
            and _value(item, "source_url") is None
            and _value(item, "source_file_url") is None
            and _value(item, "author") is None
            and (_value(item, "provider_attribution", {}) or {}) == {}
            and _value(item, "license_snapshot") is None
            and _value(item, "license_snapshot_sha256") is None
            and _value(item, "license_terms_url") is None
            and _value(item, "run_id") is None
            and _value(item, "acquired_at") is None
            and _value(item, "average_hash") is None
            and _value(item, "requirement_fingerprint") is None
            and list(_value(item, "unresolved_safety_checks", []) or []) == []
            and (_value(item, "safety_review_decisions", {}) or {}) == {}
            and _value(item, "safety_reviewed_at") is None
            and _value(item, "review_status") is None
            and _value(item, "review_disposition") is None
        )
    if (
        entry.ownership != "licensed_stock"
        or entry.usage != "production"
        or not entry.tags
        or _value(item, "page_archetype") not in entry.allowed_layouts
        or _value(item, "width") != entry.width
        or _value(item, "height") != entry.height
        or (
            _value(item, "status") == "active"
            and _value(item, "role") != entry.role
        )
    ):
        return False
    fields = (
        ("source_type", provenance.source_type),
        ("provider", provenance.provider),
        ("provider_asset_id", provenance.provider_asset_id),
        ("source_url", provenance.source_url),
        ("source_file_url", provenance.source_file_url),
        ("author", provenance.author),
        ("license_snapshot", provenance.license_snapshot),
        ("license_snapshot_sha256", provenance.license_snapshot_sha256),
        ("license_terms_url", provenance.license_terms_url),
        ("run_id", provenance.run_id),
        ("acquired_at", provenance.acquired_at),
        ("average_hash", provenance.average_hash),
        ("requirement_fingerprint", provenance.requirement_fingerprint),
        ("safety_reviewed_at", provenance.safety_reviewed_at),
        ("review_disposition", provenance.review_disposition),
    )
    return (
        all(_value(item, field_name) == expected for field_name, expected in fields)
        and (_value(item, "provider_attribution", {}) or {})
        == dict(provenance.provider_attribution)
        and list(_value(item, "unresolved_safety_checks", []) or [])
        == list(provenance.unresolved_safety_checks)
        and (_value(item, "safety_review_decisions", {}) or {})
        == dict(provenance.safety_review_decisions)
        and _approved_audit_matches_canonical(
            item,
            entry,
            catalog_root=catalog_root,
        )
    )


def _canonical_requirement(payload) -> AssetRequirement | None:
    try:
        return AssetRequirement.model_validate(
            {
                field_name: _value(payload, field_name)
                for field_name in AssetRequirement.model_fields
            }
        )
    except (TypeError, ValueError):
        return None


def _legacy_eligibility_view(requirement: AssetRequirement):
    """Bridge the Task 6 v2 requirement into the Task 7-owned eligibility API."""

    return SimpleNamespace(
        **requirement.model_dump(mode="python"),
        layout=requirement.page_archetype,
    )


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

    active_root = Path(os.path.abspath(ASSET_ACTIVE_ROOT))
    catalog_root = active_root.parent
    canonical_entries_by_path = {}
    canonical_entries = ()
    try:
        catalog_manifest_path = catalog_root / "manifest.json"
        manifest_before = _secure_file_snapshot(
            catalog_manifest_path,
            catalog_root,
        )
        if manifest_before is None:
            raise ValueError("canonical catalog manifest is not trusted")
        canonical_catalog = load_catalog_bytes(
            manifest_before[3],
            catalog_root=catalog_root,
            manifest_path=catalog_manifest_path,
        )
        canonical_entries_by_path = {
            Path(os.path.abspath(entry.path)): entry
            for entry in canonical_catalog.entries
        }
        canonical_entries = canonical_catalog.entries
    except (OSError, TypeError, ValueError):
        issues.append(
            _artifact_issue(
                "asset_catalog_not_canonical",
                "Final assets require a valid canonical active catalog manifest.",
                "asset_manifest.items",
            )
        )
    plan_requirements = _as_list(visual_plan, "required_assets")
    canonical_requirements_by_slot = {
        str(_value(payload, "slot_id") or ""): _canonical_requirement(payload)
        for payload in plan_requirements
    }
    current_asset_hashes: dict[str, str] = {}
    asset_items = _as_list(asset_manifest, "items")
    asset_slot_ids = [str(_value(item, "slot_id") or "") for item in asset_items]
    if len(asset_slot_ids) != len(set(asset_slot_ids)):
        issues.append(
            _artifact_issue(
                "duplicate_asset_slot_id",
                "AssetManifest slot IDs must be globally unique.",
                "asset_manifest.items",
            )
        )
    declarations_by_identity: dict[tuple[int, int], tuple[object, ...]] = {}
    for index, item in enumerate(asset_items):
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
        snapshot = _secure_file_snapshot(_value(item, "path"), active_root)
        actual = snapshot[2] if snapshot is not None else None
        if snapshot is None:
            issues.append(
                _artifact_issue(
                    "asset_file_missing",
                    "Final asset must be a regular, non-symlink file inside the active catalog.",
                    f"{location}.path",
                )
            )
            continue
        canonical, identity, _digest, _data = snapshot
        canonical_entry = canonical_entries_by_path.get(canonical)
        canonical_matches = canonical_entry is not None and _asset_item_matches_canonical(
            item,
            canonical_entry,
            catalog_root=catalog_root,
            canonical_path=canonical,
        )
        if not canonical_matches:
            issues.append(
                _artifact_issue(
                    "asset_provenance_not_canonical",
                    "Asset identity and provenance must match the canonical catalog and approved audit.",
                    location,
                )
            )
        requirement = canonical_requirements_by_slot.get(slot_id)
        eligibility_mode = "fallback" if status == "fallback" else "exact"
        if (
            canonical_entry is None
            or requirement is None
            or _value(item, "role") != requirement.role
            or not entry_satisfies_requirement(
                canonical_entry,
                _legacy_eligibility_view(requirement),
                mode=eligibility_mode,
                catalog_entries=canonical_entries,
                authorizer_integrity=lambda entry: (
                    (entry_snapshot := _secure_file_snapshot(entry.path, active_root))
                    is not None
                    and entry_snapshot[2] == entry.sha256
                ),
            )
            or (
                canonical_entry.provenance is not None
                and _value(item, "requirement_fingerprint")
                != requirement_fingerprint(requirement)
            )
        ):
            issues.append(
                _artifact_issue(
                    "asset_requirement_not_satisfied",
                    "Final asset must satisfy the current canonical requirement.",
                    location,
                )
            )
        declaration = (
            canonical,
            actual,
            _value(item, "sha256"),
            _value(item, "asset_id"),
            _value(item, "source_type"),
            _value(item, "provider"),
            _value(item, "provider_asset_id"),
            _value(item, "source_url"),
            _value(item, "source_file_url"),
            _value(item, "author"),
            json.dumps(
                _value(item, "provider_attribution", {}) or {},
                ensure_ascii=False,
                sort_keys=True,
            ),
            _value(item, "license"),
            _value(item, "license_snapshot"),
            _value(item, "license_snapshot_sha256"),
            _value(item, "license_terms_url"),
            _value(item, "average_hash"),
            _value(item, "review_disposition"),
        )
        prior_declaration = declarations_by_identity.get(identity)
        if prior_declaration is not None and prior_declaration != declaration:
            issues.append(
                _artifact_issue(
                    "asset_file_declaration_conflict",
                    "Reused asset bytes must have one identical hash and provenance declaration.",
                    f"{location}.path",
                )
            )
        declarations_by_identity.setdefault(identity, declaration)
        if actual != _value(item, "sha256"):
            issues.append(
                _artifact_issue(
                    "asset_file_hash_mismatch",
                    "Final asset bytes no longer match AssetManifest.",
                    f"{location}.sha256",
                )
            )
        if slot_id and slot_id not in current_asset_hashes:
            current_asset_hashes[slot_id] = actual

    plan_slots = {
        str(_value(item, "slot_id") or ""): (
            str(_value(item, "role") or ""),
            str(_value(item, "page_archetype") or ""),
        )
        for item in plan_requirements
    }
    storyboard_slot_records = []
    for frame in list(package.get("storyboards") or []):
        if not isinstance(frame, dict):
            continue
        for slot in list(frame.get("visual_slots") or []):
            storyboard_slot_records.append(
                (
                    str(_value(slot, "slot_id") or ""),
                    str(_value(slot, "role") or ""),
                    str(frame.get("page_archetype") or ""),
                )
            )
    storyboard_slot_ids = [record[0] for record in storyboard_slot_records]
    plan_slot_ids = [str(_value(item, "slot_id") or "") for item in plan_requirements]
    if (
        len(storyboard_slot_ids) != len(set(storyboard_slot_ids))
        or len(plan_slot_ids) != len(set(plan_slot_ids))
    ):
        issues.append(
            _artifact_issue(
                "duplicate_asset_slot_id",
                "Visual-plan and storyboard slot IDs must be globally unique.",
                "visual_plan.required_assets",
            )
        )
    manifest_slots = {
        str(_value(item, "slot_id") or ""): (
            str(_value(item, "role") or ""),
            str(_value(item, "page_archetype") or ""),
        )
        for item in asset_items
    }
    storyboard_slots = {
        slot_id: (role, layout)
        for slot_id, role, layout in storyboard_slot_records
    }
    slot_ids_match = set(plan_slots) == set(storyboard_slots) == set(manifest_slots)
    slot_bindings_match = slot_ids_match and all(
        plan_slots[slot_id] == manifest_slots[slot_id]
        and storyboard_slots[slot_id] == plan_slots[slot_id]
        for slot_id in plan_slots
    )
    if not (
        slot_bindings_match
        and len(plan_slots) == len(plan_requirements)
        and len(storyboard_slots) == len(storyboard_slot_records)
        and len(manifest_slots) == len(asset_items)
    ):
        issues.append(
            _artifact_issue(
                "asset_slot_binding_mismatch",
                "Asset slots must bind exactly across plan, storyboard, and manifest.",
                "asset_manifest.items",
            )
        )

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
    storyboard_frames = list(package.get("storyboards") or [])
    plan_bindings = [
        (
            str(_value(frame, "frame_id") or ""),
            str(_value(frame, "role") or ""),
            str(_value(frame, "page_archetype") or ""),
        )
        for frame in plan_frames
    ]
    storyboard_bindings = [
        (
            str(_value(frame, "frame_id") or ""),
            str(_value(frame, "role") or ""),
            str(_value(frame, "page_archetype") or ""),
        )
        for frame in storyboard_frames
    ]
    rendered_bindings = [
        (
            str(_value(page, "frame_id") or ""),
            str(_value(page, "role") or ""),
            str(_value(page, "page_archetype") or ""),
        )
        for page in pages
    ]
    if rendered_bindings != plan_bindings or rendered_bindings != storyboard_bindings:
        issues.append(
            _artifact_issue(
                "rendered_page_order_mismatch",
                "Rendered page frame, role, page archetype, and order must match plan and storyboard.",
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
    rendered_identities: set[tuple[int, int]] = set()
    rendered_canonical_paths: set[Path] = set()
    for index, page in enumerate(pages):
        raw_path = _value(page, "path")
        snapshot = _secure_png_snapshot(raw_path, Path(RENDER_OUTPUT_ROOT))
        actual = snapshot[2] if snapshot is not None else None
        actual_page_hashes.append(actual)
        if snapshot is None:
            issues.append(
                _artifact_issue(
                    "rendered_page_missing",
                    "Every final page must be a regular, non-symlink PNG inside the render root.",
                    f"render_manifest.pages[{index}].path",
                )
            )
        else:
            canonical, identity, _digest = snapshot
            if identity in rendered_identities or canonical in rendered_canonical_paths:
                issues.append(
                    _artifact_issue(
                        "rendered_page_path_alias",
                        "Every rendered page must bind a distinct canonical file and inode.",
                        f"render_manifest.pages[{index}].path",
                    )
                )
            rendered_identities.add(identity)
            rendered_canonical_paths.add(canonical)
        if actual is not None and actual != _value(page, "sha256"):
            issues.append(
                _artifact_issue(
                    "rendered_page_hash_mismatch",
                    "Rendered page bytes no longer match RenderManifest.",
                    f"render_manifest.pages[{index}].sha256",
                )
            )
        if index < len(storyboard_frames) and isinstance(storyboard_frames[index], dict):
            expected_text = {
                role: text
                for role, text in extract_storyboard_visible_text(
                    [storyboard_frames[index]]
                )[0]["text_blocks"].items()
                if text
                and (
                    role in {"kicker", "headline", "footer"}
                    or role.startswith("content_blocks[")
                )
            }
            probe = _value(page, "probe")
            text_results = _as_list(probe, "text_results")
            actual_text = {
                str(_value(result, "role") or ""): str(
                    _value(result, "text") or ""
                )
                for result in text_results
            }
            if (
                len(actual_text) != len(text_results)
                or actual_text != expected_text
            ):
                issues.append(
                    _artifact_issue(
                        "rendered_visible_text_binding_mismatch",
                        "Rendered text probe must exactly bind current storyboard-visible text.",
                        f"render_manifest.pages[{index}].probe.text_results",
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
    contact_snapshot = _secure_png_snapshot(
        _value(render_manifest, "contact_sheet_path"),
        Path(RENDER_OUTPUT_ROOT),
    )
    contact_hash = contact_snapshot[2] if contact_snapshot is not None else None
    if contact_snapshot is None:
        issues.append(
            _artifact_issue(
                "contact_sheet_missing",
                "Contact sheet must be a regular, non-symlink PNG inside the render root.",
                "render_manifest.contact_sheet_path",
            )
        )
    else:
        contact_path, contact_identity, _digest = contact_snapshot
        if (
            contact_path in rendered_canonical_paths
            or contact_identity in rendered_identities
        ):
            issues.append(
                _artifact_issue(
                    "rendered_page_path_alias",
                    "Contact sheet must not alias a rendered page.",
                    "render_manifest.contact_sheet_path",
                )
            )
    if contact_hash is not None and contact_hash != _value(render_manifest, "contact_sheet_sha256"):
        issues.append(
            _artifact_issue(
                "contact_sheet_hash_mismatch",
                "Contact-sheet bytes no longer match RenderManifest.",
                "render_manifest.contact_sheet_sha256",
            )
        )
    return issues


def validate_final_policy(state: AgentState) -> list[dict]:
    """Return the complete, side-effect-free Final Guard issue list for ``state``."""
    publish_package = state.get("publish_package")
    if publish_package is None:
        raise ValueError("validate_final_policy requires `publish_package` in state.")

    issues = _required_field_issues(publish_package)
    issues.extend(_editorial_artifact_issues(state, publish_package))
    combined_text = _URL_PATTERN.sub("", "\n".join(
        [
            _coerce_text(publish_package.get("title")),
            _coerce_text(publish_package.get("content")),
            _coerce_text(publish_package.get("cover_copy")),
            _coerce_text(publish_package.get("hashtags")),
            *_storyboard_visible_text(publish_package.get("storyboards")),
        ]
    ))
    issues.extend(
        [
            issue.model_copy(update={"location": "publish_package"}).model_dump(mode="json")
            for issue in find_policy_violations(combined_text)
        ]
    )
    return issues


def final_policy_guard_node(state: AgentState) -> AgentState:
    issues = validate_final_policy(state)
    return {
        "final_policy_issues": issues,
        "current_node": "FINAL_POLICY_GUARD",
    }


def route_after_final_guard(state: AgentState) -> str:
    issues = state.get("final_policy_issues") or []
    return "human_review" if issues else "content_writer"
