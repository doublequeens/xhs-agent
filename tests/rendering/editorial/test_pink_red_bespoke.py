"""Contract tests for the pink_red bespoke editorial layouts (Path M).

Covers: the 4 bespoke archetypes (cover / steps / comparison / save) render
their designed composition class and the persona copy role; the persona
enrichment fires for pink_red; and the cover content body is cleared by
curation so the clean cover layout is used.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.schemas.storyboard import CarouselPayload


def _frame(archetype: str, fid: str):
    from conftest import make_frame

    return make_frame(archetype, frame_id=fid, role=archetype)


@pytest.mark.parametrize(
    ("archetype", "section_cls"),
    [
        ("cover", "pr-cover"),
        ("steps", "pr-steps"),
        ("comparison", "pr-compare"),
        ("save", "pr-save"),
    ],
)
def test_pink_red_bespoke_renders_designed_composition(archetype, section_cls):
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.variant_resolver import resolve_variant

    update: dict = {"persona": "@测试人设"}
    if archetype == "cover":
        update["content_blocks"] = []
    frame = _frame(archetype, "f").model_copy(update=update)
    variant = resolve_variant("pink_red", archetype, "auto", measure_frame_copy(frame))
    html = TEMPLATE_RENDERERS["pink_red"](frame, [], variant)

    assert f"composition-{section_cls}" in html
    assert 'data-copy-role="persona"' in html
    if archetype != "cover":
        assert 'data-copy-role="content_blocks[1].items[0]"' in html


def test_pink_red_persona_renders_on_generic_fallback_path():
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.variant_resolver import resolve_variant

    frame = _frame("scene", "f").model_copy(update={"persona": "@测试人设"})
    variant = resolve_variant("pink_red", "scene", "auto", measure_frame_copy(frame))
    html = TEMPLATE_RENDERERS["pink_red"](frame, [], variant)
    assert 'data-copy-role="persona"' in html


def test_pink_red_backgrounds_strictly_alternate_by_page_index():
    """The defining trait of pink_red: pink/red backgrounds alternate strictly
    across the carousel. The page index is parsed from frame_id (frame-NN-…);
    odd positions are pink, even are red — so no two consecutive pages share a
    background."""
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.variant_resolver import resolve_variant
    from src.rendering.editorial.templates.pink_red import _is_red_page

    archetypes = ["cover", "steps", "comparison", "save", "scene", "steps"]
    reds = []
    for i, arch in enumerate(archetypes, start=1):
        frame = _frame(arch, f"frame-{i:02d}-{arch}").model_copy(
            update={"persona": "@测试人设", **({"content_blocks": []} if arch == "cover" else {})}
        )
        # parity check directly
        assert _is_red_page(frame) == (i % 2 == 0)
        # and the emitted card carries the matching background
        variant = resolve_variant("pink_red", arch, "auto", measure_frame_copy(frame))
        html = TEMPLATE_RENDERERS["pink_red"](frame, [], variant)
        if i % 2 == 0:  # red page
            assert "background:#DC2333" in html
        reds.append(_is_red_page(frame))
    # strict alternation: no two consecutive same
    for a, b in zip(reds, reds[1:]):
        assert a != b


def test_pink_red_steps_archetype_flips_card_to_red_panel():
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.variant_resolver import resolve_variant

    frame = _frame("steps", "f").model_copy(update={"persona": "@测试人设"})
    variant = resolve_variant("pink_red", "steps", "auto", measure_frame_copy(frame))
    html = TEMPLATE_RENDERERS["pink_red"](frame, [], variant)
    assert "archetype-steps" in html
    assert "pr-steps" in html


def test_curate_frames_pink_red_persona_and_cover_body():
    from src.nodes.node_o_storyboards_generator import _curate_frames_for_publish

    frames = [
        _frame(arch, f"f{i}")
        for i, arch in enumerate(["cover", "steps", "comparison", "save", "scene"])
    ]
    payload = CarouselPayload.model_validate({"storyboards": frames})

    curated = _curate_frames_for_publish(
        payload, SimpleNamespace(template_family="pink_red")
    )
    assert all(frame.footer is None for frame in curated.storyboards)
    assert all(frame.persona == "@成分党·文献派" for frame in curated.storyboards)
    assert curated.storyboards[0].content_blocks == []
    assert curated.storyboards[1].content_blocks != []
    assert all(frame.hero_numeral is None for frame in curated.storyboards)

    # coral_impact is also bespoke: persona added + cover cleared.
    other = _curate_frames_for_publish(
        payload, SimpleNamespace(template_family="coral_impact")
    )
    assert all(frame.footer is None for frame in other.storyboards)
    assert all(frame.persona == "@成分党·文献派" for frame in other.storyboards)
    assert other.storyboards[0].content_blocks == []
