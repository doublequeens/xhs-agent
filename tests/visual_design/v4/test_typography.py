from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.visual_design.v4.typography import (
    CANONICAL_FONT_FILES_V4,
    resolve_font_file_v4,
    measure_text_v4,
)


def test_measurement_preserves_unicode_and_grapheme_boundaries() -> None:
    text = "中文 ABC 👩‍🔬\n第二行"

    first = measure_text_v4(
        text,
        family="pink_red",
        role="body",
        font_size_px=32,
        max_width_px=180,
        line_height=1.25,
    )
    second = measure_text_v4(
        text,
        family="pink_red",
        role="body",
        font_size_px=32,
        max_width_px=180,
        line_height=1.25,
    )

    assert first.text == text
    assert first.lines == second.lines
    assert first.width_px == second.width_px
    assert first.height_px == second.height_px
    assert any("👩‍🔬" in line for line in first.lines)
    assert all("👩" not in line.replace("👩‍🔬", "") for line in first.lines)
    assert first.explicit_newline_count == 1


def test_font_resolution_is_checked_in_and_hash_bound() -> None:
    resolved = resolve_font_file_v4("pink_red", "body")
    assert resolved.path.is_relative_to(Path("assets/fonts").resolve())
    assert resolved.path == CANONICAL_FONT_FILES_V4["HarmonyOS Sans"]
    assert len(resolved.sha256) == 64
    assert resolved.sha256 == hashlib.sha256(resolved.path.read_bytes()).hexdigest()


def test_unknown_font_role_fails_closed_without_host_fallback() -> None:
    with pytest.raises(ValueError, match="font role|font file"):
        resolve_font_file_v4("pink_red", "unknown")


def test_unbreakable_grapheme_cluster_wider_than_box_fails() -> None:
    with pytest.raises(ValueError, match="cluster|width"):
        measure_text_v4(
            "👩‍🔬",
            family="pink_red",
            role="body",
            font_size_px=64,
            max_width_px=1,
            line_height=1.2,
        )


@pytest.mark.parametrize(
    ("font_size_px", "max_width_px", "line_height"),
    ((0, 100, 1.2), (32, 0, 1.2), (32, 100, 0)),
)
def test_measurement_rejects_non_positive_geometry(
    font_size_px: float, max_width_px: float, line_height: float
) -> None:
    with pytest.raises(ValueError):
        measure_text_v4(
            "text",
            family="pink_red",
            role="body",
            font_size_px=font_size_px,
            max_width_px=max_width_px,
            line_height=line_height,
        )
