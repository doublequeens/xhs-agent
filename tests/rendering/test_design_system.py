from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.rendering.editorial.design_system import (
    BEAUTY_EDITORIAL_V1,
    FONT_ROOT,
    REPOSITORY_ROOT,
)


def test_design_system_exposes_immutable_editorial_tokens() -> None:
    assert BEAUTY_EDITORIAL_V1.name == "beauty_editorial_v1"
    assert BEAUTY_EDITORIAL_V1.canvas == (1080, 1440)
    assert dict(BEAUTY_EDITORIAL_V1.colors) == {
        "background": "#F7F2EA",
        "ink": "#292625",
        "mauve": "#9A707B",
        "coral": "#D45D4C",
        "sage": "#78805E",
    }

    with pytest.raises(FrozenInstanceError):
        BEAUTY_EDITORIAL_V1.name = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        BEAUTY_EDITORIAL_V1.colors["ink"] = "#000000"  # type: ignore[index]


def test_design_system_fonts_are_repo_local_and_licensed() -> None:
    assert dict(BEAUTY_EDITORIAL_V1.font_paths) == {
        "display": FONT_ROOT / "SourceHanSerifSC-SemiBold.otf",
        "body_regular": FONT_ROOT / "SourceHanSansSC-Regular.otf",
        "body_medium": FONT_ROOT / "SourceHanSansSC-Medium.otf",
        "numeral": FONT_ROOT / "BodoniModa-Regular.ttf",
    }

    for font_path in BEAUTY_EDITORIAL_V1.font_paths.values():
        assert font_path.is_file()
        assert font_path.resolve().is_relative_to(REPOSITORY_ROOT)
        assert font_path.stat().st_size > 50_000

    assert (FONT_ROOT / "SourceHanSerifSC-SemiBold.otf").read_bytes()[:4] == b"OTTO"
    assert (FONT_ROOT / "SourceHanSansSC-Regular.otf").read_bytes()[:4] == b"OTTO"
    assert (FONT_ROOT / "SourceHanSansSC-Medium.otf").read_bytes()[:4] == b"OTTO"
    assert (FONT_ROOT / "BodoniModa-Regular.ttf").read_bytes()[:4] in {
        b"\x00\x01\x00\x00",
        b"true",
    }

    source_han_license = (FONT_ROOT / "LICENSE-source-han.txt").read_text(
        encoding="utf-8"
    )
    bodoni_license = (FONT_ROOT / "OFL-bodoni-moda.txt").read_text(
        encoding="utf-8"
    )
    assert "SIL OPEN FONT LICENSE Version 1.1" in source_han_license
    assert "SIL OPEN FONT LICENSE Version 1.1" in bodoni_license
