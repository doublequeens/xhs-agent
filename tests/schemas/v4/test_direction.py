from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.schemas.v4.content import canonical_sha256_v4
from src.schemas.v4.direction import (
    ALLOWED_COMPOSITIONS_V4,
    TEMPLATE_FAMILIES_V4,
    AssetDirectiveDraftV4,
    AssetDirectiveV4,
    CarouselNarrativeV4,
    NarrativeBeatV4,
    PageBriefV4,
    PageBriefSetDraftV4,
    PageBriefSetV4,
    VisualAuthoringDraftV4,
)


def _narrative(page_count: int = 5) -> CarouselNarrativeV4:
    payload = {
        "template_family": "pink_red",
        "page_count": page_count,
        "beats": tuple(
            NarrativeBeatV4(
                beat_id=f"beat-{index}",
                sequence=index + 1,
                task=f"task-{index}",
            )
            for index in range(page_count)
        ),
        "density_curve": tuple("low" for _ in range(page_count)),
        "variation_strategy": "alternate editorial structures",
        "continuity_strategy": "repeat one accent and carry one cue",
        "art_direction": "clean editorial skincare direction",
    }
    from src.schemas.v4.content import canonical_sha256_v4

    return CarouselNarrativeV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def test_direction_schema_freezes_nested_semantics_and_rejects_geometry_or_visible_copy():
    assert set(TEMPLATE_FAMILIES_V4) == {
        "pink_red",
        "deep_teal",
        "soft_pink",
        "coral_impact",
        "green_catalog",
        "white_quote",
    }
    assert set(ALLOWED_COMPOSITIONS_V4) == {
        "editorial_hero",
        "comparison_grid",
        "step_flow",
        "diagnostic_matrix",
        "checklist",
        "evidence_card",
        "image_annotation",
        "summary_closing",
    }

    narrative = _narrative()
    with pytest.raises((TypeError, ValidationError)):
        narrative.beats += ("unexpected",)
    with pytest.raises(ValidationError):
        CarouselNarrativeV4.model_validate(
            {
                **narrative.model_dump(mode="python"),
                "x": 1,
            }
        )

    with pytest.raises(ValidationError):
        AssetDirectiveV4.model_validate(
            {
                "directive_id": "asset-1",
                "page_id": "page-1",
                "role": "evidence",
                "preferred_source": "search",
                "fallback_source": "none",
                "query_or_prompt": "a clean skincare detail",
                "orientation": "portrait",
                "min_width": 1080,
                "min_height": 1440,
                "visible_text": "forbidden",
            }
        )
    with pytest.raises(ValidationError):
        AssetDirectiveV4.model_validate(
            {
                "directive_id": "asset-small",
                "page_id": "page-1",
                "role": "evidence_example",
                "purpose": "evidence",
                "supports_fragment_refs": ("fragment-1",),
                "preferred_source": "search",
                "query_or_prompt": "a clean skincare detail",
                "min_width": 720,
                "min_height": 1080,
            }
        )


def test_direction_rejects_non_contiguous_page_sequences_and_invalid_composition():
    from src.schemas.v4.direction import PageBriefV4

    page_payload = {
        "page_id": "page-1",
        "sequence": 1,
        "narrative_role": "opening",
        "beat_ref": "beat-0",
        "fragment_refs": ("fragment-1",),
        "visual_priority": ("fragment-1",),
        "density_budget": "low",
        "preferred_compositions": ("editorial_hero",),
        "forbidden_patterns": (),
        "asset_directives": (),
        "continuity_with_previous": "none",
    }
    page = PageBriefV4(
        **page_payload,
        canonical_sha256=canonical_sha256_v4(page_payload),
    )
    with pytest.raises(ValidationError):
        PageBriefSetV4(
            page_count=5,
            pages=(page,),
            canonical_sha256="0" * 64,
        )
    with pytest.raises(ValidationError):
        PageBriefV4(
            page_id="page-1",
            sequence=1,
            narrative_role="opening",
            fragment_refs=("fragment-1",),
            visual_priority=("fragment-1",),
            density_budget="low",
            preferred_compositions=("not-a-composition",),
            forbidden_patterns=(),
            asset_directives=(),
            continuity_with_previous="none",
            canonical_sha256="0" * 64,
        )


def test_provider_draft_has_no_visible_text_or_geometry_fields():
    assert not {"min_width", "min_height", "resolution"}.intersection(
        AssetDirectiveDraftV4.model_fields
    )
    with pytest.raises(ValidationError):
        VisualAuthoringDraftV4.model_validate(
            {
                "narrative": {
                    "template_family": "pink_red",
                    "page_count": 5,
                    "beats": ["a", "b", "c", "d", "e"],
                    "density_curve": ["low", "low", "low", "low", "low"],
                    "variation_strategy": "vary",
                    "continuity_strategy": "carry",
                    "art_direction": "editorial",
                    "visible_text": "should never be accepted",
                },
                "page_brief_set": PageBriefSetDraftV4(pages=()),
            }
        )

    with pytest.raises(ValidationError):
        AssetDirectiveDraftV4(
            directive_id="asset-1",
            page_id="page-1",
            role="evidence_example",
            purpose="evidence",
            supports_fragment_refs=("fragment-1",),
            preferred_source="generate",
            query_or_prompt="add text label saying skincare",
        )


def test_durable_page_brief_requires_non_empty_semantic_duties():
    payload = {
        "page_id": "page-1",
        "sequence": 1,
        "narrative_role": "opening",
        "beat_ref": "beat-0",
        "fragment_refs": (),
        "visual_priority": (),
        "density_budget": "low",
        "preferred_compositions": (),
        "forbidden_patterns": (),
        "asset_directives": (),
        "continuity_with_previous": "none",
    }
    with pytest.raises(ValidationError):
        PageBriefV4(**payload, canonical_sha256=canonical_sha256_v4(payload))


def test_durable_page_brief_set_rejects_bounds_length_and_non_contiguous_sequences():
    pages = []
    for index in range(5):
        payload = {
            "page_id": f"page-{index + 1}",
            "sequence": index + 1,
            "narrative_role": f"role-{index + 1}",
            "beat_ref": f"beat-{index}",
            "fragment_refs": (f"fragment-{index}",),
            "visual_priority": (f"fragment-{index}",),
            "density_budget": "low",
            "preferred_compositions": ("editorial_hero",),
            "forbidden_patterns": (),
            "asset_directives": (),
            "continuity_with_previous": "none" if index == 0 else "carry",
        }
        pages.append(
            PageBriefV4(
                **payload,
                canonical_sha256=canonical_sha256_v4(payload),
            )
        )
    set_payload = {"page_count": 5, "pages": tuple(pages)}
    good = PageBriefSetV4(
        **set_payload,
        canonical_sha256=canonical_sha256_v4(set_payload),
    )
    assert good.page_count == 5
    for page_count, page_subset in ((4, tuple(pages[:4])), (5, tuple(pages[:4]))):
        payload = {"page_count": page_count, "pages": page_subset}
        with pytest.raises(ValidationError):
            PageBriefSetV4(
                **payload,
                canonical_sha256=canonical_sha256_v4(payload),
            )
    changed = list(pages)
    changed[1] = changed[1].model_copy(update={"sequence": 3})
    changed_payload = {"page_count": 5, "pages": tuple(changed)}
    with pytest.raises(ValidationError):
        PageBriefSetV4(
            **changed_payload,
            canonical_sha256=canonical_sha256_v4(changed_payload),
        )
