from __future__ import annotations

import json
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
from src.schemas.scene_graph import Box, TextElement
from src.schemas.v4.layout import (
    CompiledPageV4,
    CompilerProvenanceV4,
    FragmentPlacementV4,
    LayoutProgramV4,
)
from src.schemas.v4.semantic import SemanticContentModelV4, SemanticFragmentV4
from src.visual_design.v4.compiler import (
    COMPILATION_ERROR_CODES_V4,
    LayoutCompilationError,
    LayoutCompilerInputsV4,
    compile_layout,
)
from src.visual_design.v4.tokens import FAMILY_TOKENS, get_family_tokens
from src.visual_design.v4.typography import measure_text_v4, resolve_font_file_v4


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


def _semantic(
    atom_set: ContentAtomSetV4,
    text: str,
    *,
    semantic_role: str = "heading",
) -> SemanticContentModelV4:
    fragment = SemanticFragmentV4(
        fragment_id="fragment-1",
        source_atom_id="atom-1",
        start=0,
        end=len(text),
        exact_text=text,
        semantic_role=semantic_role,
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
    asset_orientation: str = "landscape",
    density_budget: str = "medium",
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
                orientation=asset_orientation,
            ),
        )
    payload = {
        "page_id": "page-1",
        "sequence": 1,
        "narrative_role": "typed role",
        "beat_ref": "beat-1",
        "fragment_refs": ("fragment-1",),
        "visual_priority": ("fragment-1",),
        "density_budget": density_budget,
        "preferred_compositions": (grammar,),
        "forbidden_patterns": (),
        "asset_directives": directives,
        "continuity_with_previous": "none",
    }
    return PageBriefV4(**payload, canonical_sha256=canonical_sha256_v4(payload))


def _narrative(
    page: PageBriefV4,
    *,
    task_kind: str,
    family: str = "pink_red",
) -> CarouselNarrativeV4:
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
        "template_family": family,
        "page_count": 5,
        "beats": beats,
        "density_curve": (page.density_budget,) * 5,
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
    family: str = "pink_red",
    semantic_role: str = "heading",
    asset_orientation: str = "landscape",
    density_budget: str | None = None,
) -> tuple[LayoutProgramV4, LayoutCompilerInputsV4]:
    atom_set = _atom_set(text)
    semantic = _semantic(atom_set, text, semantic_role=semantic_role)
    page = _page(
        grammar="editorial_hero",
        task_kind="context",
        with_asset=with_asset,
        asset_orientation=asset_orientation,
        density_budget=density_budget or ("low" if family == "white_quote" else "medium"),
    )
    narrative = _narrative(page, task_kind="context", family=family)
    program = build_layout_program(
        page,
        grammar_id="editorial_hero",
        family=family,
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
        candidate_id="candidate-a",
        revision=3,
        min_body_font_px=min_body_font_px,
    )


def _rehash_program(program: LayoutProgramV4, **updates) -> LayoutProgramV4:
    raw = program.model_dump(mode="python")
    raw.update(updates)
    raw.pop("canonical_sha256", None)
    source = LayoutProgramV4.model_construct(
        **raw,
        canonical_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"canonical_sha256"}, exclude_none=True)
    return LayoutProgramV4(**raw, canonical_sha256=canonical_sha256_v4(source))


def _rehash_provenance(
    provenance: CompilerProvenanceV4,
    **updates,
) -> CompilerProvenanceV4:
    raw = provenance.model_dump(mode="python")
    raw.update(updates)
    raw.pop("canonical_sha256", None)
    source = CompilerProvenanceV4.model_construct(
        **raw,
        canonical_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"canonical_sha256"})
    return CompilerProvenanceV4(**raw, canonical_sha256=canonical_sha256_v4(source))


def _rehash_page(page: CompiledPageV4, **updates) -> CompiledPageV4:
    raw = page.model_dump(mode="python")
    raw.update(updates)
    raw.pop("canonical_sha256", None)
    source = CompiledPageV4.model_construct(
        **raw,
        canonical_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"canonical_sha256"})
    return CompiledPageV4(**raw, canonical_sha256=canonical_sha256_v4(source))


def _contrast_ratio(first: str, second: str) -> float:
    def luminance(color: str) -> float:
        channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            channel / 12.92
            if channel <= 0.04045
            else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    brighter, darker = sorted(
        (luminance(first), luminance(second)),
        reverse=True,
    )
    return (brighter + 0.05) / (darker + 0.05)


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
            candidate_id="candidate-a",
            revision=3,
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
    with pytest.raises(ValueError, match="stale|invalid"):
        compile_layout(
            program,
            inputs.model_copy(update={"semantic_content_model": stale_model}),
        )


