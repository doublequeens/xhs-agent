"""The v4 publish exporter: the exact reviewed bytes, ten contracts, attested.

Everything the package contains is re-verified at export time through the
public review seams: the Final Guard recompute (append-only decision record,
anchored workspace, fresh Q0-Q3, every page/contact/asset byte), then the same
ten canonical contract filenames as v3 plus ``publish-attestation.json``.
Unlike v3, a pre-review ``AssetManifest.human_decision=pending`` is accepted
exactly when the terminal review decision carries a byte-bound approved
decision for every rendered asset.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from src.nodes.v4.final_guard import verify_v4_final_policy
from src.publishing.artifacts import _decode_png
from src.review.v4_workspace import validate_review_workspace_inputs
from src.schemas.v4.publishing import (
    V4_CANONICAL_CONTRACT_FILES,
    FinalPolicyAttestationV4,
    PublishAttestationV4,
)
from src.visual_runtime.artifact_identity import read_verified_artifact_snapshot

V4_PUBLISH_ROOT = Path(__file__).resolve().parents[2] / "outputs" / "publish"

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class PublishArtifactsV4:
    """The exported, attested v4 package."""

    package_directory: Path
    publish_attestation: PublishAttestationV4
    final_policy_attestation: FinalPolicyAttestationV4
    contract_paths: Mapping[str, Path]
    page_paths: tuple[Path, ...]
    contact_sheet_path: Path
    publish_attestation_path: Path


def _contract_payload(result) -> dict[str, Any]:
    """The ten canonical contract payloads, keyed by filename."""

    inputs = result.inputs
    attestation_payload = dict(result.attestation.model_dump(mode="json"))
    return {
        "content_atom_set.json": inputs.content_atom_set.model_dump(mode="json"),
        "visual_direction_plan.json": inputs.visual_direction_plan.model_dump(
            mode="json"
        ),
        "asset_manifest.json": inputs.asset_manifest.model_dump(mode="json"),
        "carousel_design_plan.json": inputs.carousel_design_plan.model_dump(
            mode="json"
        ),
        "design_plan_qa.json": inputs.design_plan_qa.model_dump(mode="json"),
        "render_manifest.json": inputs.render_manifest.model_dump(mode="json"),
        "render_qa.json": inputs.render_qa.model_dump(mode="json"),
        "visual_critique.json": inputs.visual_critique.model_dump(mode="json"),
        "content_lock.json": inputs.content_lock.model_dump(mode="json"),
        "final_policy_attestation.json": attestation_payload,
    }


def _verified_png(
    revision_root: Path, relative: str, digest: str, *, label: str, size=None
) -> bytes:
    snapshot = read_verified_artifact_snapshot(
        revision_root / relative, digest, containment_root=revision_root
    )
    raw = snapshot.raw
    if raw[: len(PNG_SIGNATURE)] != PNG_SIGNATURE:
        raise ValueError(f"{label} must be a PNG file")
    _decode_png(raw, label=label, required_size=size)
    return raw


def _validate_title_component(title: Any) -> str:
    if not isinstance(title, str) or not title:
        raise ValueError("publish title must be a non-empty filename component")
    if title.startswith(".") or "/" in title or "\\" in title:
        raise ValueError("publish title must be one safe filename component")
    if any(unicodedata.category(character).startswith("C") for character in title):
        raise ValueError("publish title must not contain control characters")
    return title


def _package_directory(state: Mapping[str, Any], result) -> Path:
    package = state.get("publish_package")
    title_source = package.get("title") if isinstance(package, Mapping) else None
    title = _validate_title_component(
        title_source or result.decision.decision_id
    )
    date = datetime.now().strftime("%Y%m%d")
    identity = result.inputs.artifact_paths.identity
    # v4 packages are namespaced by run identity so a v3 and a v4 package of
    # the same day/domain/title can never collide or overwrite each other.
    return f"{date}-{identity.run_id}-{title}"


def _write_json(path: Path, payload: Any) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")


def export_v4_publish_package(
    state: Mapping[str, Any],
    *,
    publish_root: Path | None = None,
) -> PublishArtifactsV4:
    """Re-verify one approved terminal v4 state and export the package."""

    result = verify_v4_final_policy(state)
    inputs = result.inputs
    paths = inputs.artifact_paths
    # The public source seam recomputes the exact contract hashes to bind.
    _, hashes = validate_review_workspace_inputs(inputs)

    page_bytes: dict[str, bytes] = {}
    for page in inputs.render_manifest.pages:
        name = f"pages/{page.sequence:02d}-{page.page_id}.png"
        page_bytes[name] = _verified_png(
            paths.revision_root,
            page.path,
            page.sha256,
            label=f"rendered page {page.page_id}",
            size=(page.width, page.height),
        )
    contact = _verified_png(
        paths.revision_root,
        inputs.render_manifest.contact_sheet_path,
        inputs.render_manifest.contact_sheet_sha256,
        label="contact sheet",
    )

    page_sha256: dict[str, str] = {
        name: hashlib.sha256(raw).hexdigest() for name, raw in page_bytes.items()
    }
    page_sha256["contact-sheet.png"] = hashlib.sha256(contact).hexdigest()

    publish_attestation = PublishAttestationV4(
        workflow_version="llm_scene_v4",
        content_atom_set_sha256=hashes["content_atom_set_sha256"],
        visual_direction_plan_sha256=hashes["visual_direction_plan_sha256"],
        asset_manifest_sha256=hashes["asset_manifest_sha256"],
        carousel_design_plan_sha256=hashes["carousel_design_plan_sha256"],
        design_plan_qa_sha256=hashes["design_plan_qa_sha256"],
        render_manifest_sha256=hashes["render_manifest_sha256"],
        render_qa_sha256=hashes["render_qa_sha256"],
        visual_critique_sha256=hashes["visual_critique_sha256"],
        content_lock_sha256=hashes["content_lock_sha256"],
        final_policy_attestation_sha256=result.attestation.canonical_sha256,
        page_sha256=page_sha256,
    )

    root = Path(publish_root) if publish_root is not None else V4_PUBLISH_ROOT
    canonical = root / _package_directory(state, result)
    if canonical.exists():
        raise ValueError(
            f"canonical v4 publish package already exists; "
            f"never overwrite by hand: {canonical}"
        )
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
        _write_json(
            staging / "publish-attestation.json",
            publish_attestation.model_dump(mode="json"),
        )
        canonical.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, canonical)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise

    return PublishArtifactsV4(
        package_directory=canonical,
        publish_attestation=publish_attestation,
        final_policy_attestation=result.attestation,
        contract_paths={
            name: canonical / name for name in V4_CANONICAL_CONTRACT_FILES
        },
        page_paths=tuple(
            canonical / name for name in sorted(page_bytes)
        ),
        contact_sheet_path=canonical / "contact-sheet.png",
        publish_attestation_path=canonical / "publish-attestation.json",
    )


__all__ = [
    "PublishArtifactsV4",
    "V4_PUBLISH_ROOT",
    "export_v4_publish_package",
]
