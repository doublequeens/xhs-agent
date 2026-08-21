"""Deterministic, project-font-only typography measurement for v4.

The v4 layout compiler measures text before it creates scene primitives.  This
module is deliberately independent from Chromium and from the host font
installation: every family role resolves to one checked-in font byte stream,
and Pillow/FreeType performs the measurement locally.
"""

from __future__ import annotations

import hashlib
import json
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
CANONICAL_FONT_NOMINAL_WEIGHTS_V4: Mapping[str, int] = MappingProxyType(
    {
        "Alibaba PuHuiTi Heavy": 900,
        "HarmonyOS Sans Black": 900,
        "HarmonyOS Sans Bold": 700,
        "HarmonyOS Sans": 400,
        "LXGW WenKai": 400,
    }
)
TEXT_WRAP_POLICY_V4: Final[str] = "pre-wrap-grapheme-anywhere-v1"
CONTENT_INSET_POLICY_V4: Final[str] = "content-origin-inset-v1"


@dataclass(frozen=True)
class ResolvedFontV4:
    """One checked-in font and the digest of its exact bytes."""

    family_name: str
    role: str
    path: Path
    sha256: str
    nominal_weight: int


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
    font_nominal_weight: int
    advance_width_px: float
    ink_width_px: float
    ink_height_px: float
    break_offsets: tuple[int, ...]
    offset_unit: str
    explicit_break_spans: tuple[tuple[int, int], ...]
    inserted_break_offsets: tuple[int, ...]
    ink_left_px: float
    ink_top_px: float
    ink_right_px: float
    ink_bottom_px: float
    ascent_px: float
    descent_px: float
    content_inset_policy: str
    content_inset_left_px: float
    content_inset_top_px: float
    content_inset_right_px: float
    content_inset_bottom_px: float
    painted_offset_x_px: float
    painted_offset_y_px: float
    painted_left_px: float
    painted_top_px: float
    painted_right_px: float
    painted_bottom_px: float
    measurement_sha256: str

    @property
    def wrapped_text(self) -> str:
        """Return compiler line breaks without changing ``text`` itself."""

        return "\n".join(self.lines)

    @property
    def font_byte_sha256(self) -> str:
        return self.font_sha256

    @property
    def wrap_policy(self) -> str:
        return TEXT_WRAP_POLICY_V4