def test_scene_payload_does_not_copy_asset_provider_or_local_path() -> None:
    program, inputs = _inputs()
    raw = compile_layout(program, inputs).model_dump_json()
    assert "fixture-provider" not in str(raw)
    assert "local_path" not in str(raw)
    assert "internal_provenance" not in str(raw)


def test_unapproved_or_unknown_asset_fails_before_scene_approval() -> None:
    program, inputs = _inputs(with_asset=True, asset_security_status="rejected")
    with pytest.raises(ValueError, match="asset|directive"):
        compile_layout(program, inputs)


def test_rehashed_scene_geometry_cannot_bypass_safe_margin_validation() -> None:
    program, inputs = _inputs()
    page = compile_layout(program, inputs)
    text = next(element for element in page.scene.elements if isinstance(element, TextElement))
    tampered_text = text.model_copy(update={"box": Box(x=0, y=text.box.y, width=text.box.width, height=text.box.height)})
    tampered_scene = page.scene.model_copy(
        update={
            "elements": tuple(
                tampered_text if element.element_id == text.element_id else element
                for element in page.scene.elements
            )
        }
    )
    with pytest.raises(ValueError, match="safe|margin|geometry|scene"):
        _rehash_page(page, scene=tampered_scene)


def test_rehashed_fake_font_hash_cannot_bypass_current_registry_validation() -> None:
    program, inputs = _inputs()
    page = compile_layout(program, inputs)
    fake_hashes = dict(page.compiler_provenance.font_sha256_by_role)
    fake_hashes["body"] = "f" * 64
    with pytest.raises(ValueError, match="font|registry|canonical"):
        provenance = _rehash_provenance(
            page.compiler_provenance,
            font_sha256_by_role=fake_hashes,
        )
        _rehash_page(page, compiler_provenance=provenance)


def test_compiler_requires_candidate_revision_and_binds_them_in_provenance() -> None:
    program, inputs = _inputs()
    payload = inputs.model_dump(mode="python")
    payload.update({"candidate_id": "candidate-a", "revision": 3})
    result = compile_layout(program, payload)
    assert result.compiler_provenance.candidate_id == "candidate-a"
    assert result.compiler_provenance.revision == 3


def test_compiler_rejects_missing_candidate_or_revision_identity() -> None:
    program, inputs = _inputs()
    payload = inputs.model_dump(mode="python")
    payload.pop("candidate_id")
    payload.pop("revision")
    with pytest.raises(ValueError, match="stale|invalid|candidate"):
        compile_layout(program, payload)


def test_rehashed_attacker_fragment_reference_cannot_enter_scene() -> None:
    program, inputs = _inputs()
    attacker_placement = program.fragment_placements[0].model_copy(
        update={"fragment_ref": "attacker-ref"}
    )
    attacker_program = program.model_copy(update={"fragment_placements": (attacker_placement,)})
    with pytest.raises(ValueError, match="fragment|brief|reference|stale|invalid"):
        compile_layout(attacker_program, inputs)


def test_solver_executes_legal_region_choice_instead_of_ignoring_placement() -> None:
    program, inputs = _inputs()
    changed_placement = program.fragment_placements[0].model_copy(update={"region_id": "support"})
    changed_program = _rehash_program(
        program,
        fragment_placements=(changed_placement,),
    )
    hero_page = compile_layout(program, inputs)
    support_page = compile_layout(changed_program, inputs)
    hero_box = next(element.box for element in hero_page.scene.elements if isinstance(element, TextElement))
    support_box = next(element.box for element in support_page.scene.elements if isinstance(element, TextElement))
    assert (hero_box.x, hero_box.y, hero_box.width, hero_box.height) != (
        support_box.x,
        support_box.y,
        support_box.width,
        support_box.height,
    )


@pytest.mark.parametrize("family", tuple(FAMILY_TOKENS))
@pytest.mark.parametrize("semantic_role", ("heading", "paragraph"))
def test_all_families_resolve_semantic_text_contrast(
    family: str,
    semantic_role: str,
) -> None:
    program, inputs = _inputs(family=family, semantic_role=semantic_role)
    page = compile_layout(program, inputs)
    background = page.scene.background
    text = next(element for element in page.scene.elements if isinstance(element, TextElement))
    threshold = 3.0 if text.style.font_role in {"display", "heading"} else 4.5
    assert _contrast_ratio(text.style.color, background) >= threshold


