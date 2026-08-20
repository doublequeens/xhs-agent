from __future__ import annotations

from collections.abc import Mapping

import pytest

from src.nodes.v4.composition import build_layout_program
from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.v4.content import ContentAtomSetV4, ContentAtomV4, canonical_sha256_v4
from src.schemas.v4.direction import (
    AssetDirectiveV4,
    CarouselNarrativeV4,
    NarrativeBeatV4,
    PageBriefV4,
)
from src.schemas.v4.layout import LayoutProgramV4
from src.schemas.v4.semantic import SemanticContentModelV4, SemanticFragmentV4
from src.visual_design.v4.compiler import (
    COMPILATION_ERROR_CODES_V4,
    LayoutCompilationError,
    LayoutCompilerInputsV4,
    compile_layout,
)


def _atom_set(text: str = "这是一个可读的页面标题") -> ContentAtomSetV4:
    atom_payload = {
        "atom_id": "atom-1",
        "source_unit_id": "unit-1",
        "source_projection_sha256": "1" * 64,
        "source_field": "content",
        "raw_start": 0,
        "raw_end": len(text),
        "raw_slice_sha256": "2" * 64,
        "text": text,
        "role": "heading",
    }
    atom = ContentAtomV4(**atom_payload, sha256=canonical_sha256_v4(atom_payload))
    payload = {"projection_sha256": "1" * 64, "atoms": (atom,)}
    return ContentAtomSetV4(**payload, canonical_sha256=canonical_sha256_v4(payload))


def _semantic(atom_set: ContentAtomSetV4, text: str) -> SemanticContentModelV4:
    fragment = SemanticFragmentV4(
        fragment_id="fragment-1",
        source_atom_id="atom-1",
        start=0,
        end=len(text),
        exact_text=text,
        semantic_role="heading",
        sequence_index=0,
    )
    payload = {
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "fragments": (fragment,),
        "groups": (),
    }
    return SemanticContentModelV4(**payload, canonical_sha256=canonical_sha256_v4(payload))


def _page(
    *,
    grammar: str,
    task_kind: str,
    family: str = "pink_red",
    with_asset: bool = False,
) -> PageBriefV4:
    directives = ()
    if with_asset:
        directives = (
            AssetDirectiveV4(
                directive_id="directive-1",
                page_id="page-1",
                role="object",
                purpose="supporting",
                supports_fragment_refs=("fragment-1",),
                required=True,
                preferred_source="search",
                query_or_prompt="text-free supporting object",
                orientation="landscape",
            ),
        )
    payload = {
        "page_id": "page-1",
        "sequence": 1,
        "narrative_role": "typed role",
        "beat_ref": "beat-1",
        "fragment_refs": ("fragment-1",),
        "visual_priority": ("fragment-1",),
        "density_budget": "medium",
        "preferred_compositions": (grammar,),
        "forbidden_patterns": (),
        "asset_directives": directives,
        "continuity_with_previous": "none",
    }
    return PageBriefV4(**payload, canonical_sha256=canonical_sha256_v4(payload))


def _narrative(page: PageBriefV4, *, task_kind: str) -> CarouselNarrativeV4:
    beats = tuple(
        NarrativeBeatV4(
            beat_id=f"beat-{index}",
            sequence=index,
            task_kind=task_kind if index == 1 else "context",
            fragment_refs=page.fragment_refs,
            task="semantic task",
        )
        for index in range(1, 6)
    )
    payload = {
        "template_family": "pink_red",
        "page_count": 5,
        "beats": beats,
        "density_curve": ("medium",) * 5,
        "variation_strategy": "stable",
        "continuity_strategy": "stable",
        "art_direction": "editorial",
    }
    return CarouselNarrativeV4(**payload, canonical_sha256=canonical_sha256_v4(payload))


