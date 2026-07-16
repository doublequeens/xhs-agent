from __future__ import annotations

import pytest

from src.schemas import CopyMetrics


def _metrics(
    *,
    grapheme_count: int,
    item_count: int,
    max_item_graphemes: int = 0,
) -> CopyMetrics:
    return CopyMetrics(
        grapheme_count=grapheme_count,
        cjk_count=grapheme_count,
        latin_word_count=0,
        emoji_count=0,
        block_count=1,
        item_count=item_count,
        max_item_graphemes=max_item_graphemes,
        estimated_lines=max(1, grapheme_count // 18),
    )


def test_dense_collection_uses_grid_but_sparse_quote_uses_focus():
    from src.rendering.editorial.variant_resolver import resolve_variant

    dense = resolve_variant(
        "green_catalog",
        "item_collection",
        "auto",
        _metrics(grapheme_count=150, item_count=6),
    )
    sparse = resolve_variant(
        "white_quote",
        "quote",
        "auto",
        _metrics(grapheme_count=24, item_count=0),
    )

    assert dense.density == "dense"
    assert dense.composition_variant == "catalog-grid"
    assert sparse.density == "sparse"
    assert sparse.composition_variant == "centered-focus"


@pytest.mark.parametrize(
    ("item_count", "expected"),
    [
        (2, "catalog-card"),
        (4, "catalog-grid"),
        (6, "catalog-grid"),
    ],
)
def test_collection_composition_follows_item_cardinality(item_count, expected):
    from src.rendering.editorial.variant_resolver import resolve_variant

    variant = resolve_variant(
        "green_catalog",
        "checklist",
        "auto",
        _metrics(grapheme_count=20 * item_count, item_count=item_count),
    )

    assert variant.composition_variant == expected


@pytest.mark.parametrize(
    ("archetype", "item_count", "expected"),
    [
        ("comparison", 2, "split-card"),
        ("comparison", 3, "white-card"),
        ("steps", 4, "white-card"),
        ("steps", 6, "split-card"),
    ],
)
def test_structural_archetypes_choose_split_or_stacked_variants(
    archetype,
    item_count,
    expected,
):
    from src.rendering.editorial.variant_resolver import resolve_variant

    variant = resolve_variant(
        "pink_red",
        archetype,
        "auto",
        _metrics(grapheme_count=18 * item_count, item_count=item_count),
    )

    assert variant.composition_variant == expected


def test_explicit_density_hint_is_allowed_only_when_measured_copy_fits():
    from src.rendering.editorial.variant_resolver import (
        VariantResolutionError,
        resolve_variant,
    )

    sparse = resolve_variant(
        "soft_pink",
        "explanation",
        "sparse",
        _metrics(grapheme_count=24, item_count=1),
    )
    assert sparse.density == "sparse"

    with pytest.raises(VariantResolutionError, match="sparse"):
        resolve_variant(
            "soft_pink",
            "explanation",
            "sparse",
            _metrics(grapheme_count=120, item_count=5),
        )


def test_resolved_variant_preserves_the_exact_metrics_object():
    from src.rendering.editorial.variant_resolver import resolve_variant

    metrics = _metrics(grapheme_count=70, item_count=3)

    variant = resolve_variant("deep_teal", "qa", "auto", metrics)

    assert variant.metrics is metrics


@pytest.mark.parametrize(
    ("family", "archetype"),
    [
        ("unknown", "quote"),
        ("white_quote", "unknown"),
    ],
)
def test_variant_resolution_rejects_unknown_contract_values(family, archetype):
    from src.rendering.editorial.variant_resolver import (
        VariantResolutionError,
        resolve_variant,
    )

    with pytest.raises(VariantResolutionError):
        resolve_variant(
            family,
            archetype,
            "auto",
            _metrics(grapheme_count=10, item_count=0),
        )
