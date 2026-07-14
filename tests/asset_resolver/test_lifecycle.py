from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, BrokenBarrierError, Event
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


def _batch_item(candidate):
    return {
        "status": "pending_external",
        "pending_id": candidate.pending_id,
        "slot_id": candidate.slot_id,
        "provider": candidate.provider,
        "provider_asset_id": candidate.provider_asset_id,
        "requirement_fingerprint": candidate.requirement_fingerprint,
        "sha256": candidate.sha256,
        "metadata_path": str(candidate.metadata_path.resolve()),
    }


def _batch_decision(candidate, decision="approved", safety_decisions=None):
    from src.asset_resolver.lifecycle import pending_asset_decision_binding

    return {
        "decision": decision,
        "binding": pending_asset_decision_binding(candidate),
        "safety_decisions": safety_decisions or {},
    }


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
    import src.asset_resolver.lifecycle as lifecycle

    from src.asset_resolver.lifecycle import approve_external_asset

    pending = pending_asset(tmp_path)
    persistent_catalog = catalog(tmp_path)
    original_replace = lifecycle._durable_replace

    def failing_move(path: Path, target: Path, **kwargs) -> None:
        if path == pending.path:
            raise OSError("move failed")
        original_replace(path, target, **kwargs)

    monkeypatch.setattr(lifecycle, "_durable_replace", failing_move)

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


def test_safety_review_contract_exposes_one_strict_canonical_schema() -> None:
    from src.asset_resolver import lifecycle

    assert lifecycle.SAFETY_CHECK_KEYS == frozenset(
        {
            "has_watermark",
            "has_logo",
            "has_text",
            "recognizable_face",
            "allowed_for_publishing",
        }
    )
    review = lifecycle.ApprovedSafetyReview.model_validate(
        {
            "unresolved_safety_checks": ["has_logo", "allowed_for_publishing"],
            "safety_review_decisions": {
                "has_logo": False,
                "allowed_for_publishing": True,
            },
            "safety_reviewed_at": "2026-07-14T12:00:00+00:00",
            "review_status": "approved",
            "review_disposition": "approved_for_publishing",
        }
    )

    assert review.safety_review_decisions["allowed_for_publishing"] is True


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


def test_batch_review_rolls_back_first_approval_when_second_approval_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    first = pending_asset(tmp_path, asset_id="p1")
    second = pending_asset(tmp_path, asset_id="p2")
    asset_catalog = catalog(tmp_path)
    def fail_second(event: str) -> None:
        if event == f"{second.pending_id}.audit.intent":
            raise RuntimeError("second approval failed")

    monkeypatch.setattr(lifecycle, "_crash_point", fail_second)

    with pytest.raises(RuntimeError, match="second approval failed"):
        lifecycle.review_pending_asset_batch(
            asset_catalog,
            [_batch_item(first), _batch_item(second)],
            {
                first.pending_id: _batch_decision(first),
                second.pending_id: _batch_decision(second),
            },
            rejection_reason="not selected",
        )

    assert first.path.is_file() and second.path.is_file()
    assert json.loads(first.metadata_path.read_text())["review_status"] == "pending"
    assert json.loads(second.metadata_path.read_text())["review_status"] == "pending"
    assert json.loads((tmp_path / "manifest.json").read_text())["assets"] == []


