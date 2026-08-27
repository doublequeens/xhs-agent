"""The v4 shadow exporter: an evaluation bundle that can never publish.

A shadow bundle carries the same verified contracts and page bytes as a
publish package would, for comparison and calibration tooling, but it is
written only under the injected shadow root, is marked non-publishable through
its own ``shadow-manifest.json``, and never receives a publish attestation.
The exporter is graph-free, memory-free and network-free by construction.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from src.nodes.v4.final_guard import verify_v4_final_policy
from src.publishing.v4_artifacts import (
    V4_CANONICAL_CONTRACT_FILES,
    _contract_payload,
    _package_directory,
    _verified_png,
    _write_json,
)
from src.schemas.v4.publishing import ShadowManifestV4

SHADOW_ROOT = Path(__file__).resolve().parents[2] / "outputs" / "shadow"


@dataclass(frozen=True)
class ShadowBundleV4:
    """One exported, non-publish evaluation bundle."""

    bundle_directory: Path
    shadow_manifest: ShadowManifestV4
    contract_paths: Mapping[str, Path]
    page_paths: tuple[Path, ...]
    contact_sheet_path: Path
    shadow_manifest_path: Path


def export_v4_shadow_bundle(
    state: Mapping[str, Any],
    *,
    shadow_root: Path | None = None,
    source_run_id: str | None = None,
) -> ShadowBundleV4:
    """Re-verify one terminal v4 state and export a non-publish bundle."""

    result = verify_v4_final_policy(state)
    inputs = result.inputs
    paths = inputs.artifact_paths

    page_bytes: dict[str, bytes] = {}
    for page in inputs.render_manifest.pages:
        name = f"pages/{page.sequence:02d}-{page.page_id}.png"
        page_bytes[name] = _verified_png(
            paths.revision_root,
            page.path,
            page.sha256,
            label=f"shadow page {page.page_id}",
            size=(page.width, page.height),
        )
    contact = _verified_png(
        paths.revision_root,
        inputs.render_manifest.contact_sheet_path,
        inputs.render_manifest.contact_sheet_sha256,
        label="shadow contact sheet",
    )
    page_sha256 = {
        name: hashlib.sha256(raw).hexdigest() for name, raw in page_bytes.items()
    }
    page_sha256["contact-sheet.png"] = hashlib.sha256(contact).hexdigest()

    contract_hashes = {
        "content_atom_set.json": inputs.content_atom_set.canonical_sha256,
        "visual_direction_plan.json": inputs.visual_direction_plan.canonical_sha256,
        "asset_manifest.json": result.attestation.human_review_decision.get(
            "asset_manifest_sha256"
        ),
        "carousel_design_plan.json": inputs.carousel_design_plan.canonical_sha256,
        "design_plan_qa.json": inputs.design_plan_qa.canonical_sha256,
        "render_manifest.json": inputs.render_manifest.canonical_sha256,
        "render_qa.json": inputs.render_qa.canonical_sha256,
        "visual_critique.json": inputs.visual_critique.canonical_sha256,
        "content_lock.json": result.attestation.human_review_decision.get(
            "content_lock_sha256"
        ),
        "final_policy_attestation.json": result.attestation.canonical_sha256,
    }
    identity = paths.identity
    manifest = ShadowManifestV4.create(
        run_id=identity.run_id,
        candidate_id=identity.candidate_id,
        revision_id=identity.revision_id,
        source_run_id=source_run_id,
        contract_sha256=contract_hashes,
        page_sha256=page_sha256,
        page_count=len(page_bytes),
    )

    root = Path(shadow_root) if shadow_root is not None else SHADOW_ROOT
    date = datetime.now().strftime("%Y%m%d")
    bundle_dir = root / f"{date}-shadow-{identity.run_id}-{identity.revision_id}"
    if bundle_dir.exists():
        raise ValueError(f"shadow bundle already exists: {bundle_dir}")
    staging = root / f".{uuid.uuid4().hex}-staging"
    try:
        staging.mkdir(parents=True, exist_ok=False)
        (staging / "pages").mkdir()
        contract_payloads = _contract_payload(result)
        contract_paths: dict[str, Path] = {}
        for filename in V4_CANONICAL_CONTRACT_FILES:
            path = staging / filename
            _write_json(path, contract_payloads[filename])
            contract_paths[filename] = path
        for name, raw in page_bytes.items():
            (staging / name).write_bytes(raw)
        (staging / "contact-sheet.png").write_bytes(contact)
        _write_json(staging / "shadow-manifest.json", manifest.model_dump(mode="json"))
        bundle_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, bundle_dir)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise

    return ShadowBundleV4(
        bundle_directory=bundle_dir,
        shadow_manifest=manifest,
        contract_paths={name: bundle_dir / name for name in V4_CANONICAL_CONTRACT_FILES},
        page_paths=tuple(bundle_dir / name for name in sorted(page_bytes)),
        contact_sheet_path=bundle_dir / "contact-sheet.png",
        shadow_manifest_path=bundle_dir / "shadow-manifest.json",
    )


__all__ = [
    "SHADOW_ROOT",
    "ShadowBundleV4",
    "export_v4_shadow_bundle",
]
