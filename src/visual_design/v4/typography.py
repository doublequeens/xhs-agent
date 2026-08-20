"""Deterministic, project-font-only typography measurement for v4.

The v4 layout compiler measures text before it creates scene primitives.  This
module is deliberately independent from Chromium and from the host font
installation: every family role resolves to one checked-in font byte stream,
and Pillow/FreeType performs the measurement locally.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

import regex
from PIL import ImageFont

from src.visual_design.v4.tokens import get_family_tokens


REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
FONT_ROOT: Final[Path] = REPOSITORY_ROOT / "assets" / "fonts"

# These are the only font-family labels emitted by the approved v4 style
# registry.  Mapping the labels to repository-relative files makes the source
# of every measurement auditable and prevents an implicit system fallback.
_FONT_FILES: dict[str, Path] = {
    "Alibaba PuHuiTi Heavy": FONT_ROOT / "templates" / "Alibaba-PuHuiTi-Heavy.ttf",
    "HarmonyOS Sans Black": FONT_ROOT / "templates" / "HarmonyOS_Sans_SC_Black.ttf",
    "HarmonyOS Sans Bold": FONT_ROOT / "templates" / "HarmonyOS_Sans_SC_Bold.ttf",
    "HarmonyOS Sans": FONT_ROOT / "templates" / "HarmonyOS_Sans_SC_Regular.ttf",
    "LXGW WenKai": FONT_ROOT / "beauty-editorial-v1" / "LXGWWenKai-Regular.ttf",
}
CANONICAL_FONT_FILES_V4: Mapping[str, Path] = MappingProxyType(_FONT_FILES)
CANONICAL_FONT_SHA256_V4: Mapping[str, str] = MappingProxyType(
    {
        "Alibaba PuHuiTi Heavy": "de5f839cadcfe463c522b6fff2847f3c457a20b41b855a5fb0b527a189a1902a",
        "HarmonyOS Sans Black": "5de9560908e88820df2e0a5ed9465bc44644ae2ce1cd6c194b76f2ed8e8f186e",
        "HarmonyOS Sans Bold": "43a424b85e47fb53a17b3b32026a71801f86f8e022ca6798d186b47d39fa5f01",
        "HarmonyOS Sans": "297b088424be212207df2ce8b98e335468b782aa6b96832af0b8b773d711e2b1",
        "LXGW WenKai": "39ad71264b588165b469e35e6afb162a378dacd1f95348160240ba9038ac3009",
    }
)


@dataclass(frozen=True)
class ResolvedFontV4:
    """One checked-in font and the digest of its exact bytes."""

    family_name: str
    role: str
    path: Path
    sha256: str


@dataclass(frozen=True)
class TextMeasurementV4:
    """Stable geometry for one exact visible string.

    ``text`` always contains the original string.  ``lines`` contains the
    grapheme-safe geometry lines and may contain compiler-inserted line breaks;
    the compiler never writes those lines back into a content contract.
    """

    text: str
    lines: tuple[str, ...]
    line_widths_px: tuple[float, ...]
    width_px: float
    height_px: float
    line_count: int
    explicit_newline_count: int
    font_size_px: float
    line_height: float
    max_width_px: float
    font_sha256: str

    @property
    def wrapped_text(self) -> str:
        """Return compiler line breaks without changing ``text`` itself."""

        return "\n".join(self.lines)

    @property
    def font_byte_sha256(self) -> str:
        return self.font_sha256


def _finite_positive(value: object, field_name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite positive number")
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite positive number") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field_name} must be a finite positive number")
    return number


def _font_bytes(path: Path) -> bytes:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(FONT_ROOT.resolve(strict=True))
        if not resolved.is_file():
            raise ValueError("checked-in font path is not a regular file")
        data = resolved.read_bytes()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("checked-in v4 font file is missing or unreadable") from exc
    if not data:
        raise ValueError("checked-in v4 font file is empty")
    return data


def resolve_font_file_v4(family: str, role: str) -> ResolvedFontV4:
    """Resolve a canonical family role to a checked-in font byte hash.

    There is intentionally no fallback branch.  Unknown families, unknown
    roles, unrecognized registry font labels and missing files all fail before
    any measurement happens.
    """

    if not isinstance(family, str) or not family.strip():
        raise ValueError("font family must be a canonical v4 family ID")
    if not isinstance(role, str) or role not in {"display", "heading", "body", "caption"}:
        raise ValueError(f"unknown v4 font role: {role!r}")
    try:
        tokens = get_family_tokens(family)
    except Exception as exc:
        raise ValueError(f"unknown v4 font family: {family!r}") from exc
    family_name = getattr(tokens.font_roles, role, None)
    path = _FONT_FILES.get(family_name)
    if not isinstance(family_name, str) or path is None:
        raise ValueError(f"font file is not registered for role {role!r}")
    data = _font_bytes(path)
    digest = hashlib.sha256(data).hexdigest()
    expected_digest = CANONICAL_FONT_SHA256_V4.get(family_name)
    if expected_digest is None or digest != expected_digest:
        raise ValueError("checked-in v4 font bytes do not match the canonical font revision")
    return ResolvedFontV4(
        family_name=family_name,
        role=role,
        path=path,
        sha256=digest,
    )


def resolve_font_path_v4(family: str, role: str) -> Path:
    """Return a checked-in path after running the full font safety checks."""

    return resolve_font_file_v4(family, role).path


def _load_font(resolved: ResolvedFontV4, size_px: float):
    try:
        return ImageFont.truetype(str(resolved.path), size=max(1, round(size_px)))
    except (OSError, ValueError) as exc:
        raise ValueError("checked-in v4 font cannot be loaded by Pillow/FreeType") from exc


def _text_width(font: ImageFont.FreeTypeFont, text: str) -> float:
    try:
        width = float(font.getlength(text))
    except (AttributeError, OSError, ValueError) as exc:
        raise ValueError("Pillow/FreeType failed to measure text") from exc
    if not math.isfinite(width) or width < 0:
        raise ValueError("Pillow/FreeType returned invalid text geometry")
    return width


def _explicit_lines(text: str) -> tuple[tuple[str, ...], int]:
    # Keep CRLF as one delimiter for geometry while preserving ``text`` in the
    # returned measurement object.  A trailing delimiter deliberately creates
    # a final empty line, matching ordinary text layout semantics.
    parts = tuple(regex.split(r"\r\n|\n|\r", text))
    return parts, max(0, len(parts) - 1)


def _wrap_graphemes(
    text: str,
    *,
    font: ImageFont.FreeTypeFont,
    max_width_px: float,
) -> tuple[tuple[str, ...], tuple[float, ...]]:
    clusters = tuple(regex.findall(r"\X", text))
    if not clusters:
        return ("",), (0.0,)

    cluster_widths = tuple(_text_width(font, cluster) for cluster in clusters)
    for cluster, width in zip(clusters, cluster_widths):
        if width > max_width_px:
            raise ValueError(
                "a single grapheme cluster is wider than the available width"
            )

    lines: list[str] = []
    widths: list[float] = []
    current = ""
    for cluster in clusters:
        candidate = current + cluster
        candidate_width = _text_width(font, candidate)
        if current and candidate_width > max_width_px:
            lines.append(current)
            widths.append(_text_width(font, current))
            current = cluster
        else:
            current = candidate
    if current or not lines:
        lines.append(current)
        widths.append(_text_width(font, current))
    return tuple(lines), tuple(widths)


def measure_text_v4(
    text: str,
    *,
    family: str,
    role: str,
    font_size_px: float,
    max_width_px: float,
    line_height: float,
) -> TextMeasurementV4:
    """Measure one exact string with grapheme-safe deterministic wrapping."""

    if not isinstance(text, str):
        raise TypeError("visible text must be a string")
    font_size = _finite_positive(font_size_px, "font_size_px")
    max_width = _finite_positive(max_width_px, "max_width_px")
    line_height_value = _finite_positive(line_height, "line_height")
    resolved = resolve_font_file_v4(family, role)
    font = _load_font(resolved, font_size)

    explicit, newline_count = _explicit_lines(text)
    lines: list[str] = []
    widths: list[float] = []
    for explicit_line in explicit:
        wrapped, wrapped_widths = _wrap_graphemes(
            explicit_line,
            font=font,
            max_width_px=max_width,
        )
        lines.extend(wrapped)
        widths.extend(wrapped_widths)

    line_count = len(lines)
    return TextMeasurementV4(
        text=text,
        lines=tuple(lines),
        line_widths_px=tuple(widths),
        width_px=max(widths, default=0.0),
        height_px=float(line_count) * font_size * line_height_value,
        line_count=line_count,
        explicit_newline_count=newline_count,
        font_size_px=font_size,
        line_height=line_height_value,
        max_width_px=max_width,
        font_sha256=resolved.sha256,
    )


# Short aliases are useful to callers while retaining the explicit v4 names
# for cross-version auditing.
measure_text = measure_text_v4
resolve_font_file = resolve_font_file_v4
TypographyMeasurementV4 = TextMeasurementV4
TypographyMeasurement = TextMeasurementV4
ResolvedFont = ResolvedFontV4


__all__ = [
    "CANONICAL_FONT_FILES_V4",
    "CANONICAL_FONT_SHA256_V4",
    "FONT_ROOT",
    "REPOSITORY_ROOT",
    "ResolvedFontV4",
    "ResolvedFont",
    "TextMeasurementV4",
    "TypographyMeasurement",
    "TypographyMeasurementV4",
    "measure_text",
    "measure_text_v4",
    "resolve_font_file",
    "resolve_font_file_v4",
    "resolve_font_path_v4",
]
