from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.visual_design.style_registry import load_style_registry


EXPECTED_FAMILIES = {
    "pink_red",
    "deep_teal",
    "soft_pink",
    "coral_impact",
    "green_catalog",
    "white_quote",
}


def test_registry_has_exactly_six_families() -> None:
    assert set(load_style_registry()) == EXPECTED_FAMILIES


def test_registry_references_existing_images_and_contains_no_layout_markup() -> None:
    for profile in load_style_registry().values():
        assert all(Path(path).is_file() for path in profile.reference_image_paths)
        payload = profile.model_dump_json()
        assert "<html" not in payload.lower()
        assert "display:" not in payload.lower()
        assert "grid-template" not in payload.lower()


def test_registry_rejects_reference_path_traversal(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    payload = json.loads(
        Path("assets/visual-families/manifest.json").read_text(encoding="utf-8")
    )
    payload["families"][0]["reference_image_paths"] = ["../outside.png"]
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="reference image path"):
        load_style_registry(manifest)
