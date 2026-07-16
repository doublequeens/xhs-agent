from __future__ import annotations

import math

import regex

from src.schemas.editorial_templates import CopyMetrics
from src.schemas.storyboard import CarouselFrame


GRAPHEME_RE = regex.compile(r"\X")
EMOJI_RE = regex.compile(r"\p{Extended_Pictographic}")
CJK_RE = regex.compile(r"\p{Script=Han}")
LATIN_WORD_RE = regex.compile(r"\b[\p{Latin}\d][\p{Latin}\d'-]*\b")


def _visible_strings(frame: CarouselFrame) -> list[str]:
    values: list[str] = []
    if frame.kicker:
        values.append(frame.kicker)
    values.append(frame.headline)
    for block in frame.content_blocks:
        if block.heading:
            values.append(block.heading)
        if block.body:
            values.append(block.body)
        values.extend(block.items)
    if frame.footer:
        values.append(frame.footer)
    return values


def _graphemes(text: str) -> list[str]:
    return GRAPHEME_RE.findall(text)


def measure_frame_copy(frame: CarouselFrame) -> CopyMetrics:
    """Measure visible storyboard copy without imposing an emoji policy."""

    visible_strings = _visible_strings(frame)
    grapheme_groups = [_graphemes(text) for text in visible_strings]
    item_groups = [
        _graphemes(item)
        for block in frame.content_blocks
        for item in block.items
    ]
    return CopyMetrics(
        grapheme_count=sum(len(group) for group in grapheme_groups),
        cjk_count=sum(len(CJK_RE.findall(text)) for text in visible_strings),
        latin_word_count=sum(
            len(LATIN_WORD_RE.findall(text)) for text in visible_strings
        ),
        emoji_count=sum(
            1
            for group in grapheme_groups
            for grapheme in group
            if EMOJI_RE.search(grapheme)
        ),
        block_count=len(frame.content_blocks),
        item_count=len(item_groups),
        max_item_graphemes=max(
            (len(group) for group in item_groups),
            default=0,
        ),
        estimated_lines=sum(
            max(1, math.ceil(len(group) / 18))
            for group in grapheme_groups
        ),
    )
