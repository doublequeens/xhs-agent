"""Contract tests for the white_quote bespoke editorial layouts (Path M).

Covers: the 5 bespoke archetypes (cover / quote / explanation / checklist /
boundary) render their designed composition class and the persona copy role;
renderer._expected_copy and render_qa._expected_probe_text agree on role order;
and the deterministic persona enrichment fires only for the families whose
bespoke renderer emits the persona atom (soft_pink + white_quote).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.schemas.storyboard import CarouselPayload


def _frame(archetype: str, fid: str, *, headline: str | None = None):
    from conftest import make_frame

    frame = make_frame(archetype, frame_id=fid, role=archetype)
    if headline is not None:
        frame = frame.model_copy(update={"headline": headline})
    return frame


@pytest.mark.parametrize(
    ("archetype", "section_cls"),
    [
        ("cover", "wq-cover"),
        ("quote", "wq-quote"),
        ("explanation", "wq-explain"),
        ("checklist", "wq-checklist"),
        ("boundary", "wq-boundary"),
    ],
)
def test_white_quote_bespoke_renders_designed_composition(archetype, section_cls):
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.variant_resolver import resolve_variant

    # cover only goes bespoke when its content_blocks are clear (production
    # curation does this); other archetypes keep the fixture's blocks.
    update: dict = {"persona": "@测试人设"}
    if archetype == "cover":
        update["content_blocks"] = []
    frame = _frame(archetype, "f").model_copy(update=update)
    variant = resolve_variant("white_quote", archetype, "auto", measure_frame_copy(frame))
    html = TEMPLATE_RENDERERS["white_quote"](frame, [], variant)

    assert f"composition-{section_cls}" in html
    assert 'data-copy-role="persona"' in html
    # white_quote has no hero numeral (only soft_pink does)
    assert "hero_numeral" not in html
    if archetype != "cover":
        # every content_blocks item still carries the probe's expected copy role
        assert 'data-copy-role="content_blocks[1].items[0]"' in html


def test_white_quote_persona_renders_on_generic_fallback_path():
    """A non-bespoke archetype (e.g. scene) still renders persona, because
    render_frame threads the footer through the generic fallback too — otherwise
    the probe's actual!=expected copy contract would break."""
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.variant_resolver import resolve_variant

    frame = _frame("scene", "f").model_copy(update={"persona": "@测试人设"})
    variant = resolve_variant("white_quote", "scene", "auto", measure_frame_copy(frame))
    html = TEMPLATE_RENDERERS["white_quote"](frame, [], variant)
    assert 'data-copy-role="persona"' in html


def test_expected_copy_orders_persona_before_footer():
    from src.rendering.editorial.renderer import _expected_copy

    frame = _frame("cover", "f").model_copy(update={"persona": "@p"})
    roles = [role for role, _ in _expected_copy(frame)]
    assert "persona" in roles
    assert roles.index("persona") < roles.index("footer")
    assert "hero_numeral" not in roles


def test_expected_probe_text_matches_expected_copy_role_order():
    """renderer._expected_copy and render_qa._expected_probe_text must produce the
    same (role, text) sequence — the probe compares rendered copy against both."""
    from src.nodes.node_p_render_qa import _expected_probe_text
    from src.rendering.editorial.renderer import _expected_copy

    frame = _frame("explanation", "f").model_copy(update={"persona": "@p"})
    assert _expected_copy(frame) == _expected_probe_text(frame)


def test_curate_frames_white_quote_persona_and_cover_body():
    from src.nodes.node_o_storyboards_generator import _curate_frames_for_publish

    frames = [
        _frame(arch, f"f{i}")
        for i, arch in enumerate(["cover", "quote", "explanation", "checklist", "boundary"])
    ]
    payload = CarouselPayload.model_validate({"storyboards": frames})

    curated = _curate_frames_for_publish(
        payload, SimpleNamespace(template_family="white_quote")
    )
    # disclaimer footer dropped from every frame (never rendered in images)
    assert all(frame.footer is None for frame in curated.storyboards)
    # persona added on white_quote; cover body cleared to keep the cover clean
    assert all(frame.persona == "@成分党·文献派" for frame in curated.storyboards)
    assert curated.storyboards[0].content_blocks == []
    assert curated.storyboards[1].content_blocks != []
    # no hero numeral extraction for white_quote
    assert all(frame.hero_numeral is None for frame in curated.storyboards)

    # coral_impact is also bespoke: persona added + cover cleared.
    # no persona and the cover body is retained
    other = _curate_frames_for_publish(
        payload, SimpleNamespace(template_family="coral_impact")
    )
    assert all(frame.footer is None for frame in other.storyboards)
    assert all(frame.persona == "@成分党·文献派" for frame in other.storyboards)
    assert other.storyboards[0].content_blocks == []
