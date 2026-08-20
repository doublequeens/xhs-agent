"""Deterministic composition planning for the isolated v4 path."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.schemas.v4.content import canonical_sha256_v4
from src.schemas.v4.direction import CarouselNarrativeV4, PageBriefV4, TemplateFamilyV4
from src.schemas.v4.layout import (
    AssetPlacementV4,
    EmphasisRuleV4,
    FragmentPlacementV4,
    LayoutAlignmentAxisV4,
    LayoutProgramV4,
    LayoutRegionV4,
    ResponsiveConstraintV4,
    TASK_KIND_TO_PAGE_ROLE_V4,
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


def _checked_narrative(
    value: CarouselNarrativeV4 | Mapping[str, Any],
) -> CarouselNarrativeV4:
    raw = (
        value.model_dump(mode="python")
        if isinstance(value, CarouselNarrativeV4)
        else _tupleize(value)
    )
    if not isinstance(raw, Mapping):
        raise ValueError("build_layout_program requires a persisted CarouselNarrativeV4")
    try:
        checked = CarouselNarrativeV4.model_validate(raw)
        checked.validate_integrity()
    except Exception as exc:
        raise ValueError("carousel narrative is stale or has an invalid canonical hash") from exc
    return checked


def _support_region_id(region_ids: tuple[str, ...], roles: Mapping[str, str]) -> str:
    for region_id in region_ids:
        if roles[region_id] in {"supporting", "comparison_secondary", "accent"}:
            return region_id
    return region_ids[-1]


def build_layout_program(
    page_brief: PageBriefV4 | Mapping[str, Any],
    grammar_id: str,
    *,
    family: TemplateFamilyV4,
    narrative: CarouselNarrativeV4 | Mapping[str, Any],
) -> LayoutProgramV4:
    """Build a hash-bound structural program without rendering or provider calls.

    ``grammar_id`` is intentionally required to appear in the durable page
    brief's ``preferred_compositions``.  There is no fallback grammar: a page
    that has not explicitly selected this grammar fails closed.
    """

    page = _checked_page_brief(page_brief)
    checked_narrative = _checked_narrative(narrative)
    if not isinstance(family, str):
        raise ValueError("family must be an approved template family ID")
    selected_family = get_family_tokens(family)
    if checked_narrative.template_family != selected_family.family:
        raise ValueError("carousel narrative template_family does not match family")
    matching_beats = tuple(
        beat for beat in checked_narrative.beats if beat.beat_id == page.beat_ref
    )
    if len(matching_beats) != 1:
        raise ValueError("page brief beat_ref must resolve to exactly one narrative beat")
    beat = matching_beats[0]
    if beat.sequence != page.sequence:
        raise ValueError("narrative beat sequence does not match page brief sequence")
    if tuple(beat.fragment_refs) != tuple(page.fragment_refs):
        raise ValueError("narrative beat fragment_refs do not match page brief fragment_refs")
    if grammar_id not in page.preferred_compositions:
        raise ValueError(
            f"grammar {grammar_id!r} is not present in page brief preferred compositions"
        )
    grammar = get_grammar(grammar_id)
    if beat.task_kind not in grammar.allowed_narrative_roles:
        raise ValueError(
            f"narrative beat task_kind {beat.task_kind!r} is incompatible with grammar {grammar_id!r}"
        )
    page_role = TASK_KIND_TO_PAGE_ROLE_V4.get(beat.task_kind)
    if page_role is None or page_role not in grammar.allowed_page_roles:
        raise ValueError(
            f"derived page role {page_role!r} is incompatible with grammar {grammar_id!r}"
        )
    target_values = {"low": 0.25, "medium": 0.5, "high": 0.75}
    density_value = target_values[page.density_budget]
    if not grammar.density_range.low <= density_value <= grammar.density_range.high:
        raise ValueError(
            f"density target {page.density_budget!r} is outside grammar {grammar_id!r} density range"
        )
    if not (
        selected_family.density_envelope.low
        <= density_value
        <= selected_family.density_envelope.high
    ):
        raise ValueError(
            f"density target {page.density_budget!r} is outside family {family!r} density envelope"
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
    visual_priority = tuple(page.visual_priority)
    if (
        not visual_priority
        or len(set(visual_priority)) != len(visual_priority)
        or any(fragment_ref not in set(fragment_refs) for fragment_ref in visual_priority)
    ):
        raise ValueError("visual_priority must be unique and page-local fragment references")
    emphasis_rules = tuple(
        EmphasisRuleV4(
            rule_id=f"emphasis-{index}",
            kind="primary_focus" if index == 0 else "secondary_focus",
            target_fragment_refs=(fragment_ref,),
            priority=index,
        )
        for index, fragment_ref in enumerate(visual_priority)
    )
    emphasis_by_fragment = {
        fragment_ref: (f"emphasis-{index}",)
        for index, fragment_ref in enumerate(visual_priority)
    }
    fragment_placements = tuple(
        FragmentPlacementV4(
            fragment_ref=fragment_ref,
            region_id=region_ids[index % len(region_ids)],
            order=index,
            emphasis_rule_ids=emphasis_by_fragment.get(fragment_ref, ()),
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
        "template_family": selected_family.family,
        "family_tokens_sha256": selected_family.canonical_sha256,
        "carousel_narrative_sha256": checked_narrative.canonical_sha256,
        "beat_ref": beat.beat_id,
        "beat_task_kind": beat.task_kind,
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
