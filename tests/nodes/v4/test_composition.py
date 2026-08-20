from __future__ import annotations

from collections.abc import Mapping, Sequence
import inspect

import pytest

from src.nodes.v4.composition import build_layout_program
from src.schemas.v4.content import canonical_sha256_v4
from src.schemas.v4.direction import AssetDirectiveV4, NarrativeBeatV4, PageBriefV4
from src.visual_design.v4.tokens import FAMILY_TOKENS


def _assert_no_render_payload(value: object) -> None:
    """Inspect every nested program field without rejecting valid IDs/fonts."""

    banned_keys = {
        "x", "y", "w", "h", "width", "height", "coordinates", "coordinate",
        "box", "scene_box", "html", "css", "dom", "script", "provider",
        "url", "path", "local_path", "provenance", "visible_copy", "visible_text",
    }
    if isinstance(value, Mapping):
        for key, item in value.items():
            assert str(key).lower() not in banned_keys
            _assert_no_render_payload(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            _assert_no_render_payload(item)
        return
    if isinstance(value, str):
        lowered = value.lower()
        for marker in (
            "<html", "<script", "javascript:", "http://", "https://",
            "file://", "../",
        ):
            assert marker not in lowered


def _page_brief(
    *,
    preferred: tuple[str, ...] = ("editorial_hero",),
    with_asset: bool = True,
    density: str = "medium",
    visual_priority: tuple[str, ...] = ("fragment-1",),
    fragment_refs: tuple[str, ...] = ("fragment-1", "fragment-2"),
) -> PageBriefV4:
    directives = ()
    if with_asset:
        directive = AssetDirectiveV4(
            directive_id="asset-1",
            page_id="page-1",
            role="evidence_example",
            purpose="evidence",
            supports_fragment_refs=("fragment-1",),
            required=True,
            preferred_source="search",
            query_or_prompt="text-free skincare evidence photo",
        )
        directives = (directive,)
    payload = {
        "page_id": "page-1",
        "sequence": 1,
        "narrative_role": "free-form role that must not drive grammar compatibility",
        "beat_ref": "beat-1",
        "fragment_refs": fragment_refs,
        "visual_priority": visual_priority,
        "density_budget": density,
        "preferred_compositions": preferred,
        "forbidden_patterns": (),
        "asset_directives": directives,
        "continuity_with_previous": "none",
    }
    return PageBriefV4(**payload, canonical_sha256=canonical_sha256_v4(payload))


def _beat(
    page: PageBriefV4,
    *,
    task_kind: str = "context",
    beat_id: str = "beat-1",
    fragment_refs: tuple[str, ...] | None = None,
) -> NarrativeBeatV4:
    return NarrativeBeatV4(
        beat_id=beat_id,
        sequence=page.sequence,
        task_kind=task_kind,
        fragment_refs=fragment_refs or page.fragment_refs,
        task="typed semantic duty",
    )


def test_composition_rejects_grammar_not_allowed_by_page_brief() -> None:
    with pytest.raises(ValueError, match="preferred compositions"):
        build_layout_program(
            _page_brief(preferred=("step_flow",)),
            grammar_id="comparison_grid",
            family="pink_red",
            narrative_beat=_beat(_page_brief(preferred=("step_flow",))),
        )


def test_composition_rejects_allowed_but_not_yet_implemented_grammar() -> None:
    with pytest.raises(ValueError, match="implemented"):
        build_layout_program(
            _page_brief(preferred=("diagnostic_matrix",)),
            grammar_id="diagnostic_matrix",
            family="pink_red",
            narrative_beat=_beat(_page_brief(preferred=("diagnostic_matrix",)), task_kind="diagnosis"),
        )


def test_composition_owns_each_fragment_and_page_asset_once() -> None:
    page = _page_brief()
    program = build_layout_program(
        page,
        grammar_id="editorial_hero",
        family="pink_red",
        narrative_beat=_beat(page),
    )
    assert tuple(item.fragment_ref for item in program.fragment_placements) == (
        "fragment-1",
        "fragment-2",
    )
    assert tuple(item.directive_id for item in program.asset_placements) == ("asset-1",)
    assert program.page_brief_sha256 == page.canonical_sha256
    assert program.family_tokens_sha256 == FAMILY_TOKENS["pink_red"].canonical_sha256
    _assert_no_render_payload(program.model_dump(mode="json"))


def test_composition_is_deterministic_and_binds_exact_brief_hash() -> None:
    page = _page_brief(with_asset=False)
    first = build_layout_program(
        page,
        grammar_id="editorial_hero",
        family="pink_red",
        narrative_beat=_beat(page),
    )
    second = build_layout_program(
        page,
        grammar_id="editorial_hero",
        family="pink_red",
        narrative_beat=_beat(page),
    )
    assert first.model_dump_json() == second.model_dump_json()
    assert first.canonical_sha256 == second.canonical_sha256

    tampered = page.model_copy(update={"narrative_role": "changed"})
    with pytest.raises(ValueError, match="page brief|canonical"):
        build_layout_program(
            tampered,
            grammar_id="editorial_hero",
            family="pink_red",
            narrative_beat=_beat(page),
        )


def test_composition_revalidates_json_persisted_page_brief() -> None:
    page = _page_brief(with_asset=False)
    program = build_layout_program(
        page.model_dump(mode="json"),
        grammar_id="editorial_hero",
        family="pink_red",
        narrative_beat=_beat(page).model_dump(mode="json"),
    )
    assert program.page_brief_sha256 == page.canonical_sha256


def test_composition_rejects_dangling_or_duplicate_asset_ownership() -> None:
    page = _page_brief()
    raw = page.model_dump(mode="python")
    raw["asset_directives"] = (
        page.asset_directives[0].model_copy(update={"directive_id": "asset-1"}),
        page.asset_directives[0].model_copy(update={"directive_id": "asset-1"}),
    )
    raw.pop("canonical_sha256")
    with pytest.raises(ValueError, match="asset|directive|canonical"):
        build_layout_program(
            PageBriefV4(**raw, canonical_sha256=canonical_sha256_v4(raw)),
            grammar_id="editorial_hero",
            family="pink_red",
            narrative_beat=_beat(page),
        )


def test_family_and_beat_are_required_and_external_token_payload_is_not_an_api() -> None:
    page = _page_brief()
    beat = _beat(page)
    assert "family_tokens" not in inspect.signature(build_layout_program).parameters
    with pytest.raises(TypeError):
        build_layout_program(page, grammar_id="editorial_hero", narrative_beat=beat)
    with pytest.raises(TypeError):
        build_layout_program(page, grammar_id="editorial_hero", family="pink_red")
    with pytest.raises(TypeError):
        build_layout_program(
            page,
            grammar_id="editorial_hero",
            family="pink_red",
            narrative_beat=beat,
            family_tokens=FAMILY_TOKENS["pink_red"],
        )


def test_family_density_is_a_hard_boundary() -> None:
    page = _page_brief(preferred=("comparison_grid",), density="medium")
    with pytest.raises(ValueError, match="density|envelope"):
        build_layout_program(
            page,
            grammar_id="comparison_grid",
            family="white_quote",
            narrative_beat=_beat(page, task_kind="comparison"),
        )


@pytest.mark.parametrize(
    ("grammar_id", "family", "density", "task_kind"),
    (
        ("editorial_hero", "pink_red", "medium", "cover_hook"),
        ("comparison_grid", "deep_teal", "medium", "comparison"),
        ("step_flow", "white_quote", "low", "step"),
    ),
)
def test_three_typed_grammar_paths_are_deterministic(
    grammar_id: str,
    family: str,
    density: str,
    task_kind: str,
) -> None:
    page = _page_brief(preferred=(grammar_id,), density=density)
    first = build_layout_program(
        page,
        grammar_id=grammar_id,
        family=family,
        narrative_beat=_beat(page, task_kind=task_kind),
    )
    second = build_layout_program(
        page,
        grammar_id=grammar_id,
        family=family,
        narrative_beat=_beat(page, task_kind=task_kind),
    )
    assert first.model_dump_json() == second.model_dump_json()


def test_free_form_page_role_does_not_override_typed_beat_role() -> None:
    page = _page_brief()
    program = build_layout_program(
        page,
        grammar_id="editorial_hero",
        family="pink_red",
        narrative_beat=_beat(page, task_kind="cover_hook"),
    )
    assert program.grammar_id == "editorial_hero"


def test_beat_identity_and_fragment_binding_are_revalidated() -> None:
    page = _page_brief()
    with pytest.raises(ValueError, match="beat_id"):
        build_layout_program(
            page,
            grammar_id="editorial_hero",
            family="pink_red",
            narrative_beat=_beat(page, beat_id="other"),
        )
    with pytest.raises(ValueError, match="fragment"):
        build_layout_program(
            page,
            grammar_id="editorial_hero",
            family="pink_red",
            narrative_beat=_beat(page, fragment_refs=("fragment-2",)),
        )
    stale = _beat(page).model_copy(update={"sequence": page.sequence + 1})
    with pytest.raises(ValueError, match="sequence"):
        build_layout_program(
            page,
            grammar_id="editorial_hero",
            family="pink_red",
            narrative_beat=stale,
        )


def test_visual_priority_controls_emphasis_and_reverse_bindings() -> None:
    page = _page_brief(
        fragment_refs=("fragment-1", "fragment-2", "fragment-3"),
        visual_priority=("fragment-2", "fragment-1"),
    )
    program = build_layout_program(
        page,
        grammar_id="editorial_hero",
        family="pink_red",
        narrative_beat=_beat(page),
    )
    assert tuple(rule.target_fragment_refs for rule in program.emphasis_rules) == (
        ("fragment-2",),
        ("fragment-1",),
    )
    assert tuple(rule.kind for rule in program.emphasis_rules) == (
        "primary_focus",
        "secondary_focus",
    )
    by_fragment = {item.fragment_ref: item.emphasis_rule_ids for item in program.fragment_placements}
    assert by_fragment["fragment-2"] == ("emphasis-0",)
    assert by_fragment["fragment-1"] == ("emphasis-1",)
    assert by_fragment["fragment-3"] == ()


def test_visual_priority_must_be_page_local_and_unique() -> None:
    page = _page_brief(visual_priority=("unknown",))
    with pytest.raises(ValueError, match="visual_priority"):
        build_layout_program(
            page,
            grammar_id="editorial_hero",
            family="pink_red",
            narrative_beat=_beat(page),
        )
    page = _page_brief(visual_priority=("fragment-1", "fragment-1"))
    with pytest.raises(ValueError, match="visual_priority"):
        build_layout_program(
            page,
            grammar_id="editorial_hero",
            family="pink_red",
            narrative_beat=_beat(page),
        )