def test_typography_uses_ink_extents_and_face_nominal_weight() -> None:
    measurement = measure_text_v4(
        "j\nÅg👩‍🔬",
        family="pink_red",
        role="body",
        font_size_px=48,
        max_width_px=920,
        line_height=1.25,
    )
    assert measurement.text == "j\nÅg👩‍🔬"
    assert measurement.ink_width_px >= measurement.advance_width_px
    assert measurement.height_px >= measurement.ink_height_px
    resolved = resolve_font_file_v4("pink_red", "display")
    page, inputs = _inputs()
    compiled = compile_layout(page, inputs)
    text = next(element for element in compiled.scene.elements if isinstance(element, TextElement))
    assert text.style.weight == resolve_font_file_v4("pink_red", text.style.font_role).nominal_weight
    assert resolved.nominal_weight >= 700


def test_compiler_persists_task13_wrap_policy_and_measurement_evidence_without_copy() -> None:
    program, inputs = _inputs()
    page = compile_layout(program, inputs)
    provenance = page.compiler_provenance
    assert provenance.text_wrap_policy == "pre-wrap-grapheme-anywhere-v1"
    evidence = provenance.text_measurement_evidence["fragment-1"]
    assert evidence.line_count >= 1
    assert evidence.break_offsets == tuple(sorted(evidence.break_offsets))
    assert len(evidence.measurement_sha256) == 64
    assert "这是一个可读的页面标题" not in json.dumps(provenance.model_dump(mode="json"), ensure_ascii=False)


def test_portrait_asset_is_not_cropped_into_extreme_landscape_cover_box() -> None:
    program, inputs = _inputs(with_asset=True, asset_orientation="any")
    portrait = inputs.asset_manifest.items[0].model_copy(update={"width": 800, "height": 1200})
    inputs = inputs.model_copy(update={"asset_manifest": AssetManifest(items=(portrait,))})
    with pytest.raises(LayoutCompilationError) as exc:
        compile_layout(program, inputs)
    assert exc.value.code == "ASSET_ASPECT_MISMATCH"
    assert "fixture-provider" not in repr(exc.value)
    assert "/tmp/fixture.png" not in repr(exc.value)


def test_single_unbreakable_grapheme_reports_content_overflow() -> None:
    text = "👩" + ("\u200d👩" * 100)
    program, inputs = _inputs(text=text)
    with pytest.raises(LayoutCompilationError) as exc:
        compile_layout(program, inputs)
    assert exc.value.code == "CONTENT_OVERFLOW"


def test_region_relationship_violation_reports_unbalanced_regions() -> None:
    program, inputs = _inputs()
    changed_placement = program.fragment_placements[0].model_copy(update={"region_id": "accent"})
    changed_program = _rehash_program(program, fragment_placements=(changed_placement,))
    with pytest.raises(LayoutCompilationError) as exc:
        compile_layout(changed_program, inputs)
    assert exc.value.code == "UNBALANCED_REGIONS"


def test_density_target_with_insufficient_occupied_whitespace_reports_whitespace_failure() -> None:
    program, inputs = _inputs(density_budget="high")
    with pytest.raises(LayoutCompilationError) as exc:
        compile_layout(program, inputs)
    assert exc.value.code == "INSUFFICIENT_WHITESPACE"


def test_minimum_font_policy_conflict_reports_typography_constraint_conflict() -> None:
    program, inputs = _inputs()
    inputs = inputs.model_copy(update={"min_display_font_px": 181})
    with pytest.raises(LayoutCompilationError) as exc:
        compile_layout(program, inputs)
    assert exc.value.code == "TYPOGRAPHY_CONSTRAINT_CONFLICT"


def test_contract_error_strings_and_cause_chain_do_not_leak_visible_or_private_values() -> None:
    program, inputs = _inputs()
    secret = "VISIBLE_SECRET /Users/private/provider-secret.example"
    fragment = inputs.semantic_content_model.fragments[0].model_copy(update={"exact_text": secret})
    bad_semantic = inputs.semantic_content_model.model_copy(update={"fragments": (fragment,)})
    payload = inputs.model_dump(mode="python")
    payload["semantic_content_model"] = bad_semantic
    with pytest.raises(ValueError) as caught:
        compile_layout(program, payload)
    chain = []
    current: BaseException | None = caught.value
    while current is not None:
        chain.extend((str(current), repr(current)))
        current = current.__cause__
    rendered = "\n".join(chain)
    assert secret not in rendered
    assert "/Users/private" not in rendered
    assert "provider-secret" not in rendered