def test_batch_review_rolls_back_mixed_decisions_when_finalize_fails(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.lifecycle import review_pending_asset_batch

    approved = pending_asset(tmp_path, asset_id="p1")
    rejected = pending_asset(tmp_path, asset_id="p2")

    with pytest.raises(RuntimeError, match="resolve failed"):
        review_pending_asset_batch(
            catalog(tmp_path),
            [_batch_item(approved), _batch_item(rejected)],
            {
                approved.pending_id: _batch_decision(approved),
                rejected.pending_id: _batch_decision(rejected, "rejected"),
            },
            rejection_reason="visible logo",
            finalize=lambda: (_ for _ in ()).throw(RuntimeError("resolve failed")),
        )

    assert approved.path.is_file() and rejected.path.is_file()
    assert json.loads(approved.metadata_path.read_text())["review_status"] == "pending"
    assert json.loads(rejected.metadata_path.read_text())["review_status"] == "pending"
    assert json.loads((tmp_path / "manifest.json").read_text())["assets"] == []


def test_batch_review_mixed_decisions_commit_and_retry_idempotently(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.lifecycle import review_pending_asset_batch

    approved = pending_asset(tmp_path, asset_id="p1")
    rejected = pending_asset(tmp_path, asset_id="p2")
    asset_catalog = catalog(tmp_path)
    items = [_batch_item(approved), _batch_item(rejected)]
    decisions = {
        approved.pending_id: _batch_decision(approved),
        rejected.pending_id: _batch_decision(rejected, "rejected"),
    }

    first = review_pending_asset_batch(
        asset_catalog,
        items,
        decisions,
        rejection_reason="visible logo",
        finalize=lambda: "resolved",
    )
    second = review_pending_asset_batch(
        asset_catalog,
        items,
        decisions,
        rejection_reason="visible logo",
        finalize=lambda: "resolved-again",
    )

    assert first.any_rejected is True and first.finalized_value == "resolved"
    assert second.any_rejected is True and second.finalized_value == "resolved-again"
    assert len(json.loads((tmp_path / "manifest.json").read_text())["assets"]) == 1


def test_batch_review_rejects_stale_binding_and_implicit_safety_approval(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.lifecycle import AssetLifecycleError, review_pending_asset_batch

    candidate = pending_asset(
        tmp_path,
        unresolved_safety_checks=("has_logo", "allowed_for_publishing"),
    )
    stale = _batch_decision(candidate)
    stale["binding"] = {**stale["binding"], "sha256": "0" * 64}

    with pytest.raises(AssetLifecycleError, match="binding"):
        review_pending_asset_batch(
            catalog(tmp_path),
            [_batch_item(candidate)],
            {candidate.pending_id: stale},
            rejection_reason="not selected",
        )

    with pytest.raises(AssetLifecycleError, match="explicitly resolve"):
        review_pending_asset_batch(
            catalog(tmp_path),
            [_batch_item(candidate)],
            {candidate.pending_id: _batch_decision(candidate)},
            rejection_reason="not selected",
        )
    assert json.loads(candidate.metadata_path.read_text())["review_status"] == "pending"


def test_batch_review_and_standalone_approval_share_one_lifecycle_lock(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.lifecycle import (
        approve_external_asset,
        review_pending_asset_batch,
    )

    batch_candidate = pending_asset(tmp_path, asset_id="batch")
    standalone_candidate = pending_asset(tmp_path, asset_id="standalone")
    asset_catalog = catalog(tmp_path)
    batch_in_finalize = Event()
    release_batch = Event()
    standalone_started = Event()

    def hold_batch_lock() -> None:
        batch_in_finalize.set()
        assert release_batch.wait(timeout=5)

    def standalone_approval():
        standalone_started.set()
        return approve_external_asset(standalone_candidate, asset_catalog)

    with ThreadPoolExecutor(max_workers=2) as executor:
        batch_future = executor.submit(
            review_pending_asset_batch,
            asset_catalog,
            [_batch_item(batch_candidate)],
            {batch_candidate.pending_id: _batch_decision(batch_candidate)},
            rejection_reason="not selected",
            finalize=hold_batch_lock,
        )
        assert batch_in_finalize.wait(timeout=5)
        standalone_future = executor.submit(standalone_approval)
        assert standalone_started.wait(timeout=5)
        assert not standalone_future.done()
        release_batch.set()
        batch_future.result(timeout=5)
        standalone_future.result(timeout=5)

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert {item["asset_id"] for item in manifest["assets"]} == {
        "pexels-batch",
        "pexels-standalone",
    }


def test_batch_rollback_cas_preserves_concurrent_manifest_change(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.lifecycle import review_pending_asset_batch

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    manifest_path = tmp_path / "manifest.json"

    def concurrent_manifest_write_then_fail() -> None:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["concurrent_writer"] = "committed"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        raise RuntimeError("finalize failed after concurrent write")

    with pytest.raises(
        RuntimeError, match="finalize failed after concurrent write"
    ) as raised:
        review_pending_asset_batch(
            asset_catalog,
            [_batch_item(candidate)],
            {candidate.pending_id: _batch_decision(candidate)},
            rejection_reason="not selected",
            finalize=concurrent_manifest_write_then_fail,
        )

    assert json.loads(manifest_path.read_text())["concurrent_writer"] == "committed"
    assert any(
        "recovery refused to overwrite" in note
        for note in getattr(raised.value, "__notes__", ())
    )
    journals = list((tmp_path / ".asset-review-recovery").rglob("*.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_text())["state"] == "needs_recovery"


def test_batch_rollback_aggregates_failures_and_recovers_on_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    destination = tmp_path / "active" / "stock" / "serum-p1.webp"
    original_replace = lifecycle._durable_replace
    original_atomic_write_bytes = lifecycle._atomic_write_bytes
    original_audit_bytes = candidate.metadata_path.read_bytes()
    fail_rollback = {"enabled": True}

    def fail_asset_restore(path: Path, target: Path, **kwargs) -> None:
        if fail_rollback["enabled"] and path == destination and target == candidate.path:
            raise OSError("rollback move failed")
        original_replace(path, target, **kwargs)

    def fail_audit_restore(path: Path, payload: bytes, **kwargs) -> None:
        if (
            fail_rollback["enabled"]
            and path == candidate.metadata_path
            and payload == original_audit_bytes
        ):
            raise OSError("rollback audit write failed")
        original_atomic_write_bytes(path, payload, **kwargs)

    monkeypatch.setattr(lifecycle, "_durable_replace", fail_asset_restore)
    monkeypatch.setattr(lifecycle, "_atomic_write_bytes", fail_audit_restore)

    with pytest.raises(RuntimeError, match="finalize failed") as raised:
        lifecycle.review_pending_asset_batch(
            asset_catalog,
            [_batch_item(candidate)],
            {candidate.pending_id: _batch_decision(candidate)},
            rejection_reason="not selected",
            finalize=lambda: (_ for _ in ()).throw(RuntimeError("finalize failed")),
        )

    notes = " ".join(getattr(raised.value, "__notes__", ()))
    assert "rollback move failed" in notes
    assert "rollback audit write failed" in notes
    journal_root = tmp_path / ".asset-review-recovery"
    assert len(list(journal_root.rglob("*.json"))) == 1

    fail_rollback["enabled"] = False
    result = lifecycle.review_pending_asset_batch(
        asset_catalog,
        [_batch_item(candidate)],
        {candidate.pending_id: _batch_decision(candidate)},
        rejection_reason="not selected",
    )

    assert result.any_rejected is False
    assert destination.is_file()
    assert json.loads(candidate.metadata_path.read_text())["review_status"] == "approved"
    assert list(journal_root.rglob("*.json")) == []


def test_batch_review_accepts_only_canonical_pending_ids(tmp_path: Path) -> None:
    from src.asset_resolver.lifecycle import (
        AssetLifecycleError,
        review_pending_asset_batch,
    )

    candidate = pending_asset(tmp_path)

    with pytest.raises(AssetLifecycleError, match="unknown canonical pending"):
        review_pending_asset_batch(
            catalog(tmp_path),
            [_batch_item(candidate)],
            {candidate.provider_asset_id: _batch_decision(candidate)},
            rejection_reason="not selected",
        )

    assert candidate.path.is_file()
    assert json.loads(candidate.metadata_path.read_text())["review_status"] == "pending"


def test_batch_recovery_rejects_external_symlink_journal_directory(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.lifecycle import (
        AssetLifecycleError,
        review_pending_asset_batch,
    )

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    external_journals = tmp_path / "outside-journals"
    external_journals.mkdir()
    recovery_root = tmp_path / ".asset-review-recovery"
    recovery_root.symlink_to(external_journals, target_is_directory=True)
    outside_source = tmp_path / "outside-source.bin"
    outside_target = tmp_path / "outside-target.bin"
    outside_source.write_bytes(b"do not move")
    manifest_bytes = (tmp_path / "manifest.json").read_bytes()
    malicious = {
        "state": "needs_recovery",
        "manifest_bytes_b64": __import__("base64").b64encode(
            manifest_bytes
        ).decode("ascii"),
        "expected_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "assets": [
            {
                "pending_path": str(outside_target),
                "destination": str(outside_source),
                "metadata_path": str(candidate.metadata_path),
                "audit_bytes_b64": __import__("base64").b64encode(
                    candidate.metadata_path.read_bytes()
                ).decode("ascii"),
            }
        ],
    }
    (external_journals / "attacker.json").write_text(json.dumps(malicious))

    with pytest.raises(AssetLifecycleError, match="recovery journal directory"):
        review_pending_asset_batch(
            asset_catalog,
            [_batch_item(candidate)],
            {candidate.pending_id: _batch_decision(candidate)},
            rejection_reason="not selected",
        )

    assert outside_source.read_bytes() == b"do not move"
    assert not outside_target.exists()


def _leave_recovery_journal(
    tmp_path: Path,
    candidate,
    asset_catalog: AssetCatalog,
) -> Path:
    from src.asset_resolver.lifecycle import review_pending_asset_batch

    manifest_path = tmp_path / "manifest.json"

    def force_manifest_cas_failure() -> None:
        raw = json.loads(manifest_path.read_text())
        raw["unrelated_committed_value"] = True
        manifest_path.write_text(json.dumps(raw))
        raise RuntimeError("leave recovery journal")

    with pytest.raises(RuntimeError, match="leave recovery journal"):
        review_pending_asset_batch(
            asset_catalog,
            [_batch_item(candidate)],
            {candidate.pending_id: _batch_decision(candidate)},
            rejection_reason="not selected",
            finalize=force_manifest_cas_failure,
        )
    journals = list((tmp_path / ".asset-review-recovery").rglob("*.json"))
    assert len(journals) == 1
    return journals[0]


def test_batch_recovery_rejects_journal_path_escape_before_mutation(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.lifecycle import (
        AssetLifecycleError,
        review_pending_asset_batch,
    )

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    journal_path = _leave_recovery_journal(tmp_path, candidate, asset_catalog)
    outside_source = tmp_path / "outside-source.bin"
    outside_target = tmp_path / "outside-target.bin"
    outside_source.write_bytes(b"do not move")
    journal = json.loads(journal_path.read_text())
    journal["assets"][0]["pending_path"] = str(outside_target)
    journal["assets"][0]["destination"] = str(outside_source)
    journal_path.write_text(json.dumps(journal))

    with pytest.raises(AssetLifecycleError, match="recovery journal"):
        review_pending_asset_batch(
            asset_catalog,
            [_batch_item(candidate)],
            {candidate.pending_id: _batch_decision(candidate)},
            rejection_reason="not selected",
        )

    assert outside_source.read_bytes() == b"do not move"
    assert not outside_target.exists()


def test_batch_recovery_rejects_unknown_journal_schema_before_mutation(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.lifecycle import (
        AssetLifecycleError,
        review_pending_asset_batch,
    )

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    journal_path = _leave_recovery_journal(tmp_path, candidate, asset_catalog)
    original_audit = candidate.metadata_path.read_bytes()
    journal = json.loads(journal_path.read_text())
    journal["attacker_extension"] = {"write": "/tmp/owned"}
    journal_path.write_text(json.dumps(journal))

    with pytest.raises(AssetLifecycleError, match="schema"):
        review_pending_asset_batch(
            asset_catalog,
            [_batch_item(candidate)],
            {candidate.pending_id: _batch_decision(candidate)},
            rejection_reason="not selected",
        )

    assert candidate.metadata_path.read_bytes() == original_audit


def test_batch_recovery_rejects_tampered_audit_snapshot_before_mutation(
    tmp_path: Path,
) -> None:
    import base64

    from src.asset_resolver.lifecycle import (
        AssetLifecycleError,
        review_pending_asset_batch,
    )

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    journal_path = _leave_recovery_journal(tmp_path, candidate, asset_catalog)
    original_audit = candidate.metadata_path.read_bytes()
    journal = json.loads(journal_path.read_text())
    journal["assets"][0]["original_audit_bytes_b64"] = base64.b64encode(
        b'{"review_status":"attacker"}'
    ).decode("ascii")
    journal_path.write_text(json.dumps(journal))

    with pytest.raises(AssetLifecycleError, match="audit snapshot"):
        review_pending_asset_batch(
            asset_catalog,
            [_batch_item(candidate)],
            {candidate.pending_id: _batch_decision(candidate)},
            rejection_reason="not selected",
        )

    assert candidate.metadata_path.read_bytes() == original_audit


@pytest.mark.parametrize(
    "event_template",
    [
        "transaction.prepared",
        "transaction.applying",
        "{pending_id}.audit.intent",
        "{pending_id}.audit.applied",
        "{pending_id}.audit.done",
        "{pending_id}.move.intent",
        "{pending_id}.move.applied",
        "{pending_id}.move.done",
        "manifest.intent",
        "manifest.applied",
        "manifest.done",
        "transaction.finalizing",
        "transaction.committed",
    ],
)
def test_batch_recovers_idempotently_after_every_forward_wal_crash_point(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_template: str,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    class SimulatedProcessCrash(BaseException):
        pass

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    target_event = event_template.format(pending_id=candidate.pending_id)
    observed = []

    def crash_at_target(event: str) -> None:
        observed.append(event)
        if event == target_event:
            raise SimulatedProcessCrash(event)

    monkeypatch.setattr(lifecycle, "_crash_point", crash_at_target)
    with pytest.raises(SimulatedProcessCrash, match=target_event):
        lifecycle.review_pending_asset_batch(
            asset_catalog,
            [_batch_item(candidate)],
            {candidate.pending_id: _batch_decision(candidate)},
            rejection_reason="not selected",
        )
    assert target_event in observed

    monkeypatch.setattr(lifecycle, "_crash_point", lambda _event: None)
    lifecycle.review_pending_asset_batch(
        asset_catalog,
        [_batch_item(candidate)],
        {candidate.pending_id: _batch_decision(candidate)},
        rejection_reason="not selected",
    )

    destination = tmp_path / "active" / "stock" / "serum-p1.webp"
    assert destination.is_file()
    assert json.loads(candidate.metadata_path.read_text())["review_status"] == "approved"
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert [item["asset_id"] for item in manifest["assets"]] == ["pexels-p1"]
    assert list((tmp_path / ".asset-review-recovery").rglob("*.json")) == []


@pytest.mark.parametrize(
    "event_template",
    [
        "rollback_manifest.intent",
        "rollback_manifest.applied",
        "rollback_manifest.done",
        "{pending_id}.rollback_move.intent",
        "{pending_id}.rollback_move.applied",
        "{pending_id}.rollback_move.done",
        "{pending_id}.rollback_audit.intent",
        "{pending_id}.rollback_audit.applied",
        "{pending_id}.rollback_audit.done",
    ],
)
def test_batch_recovers_idempotently_after_every_rollback_wal_crash_point(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_template: str,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    class SimulatedProcessCrash(BaseException):
        pass

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    target_event = event_template.format(pending_id=candidate.pending_id)

    def crash_during_rollback(event: str) -> None:
        if event == target_event:
            raise SimulatedProcessCrash(event)

    monkeypatch.setattr(lifecycle, "_crash_point", crash_during_rollback)
    with pytest.raises(SimulatedProcessCrash, match=target_event):
        lifecycle.review_pending_asset_batch(
            asset_catalog,
            [_batch_item(candidate)],
            {candidate.pending_id: _batch_decision(candidate)},
            rejection_reason="not selected",
            finalize=lambda: (_ for _ in ()).throw(RuntimeError("finalize failed")),
        )

    monkeypatch.setattr(lifecycle, "_crash_point", lambda _event: None)
    lifecycle.review_pending_asset_batch(
        asset_catalog,
        [_batch_item(candidate)],
        {candidate.pending_id: _batch_decision(candidate)},
        rejection_reason="not selected",
    )

    assert (tmp_path / "active" / "stock" / "serum-p1.webp").is_file()
    assert json.loads(candidate.metadata_path.read_text())["review_status"] == "approved"
    assert list((tmp_path / ".asset-review-recovery").rglob("*.json")) == []


def test_failed_retry_of_preexisting_approval_does_not_roll_it_back(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.lifecycle import review_pending_asset_batch

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    items = [_batch_item(candidate)]
    decisions = {candidate.pending_id: _batch_decision(candidate)}
    review_pending_asset_batch(
        asset_catalog,
        items,
        decisions,
        rejection_reason="not selected",
    )

    with pytest.raises(RuntimeError, match="retry finalize failed"):
        review_pending_asset_batch(
            asset_catalog,
            items,
            decisions,
            rejection_reason="not selected",
            finalize=lambda: (_ for _ in ()).throw(
                RuntimeError("retry finalize failed")
            ),
        )

    destination = tmp_path / "active" / "stock" / "serum-p1.webp"
    assert destination.is_file()
    assert not candidate.path.exists()
    assert json.loads(candidate.metadata_path.read_text())["review_status"] == "approved"
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert [item["asset_id"] for item in manifest["assets"]] == ["pexels-p1"]


def test_catalog_review_lock_rejects_symlink(tmp_path: Path) -> None:
    from src.asset_resolver.catalog import CatalogError
    from src.asset_resolver.lifecycle import approve_external_asset

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    outside = tmp_path / "outside-lock-target"
    outside.write_bytes(b"outside")
    (tmp_path / ".asset-review.lock").symlink_to(outside)

    with pytest.raises(CatalogError, match="review lock"):
        approve_external_asset(candidate, asset_catalog)

    assert outside.read_bytes() == b"outside"
    assert candidate.path.is_file()


def test_catalog_review_lock_rejects_hardlink_alias(tmp_path: Path) -> None:
    import os

    from src.asset_resolver.catalog import CatalogError
    from src.asset_resolver.lifecycle import approve_external_asset

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    outside = tmp_path / "outside-lock-target"
    outside.write_bytes(b"outside")
    os.link(outside, tmp_path / ".asset-review.lock")

    with pytest.raises(CatalogError, match="review lock"):
        approve_external_asset(candidate, asset_catalog)

    assert candidate.path.is_file()


def test_catalog_review_lock_rejects_replacement_after_flock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.asset_resolver.catalog as catalog_module
    from src.asset_resolver.catalog import CatalogError
    from src.asset_resolver.lifecycle import approve_external_asset

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    lock_path = tmp_path / ".asset-review.lock"
    original_flock = catalog_module.fcntl.flock
    replaced = False

    def replace_after_lock(descriptor: int, operation: int) -> None:
        nonlocal replaced
        original_flock(descriptor, operation)
        if operation == catalog_module.fcntl.LOCK_EX and not replaced:
            replaced = True
            replacement = tmp_path / "replacement-lock"
            replacement.write_bytes(b"replacement")
            replacement.replace(lock_path)

    monkeypatch.setattr(catalog_module.fcntl, "flock", replace_after_lock)

    with pytest.raises(CatalogError, match="review lock"):
        approve_external_asset(candidate, asset_catalog)

    assert candidate.path.is_file()


def test_catalog_review_lock_rejects_root_swapped_during_root_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.asset_resolver.catalog as catalog_module
    from src.asset_resolver.catalog import CatalogError, catalog_review_lock

    root = tmp_path / "catalog"
    root.mkdir()
    detached_original = tmp_path / "catalog-original"
    detached_replacement = tmp_path / "catalog-replacement"
    original_open = catalog_module.os.open
    swapped = False

    def open_swapped_root(path, flags, *args, **kwargs):
        nonlocal swapped
        if Path(path) == root and kwargs.get("dir_fd") is None and not swapped:
            swapped = True
            root.rename(detached_original)
            root.mkdir()
            descriptor = original_open(path, flags, *args, **kwargs)
            root.rename(detached_replacement)
            detached_original.rename(root)
            return descriptor
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(catalog_module.os, "open", open_swapped_root)

    with pytest.raises(CatalogError, match="review lock"):
        with catalog_review_lock(root):
            pass

    assert not (detached_replacement / ".asset-review.lock").exists()


def test_committed_transaction_journal_replay_never_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    class SimulatedProcessCrash(BaseException):
        pass

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)

    def crash_after_commit(event: str) -> None:
        if event == "transaction.committed":
            raise SimulatedProcessCrash(event)

    monkeypatch.setattr(lifecycle, "_crash_point", crash_after_commit)
    with pytest.raises(SimulatedProcessCrash):
        lifecycle.review_pending_asset_batch(
            asset_catalog,
            [_batch_item(candidate)],
            {candidate.pending_id: _batch_decision(candidate)},
            rejection_reason="not selected",
        )
    journal_path = next((tmp_path / ".asset-review-recovery").rglob("*.json"))
    replay = json.loads(journal_path.read_text())
    replay["state"] = "applying"
    journal_path.write_text(json.dumps(replay))

    monkeypatch.setattr(lifecycle, "_crash_point", lambda _event: None)
    lifecycle.review_pending_asset_batch(
        asset_catalog,
        [_batch_item(candidate)],
        {candidate.pending_id: _batch_decision(candidate)},
        rejection_reason="not selected",
    )

    assert (tmp_path / "active" / "stock" / "serum-p1.webp").is_file()
    assert json.loads(candidate.metadata_path.read_text())["review_status"] == "approved"


def test_empty_operation_journal_cannot_rewrite_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import base64
    import src.asset_resolver.lifecycle as lifecycle

    class SimulatedProcessCrash(BaseException):
        pass

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)

    def crash_after_manifest(event: str) -> None:
        if event == "manifest.done":
            raise SimulatedProcessCrash(event)

    monkeypatch.setattr(lifecycle, "_crash_point", crash_after_manifest)
    with pytest.raises(SimulatedProcessCrash):
        lifecycle.review_pending_asset_batch(
            asset_catalog,
            [_batch_item(candidate)],
            {candidate.pending_id: _batch_decision(candidate)},
            rejection_reason="not selected",
        )
    manifest_path = tmp_path / "manifest.json"
    committed_manifest = manifest_path.read_bytes()
    journal_path = next((tmp_path / ".asset-review-recovery").rglob("*.json"))
    forged = json.loads(journal_path.read_text())
    malicious_manifest = json.dumps(
        {"catalog_id": "test-catalog", "assets": [], "attacker": True}
    ).encode()
    forged["assets"] = []
    forged["original_manifest_bytes_b64"] = base64.b64encode(
        malicious_manifest
    ).decode("ascii")
    forged["original_manifest_sha256"] = hashlib.sha256(
        malicious_manifest
    ).hexdigest()
    journal_path.write_text(json.dumps(forged))

    monkeypatch.setattr(lifecycle, "_crash_point", lambda _event: None)
    with pytest.raises(lifecycle.AssetLifecycleError, match="recovery journal"):
        lifecycle.review_pending_asset_batch(
            asset_catalog,
            [_batch_item(candidate)],
            {candidate.pending_id: _batch_decision(candidate)},
            rejection_reason="not selected",
        )

    assert manifest_path.read_bytes() == committed_manifest


@pytest.mark.parametrize(
    "event_template",
    [
        "transaction.registered",
        "transaction.prepared",
        "transaction.applying",
        "{pending_id}.audit.intent",
        "{pending_id}.audit.applied",
        "{pending_id}.audit.done",
        "{pending_id}.move.intent",
        "{pending_id}.move.applied",
        "{pending_id}.move.done",
        "manifest.intent",
        "manifest.applied",
        "manifest.done",
        "transaction.finalizing",
        "transaction.commit_registered",
        "transaction.committed",
    ],
)
def test_standalone_approval_recovers_through_shared_wal_crash_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_template: str,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    class SimulatedProcessCrash(BaseException):
        pass

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    target_event = event_template.format(pending_id=candidate.pending_id)

    def crash_at_target(event: str) -> None:
        if event == target_event:
            raise SimulatedProcessCrash(event)

    monkeypatch.setattr(lifecycle, "_crash_point", crash_at_target)
    with pytest.raises(SimulatedProcessCrash):
        lifecycle.approve_external_asset(candidate, asset_catalog)

    monkeypatch.setattr(lifecycle, "_crash_point", lambda _event: None)
    if target_event in {
        "transaction.commit_registered",
        "transaction.committed",
    }:
        with pytest.raises(lifecycle.AssetLifecycleError, match="only pending"):
            lifecycle.approve_external_asset(candidate, asset_catalog)
    else:
        lifecycle.approve_external_asset(candidate, asset_catalog)

    assert json.loads(candidate.metadata_path.read_text())["review_status"] == "approved"
    assert (tmp_path / "active" / "stock" / "serum-p1.webp").is_file()
    assert json.loads((tmp_path / "manifest.json").read_text())["assets"][0][
        "asset_id"
    ] == "pexels-p1"


@pytest.mark.parametrize(
    "event_template",
    [
        "transaction.registered",
        "transaction.prepared",
        "transaction.applying",
        "{pending_id}.audit.intent",
        "{pending_id}.audit.applied",
        "{pending_id}.audit.done",
        "manifest.intent",
        "manifest.applied",
        "manifest.done",
        "transaction.finalizing",
        "transaction.commit_registered",
        "transaction.committed",
    ],
)
def test_standalone_rejection_recovers_through_shared_wal_crash_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_template: str,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    class SimulatedProcessCrash(BaseException):
        pass

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    target_event = event_template.format(pending_id=candidate.pending_id)

    def crash_at_target(event: str) -> None:
        if event == target_event:
            raise SimulatedProcessCrash(event)

    monkeypatch.setattr(lifecycle, "_crash_point", crash_at_target)
    with pytest.raises(SimulatedProcessCrash):
        lifecycle.reject_external_asset(
            candidate,
            reason="not selected",
            catalog=asset_catalog,
        )

    monkeypatch.setattr(lifecycle, "_crash_point", lambda _event: None)
    if target_event in {
        "transaction.commit_registered",
        "transaction.committed",
    }:
        with pytest.raises(lifecycle.AssetLifecycleError, match="only pending"):
            lifecycle.reject_external_asset(
                candidate,
                reason="not selected",
                catalog=asset_catalog,
            )
    else:
        lifecycle.reject_external_asset(
            candidate,
            reason="not selected",
            catalog=asset_catalog,
        )

    audit = json.loads(candidate.metadata_path.read_text())
    assert audit["review_status"] == "rejected"
    assert candidate.path.is_file()
    assert json.loads((tmp_path / "manifest.json").read_text())["assets"] == []


def test_catalog_transaction_registry_supports_multiple_run_ids(
    tmp_path: Path,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    run_a = catalog(tmp_path, run_id="run-a")
    first = pending_asset(tmp_path, run_id="run-a", asset_id="a")
    lifecycle.approve_external_asset(first, run_a)

    run_b = replace(run_a, run_id="run-b")
    approved = pending_asset(tmp_path, run_id="run-b", asset_id="b")
    rejected = pending_asset(tmp_path, run_id="run-b", asset_id="c")
    lifecycle.approve_external_asset(approved, run_b)
    lifecycle.reject_external_asset(
        rejected,
        reason="not selected",
        catalog=run_b,
    )

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert {item["asset_id"] for item in manifest["assets"]} == {
        "pexels-a",
        "pexels-b",
    }
    registry = json.loads(
        (tmp_path / ".asset-review-recovery" / "transactions.registry").read_text()
    )
    assert {entry["run_id"] for entry in registry["transactions"].values()} == {
        "run-b",
    }


def test_crashed_run_does_not_isolate_other_run_and_can_recover_later(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    class SimulatedProcessCrash(BaseException):
        pass

    run_a = catalog(tmp_path, run_id="run-a")
    first = pending_asset(tmp_path, run_id="run-a", asset_id="a")

    def crash_after_audit(event: str) -> None:
        if event == f"{first.pending_id}.audit.applied":
            raise SimulatedProcessCrash(event)

    monkeypatch.setattr(lifecycle, "_crash_point", crash_after_audit)
    with pytest.raises(SimulatedProcessCrash):
        lifecycle.approve_external_asset(first, run_a)

    monkeypatch.setattr(lifecycle, "_crash_point", lambda _event: None)
    run_b = replace(run_a, run_id="run-b")
    second = pending_asset(tmp_path, run_id="run-b", asset_id="b")
    lifecycle.approve_external_asset(second, run_b)

    third = pending_asset(tmp_path, run_id="run-a", asset_id="c")
    lifecycle.approve_external_asset(third, run_a)

    assert json.loads(first.metadata_path.read_text())["review_status"] == "pending"
    assert first.path.is_file()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert {item["asset_id"] for item in manifest["assets"]} == {
        "pexels-b",
        "pexels-c",
    }


@pytest.mark.parametrize("crash_event", ["manifest.intent", "manifest.applied", "manifest.done"])
def test_new_run_recovers_prepared_manifest_transaction_before_its_own_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_event: str,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    class SimulatedProcessCrash(BaseException):
        pass

    run_a = catalog(tmp_path, run_id="run-a")
    first = pending_asset(tmp_path, run_id="run-a", asset_id="a")

    def crash_run_a(event: str) -> None:
        if event == crash_event:
            raise SimulatedProcessCrash(event)

    monkeypatch.setattr(lifecycle, "_crash_point", crash_run_a)
    with pytest.raises(SimulatedProcessCrash, match=crash_event):
        lifecycle.approve_external_asset(first, run_a)

    monkeypatch.setattr(lifecycle, "_crash_point", lambda _event: None)
    run_b = replace(run_a, run_id="run-b")
    second = pending_asset(tmp_path, run_id="run-b", asset_id="b")
    lifecycle.approve_external_asset(second, run_b)

    assert first.path.is_file()
    assert json.loads(first.metadata_path.read_text())["review_status"] == "pending"
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert [item["asset_id"] for item in manifest["assets"]] == ["pexels-b"]

    lifecycle.approve_external_asset(first, run_a)

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert {item["asset_id"] for item in manifest["assets"]} == {
        "pexels-a",
        "pexels-b",
    }
    assert json.loads(first.metadata_path.read_text())["review_status"] == "approved"
    assert json.loads(second.metadata_path.read_text())["review_status"] == "approved"
    assert list((tmp_path / ".asset-review-recovery").rglob("*.json")) == []


def test_run_recovery_directories_use_case_sensitive_hash_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    class SimulatedProcessCrash(BaseException):
        pass

    monkeypatch.setattr(
        lifecycle,
        "_crash_point",
        lambda event: (_ for _ in ()).throw(SimulatedProcessCrash(event))
        if event == "transaction.registered"
        else None,
    )
    for run_id, asset_id in (("Run", "upper"), ("run", "lower")):
        candidate = pending_asset(tmp_path, run_id=run_id, asset_id=asset_id)
        with pytest.raises(SimulatedProcessCrash, match="transaction.registered"):
            lifecycle.approve_external_asset(candidate, catalog(tmp_path, run_id=run_id))

    recovery_root = tmp_path / ".asset-review-recovery"
    expected = {
        hashlib.sha256(run_id.encode("utf-8")).hexdigest()
        for run_id in ("Run", "run")
    }
    assert expected.issubset({path.name for path in recovery_root.iterdir()})
    assert not (recovery_root / "Run").exists()
    assert not (recovery_root / "run").exists()


def test_registered_transaction_orphans_are_compacted_before_each_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    class SimulatedProcessCrash(BaseException):
        pass

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)

    def crash_after_registry_prepare(event: str) -> None:
        if event == "transaction.registered":
            raise SimulatedProcessCrash(event)

    monkeypatch.setattr(lifecycle, "_crash_point", crash_after_registry_prepare)
    for _ in range(5):
        with pytest.raises(SimulatedProcessCrash, match="transaction.registered"):
            lifecycle.approve_external_asset(candidate, asset_catalog)
        registry = json.loads(
            (
                tmp_path
                / ".asset-review-recovery"
                / "transactions.registry"
            ).read_text()
        )
        assert len(registry["transactions"]) == 1


def test_large_audit_fails_before_transaction_or_asset_mutation(
    tmp_path: Path,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    candidate = pending_asset(tmp_path)
    candidate = replace(candidate, author="a" * (800 * 1024))
    candidate.metadata_path.write_text(json.dumps(candidate.audit_record()))
    asset_catalog = catalog(tmp_path)
    original_audit = candidate.metadata_path.read_bytes()
    original_manifest = asset_catalog.manifest_path.read_bytes()

    with pytest.raises(lifecycle.AssetLifecycleError, match="too large"):
        lifecycle.review_pending_asset_batch(
            asset_catalog,
            [_batch_item(candidate)],
            {candidate.pending_id: _batch_decision(candidate)},
            rejection_reason="not selected",
        )

    assert candidate.metadata_path.read_bytes() == original_audit
    assert candidate.path.is_file()
    assert asset_catalog.manifest_path.read_bytes() == original_manifest
    assert not (tmp_path / ".asset-review-recovery").exists()
    assert not (tmp_path / "active").exists()


def test_aggregate_snapshots_fail_before_registry_prepare(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    monkeypatch.setattr(lifecycle, "MAX_RECOVERY_FILE_BYTES", 20 * 1024 * 1024)
    monkeypatch.setattr(lifecycle, "MAX_RECOVERY_TOTAL_SNAPSHOT_BYTES", 8_000)
    candidates = [
        pending_asset(tmp_path, asset_id=f"p{index}", candidate_rank=index)
        for index in range(1, 4)
    ]
    asset_catalog = catalog(tmp_path)

    with pytest.raises(lifecycle.AssetLifecycleError, match="snapshots are too large"):
        lifecycle.review_pending_asset_batch(
            asset_catalog,
            [_batch_item(candidate) for candidate in candidates],
            {
                candidate.pending_id: _batch_decision(candidate)
                for candidate in candidates
            },
            rejection_reason="not selected",
        )

    assert all(candidate.path.is_file() for candidate in candidates)
    assert not (tmp_path / ".asset-review-recovery").exists()
    assert not (tmp_path / "active").exists()


def test_serialized_journal_quota_is_checked_before_registry_prepare(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    monkeypatch.setattr(lifecycle, "MAX_RECOVERY_FILE_BYTES", 2_000)
    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)

    with pytest.raises(lifecycle.AssetLifecycleError, match="journal is too large"):
        lifecycle.review_pending_asset_batch(
            asset_catalog,
            [_batch_item(candidate)],
            {candidate.pending_id: _batch_decision(candidate)},
            rejection_reason="not selected",
        )

    assert candidate.path.is_file()
    assert not (tmp_path / ".asset-review-recovery").exists()
    assert not (tmp_path / "active").exists()


def _age_recovery_transaction(
    lifecycle,
    tmp_path: Path,
    *,
    created_at: str,
) -> Path:
    journal_path = next(
        path
        for path in (tmp_path / ".asset-review-recovery").rglob("*.json")
        if path.name != "transactions.registry"
    )
    journal = lifecycle.AssetReviewRecoveryJournal.model_validate(
        json.loads(journal_path.read_text()),
        strict=True,
    )
    journal.created_at = created_at
    journal.plan_sha256 = lifecycle._journal_plan_sha256(journal)
    journal_path.write_text(json.dumps(journal.model_dump(mode="json")))
    registry_path = tmp_path / ".asset-review-recovery" / "transactions.registry"
    registry = json.loads(registry_path.read_text())
    entry = registry["transactions"][journal.transaction_id]
    entry["created_at"] = created_at
    entry["plan_sha256"] = journal.plan_sha256
    registry_path.write_text(json.dumps(registry))
    return journal_path


def test_old_committed_transaction_journal_is_cleaned_without_freshness_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    class SimulatedProcessCrash(BaseException):
        pass

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)

    def crash_after_commit(event: str) -> None:
        if event == "transaction.committed":
            raise SimulatedProcessCrash(event)

    monkeypatch.setattr(lifecycle, "_crash_point", crash_after_commit)
    with pytest.raises(SimulatedProcessCrash):
        lifecycle.approve_external_asset(candidate, asset_catalog)
    journal_path = _age_recovery_transaction(
        lifecycle,
        tmp_path,
        created_at="2000-01-01T00:00:00+00:00",
    )

    monkeypatch.setattr(lifecycle, "_crash_point", lambda _event: None)
    with pytest.raises(lifecycle.AssetLifecycleError, match="only pending"):
        lifecycle.approve_external_asset(candidate, asset_catalog)

    assert not journal_path.exists()
    assert json.loads(candidate.metadata_path.read_text())["review_status"] == "approved"


def test_old_prepared_transaction_remains_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    class SimulatedProcessCrash(BaseException):
        pass

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)

    def crash_after_prepare(event: str) -> None:
        if event == "transaction.prepared":
            raise SimulatedProcessCrash(event)

    monkeypatch.setattr(lifecycle, "_crash_point", crash_after_prepare)
    with pytest.raises(SimulatedProcessCrash):
        lifecycle.approve_external_asset(candidate, asset_catalog)
    _age_recovery_transaction(
        lifecycle,
        tmp_path,
        created_at="2000-01-01T00:00:00+00:00",
    )

    monkeypatch.setattr(lifecycle, "_crash_point", lambda _event: None)
    with pytest.raises(lifecycle.AssetLifecycleError, match="stale"):
        lifecycle.approve_external_asset(candidate, asset_catalog)

    assert candidate.path.is_file()
    assert json.loads(candidate.metadata_path.read_text())["review_status"] == "pending"


def test_terminal_registry_entries_compact_before_small_registry_quota(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    monkeypatch.setattr(lifecycle, "MAX_TRANSACTION_REGISTRY_BYTES", 900)
    asset_catalog = catalog(tmp_path)

    for index in range(1, 11):
        candidate = pending_asset(
            tmp_path,
            asset_id=f"compact-{index}",
            candidate_rank=min(index, 3),
        )
        lifecycle.approve_external_asset(candidate, asset_catalog)

    registry = json.loads(
        (tmp_path / ".asset-review-recovery" / "transactions.registry").read_text()
    )
    assert len(registry["transactions"]) == 1


def test_move_refuses_destination_created_after_wal_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    destination = tmp_path / "active" / "stock" / "serum-p1.webp"

    def create_destination_at_intent(event: str) -> None:
        if event == f"{candidate.pending_id}.move.intent":
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"concurrent destination")

    monkeypatch.setattr(lifecycle, "_crash_point", create_destination_at_intent)

    with pytest.raises(lifecycle.AssetLifecycleError, match="destination"):
        lifecycle.approve_external_asset(candidate, asset_catalog)

    assert destination.read_bytes() == b"concurrent destination"
    assert candidate.path.is_file()
    assert json.loads((tmp_path / "manifest.json").read_text())["assets"] == []


def test_move_refuses_source_inode_swapped_after_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    original = tmp_path / "original-source.webp"

    def swap_source_before_move(event: str) -> None:
        if event == f"{candidate.pending_id}.audit.done":
            candidate.path.rename(original)
            candidate.path.write_bytes(b"swapped source")

    monkeypatch.setattr(lifecycle, "_crash_point", swap_source_before_move)

    with pytest.raises(lifecycle.AssetLifecycleError, match="source"):
        lifecycle.approve_external_asset(candidate, asset_catalog)

    assert candidate.path.read_bytes() == b"swapped source"
    assert original.is_file()
    assert not (tmp_path / "active" / "stock" / "serum-p1.webp").exists()


def test_move_cleans_new_destination_if_source_is_swapped_after_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    destination = tmp_path / "active" / "stock" / "serum-p1.webp"
    original_source = tmp_path / "original-source-after-link.webp"
    original_link = lifecycle.os.link

    def link_then_swap_source(*args, **kwargs) -> None:
        original_link(*args, **kwargs)
        candidate.path.rename(original_source)
        candidate.path.write_bytes(b"swapped after link")

    monkeypatch.setattr(lifecycle.os, "link", link_then_swap_source)

    with pytest.raises(lifecycle.AssetLifecycleError, match="source identity"):
        lifecycle.approve_external_asset(candidate, asset_catalog)

    assert candidate.path.read_bytes() == b"swapped after link"
    assert original_source.is_file()
    assert not destination.exists()
    assert json.loads((tmp_path / "manifest.json").read_text())["assets"] == []


def test_move_never_clobbers_preexisting_hardlink_destination(
    tmp_path: Path,
) -> None:
    import os
    import src.asset_resolver.lifecycle as lifecycle

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    destination = tmp_path / "active" / "stock" / "serum-p1.webp"
    destination.parent.mkdir(parents=True)
    os.link(candidate.path, destination)
    source_identity = candidate.path.stat()

    with lifecycle._batch_lifecycle_lock(asset_catalog):
        with pytest.raises(
            lifecycle.AssetLifecycleError,
            match="source identity|destination",
        ):
            lifecycle._durable_replace(
                candidate.path,
                destination,
                expected_source_identity=(
                    source_identity.st_dev,
                    source_identity.st_ino,
                ),
                expected_source_sha256=candidate.sha256,
            )

    assert candidate.path.samefile(destination)
    assert candidate.path.read_bytes() == destination.read_bytes()


def test_root_replacement_after_checkpoint_never_writes_replacement_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle
    from src.asset_resolver.catalog import CatalogError, catalog_review_lock

    root = tmp_path / "catalog"
    root.mkdir()
    asset_catalog = catalog(root)
    old_root = tmp_path / "catalog-detached"
    replacement_manifest = b'{"catalog_id":"replacement","assets":[]}\n'
    original_verify = lifecycle._verify_catalog_lock
    replaced = False

    def replace_root_after_successful_checkpoint() -> None:
        nonlocal replaced
        original_verify()
        if not replaced:
            replaced = True
            root.rename(old_root)
            root.mkdir()
            (root / "manifest.json").write_bytes(replacement_manifest)

    with pytest.raises(CatalogError, match="review lock"):
        with catalog_review_lock(root):
            monkeypatch.setattr(
                lifecycle,
                "_verify_catalog_lock",
                replace_root_after_successful_checkpoint,
            )
            lifecycle._atomic_write_bytes(
                asset_catalog.manifest_path,
                b'{"catalog_id":"test-catalog","assets":[],"old":true}\n',
            )

    assert (root / "manifest.json").read_bytes() == replacement_manifest


def test_expected_absent_atomic_write_never_clobbers_last_moment_creator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle
    from src.asset_resolver.catalog import catalog_review_lock

    asset_catalog = catalog(tmp_path)
    destination = tmp_path / "new-record.json"
    original_link = lifecycle.os.link
    injected = False

    def create_destination_before_link(*args, **kwargs):
        nonlocal injected
        if not injected:
            injected = True
            destination.write_bytes(b"concurrent creator")
        return original_link(*args, **kwargs)

    monkeypatch.setattr(lifecycle.os, "link", create_destination_before_link)

    with catalog_review_lock(asset_catalog.root):
        with pytest.raises(
            lifecycle.AssetLifecycleError,
            match="destination is no longer absent",
        ):
            lifecycle._atomic_write_bytes(
                destination,
                b"writer payload",
                expected_absent=True,
            )

    assert destination.read_bytes() == b"concurrent creator"


def test_public_retry_recovers_crash_between_move_link_and_source_unlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    class SimulatedProcessCrash(BaseException):
        pass

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    destination = tmp_path / "active" / "stock" / "serum-p1.webp"
    target_event = f"{candidate.pending_id}.move.linked"

    def crash_after_link(event: str) -> None:
        if event == target_event:
            raise SimulatedProcessCrash(event)

    monkeypatch.setattr(lifecycle, "_crash_point", crash_after_link)
    with pytest.raises(SimulatedProcessCrash, match="move.linked"):
        lifecycle.approve_external_asset(candidate, asset_catalog)

    assert candidate.path.samefile(destination)
    monkeypatch.setattr(lifecycle, "_crash_point", lambda _event: None)
    lifecycle.approve_external_asset(candidate, asset_catalog)

    assert not candidate.path.exists()
    assert destination.is_file()
    assert json.loads(candidate.metadata_path.read_text())["review_status"] == "approved"
    assert list((tmp_path / ".asset-review-recovery").rglob("*.json")) == []


def test_mid_move_recovery_rejects_unbound_third_hardlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os
    import src.asset_resolver.lifecycle as lifecycle

    class SimulatedProcessCrash(BaseException):
        pass

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    target_event = f"{candidate.pending_id}.move.linked"
    monkeypatch.setattr(
        lifecycle,
        "_crash_point",
        lambda event: (_ for _ in ()).throw(SimulatedProcessCrash(event))
        if event == target_event
        else None,
    )
    with pytest.raises(SimulatedProcessCrash):
        lifecycle.approve_external_asset(candidate, asset_catalog)
    os.link(candidate.path, tmp_path / "unbound-third-link.webp")

    monkeypatch.setattr(lifecycle, "_crash_point", lambda _event: None)
    with pytest.raises(lifecycle.AssetLifecycleError, match="mid-move"):
        lifecycle.approve_external_asset(candidate, asset_catalog)


def test_mid_move_rollback_rechecks_link_count_before_unlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os
    import src.asset_resolver.lifecycle as lifecycle

    class SimulatedProcessCrash(BaseException):
        pass

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    destination = tmp_path / "active" / "stock" / "serum-p1.webp"
    target_event = f"{candidate.pending_id}.move.linked"
    monkeypatch.setattr(
        lifecycle,
        "_crash_point",
        lambda event: (_ for _ in ()).throw(SimulatedProcessCrash(event))
        if event == target_event
        else None,
    )
    with pytest.raises(SimulatedProcessCrash):
        lifecycle.approve_external_asset(candidate, asset_catalog)

    original_unlink = lifecycle._durable_unlink
    third_link = tmp_path / "concurrent-third-link.webp"
    injected = False

    def add_link_before_unlink(path: Path, **kwargs) -> None:
        nonlocal injected
        if path == destination and not injected:
            injected = True
            os.link(candidate.path, third_link)
        original_unlink(path, **kwargs)

    monkeypatch.setattr(lifecycle, "_crash_point", lambda _event: None)
    monkeypatch.setattr(lifecycle, "_durable_unlink", add_link_before_unlink)
    with pytest.raises(lifecycle.AssetLifecycleError, match="durable unlink target is unsafe"):
        lifecycle.approve_external_asset(candidate, asset_catalog)

    assert candidate.path.exists()
    assert destination.exists()
    assert third_link.exists()


def test_mid_move_rollback_rechecks_link_count_after_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os
    import src.asset_resolver.lifecycle as lifecycle

    class SimulatedProcessCrash(BaseException):
        pass

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    destination = tmp_path / "active" / "stock" / "serum-p1.webp"
    target_event = f"{candidate.pending_id}.move.linked"
    monkeypatch.setattr(
        lifecycle,
        "_crash_point",
        lambda event: (_ for _ in ()).throw(SimulatedProcessCrash(event))
        if event == target_event
        else None,
    )
    with pytest.raises(SimulatedProcessCrash):
        lifecycle.approve_external_asset(candidate, asset_catalog)

    original_descriptor_sha256 = lifecycle._descriptor_sha256
    third_link = tmp_path / "late-third-link.webp"
    asset_metadata = candidate.path.stat()
    asset_identity = (asset_metadata.st_dev, asset_metadata.st_ino)
    injected = False

    def add_link_after_initial_nlink_snapshot(descriptor: int) -> str:
        nonlocal injected
        digest = original_descriptor_sha256(descriptor)
        opened = os.fstat(descriptor)
        if not injected and (opened.st_dev, opened.st_ino) == asset_identity:
            injected = True
            os.link(candidate.path, third_link)
        return digest

    monkeypatch.setattr(lifecycle, "_crash_point", lambda _event: None)
    monkeypatch.setattr(
        lifecycle,
        "_descriptor_sha256",
        add_link_after_initial_nlink_snapshot,
    )
    with pytest.raises(lifecycle.AssetLifecycleError, match="durable unlink target is unsafe"):
        lifecycle.approve_external_asset(candidate, asset_catalog)

    assert candidate.path.exists()
    assert destination.exists()
    assert third_link.exists()


def test_source_parent_fsync_failure_never_deletes_last_asset_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    destination = tmp_path / "active" / "stock" / "serum-p1.webp"
    source_parent = candidate.path.parent.stat()
    original_fsync = lifecycle.os.fsync
    failed = False

    def fail_source_parent_after_unlink(descriptor: int) -> None:
        nonlocal failed
        opened = lifecycle.os.fstat(descriptor)
        if (
            not failed
            and (opened.st_dev, opened.st_ino)
            == (source_parent.st_dev, source_parent.st_ino)
            and not candidate.path.exists()
            and destination.exists()
        ):
            failed = True
            raise OSError("source parent fsync failed")
        original_fsync(descriptor)

    monkeypatch.setattr(lifecycle.os, "fsync", fail_source_parent_after_unlink)
    with pytest.raises(
        lifecycle.AssetLifecycleError,
        match="parent fsync failed|trusted parent",
    ):
        lifecycle.approve_external_asset(candidate, asset_catalog)

    assert candidate.path.exists() or destination.exists()
    remaining = candidate.path if candidate.path.exists() else destination
    assert hashlib.sha256(remaining.read_bytes()).hexdigest() == candidate.sha256

    monkeypatch.setattr(lifecycle.os, "fsync", original_fsync)
    lifecycle.approve_external_asset(candidate, asset_catalog)
    assert destination.is_file() and not candidate.path.exists()


def test_prepared_transaction_missing_journal_blocks_later_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    class SimulatedProcessCrash(BaseException):
        pass

    first = pending_asset(tmp_path, asset_id="a")
    asset_catalog = catalog(tmp_path)
    monkeypatch.setattr(
        lifecycle,
        "_crash_point",
        lambda event: (_ for _ in ()).throw(SimulatedProcessCrash(event))
        if event == "manifest.applied"
        else None,
    )
    with pytest.raises(SimulatedProcessCrash):
        lifecycle.approve_external_asset(first, asset_catalog)
    journal_path = next((tmp_path / ".asset-review-recovery").rglob("*.json"))
    journal_path.unlink()

    monkeypatch.setattr(lifecycle, "_crash_point", lambda _event: None)
    second = pending_asset(tmp_path, asset_id="b")
    with pytest.raises(lifecycle.AssetLifecycleError, match="missing.*journal|needs recovery"):
        lifecycle.approve_external_asset(second, asset_catalog)

    registry = json.loads(
        (tmp_path / ".asset-review-recovery" / "transactions.registry").read_text()
    )
    assert any(entry["state"] == "prepared" for entry in registry["transactions"].values())
    assert second.path.is_file()


def test_corrupt_prepared_journal_remains_blocking_after_quarantine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    class SimulatedProcessCrash(BaseException):
        pass

    first = pending_asset(tmp_path, asset_id="a")
    asset_catalog = catalog(tmp_path)
    monkeypatch.setattr(
        lifecycle,
        "_crash_point",
        lambda event: (_ for _ in ()).throw(SimulatedProcessCrash(event))
        if event == "manifest.applied"
        else None,
    )
    with pytest.raises(SimulatedProcessCrash):
        lifecycle.approve_external_asset(first, asset_catalog)
    journal_path = next((tmp_path / ".asset-review-recovery").rglob("*.json"))
    journal_path.write_text("{}")
    second = pending_asset(tmp_path, asset_id="b")

    monkeypatch.setattr(lifecycle, "_crash_point", lambda _event: None)
    with pytest.raises(lifecycle.AssetLifecycleError, match="journal"):
        lifecycle.approve_external_asset(second, asset_catalog)
    with pytest.raises(lifecycle.AssetLifecycleError, match="missing.*journal|needs recovery"):
        lifecycle.approve_external_asset(second, asset_catalog)
    assert second.path.is_file()


def test_registered_journal_is_promoted_and_recovered_on_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    class SimulatedProcessCrash(BaseException):
        pass

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    monkeypatch.setattr(
        lifecycle,
        "_crash_point",
        lambda event: (_ for _ in ()).throw(SimulatedProcessCrash(event))
        if event == "transaction.journaled"
        else None,
    )
    with pytest.raises(SimulatedProcessCrash, match="transaction.journaled"):
        lifecycle.approve_external_asset(candidate, asset_catalog)

    registry = json.loads(
        (tmp_path / ".asset-review-recovery" / "transactions.registry").read_text()
    )
    assert {entry["state"] for entry in registry["transactions"].values()} == {
        "registered"
    }

    monkeypatch.setattr(lifecycle, "_crash_point", lambda _event: None)
    lifecycle.approve_external_asset(candidate, asset_catalog)
    assert (tmp_path / "active" / "stock" / "serum-p1.webp").is_file()


@pytest.mark.parametrize("first_uses_anchor", [False, True])
def test_global_recovery_uses_registry_manifest_not_current_api_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first_uses_anchor: bool,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    class SimulatedProcessCrash(BaseException):
        pass

    persistent = catalog(tmp_path)
    transient = replace(persistent, manifest_path=None)
    first = pending_asset(tmp_path, asset_id="a")
    monkeypatch.setattr(
        lifecycle,
        "_crash_point",
        lambda event: (_ for _ in ()).throw(SimulatedProcessCrash(event))
        if event == f"{first.pending_id}.audit.applied"
        else None,
    )
    with pytest.raises(SimulatedProcessCrash):
        if first_uses_anchor:
            lifecycle.reject_external_asset(
                first,
                reason="not selected",
                catalog=transient,
            )
        else:
            lifecycle.approve_external_asset(first, persistent)

    monkeypatch.setattr(lifecycle, "_crash_point", lambda _event: None)
    second = pending_asset(tmp_path, asset_id="b")
    if first_uses_anchor:
        lifecycle.approve_external_asset(second, persistent)
    else:
        lifecycle.reject_external_asset(
            second,
            reason="not selected",
            catalog=transient,
        )

    assert first.path.is_file()
    assert json.loads(first.metadata_path.read_text())["review_status"] == "pending"


@pytest.mark.parametrize("attack", ["symlink", "mode"])
def test_global_recovery_validates_hashed_run_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle

    class SimulatedProcessCrash(BaseException):
        pass

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    monkeypatch.setattr(
        lifecycle,
        "_crash_point",
        lambda event: (_ for _ in ()).throw(SimulatedProcessCrash(event))
        if event == "transaction.prepared"
        else None,
    )
    with pytest.raises(SimulatedProcessCrash):
        lifecycle.approve_external_asset(candidate, asset_catalog)

    recovery_root = tmp_path / ".asset-review-recovery"
    run_root = next(path for path in recovery_root.iterdir() if path.is_dir())
    if attack == "symlink":
        detached = tmp_path / "detached-run-root"
        run_root.rename(detached)
        run_root.symlink_to(detached, target_is_directory=True)
    else:
        run_root.chmod(0o755)

    monkeypatch.setattr(lifecycle, "_crash_point", lambda _event: None)
    with pytest.raises(lifecycle.AssetLifecycleError, match="run recovery journal directory"):
        lifecycle.approve_external_asset(candidate, asset_catalog)


def test_lock_replacement_stops_before_next_durable_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.asset_resolver.lifecycle as lifecycle
    from src.asset_resolver.catalog import CatalogError

    candidate = pending_asset(tmp_path)
    asset_catalog = catalog(tmp_path)
    lock_path = tmp_path / ".asset-review.lock"

    def replace_lock_after_audit(event: str) -> None:
        if event == f"{candidate.pending_id}.audit.done":
            lock_path.rename(tmp_path / ".asset-review.lock.detached")
            lock_path.write_bytes(b"replacement")
            lock_path.chmod(0o600)

    monkeypatch.setattr(lifecycle, "_crash_point", replace_lock_after_audit)

    with pytest.raises(CatalogError, match="review lock"):
        lifecycle.approve_external_asset(candidate, asset_catalog)

    assert candidate.path.is_file()
    assert json.loads((tmp_path / "manifest.json").read_text())["assets"] == []
    assert not (tmp_path / "active" / "stock" / "serum-p1.webp").exists()
