from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, BrokenBarrierError
from pathlib import Path

import pytest
from PIL import Image

from src.asset_resolver.catalog import AssetCatalog


def pending_asset(
    tmp_path: Path,
    *,
    asset_id: str = "p1",
    candidate_rank: int = 1,
    unresolved_safety_checks: tuple[str, ...] = (),
    run_id: str = "run-42",
    color: str = "ivory",
):
    from src.asset_resolver.lifecycle import PendingAsset

    path = tmp_path / "incoming" / "external" / run_id / f"pexels-{asset_id}.webp"
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1080, 1440), color).save(
        path, format="WEBP", lossless=True
    )
    metadata_path = path.with_suffix(".json")
    license_snapshot = tmp_path / "licenses" / "pexels-terms-summary-v1.txt"
    license_snapshot.parent.mkdir(parents=True, exist_ok=True)
    license_snapshot.write_text("Pexels terms summary v1", encoding="utf-8")
    pending = PendingAsset(
        pending_id=f"{run_id}-serum-slot-pexels-{asset_id}",
        slot_id="serum-slot",
        candidate_rank=candidate_rank,
        path=path,
        metadata_path=metadata_path,
        provider="pexels",
        provider_asset_id=asset_id,
        author="Ada",
        source_url=f"https://www.pexels.com/photo/{asset_id}/",
        source_file_url=f"https://images.pexels.com/photos/{asset_id}.webp",
        role="serum_texture",
        layout="texture_baseline",
        width=1080,
        height=1440,
        license="Pexels License",
        license_snapshot=license_snapshot.relative_to(tmp_path).as_posix(),
        license_snapshot_sha256=hashlib.sha256(
            license_snapshot.read_bytes()
        ).hexdigest(),
        license_terms_url="https://www.pexels.com/license/",
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        average_hash="0123456789abcdef",
        run_id=run_id,
        production_relative_path=Path(f"stock/serum-{asset_id}.webp"),
        tags=("serum", "ivory"),
        fallback_roles=("serum_texture",),
        unresolved_safety_checks=unresolved_safety_checks,
        requirement_fingerprint="a" * 64,
        attempt_number=min(candidate_rank, 3),
        provider_attribution=(("author", "Ada"),),
    )
    metadata_path.write_text(json.dumps(pending.audit_record()), encoding="utf-8")
    return pending


def catalog(tmp_path: Path, *, run_id: str = "run-42") -> AssetCatalog:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"catalog_id": "test-catalog", "assets": []}),
        encoding="utf-8",
    )
    return AssetCatalog(
        catalog_id="test-catalog",
        root=tmp_path,
        entries=(),
        run_id=run_id,
        manifest_path=manifest_path,
    )


def test_approval_preserves_hash_and_promotes_into_active_catalog(tmp_path: Path) -> None:
    from src.asset_resolver.catalog import load_catalog
    from src.asset_resolver.lifecycle import approve_external_asset

    pending = pending_asset(tmp_path, unresolved_safety_checks=())
    mutable_catalog = catalog(tmp_path)
    entry = approve_external_asset(pending, mutable_catalog)

    assert entry.path == tmp_path / "active" / "stock" / "serum-p1.webp"
    assert entry.sha256 == pending.sha256
    assert entry.fallback_roles == ("serum_texture",)
    assert json.loads(pending.metadata_path.read_text())["review_status"] == "approved"
    reloaded = load_catalog(tmp_path / "manifest.json")
    assert reloaded.entries[0].asset_id == entry.asset_id
    assert reloaded.entries[0].sha256 == pending.sha256
    assert (reloaded.entries[0].width, reloaded.entries[0].height) == (1080, 1440)
    assert reloaded.entries[0].fallback_roles == ("serum_texture",)
    provenance = reloaded.entries[0].provenance
    assert provenance is not None
    assert provenance.source_type == "stock_photo"
    assert provenance.acquired_at == pending.acquired_at
    assert provenance.run_id == pending.run_id
    assert provenance.provider == pending.provider
    assert provenance.provider_asset_id == pending.provider_asset_id
    assert provenance.source_url == pending.source_url
    assert provenance.source_file_url == pending.source_file_url
    assert provenance.author == pending.author
    assert provenance.provider_attribution == dict(pending.provider_attribution)
    assert provenance.license_snapshot == pending.license_snapshot
    assert provenance.license_snapshot_sha256 == pending.license_snapshot_sha256
    assert provenance.license_terms_url == pending.license_terms_url
    assert provenance.average_hash == pending.average_hash
    assert provenance.review_disposition == "approved_for_publishing"


