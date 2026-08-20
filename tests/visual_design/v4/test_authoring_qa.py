from __future__ import annotations

from src.schemas.v4.content import ContentAtomSetV4, ContentAtomV4, canonical_sha256_v4
from src.schemas.v4.direction import (
    AssetDirectiveV4,
    CarouselNarrativeV4,
    PageBriefSetV4,
    PageBriefV4,
)
from src.schemas.v4.semantic import SemanticContentModelV4, SemanticFragmentV4
from src.visual_design.v4.authoring_qa import evaluate_authoring


def semantic_model() -> SemanticContentModelV4:
    atom_payloads = []
    for index in range(5):
        text = f"fragment text {index}"
        atom_payload = {
            "atom_id": f"atom-{index}",
            "source_unit_id": f"unit-{index}",
            "source_projection_sha256": "1" * 64,
            "source_field": "content",
            "raw_start": 0,
            "raw_end": len(text),
            "raw_slice_sha256": canonical_sha256_v4({"text": text}),
            "text": text,
            "role": "paragraph",
        }
        atom = ContentAtomV4(
            **atom_payload,
            sha256=canonical_sha256_v4(atom_payload),
        )
        atom_payloads.append(atom)
    atom_set_payload = {
        "projection_sha256": "1" * 64,
        "atoms": tuple(atom_payloads),
    }
    atom_set = ContentAtomSetV4(
        **atom_set_payload,
        canonical_sha256=canonical_sha256_v4(atom_set_payload),
    )
    fragments = tuple(
        SemanticFragmentV4(
            fragment_id=f"fragment-{index}",
            source_atom_id=atom.atom_id,
            start=0,
            end=len(atom.text),
            exact_text=atom.text,
            semantic_role="paragraph",
            sequence_index=index,
        )
        for index, atom in enumerate(atom_set.atoms)
    )
    model_payload = {
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "fragments": fragments,
        "groups": (),
    }
    return SemanticContentModelV4(
        **model_payload,
        canonical_sha256=canonical_sha256_v4(model_payload),
    )


def briefs(*, densities: tuple[str, ...] | None = None, duplicate: bool = False):
    densities = densities or ("low", "medium", "low", "medium", "low")
    pages = []
    for index, density in enumerate(densities, start=1):
        refs = (f"fragment-{index - 1}",)
        if duplicate and index == 2:
            refs = ("fragment-0",)
        payload = {
            "page_id": f"page-{index}",
            "sequence": index,
            "narrative_role": f"role-{index}",
            "fragment_refs": refs,
            "visual_priority": refs,
            "density_budget": density,
            "preferred_compositions": (
                "editorial_hero" if index % 2 else "comparison_grid",
            ),
            "forbidden_patterns": (),
            "asset_directives": (),
            "continuity_with_previous": "none" if index == 1 else "carry cue",
        }
        pages.append(
            PageBriefV4(
                **payload,
                canonical_sha256=canonical_sha256_v4(payload),
            )
        )
    payload = {"page_count": len(pages), "pages": tuple(pages)}
    return PageBriefSetV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def recanonicalize_page_set(page_set: PageBriefSetV4, **updates) -> PageBriefSetV4:
    payload = page_set.model_dump(mode="python")
    payload["pages"] = tuple(
        PageBriefV4.model_validate(page) for page in payload["pages"]
    )
    payload.update(updates)
    payload.pop("canonical_sha256", None)

    canonical_source = PageBriefSetV4.model_construct(
        **payload,
        canonical_sha256="0" * 64,
    ).model_dump(
        mode="json",
        exclude={"canonical_sha256"},
        exclude_none=True,
    )
    return PageBriefSetV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(canonical_source),
    )


def narrative_for(page_set: PageBriefSetV4, *, family: str = "pink_red") -> CarouselNarrativeV4:
    payload = {
        "template_family": family,
        "page_count": page_set.page_count,
        "beats": tuple(f"beat-{index}" for index in range(page_set.page_count)),
        "density_curve": tuple(page.density_budget for page in page_set.pages),
        "variation_strategy": "alternate structures",
        "continuity_strategy": "carry one cue",
        "art_direction": "clean editorial",
    }
    return CarouselNarrativeV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def test_authoring_qa_requires_exact_fragment_ownership():
    result = evaluate_authoring(briefs(duplicate=True), semantic_model())
    assert result.passed is False
    assert {issue.code for issue in result.issues} == {
        "FRAGMENT_OWNERSHIP_DUPLICATED"
    }


def test_authoring_qa_rejects_three_consecutive_high_density_pages():
    result = evaluate_authoring(
        briefs(densities=("high", "high", "high", "low", "low")),
        semantic_model(),
    )
    assert "DENSITY_CURVE_UNBALANCED" in {issue.code for issue in result.issues}


