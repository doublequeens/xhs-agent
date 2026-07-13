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
    tmp_path: Path, *, asset_id: str = "p1", candidate_rank: int = 1
):
    from src.asset_resolver.lifecycle import PendingAsset

    path = tmp_path / "incoming" / "external" / "run-42" / f"pexels-{asset_id}.webp"
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1080, 1440), "ivory").save(
        path, format="WEBP", lossless=True
    )
    metadata_path = path.with_suffix(".json")
    license_snapshot = tmp_path / "licenses" / "pexels-terms-summary-v1.txt"
    license_snapshot.parent.mkdir(parents=True, exist_ok=True)
    license_snapshot.write_text("Pexels terms summary v1", encoding="utf-8")
    pending = PendingAsset(
        pending_id=f"run-42-serum-slot-pexels-{asset_id}",
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
        run_id="run-42",
        production_relative_path=Path(f"stock/serum-{asset_id}.webp"),
        tags=("serum", "ivory"),
        fallback_roles=("serum_texture",),
        unresolved_safety_checks=("has_logo", "has_text"),
    )
    metadata_path.write_text(json.dumps(pending.audit_record()), encoding="utf-8")
    return pending


def catalog(tmp_path: Path) -> AssetCatalog:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"catalog_id": "test-catalog", "assets": []}),
        encoding="utf-8",
    )
    return AssetCatalog(
        catalog_id="test-catalog",
        root=tmp_path,
        entries=(),
        run_id="run-42",
        manifest_path=manifest_path,
    )


def test_approval_preserves_hash_and_promotes_into_active_catalog(tmp_path: Path) -> None:
    from src.asset_resolver.catalog import load_catalog
    from src.asset_resolver.lifecycle import approve_external_asset

    pending = pending_asset(tmp_path)
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

    with pytest.raises(AssetLifecycleError, match="hash changed before approval"):
        approve_external_asset(pending, catalog(tmp_path))

    assert not (tmp_path / "active" / "stock" / "serum-p1.webp").exists()


def test_rejection_remains_auditable_and_never_enters_active(tmp_path: Path) -> None:
    from src.asset_resolver.lifecycle import (
        AssetLifecycleError,
        approve_external_asset,
        reject_external_asset,
    )

    pending = pending_asset(tmp_path)
    reject_external_asset(pending, reason="visible logo")

    audit = json.loads(pending.metadata_path.read_text())
    assert audit["review_status"] == "rejected"
    assert audit["rejection_reason"] == "visible logo"
    assert pending.path.exists()
    assert not (tmp_path / "active").exists()
    with pytest.raises(AssetLifecycleError, match="only pending assets can be approved"):
        approve_external_asset(pending, catalog(tmp_path))
