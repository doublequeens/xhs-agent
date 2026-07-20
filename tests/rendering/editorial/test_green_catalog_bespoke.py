"""Contract tests for the green_catalog bespoke editorial layouts (Path M).

Covers: the 4 bespoke archetypes (cover / item_collection / comparison / save)
render their designed composition class and the persona copy role; the persona
enrichment fires for green_catalog; and the cover content body is cleared.
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
        ("cover", "gc-cover"),
        ("item_collection", "gc-catalog"),
        ("comparison", "gc-compare"),
        ("save", "gc-save"),
    ],
)
def test_green_catalog_bespoke_renders_designed_composition(archetype, section_cls):
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.variant_resolver import resolve_variant

    update: dict = {"persona": "@测试人设"}
    if archetype == "cover":
        update["content_blocks"] = []
    frame = _frame(archetype, "f").model_copy(update=update)
    variant = resolve_variant("green_catalog", archetype, "auto", measure_frame_copy(frame))
    html = TEMPLATE_RENDERERS["green_catalog"](frame, [], variant)

    assert f"composition-{section_cls}" in html
    assert 'data-copy-role="persona"' in html
    if archetype != "cover":
        assert 'data-copy-role="content_blocks[1].items[0]"' in html


def test_green_catalog_persona_renders_on_generic_fallback_path():
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.variant_resolver import resolve_variant

    frame = _frame("scene", "f").model_copy(update={"persona": "@测试人设"})
    variant = resolve_variant("green_catalog", "scene", "auto", measure_frame_copy(frame))
    html = TEMPLATE_RENDERERS["green_catalog"](frame, [], variant)
    assert 'data-copy-role="persona"' in html


def test_curate_frames_green_catalog_persona_and_cover_body():
    from src.nodes.node_o_storyboards_generator import _curate_frames_for_publish

    frames = [
        _frame(arch, f"f{i}")
        for i, arch in enumerate(
            ["cover", "item_collection", "comparison", "save", "scene"]
        )
    ]
    payload = CarouselPayload.model_validate({"storyboards": frames})

    curated = _curate_frames_for_publish(
        payload, SimpleNamespace(template_family="green_catalog")
    )
    assert all(frame.footer is None for frame in curated.storyboards)
    assert all(frame.persona == "@成分党·文献派" for frame in curated.storyboards)
    assert curated.storyboards[0].content_blocks == []
    assert curated.storyboards[1].content_blocks != []
    assert all(frame.hero_numeral is None for frame in curated.storyboards)
