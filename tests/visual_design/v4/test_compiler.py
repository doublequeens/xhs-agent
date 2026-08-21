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
    PageBriefSetV4,
    PageBriefV4,
    VisualDirectionPlanV4,
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
    narrative_payload = narrative.model_dump(mode="python")
    narrative_payload["content_atom_set_sha256"] = atom_set.canonical_sha256
    narrative_payload.pop("canonical_sha256", None)
    narrative = CarouselNarrativeV4(
        **narrative_payload,
        canonical_sha256=canonical_sha256_v4(narrative_payload),
    )
    page_briefs = [page]
    for sequence in range(2, 6):
        page_payload = page.model_dump(mode="python")
        page_payload.update({"page_id": f"page-{sequence}", "sequence": sequence, "beat_ref": f"beat-{sequence}"})
        page_payload.pop("canonical_sha256", None)
        page_briefs.append(PageBriefV4(**page_payload, canonical_sha256=canonical_sha256_v4(page_payload)))
    page_set_payload = {
        "page_count": 5,
        "pages": tuple(page_briefs),
        "template_family": family,
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "semantic_content_model_sha256": semantic.canonical_sha256,
    }
    page_set = PageBriefSetV4(
        **page_set_payload,
        canonical_sha256=canonical_sha256_v4(page_set_payload),
    )
    direction_payload = {
        "semantic_content_model": semantic,
        "narrative": narrative,
        "page_brief_set": page_set,
        "template_family": family,
        "page_count": 5,
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "semantic_content_model_sha256": semantic.canonical_sha256,
        "narrative_sha256": narrative.canonical_sha256,
        "page_brief_set_sha256": page_set.canonical_sha256,
    }
    direction_plan = VisualDirectionPlanV4(
        **direction_payload,
        canonical_sha256=canonical_sha256_v4(direction_payload),
    )
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
        run_id="run-a",
        visual_direction_plan=direction_plan,
        min_body_font_px=min_body_font_px,
    )


def _direction_plan_for(
    page: PageBriefV4,
    semantic: SemanticContentModelV4,
    atom_set: ContentAtomSetV4,
    narrative: CarouselNarrativeV4,
    family: str,
) -> VisualDirectionPlanV4:
    narrative_payload = narrative.model_dump(mode="python")
    narrative_payload["content_atom_set_sha256"] = atom_set.canonical_sha256
    narrative_payload.pop("canonical_sha256", None)
    checked_narrative = CarouselNarrativeV4(
        **narrative_payload,
        canonical_sha256=canonical_sha256_v4(narrative_payload),
    )
    page_briefs = [page]
    for sequence in range(2, 6):
        page_payload = page.model_dump(mode="python")
        page_payload.update({"page_id": f"page-{sequence}", "sequence": sequence, "beat_ref": f"beat-{sequence}"})
        page_payload.pop("canonical_sha256", None)
        page_briefs.append(PageBriefV4(**page_payload, canonical_sha256=canonical_sha256_v4(page_payload)))
    page_set_payload = {
        "page_count": 5,
        "pages": tuple(page_briefs),
        "template_family": family,
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "semantic_content_model_sha256": semantic.canonical_sha256,
    }
    page_set = PageBriefSetV4(
        **page_set_payload,
        canonical_sha256=canonical_sha256_v4(page_set_payload),
    )
    direction_payload = {
        "semantic_content_model": semantic,
        "narrative": checked_narrative,
        "page_brief_set": page_set,
        "template_family": family,
        "page_count": 5,
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "semantic_content_model_sha256": semantic.canonical_sha256,
        "narrative_sha256": checked_narrative.canonical_sha256,
        "page_brief_set_sha256": page_set.canonical_sha256,
    }
    return VisualDirectionPlanV4(
        **direction_payload,
        canonical_sha256=canonical_sha256_v4(direction_payload),
    )


def _rehash_program(program: LayoutProgramV4, **updates) -> LayoutProgramV4:
    raw = program.model_dump(mode="python")
    raw.update(updates)
    raw.pop("canonical_sha256", None)
    source = {key: value for key, value in raw.items() if value is not None}
    return LayoutProgramV4(**raw, canonical_sha256=canonical_sha256_v4(source))


