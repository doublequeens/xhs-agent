from __future__ import annotations

from src.schemas.storyboard import CarouselFrame


def _frame(
    headline: str,
    *,
    kicker: str | None = None,
    content_blocks: list[dict] | None = None,
    footer: str | None = None,
) -> CarouselFrame:
    return CarouselFrame.model_validate(
        {
            "frame_id": "frame-copy-metrics",
            "role": "detail",
            "page_archetype": "explanation",
            "content_density_hint": "auto",
            "headline": headline,
            "kicker": kicker,
            "content_blocks": content_blocks or [],
            "visual_slots": [],
            "footer": footer,
        }
    )


def test_copy_metrics_count_emoji_as_graphemes_not_codepoints():
    from src.rendering.editorial.copy_metrics import measure_frame_copy

    metrics = measure_frame_copy(_frame("防晒要等一等👩‍🔬✨"))

    assert metrics.emoji_count == 2
    assert metrics.grapheme_count == 8
    assert metrics.cjk_count == 6


def test_copy_metrics_capture_item_cardinality_and_longest_item():
    from src.rendering.editorial.copy_metrics import measure_frame_copy

    metrics = measure_frame_copy(
        _frame(
            "判断标准",
            content_blocks=[
                {
                    "block_type": "checklist",
                    "items": ["短项", "这是一条明显更长的判断标准"],
                }
            ],
        )
    )

    assert metrics.block_count == 1
    assert metrics.item_count == 2
    assert metrics.max_item_graphemes == 13


def test_copy_metrics_include_every_visible_field_and_estimate_each_line_group():
    from src.rendering.editorial.copy_metrics import measure_frame_copy

    metrics = measure_frame_copy(
        _frame(
            "Headline words",
            kicker="通勤提示",
            content_blocks=[
                {
                    "block_type": "text",
                    "heading": "先看状态",
                    "body": "a" * 19,
                },
                {
                    "block_type": "bullets",
                    "items": ["第一项", "second item"],
                },
            ],
            footer="自然结束",
        )
    )

    assert metrics.block_count == 2
    assert metrics.item_count == 2
    assert metrics.latin_word_count == 5
    assert metrics.estimated_lines == 8


def test_copy_metrics_allow_copy_without_emoji():
    from src.rendering.editorial.copy_metrics import measure_frame_copy

    metrics = measure_frame_copy(_frame("不要求每页都出现 emoji"))

    assert metrics.emoji_count == 0