def test_approval_requires_persistent_manifest_and_restores_incoming(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.catalog import CatalogError
    from src.asset_resolver.lifecycle import approve_external_asset

    pending = pending_asset(tmp_path)
    transient_catalog = AssetCatalog(
        catalog_id="test-catalog",
        root=tmp_path,
        entries=(),
        run_id="run-42",
    )

    with pytest.raises(CatalogError, match="persistent catalog manifest"):
        approve_external_asset(pending, transient_catalog)

    assert pending.path.exists()
    assert not (tmp_path / "active" / "stock" / "serum-p1.webp").exists()


def test_approval_rejects_candidate_outside_catalog_run_scope(tmp_path: Path) -> None:
    from src.asset_resolver.lifecycle import AssetLifecycleError, approve_external_asset

    pending = pending_asset(tmp_path)
    outside_path = tmp_path / "outside.webp"
    pending.path.replace(outside_path)
    outside_metadata = tmp_path / "outside.json"
    outside = replace(
        pending,
        path=outside_path,
        metadata_path=outside_metadata,
    )
    outside_metadata.write_text(json.dumps(outside.audit_record()), encoding="utf-8")

    with pytest.raises(AssetLifecycleError, match="run-scoped incoming directory"):
        approve_external_asset(outside, catalog(tmp_path))

    assert outside_path.exists()


def test_strict_audit_loader_rehydrates_canonical_pending_asset(tmp_path: Path) -> None:
    from src.asset_resolver.lifecycle import load_pending_asset, write_pending_audit

    pending = pending_asset(tmp_path)
    write_pending_audit(pending)

    assert load_pending_asset(pending.metadata_path, catalog(tmp_path)) == pending


def test_audit_loader_requires_catalog_scope(tmp_path: Path) -> None:
    from src.asset_resolver.lifecycle import load_pending_asset

    pending = pending_asset(tmp_path)

    with pytest.raises(TypeError):
        load_pending_asset(pending.metadata_path)


def test_strict_audit_loader_rejects_unknown_fields(tmp_path: Path) -> None:
    from src.asset_resolver.lifecycle import AssetLifecycleError, load_pending_asset

    pending = pending_asset(tmp_path)
    audit = json.loads(pending.metadata_path.read_text(encoding="utf-8"))
    audit["forged"] = True
    pending.metadata_path.write_text(json.dumps(audit), encoding="utf-8")

    with pytest.raises(AssetLifecycleError, match="audit schema"):
        load_pending_asset(pending.metadata_path, catalog(tmp_path))


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("sha256", "not-a-hash"),
        ("average_hash", "short"),
        ("production_relative_path", "../escape.webp"),
        ("source_url", "https://evil.test/forged"),
        ("license_snapshot_sha256", "0" * 64),
        ("acquired_at", "not-a-time"),
    ],
)
def test_strict_audit_loader_rejects_invalid_canonical_fields(
    tmp_path: Path, field_name: str, value: object
) -> None:
    from src.asset_resolver.lifecycle import AssetLifecycleError, load_pending_asset

    pending = pending_asset(tmp_path)
    audit = json.loads(pending.metadata_path.read_text(encoding="utf-8"))
    audit[field_name] = value
    pending.metadata_path.write_text(json.dumps(audit), encoding="utf-8")

    with pytest.raises(AssetLifecycleError, match="audit schema|canonical"):
        load_pending_asset(pending.metadata_path, catalog(tmp_path))


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("provider", " "),
        ("candidate_rank", 1.0),
        ("tags", []),
        ("provider_attribution", []),
        ("layout", "not-a-layout"),
    ],
)
def test_pydantic_audit_schema_rejects_wrong_types_and_empty_contract_fields(
    tmp_path: Path, field_name: str, value: object
) -> None:
    from src.asset_resolver.lifecycle import AssetLifecycleError, load_pending_asset

    pending = pending_asset(tmp_path)
    audit = json.loads(pending.metadata_path.read_text(encoding="utf-8"))
    audit[field_name] = value
    pending.metadata_path.write_text(json.dumps(audit), encoding="utf-8")

    with pytest.raises(AssetLifecycleError, match="audit schema"):
        load_pending_asset(pending.metadata_path, catalog(tmp_path))


