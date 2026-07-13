from __future__ import annotations

import hashlib
import json
import struct
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import pytest

from src.rendering.editorial.design_system import ASSET_ROOT, load_catalog


EXPECTED_ROLE_COUNTS = {
    "face_angle": 3,
    "face_zone_mask": 10,
    "serum_texture": 4,
    "gel_texture": 4,
    "cream_texture": 4,
    "liquid_texture": 4,
    "pump_shape": 4,
    "dropper_shape": 3,
    "container_shape": 3,
    "hand_detail": 4,
    "skin_detail": 4,
    "background_token": 4,
    "line_token": 4,
    "page_number_token": 4,
}

REQUIRED_ENTRY_FIELDS = {
    "asset_id",
    "role",
    "path",
    "ownership",
    "license",
    "dimensions",
    "sha256",
    "allowed_layouts",
    "tags",
    "disabled_contexts",
    "fallback_roles",
    "usage",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dimensions(path: Path) -> tuple[int, int]:
    if path.suffix.lower() == ".svg":
        root = ET.parse(path).getroot()
        width = int(float(root.attrib["width"]))
        height = int(float(root.attrib["height"]))
        return width, height
    if path.suffix.lower() == ".png":
        data = path.read_bytes()[:24]
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        return struct.unpack(">II", data[16:24])
    raise AssertionError(f"Unsupported seed asset type: {path.suffix}")


def test_seed_catalog_contains_distinct_valid_production_assets() -> None:
    catalog = load_catalog(ASSET_ROOT / "manifest.json")

    assert len(catalog.entries) == 59
    assert Counter(entry.role for entry in catalog.entries) == EXPECTED_ROLE_COUNTS
    assert len({entry.asset_id for entry in catalog.entries}) == len(catalog.entries)
    assert len({entry.path for entry in catalog.entries}) == len(catalog.entries)
    assert len({entry.sha256 for entry in catalog.entries}) == len(catalog.entries)
    assert all(entry.usage == "production" for entry in catalog.entries)

    manifest = json.loads((ASSET_ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["catalog_id"] == "beauty_editorial_v1"
    assert len(manifest["assets"]) == 59

    for raw, entry in zip(manifest["assets"], catalog.entries, strict=True):
        assert REQUIRED_ENTRY_FIELDS <= raw.keys()
        assert entry.file_path.is_file()
        assert entry.file_path.resolve().is_relative_to(ASSET_ROOT.resolve())
        assert entry.file_path.parent.is_relative_to(ASSET_ROOT / "active")
        assert raw["ownership"] == "project_original"
        assert raw["license"] == "project_internal"
        assert raw["allowed_layouts"]
        assert raw["tags"]
        assert raw["fallback_roles"]
        assert raw["usage"] == "production"
        assert raw["sha256"] == _sha256(entry.file_path)
        assert tuple(raw["dimensions"].values()) == _dimensions(entry.file_path)


def test_reference_assets_cannot_enter_production_catalog() -> None:
    catalog = load_catalog(ASSET_ROOT / "manifest.json")
    reference = json.loads(
        (ASSET_ROOT / "references/manifest.json").read_text(encoding="utf-8")
    )

    assert len(reference["assets"]) == 3
    assert {item["usage"] for item in reference["assets"]} == {"reference_only"}
    assert {item["path"] for item in reference["assets"]} == {
        "editorial-cover-anchor.png",
        "face-diagram-anchor.png",
        "save-card-anchor.png",
    }
    assert all(
        item["description"]
        == "style only: never copy title, copy, topic, or page sequence."
        for item in reference["assets"]
    )

    production_paths = {entry.file_path.resolve() for entry in catalog.entries}
    for item in reference["assets"]:
        path = (ASSET_ROOT / "references" / item["path"]).resolve()
        assert path.is_file()
        assert path not in production_paths
        assert item["sha256"] == _sha256(path)
        assert tuple(item["dimensions"].values()) == _dimensions(path)


def test_catalog_loader_rejects_paths_that_escape_manifest_root(tmp_path: Path) -> None:
    manifest = {
        "catalog_id": "escape-attempt",
        "assets": [
            {
                "asset_id": "escape",
                "role": "line_token",
                "path": "../escape.svg",
                "ownership": "project_original",
                "license": "project_internal",
                "dimensions": {"width": 1, "height": 1},
                "sha256": "0" * 64,
                "allowed_layouts": ["editorial_cover"],
                "tags": ["line"],
                "disabled_contexts": [],
                "fallback_roles": ["background_token"],
                "usage": "production",
            }
        ],
    }
    manifest_path = tmp_path / "catalog" / "manifest.json"
    manifest_path.parent.mkdir()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="escapes catalog root"):
        load_catalog(manifest_path)
