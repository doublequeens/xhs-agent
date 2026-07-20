"""Contract tests for the coral_impact bespoke editorial layouts (Path M).

Covers: the 4 bespoke archetypes (cover / story_beat / steps / boundary) render
their designed composition class and the persona copy role; the persona
enrichment fires for coral_impact; and the cover content body is cleared.
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
        ("cover", "ci-cover"),
        ("story_beat", "ci-story"),
        ("steps", "ci-steps"),
        ("boundary", "ci-boundary"),
        ("save", "ci-save"),
    ],
)
def test_coral_impact_bespoke_renders_designed_composition(archetype, section_cls):
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.variant_resolver import resolve_variant

    update: dict = {"persona": "@测试人设"}
    # cover and save only go bespoke for sparse/empty content (production shape);
    # clear their blocks so the bespoke centered layouts are exercised.
    if archetype in ("cover", "save"):
        update["content_blocks"] = []
    frame = _frame(archetype, "f").model_copy(update=update)
    variant = resolve_variant("coral_impact", archetype, "auto", measure_frame_copy(frame))
    html = TEMPLATE_RENDERERS["coral_impact"](frame, [], variant)

    assert f"composition-{section_cls}" in html
    assert 'data-copy-role="persona"' in html
    if archetype not in ("cover", "save"):
        assert 'data-copy-role="content_blocks[1].items[0]"' in html


def test_coral_impact_persona_renders_on_generic_fallback_path():
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.variant_resolver import resolve_variant

    frame = _frame("scene", "f").model_copy(update={"persona": "@测试人设"})
    variant = resolve_variant("coral_impact", "scene", "auto", measure_frame_copy(frame))
    html = TEMPLATE_RENDERERS["coral_impact"](frame, [], variant)
    assert 'data-copy-role="persona"' in html


def test_coral_impact_cover_and_boundary_emit_decorative_emoji_icons():
    """The mockup places decorative 💬 (chat) and 🧴 (boundary icon) emoji as
    aria-hidden layout icons (not copy). They must render but NOT carry a copy
    role, so the probe contract is unaffected."""
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.variant_resolver import resolve_variant

    cover = _frame("cover", "f").model_copy(update={"persona": "@p", "content_blocks": []})
    save = _frame("save", "f").model_copy(update={"persona": "@p", "content_blocks": []})
    boundary = _frame("boundary", "f").model_copy(update={"persona": "@p"})
    cv = resolve_variant("coral_impact", "cover", "auto", measure_frame_copy(cover))
    sv = resolve_variant("coral_impact", "save", "auto", measure_frame_copy(save))
    bv = resolve_variant("coral_impact", "boundary", "auto", measure_frame_copy(boundary))
    cover_html = TEMPLATE_RENDERERS["coral_impact"](cover, [], cv)
    save_html = TEMPLATE_RENDERERS["coral_impact"](save, [], sv)
    boundary_html = TEMPLATE_RENDERERS["coral_impact"](boundary, [], bv)
    assert "💬" not in cover_html  # chat CTA moved OFF the cover
    assert "💬" in save_html  # decorative chat CTA now on the save closer
    assert "🧴" in boundary_html  # decorative boundary icon


def test_curate_frames_coral_impact_persona_and_cover_body():
    from src.nodes.node_o_storyboards_generator import _curate_frames_for_publish

    frames = [
        _frame(arch, f"f{i}")
        for i, arch in enumerate(["cover", "story_beat", "steps", "boundary", "save"])
    ]
    payload = CarouselPayload.model_validate({"storyboards": frames})

    curated = _curate_frames_for_publish(
        payload, SimpleNamespace(template_family="coral_impact")
    )
    assert all(frame.footer is None for frame in curated.storyboards)
    assert all(frame.persona == "@成分党·文献派" for frame in curated.storyboards)
    assert curated.storyboards[0].content_blocks == []
    assert curated.storyboards[1].content_blocks != []
    assert all(frame.hero_numeral is None for frame in curated.storyboards)
