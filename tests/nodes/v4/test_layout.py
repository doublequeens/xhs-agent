from __future__ import annotations

import pytest

from src.nodes.v4.composition import build_layout_program
from src.nodes.v4.layout import aggregate_layout_plan, layout_node
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
from src.schemas.v4.layout import CompiledPageV4, CompilerProvenanceV4
from src.schemas.v4.semantic import SemanticContentModelV4, SemanticFragmentV4
from src.visual_design.v4.compiler import LayoutCompilerInputsV4, compile_layout
from src.visual_design.v4.tokens import get_family_tokens


def _legacy_upstream(page_count: int = 5):
    atom_payload = {
        "atom_id": "atom-1",
        "source_unit_id": "unit-1",
        "source_projection_sha256": "1" * 64,
        "source_field": "content",
        "raw_start": 0,
        "raw_end": 4,
        "raw_slice_sha256": "2" * 64,
        "text": "页面标题",
        "role": "heading",
    }
    atom = ContentAtomV4(**atom_payload, sha256=canonical_sha256_v4(atom_payload))
    atom_payload_set = {"projection_sha256": "1" * 64, "atoms": (atom,)}
    atom_set = ContentAtomSetV4(**atom_payload_set, canonical_sha256=canonical_sha256_v4(atom_payload_set))
    fragment = SemanticFragmentV4(
        fragment_id="fragment-1",
        source_atom_id="atom-1",
        start=0,
        end=4,
        exact_text="页面标题",
        semantic_role="heading",
        sequence_index=0,
    )
    semantic_payload = {
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "fragments": (fragment,),
        "groups": (),
    }
    semantic = SemanticContentModelV4(
        **semantic_payload,
        canonical_sha256=canonical_sha256_v4(semantic_payload),
    )
    pages = []
    beats = []
    for sequence in range(1, page_count + 1):
        page_payload = {
            "page_id": f"page-{sequence}",
            "sequence": sequence,
            "narrative_role": "typed role",
            "beat_ref": f"beat-{sequence}",
            "fragment_refs": ("fragment-1",),
            "visual_priority": ("fragment-1",),
            "density_budget": "medium",
            "preferred_compositions": ("editorial_hero",),
            "forbidden_patterns": (),
            "asset_directives": (),
            "continuity_with_previous": "none",
        }
        pages.append(PageBriefV4(**page_payload, canonical_sha256=canonical_sha256_v4(page_payload)))
        beats.append(
            NarrativeBeatV4(
                beat_id=f"beat-{sequence}",
                sequence=sequence,
                task_kind="context",
                fragment_refs=("fragment-1",),
                task="semantic task",
            )
        )
    page_set_payload = {
        "page_count": page_count,
        "pages": tuple(pages),
        "template_family": "pink_red",
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "semantic_content_model_sha256": semantic.canonical_sha256,
    }
    page_set = PageBriefSetV4(
        **page_set_payload,
        canonical_sha256=canonical_sha256_v4(page_set_payload),
    )
    narrative_payload = {
        "template_family": "pink_red",
        "page_count": page_count,
        "beats": tuple(beats),
        "density_curve": ("medium",) * page_count,
        "variation_strategy": "stable",
        "continuity_strategy": "stable",
        "art_direction": "editorial",
    }
    narrative = CarouselNarrativeV4(
        **narrative_payload,
        canonical_sha256=canonical_sha256_v4(narrative_payload),
    )
    compiled_pages = []
    for page in pages:
        program = build_layout_program(
            page,
            grammar_id="editorial_hero",
            family="pink_red",
            narrative=narrative,
        )
        compiled_pages.append(
            compile_layout(
                program,
                LayoutCompilerInputsV4(
                    page_brief=page,
                    semantic_content_model=semantic,
                    content_atom_set=atom_set,
                    asset_manifest=AssetManifest(items=()),
                    candidate_id="candidate-a",
                    revision=0,
                ),
            )
        )
    return atom_set, semantic, page_set, compiled_pages