@pytest.mark.parametrize(
    "changes",
    [
        {"author": "Mallory"},
        {"source_url": "https://www.pexels.com/photo/forged/"},
        {"role": "face_angle"},
        {"license": "forged license"},
        {"tags": ("forged",)},
        {"production_relative_path": Path("stock/forged.webp")},
    ],
)
def test_approval_rejects_forged_caller_fields(
    tmp_path: Path, changes: dict[str, object]
) -> None:
    from src.asset_resolver.lifecycle import AssetLifecycleError, approve_external_asset

    canonical = pending_asset(tmp_path)
    forged = replace(canonical, **changes)

    with pytest.raises(AssetLifecycleError, match="canonical pending audit"):
        approve_external_asset(forged, catalog(tmp_path))

    assert canonical.path.exists()
    assert not (tmp_path / "active").exists()


def test_move_failure_restores_pending_audit_and_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.asset_resolver.lifecycle import approve_external_asset

    pending = pending_asset(tmp_path)
    persistent_catalog = catalog(tmp_path)
    original_replace = Path.replace

    def failing_move(path: Path, target: Path) -> Path:
        if path == pending.path:
            raise OSError("move failed")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", failing_move)

    with pytest.raises(OSError, match="move failed"):
        approve_external_asset(pending, persistent_catalog)

    assert pending.path.exists()
    assert json.loads(pending.metadata_path.read_text())["review_status"] == "pending"
    assert json.loads((tmp_path / "manifest.json").read_text())["assets"] == []


def test_concurrent_approvals_preserve_both_manifest_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.asset_resolver.catalog import load_catalog
    from src.asset_resolver.lifecycle import approve_external_asset

    first = pending_asset(tmp_path, asset_id="p1", candidate_rank=1)
    second = pending_asset(tmp_path, asset_id="p2", candidate_rank=2)
    persistent_catalog = catalog(tmp_path)
    barrier = Barrier(2)
    original_loads = json.loads

    def synchronize_manifest_reads(value, *args, **kwargs):
        if isinstance(value, str) and '"catalog_id"' in value:
            try:
                barrier.wait(timeout=0.2)
            except BrokenBarrierError:
                pass
        return original_loads(value, *args, **kwargs)

    monkeypatch.setattr("src.asset_resolver.catalog.json.loads", synchronize_manifest_reads)

    with ThreadPoolExecutor(max_workers=2) as executor:
        entries = list(
            executor.map(
                lambda item: approve_external_asset(item, persistent_catalog),
                (first, second),
            )
        )

    reloaded = load_catalog(tmp_path / "manifest.json")
    assert {entry.asset_id for entry in entries} == {"pexels-p1", "pexels-p2"}
    assert {entry.asset_id for entry in reloaded.entries} == {"pexels-p1", "pexels-p2"}


def test_approval_rejects_tampered_pending_bytes(tmp_path: Path) -> None:
    from src.asset_resolver.lifecycle import AssetLifecycleError, approve_external_asset

    pending = pending_asset(tmp_path)
    pending.path.write_bytes(b"tampered")

    with pytest.raises(AssetLifecycleError, match="bytes are missing or changed"):
        approve_external_asset(pending, catalog(tmp_path))

    assert not (tmp_path / "active" / "stock" / "serum-p1.webp").exists()


def test_rejection_remains_auditable_and_never_enters_active(tmp_path: Path) -> None:
    from src.asset_resolver.lifecycle import (
        AssetLifecycleError,
        approve_external_asset,
        reject_external_asset,
    )

    pending = pending_asset(tmp_path)
    reject_external_asset(pending, reason="visible logo", catalog=catalog(tmp_path))

    audit = json.loads(pending.metadata_path.read_text())
    assert audit["review_status"] == "rejected"
    assert audit["rejection_reason"] == "visible logo"
    assert pending.path.exists()
    assert not (tmp_path / "active").exists()
    with pytest.raises(AssetLifecycleError, match="only pending assets can be approved"):
        approve_external_asset(pending, catalog(tmp_path))


def _safe_review() -> dict[str, bool]:
    return {
        "has_logo": False,
        "has_text": False,
    }


