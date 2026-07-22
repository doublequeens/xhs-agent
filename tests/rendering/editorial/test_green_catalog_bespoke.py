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


def test_green_catalog_save_emits_block0_body_before_items():
    """Regression: green_catalog save bespoke must emit block 0 copy atoms in
    the contract order heading -> body -> items (matching the canonical
    ``_render_block`` and the layout probe's ``_expected_copy``). When block 0
    has BOTH a body and items, emitting body after items made the probe read
    ``heading, items, body`` while expecting ``heading, body, items`` and raise
    "frame-05-save layout probe visible text does not match storyboard". The
    shared ``make_frame`` block 0 has a body but no items, which masked this.
    """
    import re

    from conftest import make_frame
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.variant_resolver import resolve_variant

    base = make_frame("save", frame_id="f", role="save")
    block0 = base.content_blocks[0].model_copy(
        update={"items": ["出汗少：气垫补涂", "出汗多：粉饼按压"]}
    )
    frame = base.model_copy(
        update={
            "persona": "@测试人设",
            "content_blocks": [block0, base.content_blocks[1]],
            "visual_slots": [],
        }
    )
    variant = resolve_variant("green_catalog", "save", "auto", measure_frame_copy(frame))
    html = TEMPLATE_RENDERERS["green_catalog"](frame, [], variant)

    roles = re.findall(r'data-copy-role="([^"]+)"', html)
    block0_roles = [role for role in roles if role.startswith("content_blocks[0].")]
    assert block0_roles == [
        "content_blocks[0].heading",
        "content_blocks[0].body",
        "content_blocks[0].items[0]",
        "content_blocks[0].items[1]",
    ]


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
