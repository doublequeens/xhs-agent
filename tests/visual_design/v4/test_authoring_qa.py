from __future__ import annotations

from src.schemas.v4.content import ContentAtomSetV4, ContentAtomV4, canonical_sha256_v4
from src.schemas.v4.direction import (
    AssetDirectiveV4,
    CarouselNarrativeV4,
    NarrativeBeatV4,
    PageBriefSetV4,
    PageBriefV4,
)
from src.schemas.v4.semantic import (
    SemanticContentModelV4,
    SemanticFragmentV4,
    SemanticGroupV4,
)
from src.visual_design.v4.authoring_qa import (
    AuthoringCandidatePreflightV4,
    evaluate_authoring,
)


def semantic_model(*, with_group: bool = False) -> SemanticContentModelV4:
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
    groups = (
        SemanticGroupV4(
            group_id="group-1",
            group_kind="context",
            fragment_ids=("fragment-0", "fragment-1"),
            ordering=0,
        ),
    ) if with_group else ()
    model_payload = {
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "fragments": fragments,
        "groups": groups,
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
            refs = ("fragment-1", "fragment-0")
        payload = {
            "page_id": f"page-{index}",
            "sequence": index,
            "narrative_role": f"role-{index}",
            "beat_ref": f"beat-{index - 1}",
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

    canonical_source = {
        key: value
        for key, value in payload.items()
        if key != "canonical_sha256" and value is not None
    }
    return PageBriefSetV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(canonical_source),
    )


def narrative_for(page_set: PageBriefSetV4, *, family: str = "pink_red") -> CarouselNarrativeV4:
    payload = {
        "template_family": family,
        "page_count": page_set.page_count,
        "beats": tuple(
            NarrativeBeatV4(
                beat_id=f"beat-{index}",
                sequence=index + 1,
                task_kind="context",
                fragment_refs=(f"fragment-{index}",),
                task=f"task-{index}",
            )
            for index in range(page_set.page_count)
        ),
        "density_curve": tuple(page.density_budget for page in page_set.pages),
        "variation_strategy": "alternate structures",
        "continuity_strategy": "carry one cue",
        "art_direction": "clean editorial",
    }
    return CarouselNarrativeV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def recanonicalize_narrative(narrative: CarouselNarrativeV4, **updates):
    payload = narrative.model_dump(mode="python")
    payload.update(updates)
    payload.pop("canonical_sha256", None)
    canonical_payload = {
        key: value for key, value in payload.items() if value is not None
    }
    return CarouselNarrativeV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(canonical_payload),
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
    missing_raw = page_set.model_dump(mode="python")
    pages = list(missing_raw["pages"])
    missing_payload = dict(pages[-1])
    missing_payload["fragment_refs"] = ()
    missing_payload["visual_priority"] = ()
    missing_payload.pop("canonical_sha256", None)
    pages[-1] = missing_payload
    missing_raw["pages"] = tuple(pages)
    missing_raw.pop("canonical_sha256", None)
    missing_codes = {
        issue.code for issue in evaluate_authoring(missing_raw, semantic_model()).issues
    }
    assert "FRAGMENT_OWNERSHIP_MISSING" in missing_codes

    unknown_payload = page_set.pages[0].model_dump(mode="python")
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


def test_authoring_qa_reports_mixed_fragment_ownership_errors_together():
    pages = list(briefs().pages)
    first_payload = pages[0].model_dump(mode="python")
    first_payload["fragment_refs"] = ("fragment-0", "fragment-unknown")
    first_payload["visual_priority"] = ("fragment-0",)
    first_payload.pop("canonical_sha256", None)
    pages[0] = PageBriefV4(
        **first_payload,
        canonical_sha256=canonical_sha256_v4(first_payload),
    )
    second_payload = pages[1].model_dump(mode="python")
    second_payload["fragment_refs"] = ("fragment-0",)
    second_payload["visual_priority"] = ("fragment-0",)
    second_payload.pop("canonical_sha256", None)
    pages[1] = PageBriefV4(
        **second_payload,
        canonical_sha256=canonical_sha256_v4(second_payload),
    )
    result = evaluate_authoring(
        recanonicalize_page_set(briefs(), pages=tuple(pages)),
        semantic_model(),
    )
    codes = {issue.code for issue in result.issues}
    assert {
        "FRAGMENT_OWNERSHIP_DUPLICATED",
        "FRAGMENT_OWNERSHIP_MISSING",
        "FRAGMENT_OWNERSHIP_UNKNOWN",
    }.issubset(codes)


def test_authoring_qa_checks_page_bounds_sequence_family_and_hash_bindings():
    four = briefs().model_dump(mode="python")
    four["page_count"] = 4
    four["pages"] = four["pages"][:4]
    four.pop("canonical_sha256", None)
    assert "PAGE_COUNT_INVALID" in {
        issue.code for issue in evaluate_authoring(four, semantic_model()).issues
    }

    sequence_raw = briefs().model_dump(mode="python")
    pages = list(sequence_raw["pages"])
    changed_payload = dict(pages[1])
    changed_payload["sequence"] = 3
    changed_payload.pop("canonical_sha256", None)
    pages[1] = changed_payload
    sequence_raw["pages"] = tuple(pages)
    sequence_raw.pop("canonical_sha256", None)
    assert "PAGE_SEQUENCE_INVALID" in {
        issue.code for issue in evaluate_authoring(sequence_raw, semantic_model()).issues
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

    first, second = page_set.pages[:2]
    first_payload = first.model_dump(mode="python")
    first_payload["preferred_compositions"] = (
        "editorial_hero",
        "comparison_grid",
    )
    first_payload.pop("canonical_sha256", None)
    second_payload = second.model_dump(mode="python")
    second_payload["preferred_compositions"] = (
        "summary_closing",
        "comparison_grid",
    )
    second_payload.pop("canonical_sha256", None)
    different_first = recanonicalize_page_set(
        page_set,
        pages=(
            PageBriefV4(
                **first_payload,
                canonical_sha256=canonical_sha256_v4(first_payload),
            ),
            PageBriefV4(
                **second_payload,
                canonical_sha256=canonical_sha256_v4(second_payload),
            ),
            *page_set.pages[2:],
        ),
    )
    assert "COMPOSITION_REPEATED" not in {
        issue.code
        for issue in evaluate_authoring(different_first, semantic_model()).issues
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

    note_only_payload = page_set.pages[0].model_dump(mode="python")
    note_only_payload["fragment_refs"] = ("fragment-0",)
    note_only_payload["visual_priority"] = ("fragment-0",)
    note_only_payload.pop("canonical_sha256", None)
    note_only_page = PageBriefV4(
        **note_only_payload,
        canonical_sha256=canonical_sha256_v4(note_only_payload),
    )
    note_only_set = recanonicalize_page_set(
        page_set,
        pages=(note_only_page, *page_set.pages[1:]),
    )
    assert "NOTES_CANNOT_BE_PRIMARY" in {
        issue.code for issue in evaluate_authoring(note_only_set, note_model).issues
    }


def test_authoring_qa_requires_one_to_one_beat_ownership():
    pages = list(briefs().pages)
    payload = pages[1].model_dump(mode="python")
    payload["beat_ref"] = "beat-0"
    payload.pop("canonical_sha256", None)
    pages[1] = PageBriefV4(**payload, canonical_sha256=canonical_sha256_v4(payload))
    result = evaluate_authoring(
        recanonicalize_page_set(briefs(), pages=tuple(pages)),
        semantic_model(),
        narrative_for(briefs()),
    )
    codes = {issue.code for issue in result.issues}
    assert {"BEAT_OWNERSHIP_DUPLICATED", "BEAT_OWNERSHIP_MISSING"}.issubset(codes)


def test_authoring_qa_binds_beat_task_kind_and_fragment_refs():
    page_set = briefs()
    narrative = narrative_for(page_set)
    changed = list(narrative.beats)
    changed[0] = changed[0].model_copy(
        update={"fragment_refs": ("fragment-1",)}
    )
    mismatch = recanonicalize_narrative(narrative, beats=tuple(changed))
    codes = {
        issue.code
        for issue in evaluate_authoring(page_set, semantic_model(), mismatch).issues
    }
    assert "BEAT_FRAGMENT_BINDING_MISMATCH" in codes

    unknown = list(narrative.beats)
    unknown[0] = unknown[0].model_copy(
        update={"fragment_refs": ("fragment-unknown",)}
    )
    unknown_narrative = recanonicalize_narrative(
        narrative,
        beats=tuple(unknown),
    )
    unknown_codes = {
        issue.code
        for issue in evaluate_authoring(
            page_set,
            semantic_model(),
            unknown_narrative,
        ).issues
    }
    assert "BEAT_FRAGMENT_UNKNOWN" in unknown_codes

    group_unknown = list(narrative.beats)
    group_unknown[0] = group_unknown[0].model_copy(
        update={"group_refs": ("group-unknown",)}
    )
    group_narrative = recanonicalize_narrative(
        narrative,
        beats=tuple(group_unknown),
    )
    group_codes = {
        issue.code
        for issue in evaluate_authoring(
            page_set,
            semantic_model(with_group=True),
            group_narrative,
        ).issues
    }
    assert "BEAT_GROUP_UNKNOWN" in group_codes

    role_mismatch = list(narrative.beats)
    role_mismatch[0] = role_mismatch[0].model_copy(
        update={"task_kind": "step"}
    )
    role_narrative = recanonicalize_narrative(
        narrative,
        beats=tuple(role_mismatch),
    )
    assert "BEAT_TASK_KIND_MISMATCH" in {
        issue.code
        for issue in evaluate_authoring(page_set, semantic_model(), role_narrative).issues
    }


def test_candidate_preflight_is_not_a_passed_durable_q1_result():
    candidate = briefs().model_dump(mode="python")
    candidate.pop("canonical_sha256", None)
    result = evaluate_authoring(
        candidate,
        semantic_model(),
        narrative_for(briefs()),
    )
    assert isinstance(result, AuthoringCandidatePreflightV4)
    assert result.passed is True
    assert result.candidate_sha256 != "0" * 64


def test_authoring_qa_rejects_empty_page_candidate_without_throwing():
    raw = briefs().model_dump(mode="python")
    raw["canonical_sha256"] = "0" * 64
    empty_pages = list(raw["pages"])
    for index in range(1, 5):
        empty = dict(empty_pages[index])
        empty["fragment_refs"] = ()
        empty["visual_priority"] = ()
        empty["preferred_compositions"] = ()
        empty.pop("canonical_sha256", None)
        empty_pages[index] = empty
    raw["pages"] = tuple(empty_pages)
    result = evaluate_authoring(raw, semantic_model(), narrative_for(briefs()))
    assert result.passed is False
    assert "PAGE_BRIEF_DUTY_EMPTY" in {issue.code for issue in result.issues}


def test_authoring_qa_rejects_empty_narrative_role():
    raw = briefs().model_dump(mode="python")
    payload = dict(raw["pages"][0])
    payload["narrative_role"] = ""
    payload.pop("canonical_sha256", None)
    raw["pages"] = (payload, *raw["pages"][1:])
    raw.pop("canonical_sha256", None)
    assert "NARRATIVE_ROLE_EMPTY" in {
        issue.code for issue in evaluate_authoring(raw, semantic_model()).issues
    }


def test_authoring_qa_requires_unique_asset_directive_ownership_and_page_binding():
    directive = AssetDirectiveV4(
        directive_id="asset-1",
        page_id="page-1",
        role="evidence_example",
        purpose="evidence",
        supports_fragment_refs=("fragment-0",),
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


def test_authoring_qa_rejects_asset_fragment_support_that_is_missing_or_cross_page():
    pages = list(briefs().pages)
    directive = AssetDirectiveV4(
        directive_id="asset-cross-page",
        page_id="page-1",
        role="evidence_example",
        purpose="evidence",
        supports_fragment_refs=("fragment-2",),
        required=True,
        preferred_source="search",
        query_or_prompt="clean skincare evidence photo",
        orientation="portrait",
    )
    payload = pages[0].model_dump(mode="python")
    payload["asset_directives"] = (directive,)
    payload.pop("canonical_sha256", None)
    pages[0] = PageBriefV4(**payload, canonical_sha256=canonical_sha256_v4(payload))
    result = evaluate_authoring(
        recanonicalize_page_set(briefs(), pages=tuple(pages)),
        semantic_model(),
    )
    assert "ASSET_DIRECTIVE_FRAGMENT_CROSS_PAGE" in {
        issue.code for issue in result.issues
    }
