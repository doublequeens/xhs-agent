"""The first three family-neutral v4 Composition Grammars."""

from __future__ import annotations

from collections.abc import Iterable
from types import MappingProxyType

from src.schemas.v4.layout import (
    GRAMMAR_IDS_V4,
    CompositionGrammarV4,
    GrammarAlignmentAxisV4,
    GrammarConstraintV4,
    GrammarRegionV4,
    GrammarRelationshipV4,
    OrderedEnvelopeV4,
)


def _grammar(
    grammar_id: str,
    *,
    page_roles: tuple[str, ...],
    narrative_roles: tuple[str, ...],
    regions: tuple[tuple[str, str], ...],
    relationships: tuple[tuple[str, str, str, str], ...],
    axes: tuple[tuple[str, str, tuple[str, ...]], ...],
    behavior: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...], str], ...],
) -> CompositionGrammarV4:
    region_models = tuple(
        GrammarRegionV4(region_id=region_id, role=role)
        for region_id, role in regions
    )
    relationship_models = tuple(
        GrammarRelationshipV4(
            relationship_id=relationship_id,
            kind=kind,
            source_region_id=source_region_id,
            target_region_id=target_region_id,
        )
        for relationship_id, kind, source_region_id, target_region_id in relationships
    )
    axis_models = tuple(
        GrammarAlignmentAxisV4(
            axis_id=axis_id,
            orientation=orientation,
            region_ids=region_ids,
        )
        for axis_id, orientation, region_ids in axes
    )
    constraint_models = tuple(
        GrammarConstraintV4(
            constraint_id=constraint_id,
            kind=kind,
            region_ids=region_ids,
            axis_ids=axis_ids,
            behavior=constraint_behavior,
        )
        for constraint_id, kind, region_ids, axis_ids, constraint_behavior in behavior
    )
    return CompositionGrammarV4(
        grammar_id=grammar_id,
        allowed_page_roles=page_roles,
        allowed_narrative_roles=narrative_roles,
        region_roles=region_models,
        relationships=relationship_models,
        alignment_axes=axis_models,
        density_range=OrderedEnvelopeV4(low=0.1, high=0.9),
        constraints=constraint_models,
    )


EDITORIAL_HERO = _grammar(
    "editorial_hero",
    page_roles=("cover", "body", "closing"),
    narrative_roles=("cover_hook", "context", "summary", "closing"),
    regions=(
        ("hero", "primary"),
        ("support", "supporting"),
        ("accent", "accent"),
    ),
    relationships=(
        ("hero-support", "stack", "hero", "support"),
        ("support-accent", "anchor", "support", "accent"),
    ),
    axes=(
        ("hero-block", "block", ("hero", "support")),
        ("accent-inline", "inline", ("support", "accent")),
    ),
    behavior=(
        ("hero-focus", "single_focus", ("hero",), ("hero-block",), "preserve_primary_focus"),
        ("hero-reflow", "reflow_order", ("hero", "support", "accent"), ("hero-block",), "preserve_named_order"),
    ),
)

COMPARISON_GRID = _grammar(
    "comparison_grid",
    page_roles=("body",),
    narrative_roles=("diagnosis", "comparison", "evidence"),
    regions=(
        ("heading", "primary"),
        ("left", "comparison_primary"),
        ("right", "comparison_secondary"),
        ("support", "supporting"),
    ),
    relationships=(
        ("heading-grid", "stack", "heading", "left"),
        ("left-right", "pair", "left", "right"),
        ("grid-support", "anchor", "left", "support"),
    ),
    axes=(
        ("comparison-block", "block", ("heading", "left", "right")),
        ("comparison-inline", "inline", ("left", "right")),
    ),
    behavior=(
        ("paired-columns", "paired_regions", ("left", "right"), ("comparison-inline",), "preserve_pairing"),
        ("comparison-reflow", "reflow_order", ("heading", "left", "right", "support"), ("comparison-block",), "preserve_named_order"),
    ),
)

STEP_FLOW = _grammar(
    "step_flow",
    page_roles=("body",),
    narrative_roles=("step", "checklist"),
    regions=(
        ("heading", "primary"),
        ("sequence", "ordered_steps"),
        ("support", "supporting"),
    ),
    relationships=(
        ("heading-sequence", "stack", "heading", "sequence"),
        ("sequence-order", "sequence", "sequence", "support"),
    ),
    axes=(
        ("flow-block", "block", ("heading", "sequence", "support")),
        ("flow-inline", "inline", ("sequence", "support")),
    ),
    behavior=(
        ("ordered-sequence", "ordered_regions", ("sequence",), ("flow-block",), "preserve_sequence"),
        ("flow-reflow", "reflow_order", ("heading", "sequence", "support"), ("flow-block",), "preserve_named_order"),
    ),
)


def build_grammar_registry(
    definitions: Iterable[CompositionGrammarV4],
) -> MappingProxyType[str, CompositionGrammarV4]:
    """Validate duplicate IDs and return an immutable grammar registry."""

    registry: dict[str, CompositionGrammarV4] = {}
    for grammar in definitions:
        checked = CompositionGrammarV4.model_validate(grammar.model_dump(mode="python"))
        if checked.grammar_id in registry:
            raise ValueError(f"duplicate composition grammar ID: {checked.grammar_id}")
        registry[checked.grammar_id] = checked
    return MappingProxyType(registry)


GRAMMARS = build_grammar_registry((EDITORIAL_HERO, COMPARISON_GRID, STEP_FLOW))
GRAMMAR_REGISTRY = GRAMMARS
COMPOSITION_GRAMMARS = GRAMMARS


def get_grammar(grammar_id: str) -> CompositionGrammarV4:
    try:
        return GRAMMARS[grammar_id]
    except KeyError as exc:
        raise ValueError(f"composition grammar is unknown or not implemented: {grammar_id}") from exc


__all__ = [
    "COMPARISON_GRID",
    "COMPOSITION_GRAMMARS",
    "EDITORIAL_HERO",
    "GRAMMAR_REGISTRY",
    "GRAMMARS",
    "GRAMMAR_IDS_V4",
    "STEP_FLOW",
    "build_grammar_registry",
    "get_grammar",
]
