"""Contract tests for the soft_pink bespoke editorial layouts (Path M).

Covers: the 7 bespoke archetypes render their designed composition class and the
persona copy role; the cover splits its headline's ``N步`` digit into a hero
numeral in one copy atom (textContent preserved, no duplicate numeral);
renderer._expected_copy and render_qa._expected_probe_text agree on role order;
and the deterministic persona enrichment fires only for soft_pink.
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
        ("cover", "sp-cover"),
        ("scene", "sp-scene"),
        ("story_beat", "sp-story"),
        ("explanation", "sp-explain"),
        ("save", "sp-save"),
        ("steps", "sp-steps"),
        ("boundary", "sp-boundary"),
    ],
)
def test_soft_pink_bespoke_renders_designed_composition(archetype, section_cls):
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.variant_resolver import resolve_variant

    is_cover = archetype == "cover"
    frame = _frame(archetype, "f")
    update: dict = {"persona": "@测试人设"}
    if is_cover:
        update["headline"] = "下班直接去约会：3步清爽补妆"
        update["hero_numeral"] = "3"
    frame = frame.model_copy(update=update)
    variant = resolve_variant(
        "soft_pink", archetype, "auto", measure_frame_copy(frame)
    )
    html = TEMPLATE_RENDERERS["soft_pink"](frame, [], variant)

    assert f"composition-{section_cls}" in html
    assert 'data-copy-role="persona"' in html
    if is_cover:
        # cover: big numeral + title are separate copy atoms (prototype layout)
        assert 'data-copy-role="hero_numeral"' in html
        assert "sp-num" in html and "sp-ttl" in html
    else:
        # every content_blocks item still carries the probe's expected copy role
        assert 'data-copy-role="content_blocks[1].items[0]"' in html


def test_soft_pink_cover_numeral_and_title_are_separate_atoms_no_duplicate():
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.variant_resolver import resolve_variant

    frame = _frame("cover", "f", headline="下班直接去约会：3步清爽补妆").model_copy(
        update={"persona": "@p", "hero_numeral": "3"}
    )
    variant = resolve_variant("soft_pink", "cover", "auto", measure_frame_copy(frame))
    html = TEMPLATE_RENDERERS["soft_pink"](frame, [], variant)

    # hero numeral and title are separate copy atoms
    assert html.count('data-copy-role="hero_numeral"') == 1
    assert html.count('data-copy-role="headline"') == 1
    assert "sp-num" in html and "sp-ttl" in html
    # the digit lives in the hero_numeral atom and is removed from the title
    nospace = html.replace(" ", "")
    assert 'data-copy-role="hero_numeral">3<' in nospace
    assert "下班直接去约会" in html and "步清爽补妆" in html
    # no punctuation colon in the rendered cover body
    assert "：" not in html.split("</style>", 1)[1]


def test_expected_copy_orders_persona_before_footer():
    from src.rendering.editorial.renderer import _expected_copy

    frame = _frame("cover", "f").model_copy(update={"persona": "@p"})
    roles = [role for role, _ in _expected_copy(frame)]
    assert "persona" in roles
    assert roles.index("persona") < roles.index("footer")
    # hero_numeral was removed; expected_copy must not surface it
    assert "hero_numeral" not in roles


def test_expected_probe_text_matches_expected_copy_role_order():
    """renderer._expected_copy and render_qa._expected_probe_text must produce the
    same (role, text) sequence — the probe compares rendered copy against both."""
    from src.nodes.node_p_render_qa import _expected_probe_text
    from src.rendering.editorial.renderer import _expected_copy

    frame = _frame("cover", "f").model_copy(update={"persona": "@p"})
    assert _expected_copy(frame) == _expected_probe_text(frame)


def test_curate_frames_strips_footer_everywhere_and_soft_pink_persona_and_cover_body():
    from src.nodes.node_o_storyboards_generator import _curate_frames_for_publish

    frames = [_frame(arch, f"f{i}") for i, arch in enumerate(
        ["cover", "scene", "story_beat", "explanation", "save"]
    )]
    payload = CarouselPayload.model_validate({"storyboards": frames})

    curated = _curate_frames_for_publish(
        payload, SimpleNamespace(template_family="soft_pink")
    )
    # disclaimer footer dropped from every frame (never rendered in images)
    assert all(frame.footer is None for frame in curated.storyboards)
    # persona added on soft_pink; cover body cleared to keep the cover clean
    assert all(frame.persona for frame in curated.storyboards)
    assert curated.storyboards[0].content_blocks == []
    assert curated.storyboards[1].content_blocks != []

    # other families: footer still stripped (global policy), but no persona
    other = _curate_frames_for_publish(
        payload, SimpleNamespace(template_family="deep_teal")
    )
    assert all(frame.footer is None for frame in other.storyboards)
    assert all(not frame.persona for frame in other.storyboards)
    # and the cover body is retained for non-soft_pink families
    assert other.storyboards[0].content_blocks != []
