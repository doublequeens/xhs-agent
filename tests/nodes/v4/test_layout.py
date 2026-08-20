from __future__ import annotations

import pytest

from src.nodes.v4.composition import build_layout_program
from src.nodes.v4.layout import aggregate_layout_plan
from src.schemas.assets import AssetManifest
from src.schemas.v4.content import ContentAtomSetV4, ContentAtomV4, canonical_sha256_v4
from src.schemas.v4.direction import CarouselNarrativeV4, NarrativeBeatV4, PageBriefSetV4, PageBriefV4
from src.schemas.v4.semantic import SemanticContentModelV4, SemanticFragmentV4
from src.visual_design.v4.compiler import LayoutCompilerInputsV4, compile_layout
from src.visual_design.v4.tokens import get_family_tokens


def _upstream(page_count: int = 5):
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
                ),
            )
        )
    return atom_set, semantic, page_set, compiled_pages


def test_layout_node_aggregates_ordered_pages_and_binds_all_hashes() -> None:
    atom_set, semantic, page_set, pages = _upstream()
    plan = aggregate_layout_plan(
        pages,
        content_atom_set=atom_set,
        semantic_content_model=semantic,
        page_brief_set=page_set,
        asset_manifest=AssetManifest(items=()),
        family_tokens=get_family_tokens("pink_red"),
        revision=0,
    )
    assert [page.sequence for page in plan.pages] == [1, 2, 3, 4, 5]
    assert plan.content_atom_set_sha256 == atom_set.canonical_sha256
    assert plan.semantic_content_model_sha256 == semantic.canonical_sha256
    assert plan.page_brief_set_sha256 == page_set.canonical_sha256


@pytest.mark.parametrize("mutation", ("missing", "duplicate", "out_of_order"))
def test_layout_node_rejects_page_identity_errors(mutation: str) -> None:
    atom_set, semantic, page_set, pages = _upstream()
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
            revision=0,
        )


def test_layout_node_rejects_unrepresented_brief_fragment() -> None:
    atom_set, semantic, page_set, pages = _upstream()
    changed = pages[0].model_copy(update={"scene": pages[0].scene.model_copy(update={"elements": ()})})
    with pytest.raises(ValueError, match="invalid|stale|fragment|scene|represented"):
        aggregate_layout_plan(
            [changed, *pages[1:]],
            content_atom_set=atom_set,
            semantic_content_model=semantic,
            page_brief_set=page_set,
            asset_manifest=AssetManifest(items=()),
            family_tokens=get_family_tokens("pink_red"),
            revision=0,
        )
