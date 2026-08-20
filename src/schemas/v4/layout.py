"""Immutable structural-intent contracts for the v4 layout boundary.

This module deliberately stops at named regions and relationships.  It does
not model typography measurements, geometry, renderer primitives, visible
copy, provider data, or executable markup; those concerns belong to later
v4 stages.
"""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator

from src.schemas.v4.content import canonical_sha256_v4
from src.schemas.v4.direction import (
    DensityLevelV4,
    NarrativeTaskKindV4,
    TemplateFamilyV4,
)


GRAMMAR_IDS_V4 = ("editorial_hero", "comparison_grid", "step_flow")
ImplementedGrammarIDV4 = Literal["editorial_hero", "comparison_grid", "step_flow"]
PAGE_ROLES_V4 = ("cover", "body", "closing")
PageRoleV4 = Literal["cover", "body", "closing"]
TASK_KIND_TO_PAGE_ROLE_V4 = MappingProxyType(
    {
        "cover_hook": "cover",
        "context": "body",
        "diagnosis": "body",
        "step": "body",
        "comparison": "body",
        "checklist": "body",
        "evidence": "body",
        "summary": "closing",
        "closing": "closing",
    }
)
ABSTRACT_SPACING_SCALE_V4 = ("none", "xs", "sm", "md", "lg", "xl", "xxl")
ABSTRACT_RADII_V4 = ("none", "sm", "md", "lg", "pill")

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_STYLE_TOKEN_RE = re.compile(r"^[A-Za-z0-9]+(?:[ -][A-Za-z0-9]+)*$")
_FORBIDDEN_STYLE_TOKENS = frozenset(
    {
        "provider",
        "provenance",
        "pexels",
        "unsplash",
        "gemini",
        "ai",
        "openai",
        "javascript",
        "script",
        "document",
        "innerhtml",
        "dom",
        "html",
        "css",
        "localpath",
    }
)
_EVENT_HANDLER_TOKENS = frozenset(
    {
        "onclick",
        "ondblclick",
        "onmousedown",
        "onmouseup",
        "onmousemove",
        "onmouseover",
        "onmouseout",
        "onmouseenter",
        "onmouseleave",
        "onwheel",
        "onkeydown",
        "onkeypress",
        "onkeyup",
        "oninput",
        "onchange",
        "onsubmit",
        "onfocus",
        "onblur",
        "onload",
        "onerror",
        "onabort",
        "onbeforeinput",
        "oncopy",
        "oncut",
        "onpaste",
        "oncontextmenu",
        "ondrag",
        "ondragstart",
        "ondragend",
        "ondrop",
        "ontouchstart",
        "ontouchend",
        "onpointerdown",
        "onpointerup",
        "onanimationstart",
        "onanimationend",
        "ontransitionend",
    }
)


def _validate_hash(value: str, field_name: str) -> str:
    if not _HASH_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase sha256")
    return value


def _validate_identifier(value: str, field_name: str) -> str:
    if not value.strip() or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(
            f"{field_name} must be a non-empty structural identifier without copy or paths"
        )
    return value


def _validate_identifiers(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if not values:
        raise ValueError(f"{field_name} must not be empty")
    for value in values:
        _validate_identifier(value, field_name)
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} identifiers must be unique")
    return tuple(values)


def _validate_style_text(value: str, field_name: str) -> str:
    if not value.strip() or not _STYLE_TOKEN_RE.fullmatch(value):
        raise ValueError(
            f"{field_name} must be allowlisted structural/style-token text"
        )
    tokens = tuple(re.findall(r"[a-z0-9]+", value.lower()))
    collapsed = "".join(tokens)
    if (
        any(token in _FORBIDDEN_STYLE_TOKENS for token in tokens)
        or any(token in _EVENT_HANDLER_TOKENS for token in tokens)
        or "localpath" in collapsed
    ):
        raise ValueError(f"{field_name} contains a forbidden semantic style token")
    return value


