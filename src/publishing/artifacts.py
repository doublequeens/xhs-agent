"""Publish-artifact export for the ``llm_scene_v3`` dynamic-visual path (Task 16).

Rebuilds the local publish package around the dynamic visual contracts. The
export consumes the final approved contracts from a terminal ``StateSnapshot``
and emits the canonical package:

    content_atom_set.json, visual_direction_plan.json, asset_manifest.json,
    carousel_design_plan.json, design_plan_qa.json, render_manifest.json,
    render_qa.json, visual_critique.json, content_lock.json,
    final_policy_attestation.json, pages/*.png, contact-sheet.png

plus a ``publish-attestation.json`` that binds the whole bundle. Every contract
(canonical sha256) and every PNG (file-byte sha256) is hashed; the attestation
is written as a separate file so it never participates in the hash it carries
(no circular dependency).

Staging + atomic promotion only: the bundle is built in a sibling staging
directory and then atomically renamed onto the canonical
``outputs/publish/<date>-<domain>-<title>/`` path. An existing canonical
package is never overwritten by hand. No ``storyboards`` / ``visual_plan`` /
``carousel_qa`` / fixed-template variant fields are exported. AI provenance
lives ONLY in the internal asset JSON (``AssetManifestItem.internal_provenance``)
and is never rendered into page-visible copy or a PNG.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import shutil
import unicodedata
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from PIL import Image, UnidentifiedImageError
from langgraph.types import StateSnapshot

from src.nodes.node_p_editorial_carousel_renderer import (
    PUBLISH_ROOT as _RENDERER_PUBLISH_ROOT,
)
from src.nodes.node_q_01_final_policy_guard import validate_final_policy
from src.schemas.assets import AssetManifest
from src.schemas.content_atoms import ContentAtomSet, canonical_sha256
from src.schemas.content_lock import ContentLock
from src.schemas.design_qa import DesignPlanQAResult
from src.schemas.render_manifest import RenderManifest
from src.schemas.render_qa import RenderQAResult
from src.schemas.scene_graph import CarouselDesignPlan
from src.schemas.visual_critique import VisualCritique
from src.schemas.visual_director import VisualDirectionPlan
from src.schemas.visual_style import Sha256, StrictModel


# Tests monkeypatch this module global; production reads the renderer default.
PUBLISH_ROOT = _RENDERER_PUBLISH_ROOT

WORKFLOW_VERSION: Literal["llm_scene_v3"] = "llm_scene_v3"

# The canonical contract files written to every publish package, in the
# brief's verbatim order. ``publish-attestation.json`` is written alongside as
# the binding attestation (it carries the hashes of the files above + PNGs).
CANONICAL_CONTRACT_FILES: tuple[str, ...] = (
    "content_atom_set.json",
    "visual_direction_plan.json",
    "asset_manifest.json",
    "carousel_design_plan.json",
    "design_plan_qa.json",
    "render_manifest.json",
    "render_qa.json",
    "visual_critique.json",
    "content_lock.json",
    "final_policy_attestation.json",
)

# Textual publish-package fields locked into ContentLock (the visible source
# copy). Mirrors ``node_q_01_final_policy_guard._LOCK_TEXT_FIELDS`` so the
# publish layer and Final Guard agree on the locked surface.
LOCK_TEXT_FIELDS = (
    "focus_keyword",
    "topic",
    "topic_id",
    "angle",
    "angle_id",
    "target_group",
    "core_pain",
    "title",
    "cover_copy",
    "content",
)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PublishAttestation(StrictModel):
    """Whole-bundle attestation binding every contract + every PNG.

    ``workflow_version`` is pinned to ``llm_scene_v3``. Contract hashes are the
    canonical sha256 of each persisted contract model; ``page_sha256`` maps
    package-relative PNG paths (``pages/<NN>-<page_id>.png`` and
    ``contact-sheet.png``) to the sha256 of the file bytes. Every contract AND
    every PNG is covered; the attestation itself is written to a separate file
    so it never participates in the hash it carries.
    """

    workflow_version: Literal["llm_scene_v3"]
    content_atom_set_sha256: Sha256
    visual_direction_plan_sha256: Sha256
    asset_manifest_sha256: Sha256
    carousel_design_plan_sha256: Sha256
    design_plan_qa_sha256: Sha256
    render_manifest_sha256: Sha256
    render_qa_sha256: Sha256
    visual_critique_sha256: Sha256
    content_lock_sha256: Sha256
    final_policy_attestation_sha256: Sha256
    page_sha256: dict[str, Sha256]


@dataclass(frozen=True)
class PublishArtifacts:
    package_directory: Path
    content_lock: ContentLock
    publish_attestation: PublishAttestation
    contract_paths: Mapping[str, Path]
    page_paths: tuple[Path, ...]
    contact_sheet_path: Path
    publish_attestation_path: Path


# ---------------------------------------------------------------------------
# JSON + hash helpers
# ---------------------------------------------------------------------------


def canonical_content_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_json_value(item) for item in value)
    if isinstance(value, Path):
        return str(value)
    return value


def _model_or_dict(value: Any) -> Any:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else _json_value(value)


# ---------------------------------------------------------------------------
# ContentLock + publish copy
# ---------------------------------------------------------------------------


def _value(payload: Any, key: str, default: Any = None) -> Any:
    if payload is None:
        return default
    if isinstance(payload, Mapping):
        return payload.get(key, default)
    return getattr(payload, key, default)


def _content_lock_payload(package: Mapping[str, Any], atom_sha: str) -> dict[str, Any]:
    contract = package.get("content_contract")
    first_screen_promise = (
        _value(contract, "first_screen_promise")
        or package.get("first_screen_promise")
        or ""
    )
    return {
        "focus_keyword": package.get("focus_keyword"),
        "topic": package.get("topic"),
        "topic_id": package.get("topic_id"),
        "angle": package.get("angle"),
        "angle_id": package.get("angle_id"),
        "target_group": package.get("target_group"),
        "core_pain": package.get("core_pain"),
        "title": package.get("title"),
        "cover_copy": package.get("cover_copy"),
        "first_screen_promise": first_screen_promise,
        "content": package.get("content"),
        "hashtags": list(package.get("hashtags") or []),
        "content_atom_set_sha256": atom_sha,
    }


def _resolve_atom_sha(package: Mapping[str, Any]) -> str:
    atom_sha = package.get("content_atom_set_sha256")
    if not atom_sha:
        atom_set = package.get("content_atom_set")
        atom_sha = _value(atom_set, "canonical_sha256")
    if not isinstance(atom_sha, str) or not atom_sha:
        raise ValueError(
            "build_content_lock requires content_atom_set_sha256 "
            "(or an embedded content_atom_set) to bind the visual chain."
        )
    return atom_sha


def build_content_lock(package: dict) -> ContentLock:
    """Build the ``llm_scene_v3`` ContentLock from the publish package.

    Mirrors ``node_q_01_final_policy_guard._content_lock_payload``: the locked
    visible source copy plus ``content_atom_set_sha256`` (the structural binding
    for the dynamic visual chain). No storyboard payload.
    """
    if not isinstance(package, dict):
        raise TypeError("build_content_lock requires a dict publish package")
    atom_sha = _resolve_atom_sha(package)
    payload = _content_lock_payload(package, atom_sha)
    canonical = canonical_sha256(payload)
    return ContentLock.model_validate({**payload, "canonical_sha256": canonical})


def build_publish_copy(package: dict) -> str:
    if not isinstance(package, dict):
        raise TypeError("build_publish_copy requires a dict publish package")
    title = package["title"]
    content = package["content"]
    hashtags = package["hashtags"]
    return f"{title}\n\n{content}\n\n{' '.join(hashtags)}\n"


# ---------------------------------------------------------------------------
# Terminal-state validation
# ---------------------------------------------------------------------------


def _terminal_values(completed_state: Any) -> dict[str, Any]:
    if type(completed_state) is not StateSnapshot:
        raise TypeError("final export requires a real langgraph.types.StateSnapshot")
    if type(completed_state.next) is not tuple or completed_state.next != ():
        raise ValueError("final export requires terminal StateSnapshot next to be ()")
    values = completed_state.values
    if not isinstance(values, Mapping):
        raise TypeError("final export requires completed_state.values")
    # ``_json_value`` recursively rebuilds the state as plain JSON-compatible
    # structures (``model_dump(mode="json")`` for pydantic models), which both
    # detaches the snapshot and normalises MappingProxyType / tuple frozen
    # fields. No ``deepcopy``: it cannot pickle the frozen ``mappingproxy``
    # fields on the v3 contracts.
    detached = _json_value(dict(values))
    if not isinstance(detached, dict):
        raise TypeError("completed state values must serialize to a dict")
    if not isinstance(detached.get("publish_package"), dict):
        raise ValueError("completed state requires publish_package")
    if detached.get("review_status") != "approved":
        raise ValueError("final export requires an approved review_status")
    return detached


def _required_contract(state: Mapping[str, Any], key: str, model: type) -> Any:
    raw = state.get(key)
    if raw is None:
        raise ValueError(f"final export requires persisted contract: {key}")
    if isinstance(raw, model):
        return raw
    # Tolerate dict / JSON-serialised inputs by re-validating through the model.
    # ``model_dump(mode="json")`` turns tuples into lists; the v3 StrictModels
    # would reject those under strict mode, so go through ``model_validate``
    # which reconstructs the tuple fields from a plain dict payload.
    return model.model_validate(dict(raw))


def _validate_no_pending_or_rejected_assets(asset_manifest: AssetManifest) -> None:
    for item in asset_manifest.items:
        if item.security_status == "rejected":
            raise ValueError("final export rejects a security-rejected asset")
    # Final Guard already enforces every required directive is covered by an
    # approved asset; re-checking the publish-time status is the publish gate.


# ---------------------------------------------------------------------------
# Rendered PNG validation
# ---------------------------------------------------------------------------


def _decode_png(data: bytes, *, label: str, required_size: tuple[int, int] | None) -> None:
    if data[: len(PNG_SIGNATURE)] != PNG_SIGNATURE:
        raise ValueError(f"{label} must be a PNG file")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG":
                raise ValueError(f"{label} must decode as PNG")
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if required_size is not None and image.size != required_size:
                raise ValueError(f"{label} must be 1080 x 1440")
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError(f"{label} failed full PNG decode") from exc


@dataclass(frozen=True)
class _RenderedPageFile:
    source_path: Path
    page_id: str
    sequence: int
    sha256: str


def _validate_rendered_pages(
    render_manifest: RenderManifest,
) -> tuple[tuple[_RenderedPageFile, ...], Path, str]:
    files: list[_RenderedPageFile] = []
    for page in render_manifest.pages:
        source = Path(page.path)
        if not source.is_absolute():
            raise ValueError(f"render manifest page path must be absolute: {page.page_id}")
        if not source.is_file():
            raise ValueError(f"render manifest page is missing: {page.page_id}")
        data = source.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != page.sha256:
            raise ValueError(
                f"render manifest page sha256 mismatch for {page.page_id}: "
                "page bytes changed after RenderManifest"
            )
        _decode_png(data, label=f"rendered page {page.page_id}", required_size=(1080, 1440))
        files.append(
            _RenderedPageFile(
                source_path=source,
                page_id=page.page_id,
                sequence=page.sequence,
                sha256=actual,
            )
        )
    contact_source = Path(render_manifest.contact_sheet_path)
    if not contact_source.is_absolute() or not contact_source.is_file():
        raise ValueError("render manifest contact sheet must be an existing absolute path")
    contact_data = contact_source.read_bytes()
    contact_actual = hashlib.sha256(contact_data).hexdigest()
    if contact_actual != render_manifest.contact_sheet_sha256:
        raise ValueError("contact sheet sha256 changed after RenderManifest")
    _decode_png(contact_data, label="contact sheet", required_size=None)
    return tuple(files), contact_source, contact_actual


# ---------------------------------------------------------------------------
# Canonical package directory + staging/promotion
# ---------------------------------------------------------------------------


def _validate_title_component(title: str) -> str:
    if not isinstance(title, str) or not title:
        raise ValueError("publish title must be a non-empty filename component")
    if title.startswith(".") or "/" in title or "\\" in title:
        raise ValueError("publish title must be one safe filename component")
    if any(unicodedata.category(character).startswith("C") for character in title):
        raise ValueError("publish title must not contain control characters")
    return title


def _package_date(values: Mapping[str, Any]) -> str:
    now = values.get("_now_for_test")
    if isinstance(now, datetime):
        return now.strftime("%Y%m%d")
    return datetime.now().strftime("%Y%m%d")


def _canonical_package_directory(
    values: Mapping[str, Any],
    package: Mapping[str, Any],
) -> Path:
    date = _package_date(values)
    domain = package.get("domain")
    if not isinstance(domain, str) or not domain.strip():
        raise ValueError(
            "publish package requires a domain for the canonical package directory"
        )
    title = _validate_title_component(package["title"])
    return Path(PUBLISH_ROOT) / f"{date}-{domain}-{title}"


def _write_json(path: Path, payload: Any) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")


def _stage_bundle(
    staging_dir: Path,
    *,
    contracts: dict[str, Any],
    content_lock: ContentLock,
    final_policy_attestation: dict[str, Any],
    page_files: tuple[_RenderedPageFile, ...],
    contact_source: Path,
    publish_attestation: PublishAttestation,
) -> dict[str, Path]:
    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / "pages").mkdir()

    contract_paths: dict[str, Path] = {}
    contract_payloads = {
        "content_atom_set.json": contracts["content_atom_set"],
        "visual_direction_plan.json": contracts["visual_direction_plan"],
        "asset_manifest.json": contracts["asset_manifest"],
        "carousel_design_plan.json": contracts["carousel_design_plan"],
        "design_plan_qa.json": contracts["design_plan_qa_result"],
        "render_manifest.json": contracts["render_manifest"],
        "render_qa.json": contracts["render_qa_result"],
        "visual_critique.json": contracts["visual_critique"],
        "content_lock.json": content_lock,
        "final_policy_attestation.json": final_policy_attestation,
    }
    for filename, payload in contract_payloads.items():
        path = staging_dir / filename
        _write_json(path, _model_or_dict(payload))
        contract_paths[filename] = path

    for page_file in page_files:
        destination_name = f"{page_file.sequence:02d}-{page_file.page_id}.png"
        shutil.copyfile(page_file.source_path, staging_dir / "pages" / destination_name)
    shutil.copyfile(contact_source, staging_dir / "contact-sheet.png")

    attestation_path = staging_dir / "publish-attestation.json"
    _write_json(attestation_path, publish_attestation.model_dump(mode="json"))
    return contract_paths


def _atomic_promote(staging_dir: Path, canonical: Path) -> None:
    if canonical.exists():
        raise ValueError(
            f"canonical publish package already exists; never overwrite by hand: {canonical}"
        )
    canonical.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging_dir, canonical)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _export_verified_state_snapshot(completed_state: StateSnapshot) -> PublishArtifacts:
    original_values = completed_state.values
    values = _terminal_values(completed_state)
    package = values["publish_package"]

    # Recompute Final Guard; the empty issue list becomes final_policy_attestation.
    issues = validate_final_policy(values)
    if issues:
        raise ValueError(
            "final export failed recomputed Final Guard: "
            + json.dumps(issues, ensure_ascii=False, sort_keys=True)
        )
    final_policy_attestation = {
        "workflow_version": WORKFLOW_VERSION,
        "passed": True,
        "final_policy_issues": [],
        "review_status": values["review_status"],
    }

    # Read the persisted pydantic contracts directly from the terminal state.
    # They are already validated by the upstream nodes; re-validating a JSON
    # round-trip would trip the v3 StrictModels (tuple fields under strict
    # mode), so we accept the original model instances as-is.
    contracts = {
        "content_atom_set": _required_contract(original_values, "content_atom_set", ContentAtomSet),
        "visual_direction_plan": _required_contract(
            original_values, "visual_direction_plan", VisualDirectionPlan
        ),
        "asset_manifest": _required_contract(original_values, "asset_manifest", AssetManifest),
        "carousel_design_plan": _required_contract(
            original_values, "carousel_design_plan", CarouselDesignPlan
        ),
        "design_plan_qa_result": _required_contract(
            original_values, "design_plan_qa_result", DesignPlanQAResult
        ),
        "render_manifest": _required_contract(original_values, "render_manifest", RenderManifest),
        "render_qa_result": _required_contract(original_values, "render_qa_result", RenderQAResult),
        "visual_critique": _required_contract(original_values, "visual_critique", VisualCritique),
    }
    _validate_no_pending_or_rejected_assets(contracts["asset_manifest"])

    atom_sha = contracts["content_atom_set"].canonical_sha256
    lock_payload = _content_lock_payload(package, atom_sha)
    content_lock = ContentLock.model_validate(
        {**lock_payload, "canonical_sha256": canonical_sha256(lock_payload)}
    )

    page_files, contact_source, contact_sha = _validate_rendered_pages(
        contracts["render_manifest"]
    )

    page_sha256: dict[str, str] = {
        f"pages/{page_file.sequence:02d}-{page_file.page_id}.png": page_file.sha256
        for page_file in page_files
    }
    page_sha256["contact-sheet.png"] = contact_sha

    publish_attestation = PublishAttestation(
        workflow_version=WORKFLOW_VERSION,
        content_atom_set_sha256=canonical_sha256(contracts["content_atom_set"]),
        visual_direction_plan_sha256=canonical_sha256(contracts["visual_direction_plan"]),
        asset_manifest_sha256=canonical_sha256(contracts["asset_manifest"]),
        carousel_design_plan_sha256=canonical_sha256(contracts["carousel_design_plan"]),
        design_plan_qa_sha256=canonical_sha256(contracts["design_plan_qa_result"]),
        render_manifest_sha256=canonical_sha256(contracts["render_manifest"]),
        render_qa_sha256=canonical_sha256(contracts["render_qa_result"]),
        visual_critique_sha256=canonical_sha256(contracts["visual_critique"]),
        content_lock_sha256=content_lock.canonical_sha256,
        final_policy_attestation_sha256=canonical_sha256(final_policy_attestation),
        page_sha256=page_sha256,
    )

    canonical = _canonical_package_directory(values, package)
    staging_dir = Path(PUBLISH_ROOT) / f".{uuid.uuid4().hex}-staging"
    try:
        contract_paths = _stage_bundle(
            staging_dir,
            contracts=contracts,
            content_lock=content_lock,
            final_policy_attestation=final_policy_attestation,
            page_files=page_files,
            contact_source=contact_source,
            publish_attestation=publish_attestation,
        )
        _atomic_promote(staging_dir, canonical)
    except BaseException:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    page_paths = tuple(
        canonical / "pages" / f"{page_file.sequence:02d}-{page_file.page_id}.png"
        for page_file in page_files
    )
    return PublishArtifacts(
        package_directory=canonical,
        content_lock=content_lock,
        publish_attestation=publish_attestation,
        contract_paths={
            name: canonical / name for name in CANONICAL_CONTRACT_FILES
        },
        page_paths=page_paths,
        contact_sheet_path=canonical / "contact-sheet.png",
        publish_attestation_path=canonical / "publish-attestation.json",
    )


def export_publish_package(completed_state: StateSnapshot) -> PublishArtifacts:
    """Public final exporter; accepts only a real ``llm_scene_v3`` terminal StateSnapshot."""
    return _export_verified_state_snapshot(completed_state)