def _rehash_provenance(
    provenance: CompilerProvenanceV4,
    **updates,
) -> CompilerProvenanceV4:
    raw = provenance.model_dump(mode="python")
    raw.update(updates)
    raw.pop("canonical_sha256", None)
    source = dict(raw)
    return CompilerProvenanceV4(**raw, canonical_sha256=canonical_sha256_v4(source))


def _comparison_inputs_for_test(
    *,
    with_asset: bool = False,
) -> tuple[LayoutProgramV4, LayoutCompilerInputsV4]:
    texts = ("对比标题", "左侧现象", "右侧现象")
    atoms = []
    fragments = []
    for index, text in enumerate(texts, start=1):
        atom_payload = {
            "atom_id": f"comparison-atom-{index}",
            "source_unit_id": f"comparison-unit-{index}",
            "source_projection_sha256": "1" * 64,
            "source_field": "content",
            "raw_start": 0,
            "raw_end": len(text),
            "raw_slice_sha256": "2" * 64,
            "text": text,
            "role": "heading" if index == 1 else "paragraph",
        }
        atoms.append(ContentAtomV4(**atom_payload, sha256=canonical_sha256_v4(atom_payload)))
        fragments.append(
            SemanticFragmentV4(
                fragment_id=f"comparison-fragment-{index}",
                source_atom_id=f"comparison-atom-{index}",
                start=0,
                end=len(text),
                exact_text=text,
                semantic_role="heading" if index == 1 else "paragraph",
                sequence_index=index - 1,
            )
        )
    atom_set_payload = {"projection_sha256": "1" * 64, "atoms": tuple(atoms)}
    atom_set = ContentAtomSetV4(
        **atom_set_payload,
        canonical_sha256=canonical_sha256_v4(atom_set_payload),
    )
    semantic_payload = {
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "fragments": tuple(fragments),
        "groups": (),
    }
    semantic = SemanticContentModelV4(
        **semantic_payload,
        canonical_sha256=canonical_sha256_v4(semantic_payload),
    )
    refs = tuple(fragment.fragment_id for fragment in fragments)
    directives = (
        AssetDirectiveV4(
            directive_id="comparison-directive-1",
            page_id="comparison-page",
            role="object",
            purpose="supporting",
            supports_fragment_refs=(refs[0],),
            required=True,
            preferred_source="search",
            query_or_prompt="text-free comparison support object",
            orientation="landscape",
        ),
    ) if with_asset else ()
    page_payload = {
        "page_id": "comparison-page",
        "sequence": 1,
        "narrative_role": "comparison role",
        "beat_ref": "comparison-beat-1",
        "fragment_refs": refs,
        "visual_priority": (refs[0],),
        "density_budget": "medium",
        "preferred_compositions": ("comparison_grid",),
        "forbidden_patterns": (),
        "asset_directives": directives,
        "continuity_with_previous": "none",
    }
    page = PageBriefV4(**page_payload, canonical_sha256=canonical_sha256_v4(page_payload))
    beats = tuple(
        NarrativeBeatV4(
            beat_id=f"comparison-beat-{index}",
            sequence=index,
            task_kind="diagnosis",
            fragment_refs=refs,
            task="comparison task",
        )
        for index in range(1, 6)
    )
    narrative_payload = {
        "template_family": "pink_red",
        "page_count": 5,
        "beats": beats,
        "density_curve": ("medium",) * 5,
        "variation_strategy": "stable",
        "continuity_strategy": "stable",
        "art_direction": "editorial",
        "content_atom_set_sha256": atom_set.canonical_sha256,
    }
    narrative = CarouselNarrativeV4(
        **narrative_payload,
        canonical_sha256=canonical_sha256_v4(narrative_payload),
    )
    direction_plan = _direction_plan_for(page, semantic, atom_set, narrative, "pink_red")
    program = build_layout_program(
        page,
        grammar_id="comparison_grid",
        family="pink_red",
        narrative=direction_plan.narrative,
    )
    manifest = AssetManifest(items=())
    if with_asset:
        manifest = AssetManifest(
            items=(
                AssetManifestItem(
                    asset_id="resolver-production-secret-comparison",
                    directive_id="comparison-directive-1",
                    page_id="comparison-page",
                    source_kind="search",
                    provider="resolver-secret-provider",
                    license="resolver-secret-license",
                    local_path="/private/resolver/secret-comparison.png",
                    width=1200,
                    height=800,
                    sha256="4" * 64,
                    subject_focal_point=(0.5, 0.5),
                    crop_guidance="center",
                    security_status="approved",
                    human_decision="pending",
                    run_id="run-comparison",
                    transaction_id="tx-comparison",
                    internal_provenance={"provider_path": "resolver-secret"},
                ),
            )
        )
    return program, LayoutCompilerInputsV4(
        page_brief=page,
        semantic_content_model=semantic,
        content_atom_set=atom_set,
        asset_manifest=manifest,
        candidate_id="candidate-comparison",
        revision=1,
        run_id="run-comparison",
        visual_direction_plan=direction_plan,
    )


