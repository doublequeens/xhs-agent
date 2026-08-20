"""Deterministic composition planning for the isolated v4 path."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.schemas.v4.content import canonical_sha256_v4
from src.schemas.v4.direction import PageBriefV4
from src.schemas.v4.layout import (
    AssetPlacementV4,
    EmphasisRuleV4,
    FamilyTokensV4,
    FragmentPlacementV4,
    LayoutAlignmentAxisV4,
    LayoutProgramV4,
    LayoutRegionV4,
    ResponsiveConstraintV4,
)
from src.visual_design.v4.grammars import get_grammar
from src.visual_design.v4.tokens import get_family_tokens


def _tupleize(value: Any) -> Any:
    """Normalize JSON arrays before entering the strict durable direction model."""

    if isinstance(value, Mapping):
        return {key: _tupleize(item) for key, item in value.items()}
    if isinstance(value, list):
        return tuple(_tupleize(item) for item in value)
    return value


def _checked_page_brief(value: PageBriefV4 | Mapping[str, Any]) -> PageBriefV4:
    raw = value.model_dump(mode="python") if isinstance(value, PageBriefV4) else _tupleize(value)
    if not isinstance(raw, Mapping):
        raise ValueError("build_layout_program requires a persisted PageBriefV4")
    try:
        checked = PageBriefV4.model_validate(raw)
        checked.validate_integrity()
    except Exception as exc:
        raise ValueError("page brief is stale or has an invalid canonical hash") from exc
    return checked


def _checked_family_tokens(
    family_tokens: FamilyTokensV4 | Mapping[str, Any] | str | None,
    family: str | None,
) -> FamilyTokensV4 | None:
    selected: FamilyTokensV4 | None = None
    if family_tokens is not None:
        if isinstance(family_tokens, str):
            selected = get_family_tokens(family_tokens)
        elif isinstance(family_tokens, FamilyTokensV4):
            selected = FamilyTokensV4.model_validate(
                family_tokens.model_dump(mode="python")
            )
        elif isinstance(family_tokens, Mapping):
            try:
                selected = FamilyTokensV4.model_validate(family_tokens)
            except Exception as exc:
                raise ValueError("family tokens are invalid") from exc
        else:
            raise ValueError("family tokens must be a family ID or FamilyTokensV4")
    if family is not None:
        named = get_family_tokens(family)
        if selected is not None and selected.family != named.family:
            raise ValueError("family tokens and family argument are incompatible")
        selected = named
    return selected


def _support_region_id(region_ids: tuple[str, ...], roles: Mapping[str, str]) -> str:
    for region_id in region_ids:
        if roles[region_id] in {"supporting", "comparison_secondary", "accent"}:
            return region_id
    return region_ids[-1]


def build_layout_program(
    page_brief: PageBriefV4 | Mapping[str, Any],
    grammar_id: str,
    family_tokens: FamilyTokensV4 | Mapping[str, Any] | str | None = None,
    *,
    family: str | None = None,
) -> LayoutProgramV4:
    """Build a hash-bound structural program without rendering or provider calls.

    ``grammar_id`` is intentionally required to appear in the durable page
    brief's ``preferred_compositions``.  There is no fallback grammar: a page
    that has not explicitly selected this grammar fails closed.
    """

    page = _checked_page_brief(page_brief)
    if grammar_id not in page.preferred_compositions:
        raise ValueError(
            f"grammar {grammar_id!r} is not present in page brief preferred compositions"
        )
    grammar = get_grammar(grammar_id)
    allowed_roles = set(grammar.allowed_page_roles) | set(grammar.allowed_narrative_roles)
    if page.narrative_role not in allowed_roles:
        raise ValueError(
            f"page narrative role {page.narrative_role!r} is incompatible with grammar {grammar_id!r}"
        )
    selected_family = _checked_family_tokens(family_tokens, family)

    target_values = {"low": 0.25, "medium": 0.5, "high": 0.75}
    density_value = target_values[page.density_budget]
    if not grammar.density_range.low <= density_value <= grammar.density_range.high:
        raise ValueError(
            f"density target {page.density_budget!r} is outside grammar {grammar_id!r} density range"
        )

    region_roles = {region.region_id: region.role for region in grammar.region_roles}
    regions = tuple(
        LayoutRegionV4(region_id=region.region_id, role=region.role, order=index)
        for index, region in enumerate(grammar.region_roles)
    )
    region_ids = tuple(region.region_id for region in regions)

    fragment_refs = tuple(page.fragment_refs)
    if len(set(fragment_refs)) != len(fragment_refs):
        raise ValueError("page brief fragment references must be unique for composition")
    fragment_placements = tuple(
        FragmentPlacementV4(
            fragment_ref=fragment_ref,
            region_id=region_ids[index % len(region_ids)],
            order=index,
        )
        for index, fragment_ref in enumerate(fragment_refs)
    )

    directives = tuple(page.asset_directives)
    directive_ids = tuple(directive.directive_id for directive in directives)
    if len(set(directive_ids)) != len(directive_ids):
        raise ValueError("page brief asset directive IDs must be unique")
    fragment_set = set(fragment_refs)
    for directive in directives:
        if directive.page_id != page.page_id:
            raise ValueError("asset directive belongs to a different page")
        if any(fragment_ref not in fragment_set for fragment_ref in directive.supports_fragment_refs):
            raise ValueError("asset directive references a fragment outside this page")
    support_region = _support_region_id(region_ids, region_roles)
    asset_placements = tuple(
        AssetPlacementV4(
            directive_id=directive.directive_id,
            region_id=support_region,
            order=index,
        )
        for index, directive in enumerate(directives)
    )

    emphasis_rules = (
        EmphasisRuleV4(
            rule_id="primary-focus",
            kind="primary_focus",
            target_fragment_refs=(fragment_refs[0],),
            priority=0,
        ),
    )
    alignment_axes = tuple(
        LayoutAlignmentAxisV4(
            axis_id=axis.axis_id,
            orientation=axis.orientation,
            region_ids=axis.region_ids,
        )
        for axis in grammar.alignment_axes
    )
    responsive_constraints = tuple(
        ResponsiveConstraintV4(
            constraint_id=constraint.constraint_id,
            kind=constraint.kind,
            region_ids=constraint.region_ids,
            axis_ids=constraint.axis_ids,
            behavior=constraint.behavior,
        )
        for constraint in grammar.constraints
    )
    payload = {
        "page_id": page.page_id,
        "page_brief_sha256": page.canonical_sha256,
        "grammar_id": grammar.grammar_id,
        "template_family": selected_family.family if selected_family is not None else None,
        "regions": regions,
        "fragment_placements": fragment_placements,
        "asset_placements": asset_placements,
        "emphasis_rules": emphasis_rules,
        "alignment_axes": alignment_axes,
        "density_target": page.density_budget,
        "responsive_constraints": responsive_constraints,
    }
    canonical_source = LayoutProgramV4.model_construct(
        **payload,
        canonical_sha256="0" * 64,
    ).model_dump(
        mode="json",
        exclude={"canonical_sha256"},
        exclude_none=True,
    )
    return LayoutProgramV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(canonical_source),
    )


__all__ = ["build_layout_program"]
