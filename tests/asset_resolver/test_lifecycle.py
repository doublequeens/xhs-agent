from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from src.asset_resolver.catalog import AssetCatalog


def pending_asset(tmp_path: Path):
    from src.asset_resolver.lifecycle import PendingAsset

    path = tmp_path / "incoming" / "external" / "run-42" / "pexels-p1.webp"
    path.parent.mkdir(parents=True)
    Image.new("RGB", (1080, 1440), "ivory").save(
        path, format="WEBP", lossless=True
    )
    metadata_path = path.with_suffix(".json")
    metadata_path.write_text(json.dumps({"review_status": "pending"}), encoding="utf-8")
    return PendingAsset(
        pending_id="run-42-serum-slot-pexels-p1",
        path=path,
        metadata_path=metadata_path,
        provider="pexels",
        provider_asset_id="p1",
        author="Ada",
        source_url="https://www.pexels.com/photo/p1/",
        source_file_url="https://images.pexels.com/photos/p1.webp",
        role="serum_texture",
        layout="texture_baseline",
        width=1080,
        height=1440,
        license="Pexels License",
        license_snapshot="https://www.pexels.com/license/",
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        average_hash="0123456789abcdef",
        run_id="run-42",
        production_relative_path=Path("stock/serum-p1.webp"),
        tags=("serum", "ivory"),
        fallback_roles=("serum_texture",),
    )


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
    outside_metadata.write_text(json.dumps({"review_status": "pending"}), encoding="utf-8")
    outside = replace(
        pending,
        path=outside_path,
        metadata_path=outside_metadata,
    )

    with pytest.raises(AssetLifecycleError, match="run-scoped incoming directory"):
        approve_external_asset(outside, catalog(tmp_path))

    assert outside_path.exists()


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
