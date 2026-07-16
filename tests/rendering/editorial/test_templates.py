from __future__ import annotations

import re
from html import escape
from typing import get_args

import pytest

from src.schemas.editorial_templates import PageArchetype, TemplateFamily


ALL_TEMPLATE_FAMILIES = get_args(TemplateFamily)
ALL_PAGE_ARCHETYPES = get_args(PageArchetype)


@pytest.mark.parametrize("family", ALL_TEMPLATE_FAMILIES)
@pytest.mark.parametrize("archetype", ALL_PAGE_ARCHETYPES)
def test_every_family_renders_every_archetype(family, archetype):
    from conftest import make_frame
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.variant_resolver import resolve_variant

    frame = make_frame(archetype)
    variant = resolve_variant(
        family,
        archetype,
        "auto",
        measure_frame_copy(frame),
    )

    html = TEMPLATE_RENDERERS[family](frame, [], variant)

    assert f'data-template-family="{family}"' in html
    assert f'data-page-archetype="{archetype}"' in html
    assert f'data-density="{variant.density}"' in html
    assert (
        f'data-composition-variant="{variant.composition_variant}"'
        in html
    )
    assert escape(frame.headline, quote=True) in html


def test_template_renderers_escape_copy_and_do_not_emit_asset_placeholder():
    from conftest import make_frame
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.variant_resolver import resolve_variant

    frame = make_frame("explanation").model_copy(
        update={"headline": "<script>alert(1)</script>"}
    )
    variant = resolve_variant(
        "soft_pink",
        "explanation",
        "auto",
        measure_frame_copy(frame),
    )

    html = TEMPLATE_RENDERERS["soft_pink"](frame, [], variant)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "asset-placeholder" not in html
    assert "http://" not in html
    assert "https://" not in html


def test_every_visible_storyboard_string_is_emitted_exactly_once():
    from conftest import make_frame
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.variant_resolver import resolve_variant

    frame = make_frame("checklist")
    variant = resolve_variant(
        "green_catalog",
        "checklist",
        "auto",
        measure_frame_copy(frame),
    )

    html = TEMPLATE_RENDERERS["green_catalog"](frame, [], variant)
    roles = re.findall(r'data-copy-role="([^"]+)"', html)
    expected = [
        "kicker",
        "headline",
        "content_blocks[0].heading",
        "content_blocks[0].body",
        "content_blocks[1].heading",
        "content_blocks[1].items[0]",
        "content_blocks[1].items[1]",
        "content_blocks[1].items[2]",
        "content_blocks[2].heading",
        "content_blocks[2].items[0]",
        "content_blocks[2].items[1]",
        "emphasis[0]",
        "emphasis[1]",
        "footer",
    ]

    assert roles == expected
    assert len(roles) == len(set(roles))


@pytest.mark.parametrize("item_count", range(1, 7))
def test_list_and_step_rendering_supports_one_to_six_items(item_count):
    from conftest import make_frame
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.variant_resolver import resolve_variant

    frame = make_frame("steps").model_copy(deep=True)
    frame.content_blocks[0].items = [
        f"动态步骤 {index}" for index in range(1, item_count + 1)
    ]
    frame.content_blocks[0].body = None
    variant = resolve_variant(
        "deep_teal",
        "steps",
        "auto",
        measure_frame_copy(frame),
    )

    html = TEMPLATE_RENDERERS["deep_teal"](frame, [], variant)

    assert html.count('class="item-copy"') >= item_count
    for index in range(1, item_count + 1):
        assert f"动态步骤 {index}" in html


def test_template_renderer_emits_only_resolved_local_assets(tmp_path):
    from conftest import make_asset, make_frame
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.variant_resolver import resolve_variant

    asset_path = tmp_path / "proof.svg"
    asset_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"/>',
        encoding="utf-8",
    )
    frame = make_frame("scene")
    asset = make_asset(
        "scene",
        slot_id=frame.visual_slots[0].slot_id,
        path=asset_path,
    )
    variant = resolve_variant(
        "coral_impact",
        "scene",
        "auto",
        measure_frame_copy(frame),
    )

    html = TEMPLATE_RENDERERS["coral_impact"](
        frame,
        [asset],
        variant,
    )

    assert asset_path.resolve().as_uri() in html
    assert 'data-asset-slot="frame-visual"' in html


@pytest.mark.parametrize(
    ("family", "root_class", "color"),
    [
        ("pink_red", "template-pink-red", "#F4A7BF"),
        ("deep_teal", "template-deep-teal", "#0E5A5A"),
        ("soft_pink", "template-soft-pink", "#F8DADA"),
        ("coral_impact", "template-coral-impact", "#F45A5A"),
        ("green_catalog", "template-green-catalog", "#1E5A2E"),
        ("white_quote", "template-white-quote", "#2A4A8C"),
    ],
)
def test_each_family_keeps_its_mockup_visual_identity(
    family,
    root_class,
    color,
):
    from conftest import make_frame
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.variant_resolver import resolve_variant

    frame = make_frame("cover")
    variant = resolve_variant(
        family,
        "cover",
        "auto",
        measure_frame_copy(frame),
    )

    html = TEMPLATE_RENDERERS[family](frame, [], variant)

    assert root_class in html
    assert color in html


def test_pink_red_standard_story_beat_uses_the_red_panel_variant():
    from conftest import make_frame
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.variant_resolver import resolve_variant

    frame = make_frame("story_beat").model_copy(deep=True)
    frame.content_blocks[2].items = ["偏干：减少清洁"]
    variant = resolve_variant(
        "pink_red",
        "story_beat",
        "standard",
        measure_frame_copy(frame),
    )

    assert variant.composition_variant == "red-panel"
    html = TEMPLATE_RENDERERS["pink_red"](frame, [], variant)
    assert "variant-red-panel" in html