def _direction_upstream(*, candidate_id: str = "candidate-a", revision: int = 1):
    atoms = []
    fragments = []
    pages = []
    beats = []
    for index in range(1, 6):
        text = f"页面标题{index}"
        atom_payload = {
            "atom_id": f"atom-{index}",
            "source_unit_id": f"unit-{index}",
            "source_projection_sha256": "1" * 64,
            "source_field": "content",
            "raw_start": 0,
            "raw_end": len(text),
            "raw_slice_sha256": "2" * 64,
            "text": text,
            "role": "heading",
        }
        atoms.append(ContentAtomV4(**atom_payload, sha256=canonical_sha256_v4(atom_payload)))
        fragments.append(
            SemanticFragmentV4(
                fragment_id=f"fragment-{index}",
                source_atom_id=f"atom-{index}",
                start=0,
                end=len(text),
                exact_text=text,
                semantic_role="heading",
                sequence_index=index - 1,
            )
        )
    atom_payload = {"projection_sha256": "1" * 64, "atoms": tuple(atoms)}
    atom_set = ContentAtomSetV4(
        **atom_payload,
        canonical_sha256=canonical_sha256_v4(atom_payload),
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
    for index in range(1, 6):
        page_payload = {
            "page_id": f"page-{index}",
            "sequence": index,
            "narrative_role": "typed role",
            "beat_ref": f"beat-{index}",
            "fragment_refs": (f"fragment-{index}",),
            "visual_priority": (f"fragment-{index}",),
            "density_budget": "medium",
            "preferred_compositions": ("editorial_hero",),
            "forbidden_patterns": (),
            "asset_directives": (),
            "continuity_with_previous": "none",
        }
        pages.append(PageBriefV4(**page_payload, canonical_sha256=canonical_sha256_v4(page_payload)))
        beats.append(
            NarrativeBeatV4(
                beat_id=f"beat-{index}",
                sequence=index,
                task_kind="context",
                fragment_refs=(f"fragment-{index}",),
                task="semantic task",
            )
        )
    page_set_payload = {
        "page_count": 5,
        "pages": tuple(pages),
        "template_family": "pink_red",
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "semantic_content_model_sha256": semantic.canonical_sha256,
    }
    page_set = PageBriefSetV4(
        **page_set_payload,
        canonical_sha256=canonical_sha256_v4(page_set_payload),
    )
    narrative_payload = {
        "template_family": "pink_red",
        "page_count": 5,
        "beats": tuple(beats),
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
    plan_payload = {
        "semantic_content_model": semantic,
        "narrative": narrative,
        "page_brief_set": page_set,
        "template_family": "pink_red",
        "page_count": 5,
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "semantic_content_model_sha256": semantic.canonical_sha256,
        "narrative_sha256": narrative.canonical_sha256,
        "page_brief_set_sha256": page_set.canonical_sha256,
    }
    plan = VisualDirectionPlanV4(
        **plan_payload,
        canonical_sha256=canonical_sha256_v4(plan_payload),
    )
    compiled_pages = []
    for page in pages:
        program = build_layout_program(
            page,
            grammar_id="editorial_hero",
            family="pink_red",
            narrative=narrative,
        )
        compiled_pages.append(
            compile_layout(
                program,
                LayoutCompilerInputsV4(
                    page_brief=page,
                    semantic_content_model=semantic,
                    content_atom_set=atom_set,
                    asset_manifest=AssetManifest(items=()),
                    candidate_id=candidate_id,
                    revision=revision,
                    run_id="run-a",
                    visual_direction_plan=plan,
                ),
            )
        )
    return atom_set, semantic, page_set, narrative, plan, tuple(compiled_pages)


def _direction_upstream_with_approved_asset():
    atom_set, semantic, page_set, narrative, direction_plan, base_pages = _direction_upstream()
    directive = AssetDirectiveV4(
        directive_id="directive-1",
        page_id="page-1",
        role="object",
        purpose="supporting",
        supports_fragment_refs=("fragment-1",),
        required=True,
        preferred_source="search",
        query_or_prompt="text-free supporting object",
        orientation="landscape",
    )
    first_page_payload = page_set.pages[0].model_dump(mode="python")
    first_page_payload["asset_directives"] = (directive,)
    first_page_payload.pop("canonical_sha256", None)
    first_page = PageBriefV4(
        **first_page_payload,
        canonical_sha256=canonical_sha256_v4(first_page_payload),
    )
    page_set_payload = page_set.model_dump(mode="python")
    page_set_payload["pages"] = (first_page, *page_set.pages[1:])
    page_set_payload.pop("canonical_sha256", None)
    updated_page_set = PageBriefSetV4(
        **page_set_payload,
        canonical_sha256=canonical_sha256_v4(page_set_payload),
    )
    plan_payload = direction_plan.model_dump(mode="python")
    plan_payload.update(
        {
            "page_brief_set": updated_page_set,
            "page_brief_set_sha256": updated_page_set.canonical_sha256,
        }
    )
    plan_payload.pop("canonical_sha256", None)
    updated_plan = VisualDirectionPlanV4(
        **plan_payload,
        canonical_sha256=canonical_sha256_v4(plan_payload),
    )
    manifest = AssetManifest(
        items=(
            AssetManifestItem(
                asset_id="asset-1",
                directive_id="directive-1",
                page_id="page-1",
                source_kind="search",
                provider="fixture-provider-secret",
                license="fixture-license",
                local_path="/Users/private/fixture.png",
                width=1200,
                height=800,
                sha256="3" * 64,
                subject_focal_point=(0.5, 0.5),
                crop_guidance="center",
                security_status="approved",
                human_decision="pending",
                run_id="run-a",
                transaction_id="tx-1",
                internal_provenance={"secret": "fixture provenance"},
            ),
        )
    )
    compiled_pages = []
    for index, page in enumerate(updated_page_set.pages):
        program = (
            build_layout_program(
                page,
                grammar_id="editorial_hero",
                family="pink_red",
                narrative=narrative,
            )
            if index == 0
            else base_pages[index].layout_program
        )
        compiled_pages.append(
            compile_layout(
                program,
                LayoutCompilerInputsV4(
                    page_brief=page,
                    semantic_content_model=semantic,
                    content_atom_set=atom_set,
                    asset_manifest=manifest,
                    candidate_id="candidate-a",
                    revision=1,
                    run_id="run-a",
                    visual_direction_plan=updated_plan,
                ),
            )
        )
    return atom_set, semantic, updated_page_set, updated_plan, manifest, tuple(compiled_pages)


def _upstream(page_count: int = 5):
    del page_count
    atom_set, semantic, page_set, _narrative, plan, pages = _direction_upstream()
    return atom_set, semantic, page_set, plan, pages


def _rehash_page(page: CompiledPageV4, **updates) -> CompiledPageV4:
    raw = page.model_dump(mode="python")
    raw.update(updates)
    raw.pop("canonical_sha256", None)
    source = dict(raw)
    return CompiledPageV4(**raw, canonical_sha256=canonical_sha256_v4(source))


def _rehash_provenance(provenance: CompilerProvenanceV4, **updates) -> CompilerProvenanceV4:
    raw = provenance.model_dump(mode="python")
    raw.update(updates)
    raw.pop("canonical_sha256", None)
    source = dict(raw)
    return CompilerProvenanceV4(**raw, canonical_sha256=canonical_sha256_v4(source))


def test_layout_node_aggregates_ordered_pages_and_binds_all_hashes() -> None:
    atom_set, semantic, page_set, direction_plan, pages = _upstream()
    plan = aggregate_layout_plan(
        pages,
        content_atom_set=atom_set,
        semantic_content_model=semantic,
        page_brief_set=page_set,
        asset_manifest=AssetManifest(items=()),
        family_tokens=get_family_tokens("pink_red"),
        revision=1,
        run_id="run-a",
        candidate_id="candidate-a",
        visual_direction_plan=direction_plan,
    )
    assert [page.sequence for page in plan.pages] == [1, 2, 3, 4, 5]
    assert plan.content_atom_set_sha256 == atom_set.canonical_sha256
    assert plan.semantic_content_model_sha256 == semantic.canonical_sha256
    assert plan.page_brief_set_sha256 == page_set.canonical_sha256


@pytest.mark.parametrize("mutation", ("missing", "duplicate", "out_of_order"))
def test_layout_node_rejects_page_identity_errors(mutation: str) -> None:
    atom_set, semantic, page_set, direction_plan, pages = _upstream()
    if mutation == "missing":
        pages = pages[:-1]
    elif mutation == "duplicate":
        pages = [*pages[:-1], pages[0]]
    else:
        pages = [pages[1], pages[0], *pages[2:]]
    with pytest.raises(ValueError, match="page|sequence|brief"):
        aggregate_layout_plan(
            pages,
            content_atom_set=atom_set,
            semantic_content_model=semantic,
            page_brief_set=page_set,
            asset_manifest=AssetManifest(items=()),
            family_tokens=get_family_tokens("pink_red"),
            revision=1,
            run_id="run-a",
            candidate_id="candidate-a",
            visual_direction_plan=direction_plan,
        )


def test_layout_node_rejects_unrepresented_brief_fragment() -> None:
    atom_set, semantic, page_set, direction_plan, pages = _upstream()
    changed = pages[0].model_copy(update={"scene": pages[0].scene.model_copy(update={"elements": ()})})
    with pytest.raises(ValueError, match="invalid|stale|fragment|scene|represented"):
        aggregate_layout_plan(
            [changed, *pages[1:]],
            content_atom_set=atom_set,
            semantic_content_model=semantic,
            page_brief_set=page_set,
            asset_manifest=AssetManifest(items=()),
            family_tokens=get_family_tokens("pink_red"),
            revision=1,
            run_id="run-a",
            candidate_id="candidate-a",
            visual_direction_plan=direction_plan,
        )


def test_aggregate_requires_one_hash_bound_direction_plan_and_candidate_revision() -> None:
    atom_set, semantic, page_set, _narrative, direction_plan, pages = _direction_upstream()
    plan = aggregate_layout_plan(
        pages,
        content_atom_set=atom_set,
        semantic_content_model=semantic,
        page_brief_set=page_set,
        asset_manifest=AssetManifest(items=()),
        family_tokens=get_family_tokens("pink_red"),
        visual_direction_plan=direction_plan,
        candidate_id="candidate-a",
        revision=1,
        run_id="run-a",
    )
    assert plan.visual_direction_plan_sha256 == direction_plan.canonical_sha256
    assert plan.candidate_id == "candidate-a"
    assert plan.revision == 1
    assert {page.compiler_provenance.candidate_id for page in plan.pages} == {"candidate-a"}


def test_aggregate_recompiles_scene_after_outer_hashes_are_recomputed() -> None:
    atom_set, semantic, page_set, _narrative, direction_plan, pages = _direction_upstream()
    original = pages[0]
    text = next(element for element in original.scene.elements if isinstance(element, TextElement))
    changed_text = text.model_copy(
        update={"box": Box(x=0, y=text.box.y, width=text.box.width, height=text.box.height)}
    )
    changed_scene = original.scene.model_copy(
        update={
            "elements": tuple(
                changed_text if element.element_id == text.element_id else element
                for element in original.scene.elements
            )
        }
    )
    raw = original.model_dump(mode="python")
    raw["scene"] = changed_scene
    raw.pop("canonical_sha256", None)
    source = dict(raw)
    raw["canonical_sha256"] = canonical_sha256_v4(source)
    with pytest.raises(ValueError, match="safe|geometry|scene|stale|invalid"):
        aggregate_layout_plan(
            [raw, *pages[1:]],
            content_atom_set=atom_set,
            semantic_content_model=semantic,
            page_brief_set=page_set,
            asset_manifest=AssetManifest(items=()),
            family_tokens=get_family_tokens("pink_red"),
            visual_direction_plan=direction_plan,
            candidate_id="candidate-a",
            revision=1,
            run_id="run-a",
        )


def test_durable_direction_boundary_rejects_duplicate_global_fragment_ownership() -> None:
    atom_set, semantic, page_set, _narrative, direction_plan, pages = _direction_upstream()
    duplicate_page = page_set.pages[1]
    duplicate_payload = duplicate_page.model_dump(mode="python")
    duplicate_payload.update({"fragment_refs": ("fragment-1",), "visual_priority": ("fragment-1",)})
    duplicate_payload.pop("canonical_sha256", None)
    duplicate_page = PageBriefV4(
        **duplicate_payload,
        canonical_sha256=canonical_sha256_v4(duplicate_payload),
    )
    page_set_payload = page_set.model_dump(mode="python")
    page_set_payload["pages"] = (page_set.pages[0], duplicate_page, *page_set.pages[2:])
    page_set_payload.pop("canonical_sha256", None)
    duplicate_page_set = PageBriefSetV4(
        **page_set_payload,
        canonical_sha256=canonical_sha256_v4(page_set_payload),
    )
    plan_payload = direction_plan.model_dump(mode="python")
    plan_payload.update(
        {
            "page_brief_set": duplicate_page_set,
            "page_brief_set_sha256": duplicate_page_set.canonical_sha256,
        }
    )
    plan_payload.pop("canonical_sha256", None)
    duplicate_plan = VisualDirectionPlanV4(
        **plan_payload,
        canonical_sha256=canonical_sha256_v4(plan_payload),
    )
    with pytest.raises(ValueError, match="fragment|ownership|brief"):
        aggregate_layout_plan(
            pages,
            content_atom_set=atom_set,
            semantic_content_model=semantic,
            page_brief_set=duplicate_page_set,
            asset_manifest=AssetManifest(items=()),
            family_tokens=get_family_tokens("pink_red"),
            visual_direction_plan=duplicate_plan,
            candidate_id="candidate-a",
            revision=1,
            run_id="run-a",
        )


def test_durable_direction_boundary_rejects_mixed_candidate_pages() -> None:
    atom_set, semantic, page_set, _narrative, direction_plan, pages = _direction_upstream()
    changed_provenance = _rehash_provenance(
        pages[1].compiler_provenance,
        candidate_id="candidate-b",
    )
    changed_page = _rehash_page(pages[1], compiler_provenance=changed_provenance)
    with pytest.raises(ValueError, match="candidate|identity|mix"):
        aggregate_layout_plan(
            [pages[0], changed_page, *pages[2:]],
            content_atom_set=atom_set,
            semantic_content_model=semantic,
            page_brief_set=page_set,
            asset_manifest=AssetManifest(items=()),
            family_tokens=get_family_tokens("pink_red"),
            visual_direction_plan=direction_plan,
            candidate_id="candidate-a",
            revision=1,
            run_id="run-a",
        )


def test_carousel_plan_json_contains_no_asset_provider_path_or_provenance() -> None:
    atom_set, semantic, page_set, _narrative, direction_plan, pages = _direction_upstream()
    plan = aggregate_layout_plan(
        pages,
        content_atom_set=atom_set,
        semantic_content_model=semantic,
        page_brief_set=page_set,
        asset_manifest=AssetManifest(items=()),
        family_tokens=get_family_tokens("pink_red"),
        visual_direction_plan=direction_plan,
        candidate_id="candidate-a",
        revision=1,
        run_id="run-a",
    )
    payload = plan.model_dump_json()
    assert "/tmp/fixture.png" not in payload
    assert "fixture-provider" not in payload
    assert "internal_provenance" not in payload


def test_compiled_page_and_carousel_json_strip_real_asset_private_fields_recursively() -> None:
    atom_set, semantic, page_set, direction_plan, manifest, pages = _direction_upstream_with_approved_asset()
    plan = aggregate_layout_plan(
        pages,
        content_atom_set=atom_set,
        semantic_content_model=semantic,
        page_brief_set=page_set,
        asset_manifest=manifest,
        family_tokens=get_family_tokens("pink_red"),
        candidate_id="candidate-a",
        revision=1,
        run_id="run-a",
        visual_direction_plan=direction_plan,
    )

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                assert key not in {"provider", "local_path", "internal_provenance", "asset_provenance"}
                yield from walk(item)
        elif isinstance(value, list):
            for item in value:
                yield from walk(item)

    import json

    for payload in (pages[0].model_dump(mode="json"), plan.model_dump(mode="json")):
        tuple(walk(payload))
        rendered = json.dumps(payload, ensure_ascii=False)
        assert "fixture-provider-secret" not in rendered
        assert "/Users/private/fixture.png" not in rendered
        assert "fixture provenance" not in rendered