def _inputs(
    *,
    text: str = "这是一个可读的页面标题",
    min_body_font_px: int = 24,
    with_asset: bool = False,
    asset_security_status: str = "approved",
) -> tuple[LayoutProgramV4, LayoutCompilerInputsV4]:
    atom_set = _atom_set(text)
    semantic = _semantic(atom_set, text)
    page = _page(grammar="editorial_hero", task_kind="context", with_asset=with_asset)
    narrative = _narrative(page, task_kind="context")
    program = build_layout_program(
        page,
        grammar_id="editorial_hero",
        family="pink_red",
        narrative=narrative,
    )
    manifest = AssetManifest(items=())
    if with_asset:
        manifest = AssetManifest(
            items=(
                AssetManifestItem(
                    asset_id="asset-1",
                    directive_id="directive-1",
                    page_id="page-1",
                    source_kind="search",
                    provider="fixture-provider",
                    license="fixture-license",
                    local_path="/tmp/fixture.png",
                    width=1200,
                    height=800,
                    sha256="3" * 64,
                    subject_focal_point=(0.5, 0.5),
                    crop_guidance="center",
                    security_status=asset_security_status,
                    human_decision="pending",
                    run_id="run-1",
                    transaction_id="tx-1",
                    internal_provenance={"source": "fixture"},
                ),
            )
        )
    return program, LayoutCompilerInputsV4(
        page_brief=page,
        semantic_content_model=semantic,
        content_atom_set=atom_set,
        asset_manifest=manifest,
        min_body_font_px=min_body_font_px,
    )


def test_compiler_is_deterministic() -> None:
    program, inputs = _inputs()
    first = compile_layout(program, inputs)
    second = compile_layout(program, inputs)
    assert first.canonical_sha256 == second.canonical_sha256
    assert first.model_dump_json() == second.model_dump_json()


@pytest.mark.parametrize(
    ("grammar", "task_kind"),
    (("editorial_hero", "context"), ("comparison_grid", "comparison"), ("step_flow", "step")),
)
def test_each_implemented_grammar_returns_safe_flat_scene(
    grammar: str, task_kind: str
) -> None:
    atom_set = _atom_set()
    semantic = _semantic(atom_set, "这是一个可读的页面标题")
    page = _page(grammar=grammar, task_kind=task_kind)
    narrative = _narrative(page, task_kind=task_kind)
    program = build_layout_program(page, grammar_id=grammar, family="pink_red", narrative=narrative)
    result = compile_layout(
        program,
        LayoutCompilerInputsV4(
            page_brief=page,
            semantic_content_model=semantic,
            content_atom_set=atom_set,
            asset_manifest=AssetManifest(items=()),
        ),
    )
    assert result.scene.sequence == 1
    assert tuple(item.content_ref for item in result.scene.elements if item.kind == "text") == (
        "fragment-1",
    )
    for element in result.scene.elements:
        if element.kind in {"text", "image", "shape", "icon"}:
            assert element.box.x >= 80
            assert element.box.y >= 80
            assert element.box.x + element.box.width <= 1000
            assert element.box.y + element.box.height <= 1360


def test_compiler_never_shrinks_below_minimum_font() -> None:
    program, inputs = _inputs(text="非常长的文字" * 120, min_body_font_px=24)
    with pytest.raises(LayoutCompilationError) as exc:
        compile_layout(program, inputs)
    assert exc.value.code in COMPILATION_ERROR_CODES_V4
    assert exc.value.code == "DENSITY_EXCEEDED"


def test_stale_program_and_semantic_model_copy_are_revalidated() -> None:
    program, inputs = _inputs()
    stale_program = program.model_copy(update={"page_id": "other-page"})
    with pytest.raises(ValueError, match="program|page|canonical"):
        compile_layout(stale_program, inputs)
    stale_model = inputs.semantic_content_model.model_copy(update={"canonical_sha256": "0" * 64})
    with pytest.raises(ValueError, match="semantic|canonical"):
        compile_layout(
            program,
            inputs.model_copy(update={"semantic_content_model": stale_model}),
        )


def test_scene_payload_does_not_copy_asset_provider_or_local_path() -> None:
    program, inputs = _inputs()
    raw = inputs.model_dump(mode="json")
    assert "provider" not in str(raw)
    assert "local_path" not in str(raw)
    assert "provenance" not in str(raw)


def test_unapproved_or_unknown_asset_fails_before_scene_approval() -> None:
    program, inputs = _inputs(with_asset=True, asset_security_status="rejected")
    with pytest.raises(ValueError, match="asset|directive"):
        compile_layout(program, inputs)