def test_approval_requires_explicit_resolution_for_every_unknown_safety_check(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.lifecycle import AssetLifecycleError, approve_external_asset

    pending = pending_asset(
        tmp_path,
        unresolved_safety_checks=("has_logo", "has_text"),
    )

    with pytest.raises(AssetLifecycleError, match="safety review"):
        approve_external_asset(pending, catalog(tmp_path))

    with pytest.raises(AssetLifecycleError, match="safety review"):
        approve_external_asset(
            pending,
            catalog(tmp_path),
            safety_decisions={"has_logo": False},
        )


def test_approval_persists_explicit_safe_human_review(tmp_path: Path) -> None:
    from src.asset_resolver.lifecycle import approve_external_asset

    pending = pending_asset(
        tmp_path,
        unresolved_safety_checks=("has_logo", "has_text"),
    )

    approve_external_asset(
        pending,
        catalog(tmp_path),
        safety_decisions=_safe_review(),
    )

    audit = json.loads(pending.metadata_path.read_text(encoding="utf-8"))
    assert audit["safety_review_decisions"] == _safe_review()
    assert audit["safety_reviewed_at"]
    assert audit["review_disposition"] == "approved_for_publishing"


def test_same_candidate_concurrent_approvals_have_exactly_one_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    pending = pending_asset(tmp_path, unresolved_safety_checks=())
    persistent_catalog = catalog(tmp_path)
    barrier = Barrier(2)
    original_write = lifecycle._atomic_write_json

    def synchronized_write(path: Path, payload: dict[str, object]) -> None:
        if path == pending.metadata_path and payload.get("review_status") == "approved":
            try:
                barrier.wait(timeout=0.2)
            except BrokenBarrierError:
                pass
        original_write(path, payload)

    monkeypatch.setattr(lifecycle, "_atomic_write_json", synchronized_write)

    def approve() -> object:
        try:
            return lifecycle.approve_external_asset(
                pending,
                persistent_catalog,
            )
        except Exception as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: approve(), range(2)))

    assert sum(not isinstance(item, Exception) for item in outcomes) == 1
    assert json.loads(pending.metadata_path.read_text())["review_status"] == "approved"
    destination = tmp_path / "active" / "stock" / "serum-p1.webp"
    assert destination.is_file()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert [item["asset_id"] for item in manifest["assets"]] == ["pexels-p1"]


def test_same_candidate_approve_reject_race_has_exactly_one_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    pending = pending_asset(tmp_path, unresolved_safety_checks=())
    persistent_catalog = catalog(tmp_path)
    barrier = Barrier(2)
    original_write = lifecycle._atomic_write_json

    def synchronized_write(path: Path, payload: dict[str, object]) -> None:
        if path == pending.metadata_path and payload.get("review_status") in {
            "approved",
            "rejected",
        }:
            try:
                barrier.wait(timeout=0.2)
            except BrokenBarrierError:
                pass
        original_write(path, payload)

    monkeypatch.setattr(lifecycle, "_atomic_write_json", synchronized_write)

    def approve() -> object:
        try:
            return lifecycle.approve_external_asset(
                pending,
                persistent_catalog,
            )
        except Exception as error:
            return error

    def reject() -> object:
        try:
            return lifecycle.reject_external_asset(
                pending,
                reason="review rejection",
                catalog=persistent_catalog,
            )
        except Exception as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [executor.submit(approve), executor.submit(reject)]
        results = [future.result() for future in outcomes]

    assert sum(not isinstance(item, Exception) for item in results) == 1
    audit = json.loads(pending.metadata_path.read_text())
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    destination = tmp_path / "active" / "stock" / "serum-p1.webp"
    if audit["review_status"] == "approved":
        assert destination.is_file()
        assert [item["asset_id"] for item in manifest["assets"]] == ["pexels-p1"]
    else:
        assert audit["review_status"] == "rejected"
        assert pending.path.is_file()
        assert manifest["assets"] == []