def _validate_descriptions(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if not values or any(not value.strip() for value in values):
        raise ValueError(f"{field_name} must not contain empty entries")
    return tuple(_validate_style_text(value, field_name) for value in values)


class _FrozenLayoutV4(BaseModel):
    """All persisted layout values are immutable and reject unknown fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class OrderedEnvelopeV4(_FrozenLayoutV4):
    """An abstract normalized range, never a pixel or coordinate range."""

    low: float = Field(ge=0, le=1)
    high: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_order(self) -> "OrderedEnvelopeV4":
        if self.low > self.high:
            raise ValueError("range low must not exceed high")
        return self

    @property
    def minimum(self) -> float:
        return self.low

    @property
    def maximum(self) -> float:
        return self.high


class TypographyRolesV4(_FrozenLayoutV4):
    """The four semantic font roles; measurements are deferred to Task 11."""

    display: StrictStr = Field(min_length=1)
    heading: StrictStr = Field(min_length=1)
    body: StrictStr = Field(min_length=1)
    caption: StrictStr = Field(min_length=1)

    @field_validator("display", "heading", "body", "caption")
    @classmethod
    def validate_font_role(cls, value: str, info) -> str:
        return _validate_style_text(value, info.field_name)


class MotifRulesV4(_FrozenLayoutV4):
    """Family motifs expressed as semantic tokens, not DOM/CSS snippets."""

    allowed: tuple[StrictStr, ...] = Field(min_length=1)
    prohibited: tuple[StrictStr, ...] = Field(min_length=1)

    @field_validator("allowed", "prohibited")
    @classmethod
    def validate_motif_names(cls, value: tuple[str, ...], info) -> tuple[str, ...]:
        return _validate_descriptions(value, info.field_name)


class FamilyTokensV4(_FrozenLayoutV4):
    """Immutable design DNA derived from one approved style profile."""

    family: TemplateFamilyV4
    palette: tuple[StrictStr, ...] = Field(min_length=3)
    font_roles: TypographyRolesV4
    spacing_scale: tuple[StrictStr, ...] = Field(min_length=1)
    radii: tuple[StrictStr, ...] = Field(min_length=1)
    motif_rules: MotifRulesV4
    whitespace_envelope: OrderedEnvelopeV4
    density_envelope: OrderedEnvelopeV4
    composition_principles: tuple[StrictStr, ...] = Field(min_length=1)
    canonical_sha256: StrictStr

    @field_validator("palette")
    @classmethod
    def validate_palette(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("palette entries must be unique")
        for color in value:
            if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
                raise ValueError("palette entries must be six-digit hex colors")
        return tuple(value)

    @field_validator("spacing_scale", "radii")
    @classmethod
    def validate_token_names(cls, value: tuple[str, ...], info) -> tuple[str, ...]:
        allowed = (
            ABSTRACT_SPACING_SCALE_V4
            if info.field_name == "spacing_scale"
            else ABSTRACT_RADII_V4
        )
        _validate_identifiers(value, info.field_name)
        if any(item not in allowed for item in value):
            raise ValueError(f"{info.field_name} contains an unknown abstract token")
        return tuple(value)

    @field_validator("composition_principles")
    @classmethod
    def validate_principles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_descriptions(value, "composition_principles")

    @field_validator("canonical_sha256")
    @classmethod
    def validate_canonical_shape(cls, value: str) -> str:
        return _validate_hash(value, "canonical_sha256")

    @model_validator(mode="after")
    def validate_canonical_hash(self) -> "FamilyTokensV4":
        expected = canonical_sha256_v4(
            self.model_dump(mode="json", exclude={"canonical_sha256"})
        )
        if self.canonical_sha256 != expected:
            raise ValueError("family token canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))

    @property
    def typography_roles(self) -> TypographyRolesV4:
        """Readable alias matching the design-spec terminology."""

        return self.font_roles


class GrammarRegionV4(_FrozenLayoutV4):
    """A named semantic region in a composition grammar."""

    region_id: StrictStr = Field(min_length=1)
    role: StrictStr = Field(min_length=1)

    @field_validator("region_id", "role")
    @classmethod
    def validate_region_tokens(cls, value: str, info) -> str:
        return _validate_identifier(value, info.field_name)


RelationshipKindV4 = Literal[
    "stack",
    "pair",
    "sequence",
    "contain",
    "anchor",
    "contrast",
]


class GrammarRelationshipV4(_FrozenLayoutV4):
    """A legal named relationship between grammar regions."""

    relationship_id: StrictStr = Field(min_length=1)
    kind: RelationshipKindV4
    source_region_id: StrictStr = Field(min_length=1)
    target_region_id: StrictStr = Field(min_length=1)

    @field_validator("relationship_id", "source_region_id", "target_region_id")
    @classmethod
    def validate_relationship_tokens(cls, value: str, info) -> str:
        return _validate_identifier(value, info.field_name)


AlignmentOrientationV4 = Literal["inline", "block", "baseline", "center", "edge"]


class GrammarAlignmentAxisV4(_FrozenLayoutV4):
    """An abstract alignment axis shared by one or more named regions."""

    axis_id: StrictStr = Field(min_length=1)
    orientation: AlignmentOrientationV4
    region_ids: tuple[StrictStr, ...] = Field(min_length=1)

    @field_validator("axis_id")
    @classmethod
    def validate_axis_id(cls, value: str) -> str:
        return _validate_identifier(value, "axis_id")

    @field_validator("region_ids")
    @classmethod
    def validate_axis_regions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_identifiers(value, "region_ids")


class GrammarConstraintV4(_FrozenLayoutV4):
    """A symbolic constraint consumed by the future deterministic compiler."""

    constraint_id: StrictStr = Field(min_length=1)
    kind: StrictStr = Field(min_length=1)
    region_ids: tuple[StrictStr, ...] = ()
    axis_ids: tuple[StrictStr, ...] = ()
    behavior: StrictStr = Field(min_length=1)

    @field_validator("constraint_id", "kind", "behavior")
    @classmethod
    def validate_constraint_tokens(cls, value: str, info) -> str:
        return _validate_identifier(value, info.field_name)

    @field_validator("region_ids", "axis_ids")
    @classmethod
    def validate_constraint_refs(cls, value: tuple[str, ...], info) -> tuple[str, ...]:
        if not value:
            return ()
        return _validate_identifiers(value, info.field_name)


class CompositionGrammarV4(_FrozenLayoutV4):
    """Family-neutral composition language, not a render-ready template."""

    grammar_id: StrictStr = Field(min_length=1)
    allowed_page_roles: tuple[PageRoleV4, ...] = Field(min_length=1)
    allowed_narrative_roles: tuple[NarrativeTaskKindV4, ...] = Field(min_length=1)
    region_roles: tuple[GrammarRegionV4, ...] = Field(min_length=1)
    relationships: tuple[GrammarRelationshipV4, ...] = Field(min_length=1)
    alignment_axes: tuple[GrammarAlignmentAxisV4, ...] = Field(min_length=1)
    density_range: OrderedEnvelopeV4
    constraints: tuple[GrammarConstraintV4, ...] = Field(min_length=1)

    @field_validator("grammar_id")
    @classmethod
    def validate_grammar_id(cls, value: str) -> str:
        return _validate_identifier(value, "grammar_id")

    @field_validator("allowed_page_roles", "allowed_narrative_roles")
    @classmethod
    def validate_role_tokens(cls, value: tuple[str, ...], info) -> tuple[str, ...]:
        return _validate_identifiers(value, info.field_name)

    @model_validator(mode="after")
    def validate_relationship_integrity(self) -> "CompositionGrammarV4":
        region_ids = tuple(region.region_id for region in self.region_roles)
        if len(set(region_ids)) != len(region_ids):
            raise ValueError("grammar region IDs must be unique")
        axis_ids = tuple(axis.axis_id for axis in self.alignment_axes)
        if len(set(axis_ids)) != len(axis_ids):
            raise ValueError("grammar alignment axis IDs must be unique")
        relationship_ids = tuple(item.relationship_id for item in self.relationships)
        if len(set(relationship_ids)) != len(relationship_ids):
            raise ValueError("grammar relationship IDs must be unique")
        constraint_ids = tuple(item.constraint_id for item in self.constraints)
        if len(set(constraint_ids)) != len(constraint_ids):
            raise ValueError("grammar constraint IDs must be unique")

        region_set = set(region_ids)
        axis_set = set(axis_ids)
        for relationship in self.relationships:
            if relationship.source_region_id not in region_set or relationship.target_region_id not in region_set:
                raise ValueError("grammar relationship references an unknown region")
        for axis in self.alignment_axes:
            if any(region_id not in region_set for region_id in axis.region_ids):
                raise ValueError("grammar alignment axis references an unknown region")
        for constraint in self.constraints:
            if any(region_id not in region_set for region_id in constraint.region_ids):
                raise ValueError("grammar constraint references an unknown region")
            if any(axis_id not in axis_set for axis_id in constraint.axis_ids):
                raise ValueError("grammar constraint references an unknown alignment axis")
        return self

    @property
    def region_ids(self) -> tuple[str, ...]:
        return tuple(region.region_id for region in self.region_roles)

    @property
    def regions(self) -> tuple[GrammarRegionV4, ...]:
        """Alias used by compiler-facing callers."""

        return self.region_roles


class LayoutRegionV4(_FrozenLayoutV4):
    """A named region selected for one page; ``order`` is structural only."""

    region_id: StrictStr = Field(min_length=1)
    role: StrictStr = Field(min_length=1)
    order: StrictInt = Field(ge=0)

    @field_validator("region_id", "role")
    @classmethod
    def validate_region_tokens(cls, value: str, info) -> str:
        return _validate_identifier(value, info.field_name)


class FragmentPlacementV4(_FrozenLayoutV4):
    """One exact semantic fragment reference, without copying its text."""

    fragment_ref: StrictStr = Field(min_length=1)
    region_id: StrictStr = Field(min_length=1)
    order: StrictInt = Field(ge=0)
    alignment_axis_ids: tuple[StrictStr, ...] = ()
    emphasis_rule_ids: tuple[StrictStr, ...] = ()

    @field_validator("fragment_ref", "region_id")
    @classmethod
    def validate_fragment_tokens(cls, value: str, info) -> str:
        return _validate_identifier(value, info.field_name)

    @field_validator("alignment_axis_ids", "emphasis_rule_ids")
    @classmethod
    def validate_fragment_refs(cls, value: tuple[str, ...], info) -> tuple[str, ...]:
        if not value:
            return ()
        return _validate_identifiers(value, info.field_name)


class AssetPlacementV4(_FrozenLayoutV4):
    """One page-local asset directive reference, never provider metadata."""

    directive_id: StrictStr = Field(min_length=1)
    region_id: StrictStr = Field(min_length=1)
    order: StrictInt = Field(ge=0)
    alignment_axis_ids: tuple[StrictStr, ...] = ()

    @field_validator("directive_id", "region_id")
    @classmethod
    def validate_asset_tokens(cls, value: str, info) -> str:
        return _validate_identifier(value, info.field_name)

    @field_validator("alignment_axis_ids")
    @classmethod
    def validate_asset_axes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            return ()
        return _validate_identifiers(value, "alignment_axis_ids")


EmphasisKindV4 = Literal["primary_focus", "secondary_focus", "supporting"]


class EmphasisRuleV4(_FrozenLayoutV4):
    """Semantic emphasis instruction; no visual copy or geometry."""

    rule_id: StrictStr = Field(min_length=1)
    kind: EmphasisKindV4
    target_fragment_refs: tuple[StrictStr, ...] = Field(min_length=1)
    priority: StrictInt = Field(ge=0)

    @field_validator("rule_id")
    @classmethod
    def validate_rule_id(cls, value: str) -> str:
        return _validate_identifier(value, "rule_id")

    @field_validator("target_fragment_refs")
    @classmethod
    def validate_targets(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_identifiers(value, "target_fragment_refs")


class LayoutAlignmentAxisV4(_FrozenLayoutV4):
    """A grammar axis selected by a page program."""

    axis_id: StrictStr = Field(min_length=1)
    orientation: AlignmentOrientationV4
    region_ids: tuple[StrictStr, ...] = Field(min_length=1)

    @field_validator("axis_id")
    @classmethod
    def validate_axis_id(cls, value: str) -> str:
        return _validate_identifier(value, "axis_id")

    @field_validator("region_ids")
    @classmethod
    def validate_axis_regions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_identifiers(value, "region_ids")


class ResponsiveConstraintV4(_FrozenLayoutV4):
    """Abstract responsive behavior for a later compiler."""

    constraint_id: StrictStr = Field(min_length=1)
    kind: StrictStr = Field(min_length=1)
    region_ids: tuple[StrictStr, ...] = ()
    axis_ids: tuple[StrictStr, ...] = ()
    behavior: StrictStr = Field(min_length=1)

    @field_validator("constraint_id", "kind", "behavior")
    @classmethod
    def validate_constraint_tokens(cls, value: str, info) -> str:
        return _validate_identifier(value, info.field_name)

    @field_validator("region_ids", "axis_ids")
    @classmethod
    def validate_constraint_refs(cls, value: tuple[str, ...], info) -> tuple[str, ...]:
        if not value:
            return ()
        return _validate_identifiers(value, info.field_name)


class LayoutProgramV4(_FrozenLayoutV4):
    """Hash-bound structural intent for exactly one durable page brief."""

    page_id: StrictStr = Field(min_length=1)
    page_brief_sha256: StrictStr
    grammar_id: ImplementedGrammarIDV4
    template_family: TemplateFamilyV4
    family_tokens_sha256: StrictStr
    carousel_narrative_sha256: StrictStr
    beat_ref: StrictStr
    beat_task_kind: NarrativeTaskKindV4
    regions: tuple[LayoutRegionV4, ...] = Field(min_length=1)
    fragment_placements: tuple[FragmentPlacementV4, ...] = Field(min_length=1)
    asset_placements: tuple[AssetPlacementV4, ...] = ()
    emphasis_rules: tuple[EmphasisRuleV4, ...] = ()
    alignment_axes: tuple[LayoutAlignmentAxisV4, ...] = ()
    density_target: DensityLevelV4
    responsive_constraints: tuple[ResponsiveConstraintV4, ...] = ()
    canonical_sha256: StrictStr

    @field_validator("page_id")
    @classmethod
    def validate_page_id(cls, value: str) -> str:
        return _validate_identifier(value, "page_id")

    @field_validator(
        "page_brief_sha256",
        "family_tokens_sha256",
        "carousel_narrative_sha256",
        "canonical_sha256",
    )
    @classmethod
    def validate_hash_shape(cls, value: str, info) -> str:
        return _validate_hash(value, info.field_name)

    @field_validator("beat_ref")
    @classmethod
    def validate_beat_ref(cls, value: str) -> str:
        return _validate_identifier(value, "beat_ref")

    @model_validator(mode="after")
    def validate_program_integrity(self) -> "LayoutProgramV4":
        # Re-run nested validators on the serialized payload.  This is
        # important after model_copy(update=...), which bypasses Pydantic's
        # normal constructor validators.
        for model in (*self.regions, *self.fragment_placements, *self.asset_placements, *self.emphasis_rules, *self.alignment_axes, *self.responsive_constraints):
            type(model).model_validate(model.model_dump(mode="python"))

        # The registry is the only family-token authority.  Resolve it at the
        # integrity boundary rather than accepting a caller-supplied token
        # payload or a self-consistent but stale digest.
        try:
            from src.visual_design.v4.tokens import get_family_tokens

            current_tokens = get_family_tokens(self.template_family)
        except Exception as exc:
            raise ValueError("layout program family token registry is unavailable") from exc
        if self.family_tokens_sha256 != current_tokens.canonical_sha256:
            raise ValueError("layout program family token hash does not match current family tokens")

        region_ids = tuple(region.region_id for region in self.regions)
        if len(set(region_ids)) != len(region_ids):
            raise ValueError("layout program region IDs must be unique")
        region_set = set(region_ids)
        if [region.order for region in self.regions] != list(range(len(self.regions))):
            raise ValueError("layout program region order must be continuous")

        fragment_refs = tuple(item.fragment_ref for item in self.fragment_placements)
        if len(set(fragment_refs)) != len(fragment_refs):
            raise ValueError("layout program fragment placements must be unique")
        if [item.order for item in self.fragment_placements] != list(range(len(self.fragment_placements))):
            raise ValueError("layout program fragment placement order must be continuous")
        if any(item.region_id not in region_set for item in self.fragment_placements):
            raise ValueError("layout program fragment placement references an unknown region")

        directive_refs = tuple(item.directive_id for item in self.asset_placements)
        if len(set(directive_refs)) != len(directive_refs):
            raise ValueError("layout program asset placements must be unique")
        if [item.order for item in self.asset_placements] != list(range(len(self.asset_placements))):
            raise ValueError("layout program asset placement order must be continuous")
        if any(item.region_id not in region_set for item in self.asset_placements):
            raise ValueError("layout program asset placement references an unknown region")

        axis_ids = tuple(axis.axis_id for axis in self.alignment_axes)
        if len(set(axis_ids)) != len(axis_ids):
            raise ValueError("layout program alignment axis IDs must be unique")
        axis_set = set(axis_ids)
        if any(
            region_id not in region_set
            for axis in self.alignment_axes
            for region_id in axis.region_ids
        ):
            raise ValueError("layout program alignment axis references an unknown region")

        rule_ids = tuple(rule.rule_id for rule in self.emphasis_rules)
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("layout program emphasis rule IDs must be unique")
        priorities = tuple(rule.priority for rule in self.emphasis_rules)
        if sorted(priorities) != list(range(len(priorities))):
            raise ValueError("layout program emphasis rule priority values must be unique and continuous")
        fragment_set = set(fragment_refs)
        if any(
            fragment_ref not in fragment_set
            for rule in self.emphasis_rules
            for fragment_ref in rule.target_fragment_refs
        ):
            raise ValueError("layout program emphasis rule references an unknown fragment")
        rule_set = set(rule_ids)
        if any(
            rule_id not in rule_set
            for placement in self.fragment_placements
            for rule_id in placement.emphasis_rule_ids
        ):
            raise ValueError("layout program fragment references an unknown emphasis rule")
        placements_by_fragment = {
            placement.fragment_ref: set(placement.emphasis_rule_ids)
            for placement in self.fragment_placements
        }
        for rule in self.emphasis_rules:
            for fragment_ref in rule.target_fragment_refs:
                if rule.rule_id not in placements_by_fragment.get(fragment_ref, set()):
                    raise ValueError("layout program emphasis rule is not reverse-bound to its fragment")
        for placement in self.fragment_placements:
            for rule_id in placement.emphasis_rule_ids:
                rule = next(rule for rule in self.emphasis_rules if rule.rule_id == rule_id)
                if placement.fragment_ref not in rule.target_fragment_refs:
                    raise ValueError("layout program fragment reverse-binds an unrelated emphasis rule")
        if any(
            axis_id not in axis_set
            for placement in (*self.fragment_placements, *self.asset_placements)
            for axis_id in placement.alignment_axis_ids
        ):
            raise ValueError("layout program placement references an unknown alignment axis")

        constraint_ids = tuple(item.constraint_id for item in self.responsive_constraints)
        if len(set(constraint_ids)) != len(constraint_ids):
            raise ValueError("layout program responsive constraint IDs must be unique")
        for constraint in self.responsive_constraints:
            if any(region_id not in region_set for region_id in constraint.region_ids):
                raise ValueError("layout program constraint references an unknown region")
            if any(axis_id not in axis_set for axis_id in constraint.axis_ids):
                raise ValueError("layout program constraint references an unknown alignment axis")

        expected = canonical_sha256_v4(
            self.model_dump(
                mode="json",
                exclude={"canonical_sha256"},
                exclude_none=True,
            )
        )
        if self.canonical_sha256 != expected:
            raise ValueError("layout program canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))

    @property
    def family(self) -> TemplateFamilyV4:
        return self.template_family

    @property
    def page_brief_hash(self) -> str:
        return self.page_brief_sha256

    @property
    def asset_directive_placements(self) -> tuple[AssetPlacementV4, ...]:
        return self.asset_placements


# Explicit aliases keep v4 callers discoverable without importing v3 layout
# contracts.  The suffixed names remain the canonical implementation names.
CompositionGrammar = CompositionGrammarV4
FamilyTokens = FamilyTokensV4
LayoutProgram = LayoutProgramV4


__all__ = [
    "AlignmentOrientationV4",
    "ABSTRACT_RADII_V4",
    "ABSTRACT_SPACING_SCALE_V4",
    "AssetPlacementV4",
    "CompositionGrammar",
    "CompositionGrammarV4",
    "FamilyTokens",
    "FamilyTokensV4",
    "FragmentPlacementV4",
    "GRAMMAR_IDS_V4",
    "GrammarAlignmentAxisV4",
    "GrammarConstraintV4",
    "GrammarRegionV4",
    "GrammarRelationshipV4",
    "ImplementedGrammarIDV4",
    "LayoutAlignmentAxisV4",
    "LayoutProgram",
    "LayoutProgramV4",
    "LayoutRegionV4",
    "MotifRulesV4",
    "OrderedEnvelopeV4",
    "PAGE_ROLES_V4",
    "PageRoleV4",
    "TASK_KIND_TO_PAGE_ROLE_V4",
    "EmphasisRuleV4",
    "ResponsiveConstraintV4",
    "TypographyRolesV4",
]
