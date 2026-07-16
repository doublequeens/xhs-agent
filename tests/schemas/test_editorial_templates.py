import pytest
from pydantic import ValidationError

from src.schemas import CopyMetrics, ResolvedVariant, TemplateSelection


REJECTED_FAMILIES = {
    "pink_red": ["recent repetition"],
    "deep_teal": ["lower item-cardinality fit"],
    "soft_pink": ["lower density fit"],
    "coral_impact": ["lower tone fit"],
    "white_quote": ["dense list"],
}


def _copy_metrics(**overrides):
    metrics = {
        "grapheme_count": 42,
        "cjk_count": 32,
        "latin_word_count": 2,
        "emoji_count": 1,
        "block_count": 3,
        "item_count": 4,
        "max_item_graphemes": 12,
        "estimated_lines": 8,
    }
    metrics.update(overrides)
    return metrics


def test_template_selection_accepts_exactly_one_of_six_families():
    selection = TemplateSelection(
        template_family="green_catalog",
        score=82,
        reasons=["checklist affinity"],
        rejected_families=REJECTED_FAMILIES,
    )

    assert selection.template_family == "green_catalog"
    assert set(selection.rejected_families) == {
        "pink_red",
        "deep_teal",
        "soft_pink",
        "coral_impact",
        "white_quote",
    }


def test_template_selection_excludes_selected_family_from_rejections():
    rejected = dict(REJECTED_FAMILIES)
    rejected["green_catalog"] = ["must not reject selected family"]

    with pytest.raises(ValidationError):
        TemplateSelection(
            template_family="green_catalog",
            score=82,
            reasons=["checklist affinity"],
            rejected_families=rejected,
        )


def test_template_selection_requires_every_other_family():
    rejected = dict(REJECTED_FAMILIES)
    rejected.pop("white_quote")

    with pytest.raises(ValidationError):
        TemplateSelection(
            template_family="green_catalog",
            score=82,
            reasons=["checklist affinity"],
            rejected_families=rejected,
        )


def test_copy_metrics_rejects_negative_counts():
    with pytest.raises(ValidationError):
        CopyMetrics(**_copy_metrics(grapheme_count=-1))


def test_template_contracts_reject_extra_fields():
    with pytest.raises(ValidationError):
        CopyMetrics(**_copy_metrics(emoji_policy="forbidden"))


def test_resolved_variant_carries_density_composition_and_metrics():
    variant = ResolvedVariant(
        density="dense",
        composition_variant="catalog-grid-3x2",
        metrics=_copy_metrics(),
    )

    assert variant.density == "dense"
    assert variant.composition_variant == "catalog-grid-3x2"
    assert variant.metrics.emoji_count == 1


def test_copy_metrics_allow_content_without_emoji():
    metrics = CopyMetrics(**_copy_metrics(emoji_count=0))

    assert metrics.emoji_count == 0