def test_cross_run_same_asset_approvals_have_one_catalog_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    first = pending_asset(tmp_path, run_id="run-a", color="red")
    second = pending_asset(tmp_path, run_id="run-b", color="blue")
    first_catalog = catalog(tmp_path, run_id="run-a")
    second_catalog = catalog(tmp_path, run_id="run-b")
    destination = tmp_path / "active" / "stock" / "serum-p1.webp"
    barrier = Barrier(2)
    original_exists = Path.exists

    def synchronized_destination_check(path: Path) -> bool:
        exists = original_exists(path)
        if path == destination and not exists:
            try:
                barrier.wait(timeout=0.2)
            except BrokenBarrierError:
                pass
        return exists

    monkeypatch.setattr(Path, "exists", synchronized_destination_check)

    def approve(item, asset_catalog) -> object:
        try:
            return lifecycle.approve_external_asset(item, asset_catalog)
        except Exception as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(approve, first, first_catalog),
            executor.submit(approve, second, second_catalog),
        ]
        outcomes = [future.result() for future in futures]

    assert sum(not isinstance(item, Exception) for item in outcomes) == 1
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert destination.is_file()
    assert len(manifest["assets"]) == 1
    assert manifest["assets"][0]["sha256"] == hashlib.sha256(
        destination.read_bytes()
    ).hexdigest()
    audits = [
        json.loads(item.metadata_path.read_text(encoding="utf-8"))
        for item in (first, second)
    ]
    assert sorted(audit["review_status"] for audit in audits) == [
        "approved",
        "pending",
    ]


def test_reloaded_approved_stock_keeps_provenance_in_local_manifest(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.catalog import load_catalog
    from src.asset_resolver.lifecycle import approve_external_asset
    from src.asset_resolver.resolver import resolve_assets
    from src.schemas.assets import AssetRequirement
    from src.schemas.visual_plan import FramePlanItem, VisualPlan

    pending = pending_asset(tmp_path)
    approve_external_asset(pending, catalog(tmp_path))
    reloaded = load_catalog(tmp_path / "manifest.json")
    plan = VisualPlan(
        design_system="beauty_editorial_v1",
        content_job="diagnose_and_adjust",
        primary_visual_family="face_zone_map",
        supporting_families=["beauty_editorial", "saveable_reference"],
        frame_plan=[
            FramePlanItem(frame_id="cover", role="cover", layout="editorial_cover", purpose="cover"),
            FramePlanItem(frame_id="texture", role="texture", layout="texture_baseline", purpose="texture"),
            FramePlanItem(frame_id="face", role="face", layout="front_face_zone", purpose="face"),
            FramePlanItem(frame_id="steps", role="steps", layout="step_timeline", purpose="steps"),
            FramePlanItem(frame_id="save", role="save", layout="saveable_reference", purpose="save"),
        ],
        required_assets=[
            AssetRequirement(
                slot_id="serum-slot",
                role="serum_texture",
                layout="texture_baseline",
                min_width=1080,
                min_height=1440,
                context_tags=["serum"],
                orientation="portrait",
            )
        ],
    )

    manifest = resolve_assets(plan, reloaded)
    item = manifest.items[0]

    assert item.status == "active"
    assert item.source_type == "stock_photo"
    assert item.provider == pending.provider
    assert item.provider_asset_id == pending.provider_asset_id
    assert item.source_url == pending.source_url
    assert item.source_file_url == pending.source_file_url
    assert item.author == pending.author
    assert item.provider_attribution == dict(pending.provider_attribution)
    assert item.license_snapshot == pending.license_snapshot
    assert item.license_snapshot_sha256 == pending.license_snapshot_sha256
    assert item.license_terms_url == pending.license_terms_url
    assert item.run_id == pending.run_id
    assert item.acquired_at == pending.acquired_at
    assert item.average_hash == pending.average_hash
    assert item.safety_review_decisions == {}
    assert item.review_status == "approved"
    assert item.review_disposition == "approved_for_publishing"
    assert item.requirement_fingerprint == pending.requirement_fingerprint


@pytest.mark.parametrize(
    "field_name,unsafe_value",
    [
        ("has_logo", True),
        ("allowed_for_publishing", False),
    ],
)
def test_catalog_reload_rejects_unsafe_approved_safety_decisions(
    tmp_path: Path, field_name: str, unsafe_value: bool
) -> None:
    from src.asset_resolver.catalog import CatalogError, load_catalog
    from src.asset_resolver.lifecycle import approve_external_asset

    pending = pending_asset(
        tmp_path,
        unresolved_safety_checks=(field_name,),
    )
    safe_value = field_name == "allowed_for_publishing"
    approve_external_asset(
        pending,
        catalog(tmp_path),
        safety_decisions={field_name: safe_value},
    )
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["assets"][0]["provenance"]["safety_review_decisions"][
        field_name
    ] = unsafe_value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(CatalogError, match="safety review"):
        load_catalog(manifest_path)
