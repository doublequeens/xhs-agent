from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def _entry(path: str, *, usage: str = "production") -> dict[str, object]:
    return {
        "asset_id": "face_front",
        "role": "face_angle",
        "path": path,
        "ownership": "project_original",
        "license": "project_internal",
        "dimensions": {"width": 1080, "height": 1440},
        "sha256": "",
        "allowed_layouts": ["front_face_zone"],
        "tags": ["face", "zone"],
        "disabled_contexts": [],
        "fallback_roles": ["face_zone_mask"],
        "usage": usage,
    }


def _write_manifest(tmp_path: Path, entry: dict[str, object]) -> Path:
    asset = tmp_path / str(entry["path"])
    asset.parent.mkdir(parents=True)
    asset.write_text(
        '<svg width="1080" height="1440" xmlns="http://www.w3.org/2000/svg"/>',
        encoding="utf-8",
    )
    entry["sha256"] = hashlib.sha256(asset.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"catalog_id": "test-catalog", "assets": [entry]}),
        encoding="utf-8",
    )
    return manifest


def test_load_catalog_returns_repo_local_production_entries(tmp_path: Path) -> None:
    from src.asset_resolver.catalog import load_catalog

    manifest = _write_manifest(tmp_path, _entry("active/faces/front.svg"))

    catalog = load_catalog(manifest)

    assert catalog.catalog_id == "test-catalog"
    assert catalog.entries[0].asset_id == "face_front"
    assert catalog.entries[0].path == tmp_path / "active/faces/front.svg"
    assert catalog.entries[0].usage == "production"


def test_load_catalog_rejects_reference_only_entry(tmp_path: Path) -> None:
    from src.asset_resolver.catalog import CatalogError, load_catalog

    manifest = _write_manifest(
        tmp_path, _entry("active/faces/front.svg", usage="reference_only")
    )

    with pytest.raises(CatalogError, match="production"):
        load_catalog(manifest)


def test_load_catalog_rejects_incomplete_provenance(tmp_path: Path) -> None:
    from src.asset_resolver.catalog import CatalogError, load_catalog

    entry = _entry("active/faces/front.svg")
    entry["license"] = ""
    manifest = _write_manifest(tmp_path, entry)

    with pytest.raises(CatalogError, match="license"):
        load_catalog(manifest)


def test_load_catalog_rejects_paths_outside_active_root(tmp_path: Path) -> None:
    from src.asset_resolver.catalog import CatalogError, load_catalog

    manifest = _write_manifest(tmp_path, _entry("references/front.svg"))

    with pytest.raises(CatalogError, match="active"):
        load_catalog(manifest)
