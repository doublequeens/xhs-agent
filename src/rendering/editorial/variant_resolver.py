from __future__ import annotations

from typing import get_args

from src.schemas.editorial_templates import (
    CopyMetrics,
    Density,
    DensityHint,
    PageArchetype,
    ResolvedVariant,
    TemplateFamily,
)

from .template_registry import TEMPLATE_REGISTRY


class VariantResolutionError(ValueError):
    """Raised when measured copy cannot satisfy a requested variant contract."""


_ITEM_LIMIT_BY_DENSITY: dict[Density, int] = {
    "sparse": 2,
    "standard": 4,
    "dense": 6,
}


def _auto_density(capability, metrics: CopyMetrics) -> Density:
    if (
        metrics.grapheme_count <= capability.sparse_max_graphemes
        and metrics.item_count <= _ITEM_LIMIT_BY_DENSITY["sparse"]
    ):
        return "sparse"
    if (
        metrics.grapheme_count <= capability.standard_max_graphemes
        and metrics.item_count <= _ITEM_LIMIT_BY_DENSITY["standard"]
    ):
        return "standard"
    return "dense"


def _resolve_density(
    capability,
    hint: DensityHint,
    metrics: CopyMetrics,
) -> Density:
    if hint == "auto":
        return _auto_density(capability, metrics)
    max_graphemes = getattr(capability, f"{hint}_max_graphemes")
    if (
        metrics.grapheme_count > max_graphemes
        or metrics.item_count > _ITEM_LIMIT_BY_DENSITY[hint]
    ):
        raise VariantResolutionError(
            f"measured copy does not fit requested {hint} density"
        )
    return hint


def _composition(
    archetype: PageArchetype,
    density: Density,
    item_count: int,
    variants: tuple[str, ...],
) -> str:
    focus = variants[0]
    stacked = variants[-2] if len(variants) > 1 else variants[0]
    grid = variants[-1]
    if archetype in {"item_collection", "checklist"}:
        return stacked if item_count <= 3 else grid
    if archetype == "comparison":
        return grid if item_count in {2, 4} else stacked
    if archetype == "steps":
        return stacked if item_count <= 4 else grid
    if archetype == "quote":
        return focus if density == "sparse" else stacked
    if (
        "red-panel" in variants
        and archetype in {"thesis", "story_beat", "boundary", "closing"}
        and density != "dense"
    ):
        return "red-panel"
    if density == "sparse":
        return focus
    if density == "dense":
        return grid
    return stacked


def resolve_variant(
    family: TemplateFamily | str,
    archetype: PageArchetype | str,
    hint: DensityHint,
    metrics: CopyMetrics,
) -> ResolvedVariant:
    if family not in get_args(TemplateFamily):
        raise VariantResolutionError(f"unknown template family: {family}")
    if archetype not in get_args(PageArchetype):
        raise VariantResolutionError(f"unknown page archetype: {archetype}")
    if hint not in get_args(DensityHint):
        raise VariantResolutionError(f"unknown density hint: {hint}")

    definition = TEMPLATE_REGISTRY[family]
    capability = definition.archetypes[archetype]
    density = _resolve_density(capability, hint, metrics)
    return ResolvedVariant(
        density=density,
        composition_variant=_composition(
            archetype,
            density,
            metrics.item_count,
            capability.composition_variants,
        ),
        metrics=metrics,
    )