def _finite_positive(value: object, field_name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite positive number")
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a finite positive number") from None
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
    except (OSError, RuntimeError, ValueError):
        raise ValueError("checked-in v4 font file is missing or unreadable") from None
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
    except Exception:
        raise ValueError("unknown v4 font family") from None
    family_name = getattr(tokens.font_roles, role, None)
    path = _FONT_FILES.get(family_name)
    if not isinstance(family_name, str) or path is None:
        raise ValueError(f"font file is not registered for role {role!r}")
    data = _font_bytes(path)
    digest = hashlib.sha256(data).hexdigest()
    expected_digest = CANONICAL_FONT_SHA256_V4.get(family_name)
    if expected_digest is None or digest != expected_digest:
        raise ValueError("checked-in v4 font bytes do not match the canonical font revision")
    nominal_weight = CANONICAL_FONT_NOMINAL_WEIGHTS_V4.get(family_name)
    if nominal_weight is None:
        raise ValueError("checked-in v4 font weight is not registered")
    return ResolvedFontV4(
        family_name=family_name,
        role=role,
        path=path,
        sha256=digest,
        nominal_weight=nominal_weight,
    )


def resolve_font_path_v4(family: str, role: str) -> Path:
    """Return a checked-in path after running the full font safety checks."""

    return resolve_font_file_v4(family, role).path


def _load_font(resolved: ResolvedFontV4, size_px: float):
    try:
        return ImageFont.truetype(str(resolved.path), size=max(1, round(size_px)))
    except (OSError, ValueError):
        raise ValueError("checked-in v4 font cannot be loaded by Pillow/FreeType") from None


def _text_width(font: ImageFont.FreeTypeFont, text: str) -> float:
    try:
        width = float(font.getlength(text))
    except (AttributeError, OSError, ValueError):
        raise ValueError("Pillow/FreeType failed to measure text") from None
    if not math.isfinite(width) or width < 0:
        raise ValueError("Pillow/FreeType returned invalid text geometry")
    return width


def _text_ink_extents(
    font: ImageFont.FreeTypeFont,
    text: str,
) -> tuple[float, float, float, float]:
    """Return Pillow's complete ink bbox, including negative bearings."""

    try:
        left, top, right, bottom = font.getbbox(text)
        left_value = float(left)
        top_value = float(top)
        right_value = float(right)
        bottom_value = float(bottom)
    except (AttributeError, OSError, ValueError):
        raise ValueError("Pillow/FreeType failed to measure ink extents") from None
    if not all(
        math.isfinite(value)
        for value in (left_value, top_value, right_value, bottom_value)
    ):
        raise ValueError("Pillow/FreeType returned invalid ink extents")
    return left_value, top_value, right_value, bottom_value


def _text_extent(font: ImageFont.FreeTypeFont, text: str) -> float:
    """Measure the conservative horizontal extent used for wrapping."""

    left, _top, right, _bottom = _text_ink_extents(font, text)
    return max(_text_width(font, text), max(0.0, right - left))


def _explicit_lines(
    text: str,
) -> tuple[tuple[tuple[str, int], ...], tuple[tuple[int, int], ...]]:
    """Return exact line slices and original codepoint spans for delimiters."""

    lines: list[tuple[str, int]] = []
    break_spans: list[tuple[int, int]] = []
    cursor = 0
    for match in regex.finditer(r"\r\n|\n|\r", text):
        lines.append((text[cursor : match.start()], cursor))
        break_spans.append((match.start(), match.end()))
        cursor = match.end()
    lines.append((text[cursor:], cursor))
    return tuple(lines), tuple(break_spans)


def _wrap_graphemes(
    text: str,
    *,
    font: ImageFont.FreeTypeFont,
    max_width_px: float,
) -> tuple[tuple[str, ...], tuple[float, ...]]:
    clusters = tuple(regex.findall(r"\X", text))
    if not clusters:
        return ("",), (0.0,)

    cluster_widths = tuple(_text_extent(font, cluster) for cluster in clusters)
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
        candidate_width = _text_extent(font, candidate)
        if current and candidate_width > max_width_px:
            lines.append(current)
            widths.append(_text_extent(font, current))
            current = cluster
        else:
            current = candidate
    if current or not lines:
        lines.append(current)
        widths.append(_text_extent(font, current))
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

    explicit, explicit_break_spans = _explicit_lines(text)
    lines: list[str] = []
    widths: list[float] = []
    inserted_break_offsets: list[int] = []
    for explicit_line, line_start in explicit:
        wrapped, wrapped_widths = _wrap_graphemes(
            explicit_line,
            font=font,
            max_width_px=max_width,
        )
        lines.extend(wrapped)
        widths.extend(wrapped_widths)
        cursor = line_start
        for wrapped_line in wrapped[:-1]:
            cursor += len(wrapped_line)
            inserted_break_offsets.append(cursor)

    line_count = len(lines)
    try:
        ascent, descent = font.getmetrics()
    except (AttributeError, OSError, ValueError):
        raise ValueError("Pillow/FreeType failed to measure font metrics") from None
    line_ink_widths: list[float] = []
    line_ink_heights: list[float] = []
    line_bboxes: list[tuple[float, float, float, float]] = []
    for line in lines:
        left, top, right, bottom = _text_ink_extents(font, line)
        ink_width = max(0.0, right - left)
        ink_height = max(0.0, bottom - top)
        line_ink_widths.append(ink_width)
        line_ink_heights.append(ink_height)
        line_bboxes.append((left, top, right, bottom))
    advance_width = max(
        (_text_width(font, line) for line in lines),
        default=0.0,
    )
    ink_width = max([advance_width, *line_ink_widths])
    line_box_height = max(
        float(ascent + descent),
        max(line_ink_heights, default=0.0),
        font_size * line_height_value,
    )
    positioned_bboxes = [
        (
            left,
            top + index * line_box_height,
            right,
            bottom + index * line_box_height,
        )
        for index, (left, top, right, bottom) in enumerate(line_bboxes)
    ]
    nonempty_bboxes = [bbox for line, bbox in zip(lines, positioned_bboxes) if line]
    if nonempty_bboxes:
        ink_left = min(bbox[0] for bbox in nonempty_bboxes)
        ink_top = min(bbox[1] for bbox in nonempty_bboxes)
        ink_right = max(bbox[2] for bbox in nonempty_bboxes)
        ink_bottom = max(bbox[3] for bbox in nonempty_bboxes)
    else:
        ink_left = ink_top = ink_right = ink_bottom = 0.0
    ink_height = max(0.0, ink_bottom - ink_top)
    # Keep the reserved box at the caller's requested origin.  Negative
    # bearings (for example ``j``) are represented as a content-origin inset
    # for the later renderer adapter, with painted bounds retained separately.
    content_height = float(line_count) * line_box_height
    content_inset_left = max(0.0, -ink_left)
    content_inset_top = max(0.0, -ink_top)
    # Painted bounds are measured relative to the content origin.  The later
    # renderer adapter adds the declared inset before applying this offset;
    # keeping the two values separate makes the negative-bearing contract
    # executable instead of silently moving the reserved scene box.
    painted_offset_x = 0.0
    painted_offset_y = 0.0
    painted_right_from_origin = (
        content_inset_left + painted_offset_x + ink_right
    )
    if painted_right_from_origin > max_width + 1e-6:
        raise ValueError("painted ink width exceeds available width")
    content_inset_right = max(
        0.0,
        painted_right_from_origin - max_width,
    )
    content_inset_bottom = max(
        0.0,
        painted_offset_y + ink_bottom - content_height,
    )
    measured_height = max(content_height, content_inset_top + ink_bottom)
    measurement_payload = {
        "content_inset_bottom_px": content_inset_bottom,
        "content_inset_left_px": content_inset_left,
        "content_inset_policy": CONTENT_INSET_POLICY_V4,
        "content_inset_right_px": content_inset_right,
        "content_inset_top_px": content_inset_top,
        "explicit_break_spans": tuple(explicit_break_spans),
        "font_nominal_weight": resolved.nominal_weight,
        "font_sha256": resolved.sha256,
        "font_size_px": font_size,
        "ink_height_px": ink_height,
        "ink_left_px": ink_left,
        "ink_top_px": ink_top,
        "ink_right_px": ink_right,
        "ink_bottom_px": ink_bottom,
        "ink_width_px": ink_width,
        "ascent_px": float(ascent),
        "descent_px": float(descent),
        "inserted_break_offsets": tuple(inserted_break_offsets),
        "line_count": line_count,
        "line_height": line_height_value,
        "line_widths_px": tuple(widths),
        "max_width_px": max_width,
        "painted_bottom_px": ink_bottom,
        "painted_left_px": ink_left,
        "painted_offset_x_px": painted_offset_x,
        "painted_offset_y_px": painted_offset_y,
        "painted_right_px": ink_right,
        "painted_top_px": ink_top,
    }
    measurement_sha256 = hashlib.sha256(
        json.dumps(measurement_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return TextMeasurementV4(
        text=text,
        lines=tuple(lines),
        line_widths_px=tuple(widths),
        width_px=ink_width,
        height_px=measured_height,
        line_count=line_count,
        explicit_newline_count=len(explicit_break_spans),
        font_size_px=font_size,
        line_height=line_height_value,
        max_width_px=max_width,
        font_sha256=resolved.sha256,
        font_nominal_weight=resolved.nominal_weight,
        advance_width_px=advance_width,
        ink_width_px=ink_width,
        ink_height_px=ink_height,
        break_offsets=tuple(inserted_break_offsets),
        offset_unit="unicode_codepoint_v1",
        explicit_break_spans=tuple(explicit_break_spans),
        inserted_break_offsets=tuple(inserted_break_offsets),
        ink_left_px=ink_left,
        ink_top_px=ink_top,
        ink_right_px=ink_right,
        ink_bottom_px=ink_bottom,
        ascent_px=float(ascent),
        descent_px=float(descent),
        content_inset_policy=CONTENT_INSET_POLICY_V4,
        content_inset_left_px=content_inset_left,
        content_inset_top_px=content_inset_top,
        content_inset_right_px=content_inset_right,
        content_inset_bottom_px=content_inset_bottom,
        painted_offset_x_px=painted_offset_x,
        painted_offset_y_px=painted_offset_y,
        painted_left_px=ink_left,
        painted_top_px=ink_top,
        painted_right_px=ink_right,
        painted_bottom_px=ink_bottom,
        measurement_sha256=measurement_sha256,
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
    "CANONICAL_FONT_NOMINAL_WEIGHTS_V4",
    "CONTENT_INSET_POLICY_V4",
    "FONT_ROOT",
    "REPOSITORY_ROOT",
    "ResolvedFontV4",
    "ResolvedFont",
    "TextMeasurementV4",
    "TEXT_WRAP_POLICY_V4",
    "TypographyMeasurement",
    "TypographyMeasurementV4",
    "measure_text",
    "measure_text_v4",
    "resolve_font_file",
    "resolve_font_file_v4",
    "resolve_font_path_v4",
]