def _rehash_page(page: CompiledPageV4, **updates) -> CompiledPageV4:
    raw = page.model_dump(mode="python")
    raw.update(updates)
    raw.pop("canonical_sha256", None)
    source = {key: value for key, value in raw.items() if value is not None}
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
    if grammar == "comparison_grid":
        program, compiler_inputs = _comparison_inputs_for_test()
    else:
        atom_set = _atom_set()
        semantic = _semantic(atom_set, "这是一个可读的页面标题")
        page = _page(grammar=grammar, task_kind=task_kind)
        narrative = _narrative(page, task_kind=task_kind)
        direction_plan = _direction_plan_for(page, semantic, atom_set, narrative, "pink_red")
        program = build_layout_program(
            page,
            grammar_id=grammar,
            family="pink_red",
            narrative=direction_plan.narrative,
        )
        compiler_inputs = LayoutCompilerInputsV4(
            page_brief=page,
            semantic_content_model=semantic,
            content_atom_set=atom_set,
            asset_manifest=AssetManifest(items=()),
            candidate_id="candidate-a",
            revision=3,
            run_id="run-a",
            visual_direction_plan=direction_plan,
        )
    result = compile_layout(
        program,
        compiler_inputs,
    )
    assert result.scene.sequence == 1
    assert tuple(item.content_ref for item in result.scene.elements if item.kind == "text") == tuple(
        item.fragment_ref for item in program.fragment_placements
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
    with pytest.raises(LayoutCompilationError) as exc:
        compile_layout(changed_program, inputs)
    assert exc.value.code == "UNBALANCED_REGIONS"


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


def test_display_bearings_are_safe_at_88px_for_j_and_ringed_letters() -> None:
    program, inputs = _inputs(text="j\nÅg", semantic_role="heading")
    compiled = compile_layout(program, inputs)
    element = next(item for item in compiled.scene.elements if isinstance(item, TextElement))
    evidence = compiled.compiler_provenance.text_measurement_evidence[element.content_ref]
    assert element.box.x == 80
    assert element.box.y == 100
    assert element.box.width == 920
    assert element.box.x + evidence.content_inset_left_px + evidence.painted_offset_x_px + evidence.painted_left_px >= 80
    assert element.box.x + evidence.content_inset_left_px + evidence.painted_offset_x_px + evidence.painted_right_px <= 1000
    assert element.box.y + evidence.content_inset_top_px + evidence.painted_offset_y_px + evidence.painted_top_px >= 80
    assert element.box.y + evidence.content_inset_top_px + evidence.painted_offset_y_px + evidence.painted_bottom_px <= 1360


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
    compiled = compile_layout(program, inputs)
    image = next(element for element in compiled.scene.elements if element.kind == "image")
    assert image.fit == "contain"
    assert "fixture-provider" not in compiled.model_dump_json()
    assert "/tmp/fixture.png" not in compiled.model_dump_json()


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
    program, inputs = _inputs(family="white_quote", with_asset=True, asset_orientation="landscape")
    with pytest.raises(LayoutCompilationError) as exc:
        compile_layout(program, inputs)
    assert exc.value.code == "INSUFFICIENT_WHITESPACE"
    assert "actual_whitespace=" in exc.value.evidence
    assert "minimum_whitespace=" in exc.value.evidence


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


def test_public_compile_requires_direction_plan_and_run_identity() -> None:
    program, inputs = _inputs()
    payload = inputs.model_dump(mode="python")
    payload.pop("visual_direction_plan")
    payload.pop("run_id")
    with pytest.raises(ValueError, match="direction|plan|run|invalid"):
        compile_layout(program, payload)


def test_provenance_policy_values_are_fixed_not_only_well_formed() -> None:
    program, inputs = _inputs()
    page = compile_layout(program, inputs)
    raw = page.compiler_provenance.model_dump(mode="json")
    raw.update(
        {
            "contrast_policy_version": "attacker-policy-v1",
            "accessibility_ink": "#ABCDEF",
        }
    )
    raw.pop("canonical_sha256")
    with pytest.raises(ValueError, match="contrast|accessibility|policy|canonical"):
        CompilerProvenanceV4(**raw, canonical_sha256=canonical_sha256_v4(raw))


def test_provenance_evidence_and_font_maps_are_deeply_immutable() -> None:
    program, inputs = _inputs(with_asset=True)
    page = compile_layout(program, inputs)
    provenance = page.compiler_provenance
    with pytest.raises(TypeError):
        provenance.font_sha256_by_role["body"] = "f" * 64
    with pytest.raises((TypeError, AttributeError)):
        provenance.text_measurement_evidence.pop("fragment-1")
    with pytest.raises((TypeError, AttributeError)):
        provenance.asset_binding_evidence["directive-1"] = None
    with pytest.raises((TypeError, AttributeError)):
        provenance.region_geometry_evidence.pop("hero")
    with pytest.raises((TypeError, AttributeError)):
        provenance.element_region_bindings["v4-text-fragment-1-0"] = "accent"
    assert page.canonical_sha256 == _rehash_page(page).canonical_sha256


def test_provenance_records_hash_bound_region_geometry_evidence() -> None:
    program, inputs = _inputs()
    page = compile_layout(program, inputs)
    evidence = page.compiler_provenance.region_geometry_evidence
    assert set(evidence) == {"hero", "support", "accent"}
    assert all(item.width > 0 and item.height > 0 for item in evidence.values())
    assert all("这是一个可读的页面标题" not in item.model_dump_json() for item in evidence.values())


def test_editorial_primary_visual_priority_must_remain_in_hero() -> None:
    program, inputs = _inputs()
    changed_placement = program.fragment_placements[0].model_copy(update={"region_id": "support"})
    changed_program = _rehash_program(program, fragment_placements=(changed_placement,))
    with pytest.raises(LayoutCompilationError) as exc:
        compile_layout(changed_program, inputs)
    assert exc.value.code == "UNBALANCED_REGIONS"


def test_portrait_asset_uses_contain_when_cover_crop_would_be_extreme() -> None:
    program, inputs = _inputs(with_asset=True, asset_orientation="any")
    portrait = inputs.asset_manifest.items[0].model_copy(update={"width": 800, "height": 1200})
    compiled = compile_layout(
        program,
        inputs.model_copy(update={"asset_manifest": AssetManifest(items=(portrait,))}),
    )
    image = next(element for element in compiled.scene.elements if element.kind == "image")
    assert image.fit == "contain"
    assert compiled.compiler_provenance.asset_binding_evidence["directive-1"].fit == "contain"


def test_intrinsic_asset_orientation_conflict_remains_aspect_failure() -> None:
    program, inputs = _inputs(with_asset=True, asset_orientation="landscape")
    portrait = inputs.asset_manifest.items[0].model_copy(update={"width": 800, "height": 1200})
    with pytest.raises(LayoutCompilationError) as exc:
        compile_layout(
            program,
            inputs.model_copy(update={"asset_manifest": AssetManifest(items=(portrait,))}),
        )
    assert exc.value.code == "ASSET_ASPECT_MISMATCH"


def test_high_density_underfill_is_not_misclassified_as_insufficient_whitespace() -> None:
    program, inputs = _inputs(density_budget="high")
    compiled = compile_layout(program, inputs)
    assert compiled.scene.elements


def _many_fragment_inputs(
    count: int,
    *,
    with_asset: bool = False,
) -> tuple[LayoutProgramV4, LayoutCompilerInputsV4]:
    pieces = ("步骤标题", "第一步", "第二步", "第三步", "第四步")[:count]
    text = "".join(pieces)
    atom_payload = {
        "atom_id": "atom-steps",
        "source_unit_id": "unit-steps",
        "source_projection_sha256": "1" * 64,
        "source_field": "content",
        "raw_start": 0,
        "raw_end": len(text),
        "raw_slice_sha256": "2" * 64,
        "text": text,
        "role": "paragraph",
    }
    atom = ContentAtomV4(**atom_payload, sha256=canonical_sha256_v4(atom_payload))
    atom_set_payload = {"projection_sha256": "1" * 64, "atoms": (atom,)}
    atom_set = ContentAtomSetV4(**atom_set_payload, canonical_sha256=canonical_sha256_v4(atom_set_payload))
    fragments = []
    cursor = 0
    for index, piece in enumerate(pieces):
        fragments.append(
            SemanticFragmentV4(
                fragment_id=f"step-fragment-{index}",
                source_atom_id="atom-steps",
                start=cursor,
                end=cursor + len(piece),
                exact_text=piece,
                semantic_role="heading" if index == 0 else "paragraph",
                sequence_index=index,
            )
        )
        cursor += len(piece)
    semantic_payload = {
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "fragments": tuple(fragments),
        "groups": (),
    }
    semantic = SemanticContentModelV4(**semantic_payload, canonical_sha256=canonical_sha256_v4(semantic_payload))
    refs = tuple(fragment.fragment_id for fragment in fragments)
    directives = (
        AssetDirectiveV4(
            directive_id="steps-directive-1",
            page_id="steps-page",
            role="object",
            purpose="supporting",
            supports_fragment_refs=(refs[0],),
            required=True,
            preferred_source="search",
            query_or_prompt="text-free step support object",
            orientation="landscape",
        ),
    ) if with_asset else ()
    page_payload = {
        "page_id": "steps-page",
        "sequence": 1,
        "narrative_role": "typed role",
        "beat_ref": "steps-beat-1",
        "fragment_refs": refs,
        "visual_priority": (refs[0],),
        "density_budget": "medium",
        "preferred_compositions": ("step_flow",),
        "forbidden_patterns": (),
        "asset_directives": directives,
        "continuity_with_previous": "none",
    }
    page = PageBriefV4(**page_payload, canonical_sha256=canonical_sha256_v4(page_payload))
    beats = tuple(
        NarrativeBeatV4(
            beat_id=f"steps-beat-{index}",
            sequence=index,
            task_kind="step",
            fragment_refs=refs,
            task="ordered steps",
        )
        for index in range(1, 6)
    )
    narrative_payload = {
        "template_family": "pink_red",
        "page_count": 5,
        "beats": beats,
        "density_curve": ("medium",) * 5,
        "variation_strategy": "stable",
        "continuity_strategy": "stable",
        "art_direction": "editorial",
        "content_atom_set_sha256": atom_set.canonical_sha256,
    }
    checked_narrative = CarouselNarrativeV4(
        **narrative_payload,
        canonical_sha256=canonical_sha256_v4(narrative_payload),
    )
    program = build_layout_program(page, grammar_id="step_flow", family="pink_red", narrative=checked_narrative)
    direction_plan = _direction_plan_for(
        page,
        semantic,
        atom_set,
        checked_narrative,
        "pink_red",
    )
    manifest = AssetManifest(items=())
    if with_asset:
        manifest = AssetManifest(
            items=(
                AssetManifestItem(
                    asset_id="resolver-production-secret-steps",
                    directive_id="steps-directive-1",
                    page_id="steps-page",
                    source_kind="search",
                    provider="resolver-secret-provider",
                    license="resolver-secret-license",
                    local_path="/private/resolver/secret-steps.png",
                    width=1200,
                    height=800,
                    sha256="5" * 64,
                    subject_focal_point=(0.5, 0.5),
                    crop_guidance="center",
                    security_status="approved",
                    human_decision="pending",
                    run_id="run-steps",
                    transaction_id="tx-steps",
                    internal_provenance={"provider_path": "resolver-secret"},
                ),
            )
        )
    return program, LayoutCompilerInputsV4(
        page_brief=page,
        semantic_content_model=semantic,
        content_atom_set=atom_set,
        asset_manifest=manifest,
        candidate_id="candidate-steps",
        revision=1,
        run_id="run-steps",
        visual_direction_plan=direction_plan,
    )


@pytest.mark.parametrize("count", (3, 5))
def test_step_flow_allocates_three_and_five_fragment_pages_without_overlap(count: int) -> None:
    program, inputs = _many_fragment_inputs(count)
    compiled = compile_layout(program, inputs)
    sequence_count = sum(item.region_id == "sequence" for item in program.fragment_placements)
    assert sum(element.kind == "icon" for element in compiled.scene.elements) == sequence_count


def test_solver_region_choice_changes_compiled_geometry() -> None:
    program, inputs = _many_fragment_inputs(3)
    baseline = compile_layout(program, inputs)
    changed_placement = program.fragment_placements[0].model_copy(update={"region_id": "support"})
    changed_program = _rehash_program(
        program,
        fragment_placements=(changed_placement, *program.fragment_placements[1:]),
    )
    changed = compile_layout(changed_program, inputs)
    baseline_text = next(element for element in baseline.scene.elements if element.kind == "text")
    changed_text = next(element for element in changed.scene.elements if element.kind == "text")
    assert (changed_text.box.x, changed_text.box.y) != (baseline_text.box.x, baseline_text.box.y)


def test_comparison_heading_only_program_is_not_a_vacuous_pair() -> None:
    atom_set = _atom_set()
    semantic = _semantic(atom_set, "这是一个可读的页面标题")
    page = _page(grammar="comparison_grid", task_kind="diagnosis")
    narrative = _narrative(page, task_kind="diagnosis")
    direction_plan = _direction_plan_for(page, semantic, atom_set, narrative, "pink_red")
    program = build_layout_program(
        page,
        grammar_id="comparison_grid",
        family="pink_red",
        narrative=direction_plan.narrative,
    )
    with pytest.raises(LayoutCompilationError) as exc:
        compile_layout(
            program,
            LayoutCompilerInputsV4(
                page_brief=page,
                semantic_content_model=semantic,
                content_atom_set=atom_set,
                asset_manifest=AssetManifest(items=()),
                candidate_id="candidate-a",
                revision=3,
                run_id="run-a",
                visual_direction_plan=direction_plan,
            ),
        )
    assert exc.value.code == "UNBALANCED_REGIONS"


def test_negative_bearing_uses_inset_evidence_without_moving_reserved_box() -> None:
    program, inputs = _inputs(text="j\nÅg", semantic_role="heading")
    compiled = compile_layout(program, inputs)
    element = next(item for item in compiled.scene.elements if isinstance(item, TextElement))
    evidence = compiled.compiler_provenance.text_measurement_evidence[element.content_ref]
    assert element.box.x == 80
    assert element.box.width == 920
    assert evidence.content_inset_left_px > 0
    assert evidence.painted_offset_x_px == 0
    assert evidence.painted_left_px <= 0
    assert evidence.painted_right_px >= evidence.painted_left_px


def test_combining_mark_keeps_exact_text_and_painted_bounds_safe() -> None:
    text = "e\u0301"
    measurement = measure_text_v4(
        text,
        family="pink_red",
        role="heading",
        font_size_px=64,
        max_width_px=920,
        line_height=1.15,
    )
    assert measurement.text == text
    assert measurement.lines == (text,)
    program, inputs = _inputs(text=text, semantic_role="heading")
    compiled = compile_layout(program, inputs)
    element = next(item for item in compiled.scene.elements if isinstance(item, TextElement))
    evidence = compiled.compiler_provenance.text_measurement_evidence[element.content_ref]
    painted_left = element.box.x + evidence.content_inset_left_px + evidence.painted_offset_x_px + evidence.painted_left_px
    painted_right = element.box.x + evidence.content_inset_left_px + evidence.painted_offset_x_px + evidence.painted_right_px
    assert painted_left >= 80
    assert painted_right <= 1000


def test_asset_binding_uses_versioned_opaque_ref_not_manifest_asset_id() -> None:
    program, inputs = _inputs(with_asset=True)
    compiled = compile_layout(program, inputs)
    image = next(element for element in compiled.scene.elements if element.kind == "image")
    evidence = compiled.compiler_provenance.asset_binding_evidence["directive-1"]
    assert image.asset_ref != inputs.asset_manifest.items[0].asset_id
    assert image.asset_ref.startswith("v4-asset-")
    assert evidence.asset_ref == image.asset_ref
    assert evidence.page_id == "page-1"
    assert "asset_id" not in evidence.model_dump(mode="json")
    assert "fixture-provider" not in compiled.model_dump_json()


def test_rehashed_asset_digest_cannot_break_opaque_reference_binding() -> None:
    program, inputs = _inputs(with_asset=True)
    compiled = compile_layout(program, inputs)
    evidence = dict(compiled.compiler_provenance.asset_binding_evidence)
    evidence["directive-1"] = evidence["directive-1"].model_copy(
        update={"asset_sha256": "4" * 64},
    )
    provenance = _rehash_provenance(
        compiled.compiler_provenance,
        asset_binding_evidence=evidence,
    )
    with pytest.raises(ValueError, match="opaque|asset|evidence"):
        _rehash_page(compiled, compiler_provenance=provenance)


def test_compiled_elements_are_deep_bound_to_regions_and_asset_lane_is_contained() -> None:
    program, inputs = _inputs(with_asset=True)
    compiled = compile_layout(program, inputs)
    provenance = compiled.compiler_provenance
    bindings = provenance.element_region_bindings
    assert set(bindings) == {element.element_id for element in compiled.scene.elements}
    for element in compiled.scene.elements:
        region = provenance.region_geometry_evidence[bindings[element.element_id]]
        assert element.box.x >= region.x
        assert element.box.y >= region.y
        assert element.box.x + element.box.width <= region.x + region.width
        assert element.box.y + element.box.height <= region.y + region.height
    image = next(element for element in compiled.scene.elements if element.kind == "image")
    assert bindings[image.element_id] == "support"
    assert image.box.y + image.box.height <= provenance.region_geometry_evidence["support"].y + provenance.region_geometry_evidence["support"].height


def test_rehashed_region_binding_cannot_hide_region_geometry_contradiction() -> None:
    program, inputs = _inputs(with_asset=True)
    compiled = compile_layout(program, inputs)
    text = next(element for element in compiled.scene.elements if isinstance(element, TextElement))
    bindings = dict(compiled.compiler_provenance.element_region_bindings)
    bindings[text.element_id] = "accent"
    provenance = _rehash_provenance(
        compiled.compiler_provenance,
        element_region_bindings=bindings,
    )
    with pytest.raises(ValueError, match="region|geometry|bound"):
        _rehash_page(compiled, compiler_provenance=provenance)


@pytest.mark.parametrize("grammar", ("editorial_hero", "comparison_grid", "step_flow"))
def test_all_grammars_compile_normal_asset_and_text_paths_with_opaque_bindings(
    grammar: str,
) -> None:
    if grammar == "editorial_hero":
        program, inputs = _inputs(with_asset=True)
    elif grammar == "comparison_grid":
        program, inputs = _comparison_inputs_for_test(with_asset=True)
    else:
        program, inputs = _many_fragment_inputs(3, with_asset=True)

    compiled = compile_layout(program, inputs)
    rendered = compiled.model_dump_json()
    assert "resolver-production-secret" not in rendered
    assert "resolver-secret-provider" not in rendered
    assert "/private/resolver" not in rendered
    images = [element for element in compiled.scene.elements if element.kind == "image"]
    assert len(images) == len(program.asset_placements) == 1
    for image in images:
        region_id = compiled.compiler_provenance.element_region_bindings[image.element_id]
        placement = program.asset_placements[0]
        assert region_id == placement.region_id
        assert image.asset_ref.startswith("v4-asset-")
        evidence = compiled.compiler_provenance.asset_binding_evidence[placement.directive_id]
        assert evidence.asset_ref == image.asset_ref
        assert evidence.region_id == region_id