def test_authoring_qa_reports_missing_and_unknown_fragment_ownership():
    page_set = briefs()
    pages = list(page_set.pages)
    missing_payload = pages[-1].model_dump(mode="python")
    missing_payload["fragment_refs"] = ()
    missing_payload["visual_priority"] = ()
    missing_payload.pop("canonical_sha256", None)
    pages[-1] = PageBriefV4(
        **missing_payload,
        canonical_sha256=canonical_sha256_v4(missing_payload),
    )
    missing_set = recanonicalize_page_set(page_set, pages=tuple(pages))
    missing_codes = {
        issue.code for issue in evaluate_authoring(missing_set, semantic_model()).issues
    }
    assert "FRAGMENT_OWNERSHIP_MISSING" in missing_codes

    unknown_payload = pages[0].model_dump(mode="python")
    unknown_payload["fragment_refs"] = ("fragment-does-not-exist",)
    unknown_payload["visual_priority"] = ("fragment-does-not-exist",)
    unknown_payload.pop("canonical_sha256", None)
    unknown_page = PageBriefV4(
        **unknown_payload,
        canonical_sha256=canonical_sha256_v4(unknown_payload),
    )
    unknown_set = recanonicalize_page_set(
        page_set, pages=(unknown_page, *page_set.pages[1:])
    )
    unknown_codes = {
        issue.code for issue in evaluate_authoring(unknown_set, semantic_model()).issues
    }
    assert "FRAGMENT_OWNERSHIP_UNKNOWN" in unknown_codes


def test_authoring_qa_checks_page_bounds_sequence_family_and_hash_bindings():
    four = briefs(densities=("low", "low", "low", "low"))
    assert "PAGE_COUNT_INVALID" in {
        issue.code for issue in evaluate_authoring(four, semantic_model()).issues
    }

    pages = list(briefs().pages)
    changed_payload = pages[1].model_dump(mode="python")
    changed_payload["sequence"] = 3
    changed_payload.pop("canonical_sha256", None)
    pages[1] = PageBriefV4(
        **changed_payload,
        canonical_sha256=canonical_sha256_v4(changed_payload),
    )
    sequence_set = recanonicalize_page_set(briefs(), pages=tuple(pages))
    assert "PAGE_SEQUENCE_INVALID" in {
        issue.code for issue in evaluate_authoring(sequence_set, semantic_model()).issues
    }

    page_set = recanonicalize_page_set(briefs(), template_family="pink_red")
    narrative = narrative_for(page_set, family="deep_teal")
    family_codes = {
        issue.code
        for issue in evaluate_authoring(page_set, semantic_model(), narrative).issues
    }
    assert "FAMILY_MISMATCH" in family_codes

    stale = page_set.model_copy(update={"page_count": 6})
    assert "HASH_BINDING_MISMATCH" in {
        issue.code for issue in evaluate_authoring(stale, semantic_model()).issues
    }


def test_authoring_qa_rejects_repeated_composition_and_note_only_priority():
    page_set = briefs()
    pages = []
    for page in page_set.pages:
        payload = page.model_dump(mode="python")
        payload["preferred_compositions"] = ("editorial_hero",)
        payload.pop("canonical_sha256", None)
        pages.append(PageBriefV4(**payload, canonical_sha256=canonical_sha256_v4(payload)))
    repeated = recanonicalize_page_set(page_set, pages=tuple(pages))
    assert "COMPOSITION_REPEATED" in {
        issue.code for issue in evaluate_authoring(repeated, semantic_model()).issues
    }

    note_fragment = semantic_model().fragments[0].model_copy(
        update={"semantic_role": "note"}
    )
    model_payload = semantic_model().model_dump(mode="python")
    model_payload["fragments"] = (note_fragment, *semantic_model().fragments[1:])
    model_payload.pop("canonical_sha256", None)
    note_model = SemanticContentModelV4(
        **model_payload,
        canonical_sha256=canonical_sha256_v4(model_payload),
    )
    note_page_payload = page_set.pages[0].model_dump(mode="python")
    note_page_payload["fragment_refs"] = ("fragment-0", "fragment-1")
    note_page_payload["visual_priority"] = ("fragment-0",)
    note_page_payload.pop("canonical_sha256", None)
    note_page = PageBriefV4(
        **note_page_payload,
        canonical_sha256=canonical_sha256_v4(note_page_payload),
    )
    note_set = recanonicalize_page_set(
        page_set, pages=(note_page, *page_set.pages[1:])
    )
    assert "NOTES_CANNOT_BE_PRIMARY" in {
        issue.code for issue in evaluate_authoring(note_set, note_model).issues
    }


def test_authoring_qa_rejects_empty_narrative_role():
    page = briefs().pages[0]
    payload = page.model_dump(mode="python")
    payload["narrative_role"] = ""
    payload.pop("canonical_sha256", None)
    empty_role = PageBriefV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )
    page_set = recanonicalize_page_set(briefs(), pages=(empty_role, *briefs().pages[1:]))
    assert "NARRATIVE_ROLE_EMPTY" in {
        issue.code for issue in evaluate_authoring(page_set, semantic_model()).issues
    }


def test_authoring_qa_requires_unique_asset_directive_ownership_and_page_binding():
    directive = AssetDirectiveV4(
        directive_id="asset-1",
        page_id="page-1",
        role="evidence",
        required=True,
        preferred_source="search",
        fallback_source="none",
        query_or_prompt="clean skincare evidence photo",
        orientation="portrait",
        min_width=1080,
        min_height=1440,
    )
    pages = list(briefs().pages)
    for page_index in (0, 1):
        payload = pages[page_index].model_dump(mode="python")
        payload["asset_directives"] = (directive,)
        payload.pop("canonical_sha256", None)
        pages[page_index] = PageBriefV4(
            **payload,
            canonical_sha256=canonical_sha256_v4(payload),
        )
    with_assets = recanonicalize_page_set(briefs(), pages=tuple(pages))
    codes = {
        issue.code for issue in evaluate_authoring(with_assets, semantic_model()).issues
    }
    assert "ASSET_DIRECTIVE_OWNERSHIP_DUPLICATED" in codes
    assert "ASSET_DIRECTIVE_PAGE_MISMATCH" in codes
