"""Immutable structural-intent contracts for the v4 layout boundary.

This module deliberately stops at named regions and relationships.  It does
not model typography measurements, geometry, renderer primitives, visible
copy, provider data, or executable markup; those concerns belong to later
v4 stages.
"""

from __future__ import annotations

import re
import math
from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_serializer,
    field_validator,
    model_validator,
)

from src.schemas.v4.content import canonical_sha256_v4
from src.schemas.v4.direction import (
    DensityLevelV4,
    NarrativeTaskKindV4,
    TemplateFamilyV4,
)
from src.schemas.scene_graph import Box, ImageElement, LineElement, PageScene, TextElement
from src.schemas.visual_style import deep_freeze, deep_thaw


GRAMMAR_IDS_V4 = ("editorial_hero", "comparison_grid", "step_flow")
ImplementedGrammarIDV4 = Literal["editorial_hero", "comparison_grid", "step_flow"]
PAGE_ROLES_V4 = ("cover", "body", "closing")
PageRoleV4 = Literal["cover", "body", "closing"]
CANONICAL_COMPILER_VERSION_V4 = "v4-layout-compiler-2"
CANONICAL_TEXT_WRAP_POLICY_V4 = "pre-wrap-grapheme-anywhere-v1"
CANONICAL_CONTENT_INSET_POLICY_V4 = "content-origin-inset-v1"
CANONICAL_CONTRAST_POLICY_VERSION_V4 = "wcag-semantic-ink-v1"
CANONICAL_ACCESSIBILITY_INK_V4 = "#111111"
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


# This is the complete non-visible payload emitted by the Pillow producer and
# persisted in ``TextMeasurementEvidenceV4``.  Keeping the field set here
# makes the durable consumer use exactly the producer's hash contract instead
# of maintaining a second, silently drifting list.
_TEXT_MEASUREMENT_PAYLOAD_FIELDS_V4 = frozenset(
    {
        "advance_width_px",
        "ascent_px",
        "break_offsets",
        "content_inset_bottom_px",
        "content_inset_left_px",
        "content_inset_policy",
        "content_inset_right_px",
        "content_inset_top_px",
        "descent_px",
        "explicit_break_spans",
        "explicit_newline_count",
        "font_nominal_weight",
        "font_role",
        "font_sha256",
        "font_size_px",
        "height_px",
        "ink_bottom_px",
        "ink_height_px",
        "ink_left_px",
        "ink_right_px",
        "ink_top_px",
        "ink_width_px",
        "inserted_break_offsets",
        "line_codepoint_counts",
        "line_count",
        "line_height",
        "line_widths_px",
        "max_width_px",
        "offset_unit",
        "painted_bottom_px",
        "painted_left_px",
        "painted_offset_x_px",
        "painted_offset_y_px",
        "painted_right_px",
        "painted_top_px",
        "width_px",
        "wrap_policy",
    }
)


def canonical_text_measurement_payload_v4(
    payload: Mapping[str, object],
) -> dict[str, object]:
    """Return the exact canonical, non-visible measurement payload.

    The helper is deliberately pure: it performs no font lookup, filesystem
    access, or visible-copy handling.  Both Pillow production and durable
    schema validation call this function before hashing.
    """

    if set(payload) != _TEXT_MEASUREMENT_PAYLOAD_FIELDS_V4:
        raise ValueError("text measurement payload fields are not canonical")
    return {key: payload[key] for key in sorted(_TEXT_MEASUREMENT_PAYLOAD_FIELDS_V4)}


def canonical_text_measurement_sha256_v4(payload: Mapping[str, object]) -> str:
    """Hash one canonical measurement payload with the v4 JSON contract."""

    return canonical_sha256_v4(canonical_text_measurement_payload_v4(payload))


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
    words = tuple(value.lower().split())
    normalized_words = tuple(word.replace("-", "") for word in words)
    if (
        any(word in _FORBIDDEN_STYLE_TOKENS for word in normalized_words)
        or any(word in _EVENT_HANDLER_TOKENS for word in normalized_words)
        or any(
            left == "local" and right == "path"
            for left, right in zip(normalized_words, normalized_words[1:])
        )
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
        except Exception:
            raise ValueError("layout program family token registry is unavailable") from None
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


class TextMeasurementEvidenceV4(_FrozenLayoutV4):
    """Non-visible measurement evidence consumed by the future CSS adapter."""

    fragment_ref: StrictStr = Field(min_length=1)
    font_role: Literal["display", "heading", "body", "caption"]
    font_sha256: StrictStr
    font_nominal_weight: StrictInt = Field(ge=1, le=1000)
    font_size_px: float = Field(gt=0)
    width_px: float = Field(ge=0)
    height_px: float = Field(gt=0)
    line_count: StrictInt = Field(ge=1)
    explicit_newline_count: StrictInt = Field(ge=0)
    line_height: float = Field(gt=0)
    max_width_px: float = Field(gt=0)
    advance_width_px: float = Field(ge=0)
    ink_width_px: float = Field(ge=0)
    ink_height_px: float = Field(ge=0)
    line_widths_px: tuple[float, ...]
    line_codepoint_counts: tuple[StrictInt, ...]
    break_offsets: tuple[StrictInt, ...] = ()
    offset_unit: Literal["unicode_codepoint_v1"] = "unicode_codepoint_v1"
    explicit_break_spans: tuple[tuple[StrictInt, StrictInt], ...] = ()
    inserted_break_offsets: tuple[StrictInt, ...] = ()
    ink_left_px: float = 0.0
    ink_top_px: float = 0.0
    ink_right_px: float = 0.0
    ink_bottom_px: float = 0.0
    ascent_px: float = Field(ge=0)
    descent_px: float = Field(ge=0)
    wrap_policy: StrictStr = CANONICAL_TEXT_WRAP_POLICY_V4
    measurement_sha256: StrictStr

    # Task 13 applies this versioned content-origin inset inside the complete
    # reserved scene box; the compiler never moves or shrinks that box.
    content_inset_policy: StrictStr = CANONICAL_CONTENT_INSET_POLICY_V4
    content_inset_left_px: float = 0.0
    content_inset_top_px: float = 0.0
    content_inset_right_px: float = 0.0
    content_inset_bottom_px: float = 0.0
    painted_offset_x_px: float = 0.0
    painted_offset_y_px: float = 0.0
    painted_left_px: float = 0.0
    painted_top_px: float = 0.0
    painted_right_px: float = 0.0
    painted_bottom_px: float = 0.0
    # Exact immutable inputs used by the compiler.  These are intentionally
    # separate from the Pillow measurement hash: the page validator binds
    # them to the scene box/style, so a caller cannot rehash a self-consistent
    # evidence object with a different reserved geometry.
    reserved_box_x_px: float = Field(ge=0)
    reserved_box_y_px: float = Field(ge=0)
    reserved_box_width_px: float = Field(gt=0)
    reserved_box_height_px: float = Field(gt=0)

    @field_validator("font_sha256", "measurement_sha256")
    @classmethod
    def validate_evidence_hash(cls, value: str, info) -> str:
        return _validate_hash(value, info.field_name)

    @field_validator(
        "font_size_px",
        "width_px",
        "height_px",
        "line_height",
        "max_width_px",
        "advance_width_px",
        "ink_width_px",
        "ink_height_px",
        "reserved_box_x_px",
        "reserved_box_y_px",
        "reserved_box_width_px",
        "reserved_box_height_px",
    )
    @classmethod
    def validate_positive_metrics(cls, value: float, info) -> float:
        if not math.isfinite(value):
            raise ValueError(f"text measurement {info.field_name} must be finite")
        return value

    @field_validator("line_widths_px")
    @classmethod
    def validate_line_widths(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if any(
            isinstance(width, bool) or not math.isfinite(float(width)) or float(width) < 0
            for width in value
        ):
            raise ValueError("text measurement line widths must be finite and non-negative")
        return tuple(float(width) for width in value)

    @field_validator("line_codepoint_counts")
    @classmethod
    def validate_line_codepoint_counts(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(type(count) is not int or count < 0 for count in value):
            raise ValueError("text measurement line codepoint counts must be non-negative integers")
        return value

    @field_validator("break_offsets", "inserted_break_offsets")
    @classmethod
    def validate_break_offsets(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(offset < 0 for offset in value):
            raise ValueError("text measurement break offsets must be non-negative")
        if tuple(value) != tuple(sorted(value)):
            raise ValueError("text measurement break offsets must be ordered")
        return value

    @field_validator("explicit_break_spans")
    @classmethod
    def validate_break_spans(
        cls,
        value: tuple[tuple[int, int], ...],
    ) -> tuple[tuple[int, int], ...]:
        previous_end = -1
        for start, end in value:
            if start < 0 or end <= start or start < previous_end:
                raise ValueError("text measurement explicit break spans are invalid")
            previous_end = end
        return value

    @field_validator(
        "ink_left_px",
        "ink_top_px",
        "ink_right_px",
        "ink_bottom_px",
        "ascent_px",
        "descent_px",
        "content_inset_left_px",
        "content_inset_top_px",
        "content_inset_right_px",
        "content_inset_bottom_px",
        "painted_offset_x_px",
        "painted_offset_y_px",
        "painted_left_px",
        "painted_top_px",
        "painted_right_px",
        "painted_bottom_px",
    )
    @classmethod
    def validate_metrics(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("text measurement metric must be finite")
        return value

    @field_validator("wrap_policy")
    @classmethod
    def validate_wrap_policy(cls, value: str) -> str:
        if value != CANONICAL_TEXT_WRAP_POLICY_V4:
            raise ValueError("text measurement wrap policy is not canonical")
        return value

    @field_validator("content_inset_policy")
    @classmethod
    def validate_content_inset_policy(cls, value: str) -> str:
        if value != CANONICAL_CONTENT_INSET_POLICY_V4:
            raise ValueError("text measurement content inset policy is not canonical")
        return value

    @model_validator(mode="after")
    def validate_ink_bounds(self) -> "TextMeasurementEvidenceV4":
        if len(self.line_widths_px) != self.line_count:
            raise ValueError("text measurement line widths must match line count")
        if len(self.line_codepoint_counts) != self.line_count:
            raise ValueError("text measurement line codepoint counts must match line count")
        if self.explicit_newline_count != len(self.explicit_break_spans):
            raise ValueError("text measurement newline count must match explicit break spans")
        if abs(self.reserved_box_width_px - self.max_width_px) > 1e-6:
            raise ValueError("text measurement reserved width must match max width")
        if self.reserved_box_width_px <= 0 or self.reserved_box_height_px <= 0:
            raise ValueError("text measurement reserved box must be positive")
        if (
            self.width_px > self.max_width_px + 1e-6
            or self.advance_width_px > self.max_width_px + 1e-6
            or self.ink_width_px > self.max_width_px + 1e-6
            or any(width > self.max_width_px + 1e-6 for width in self.line_widths_px)
        ):
            raise ValueError("text measurement width exceeds reserved max width")
        if self.height_px > self.reserved_box_height_px + 1e-6:
            raise ValueError("text measurement height exceeds reserved box")
        if self.ink_right_px < self.ink_left_px or self.ink_bottom_px < self.ink_top_px:
            raise ValueError("text measurement ink bounds are inverted")
        if any(
            value < 0
            for value in (
                self.content_inset_left_px,
                self.content_inset_top_px,
                self.content_inset_right_px,
                self.content_inset_bottom_px,
            )
        ):
            raise ValueError("text measurement content insets must be non-negative")
        if self.painted_right_px < self.painted_left_px or self.painted_bottom_px < self.painted_top_px:
            raise ValueError("text measurement painted bounds are inverted")
        expected = canonical_text_measurement_sha256_v4(
            {
                "advance_width_px": self.advance_width_px,
                "ascent_px": self.ascent_px,
                "break_offsets": self.break_offsets,
                "content_inset_bottom_px": self.content_inset_bottom_px,
                "content_inset_left_px": self.content_inset_left_px,
                "content_inset_policy": self.content_inset_policy,
                "content_inset_right_px": self.content_inset_right_px,
                "content_inset_top_px": self.content_inset_top_px,
                "descent_px": self.descent_px,
                "explicit_break_spans": self.explicit_break_spans,
                "explicit_newline_count": self.explicit_newline_count,
                "font_nominal_weight": self.font_nominal_weight,
                "font_role": self.font_role,
                "font_sha256": self.font_sha256,
                "font_size_px": self.font_size_px,
                "height_px": self.height_px,
                "ink_bottom_px": self.ink_bottom_px,
                "ink_height_px": self.ink_height_px,
                "ink_left_px": self.ink_left_px,
                "ink_right_px": self.ink_right_px,
                "ink_top_px": self.ink_top_px,
                "ink_width_px": self.ink_width_px,
                "inserted_break_offsets": self.inserted_break_offsets,
                "line_codepoint_counts": self.line_codepoint_counts,
                "line_count": self.line_count,
                "line_height": self.line_height,
                "line_widths_px": self.line_widths_px,
                "max_width_px": self.max_width_px,
                "offset_unit": self.offset_unit,
                "painted_bottom_px": self.painted_bottom_px,
                "painted_left_px": self.painted_left_px,
                "painted_offset_x_px": self.painted_offset_x_px,
                "painted_offset_y_px": self.painted_offset_y_px,
                "painted_right_px": self.painted_right_px,
                "painted_top_px": self.painted_top_px,
                "width_px": self.width_px,
                "wrap_policy": self.wrap_policy,
            }
        )
        if self.measurement_sha256 != expected:
            raise ValueError("text measurement sha256 does not match canonical payload")
        return self


class AssetBindingEvidenceV4(_FrozenLayoutV4):
    """Exact asset binding facts without path/provider/provenance data."""

    directive_id: StrictStr = Field(min_length=1)
    asset_ref: StrictStr = Field(pattern=r"^v4-asset-[0-9a-f]{64}$")
    asset_sha256: StrictStr
    page_id: StrictStr = Field(min_length=1)
    region_id: StrictStr = Field(min_length=1)
    orientation: Literal["any", "portrait", "landscape", "square"]
    fit: Literal["cover", "contain"]
    box_ratio: float = Field(gt=0)
    crop_factor: float = Field(ge=1)

    @field_validator("asset_sha256")
    @classmethod
    def validate_asset_hash(cls, value: str) -> str:
        return _validate_hash(value, "asset_sha256")

    @field_validator("directive_id", "page_id", "region_id")
    @classmethod
    def validate_asset_binding_identifiers(cls, value: str, info) -> str:
        return _validate_identifier(value, info.field_name)

    @field_validator("box_ratio", "crop_factor")
    @classmethod
    def validate_asset_geometry(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("asset binding geometry must be finite")
        return value


class RegionGeometryEvidenceV4(_FrozenLayoutV4):
    """Hash-bound named-region geometry emitted by a grammar solver."""

    region_id: StrictStr = Field(min_length=1)
    role: StrictStr = Field(min_length=1)
    order: StrictInt = Field(ge=0)
    x: float = Field(ge=80)
    y: float = Field(ge=80)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    geometry_sha256: StrictStr

    @field_validator("region_id", "role")
    @classmethod
    def validate_region_tokens(cls, value: str, info) -> str:
        return _validate_identifier(value, info.field_name)

    @field_validator("geometry_sha256")
    @classmethod
    def validate_geometry_hash(cls, value: str) -> str:
        return _validate_hash(value, "geometry_sha256")

    @field_validator("x", "y", "width", "height")
    @classmethod
    def validate_region_geometry(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("region geometry must be finite")
        return value

    @model_validator(mode="after")
    def validate_region_bounds(self) -> "RegionGeometryEvidenceV4":
        payload = {
            "region_id": self.region_id,
            "role": self.role,
            "order": self.order,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }
        if self.geometry_sha256 != canonical_sha256_v4(payload):
            raise ValueError("region geometry evidence hash does not match payload")
        if self.x + self.width > 1000 or self.y + self.height > 1360:
            raise ValueError("region geometry evidence exceeds compiler safe margin")
        return self


class CompilerProvenanceV4(_FrozenLayoutV4):
    """Auditable deterministic compiler inputs without machine-local data.

    Only byte hashes of the checked-in role fonts are persisted.  Absolute
    paths, provider metadata and asset provenance belong to upstream private
    boundaries and cannot enter this durable scene contract.
    """

    compiler_version: StrictStr = CANONICAL_COMPILER_VERSION_V4
    grammar_id: ImplementedGrammarIDV4
    template_family: TemplateFamilyV4
    program_sha256: StrictStr
    content_atom_set_sha256: StrictStr
    semantic_content_model_sha256: StrictStr
    page_brief_sha256: StrictStr
    page_brief_set_sha256: StrictStr
    visual_direction_plan_sha256: StrictStr
    asset_manifest_sha256: StrictStr
    family_tokens_sha256: StrictStr
    font_sha256_by_role: dict[StrictStr, StrictStr]
    candidate_id: StrictStr
    revision: StrictInt = Field(ge=0)
    run_id: StrictStr
    canvas_width: StrictInt = 1080
    canvas_height: StrictInt = 1440
    safe_margin_px: StrictInt = 80
    min_body_font_px: StrictInt = Field(default=24, ge=24)
    min_display_font_px: StrictInt = Field(default=32, ge=32)
    text_wrap_policy: StrictStr = CANONICAL_TEXT_WRAP_POLICY_V4
    contrast_policy_version: StrictStr = CANONICAL_CONTRAST_POLICY_VERSION_V4
    accessibility_ink: StrictStr = CANONICAL_ACCESSIBILITY_INK_V4
    text_measurement_evidence: dict[StrictStr, TextMeasurementEvidenceV4] = {}
    asset_binding_evidence: dict[StrictStr, AssetBindingEvidenceV4] = {}
    region_geometry_evidence: dict[StrictStr, RegionGeometryEvidenceV4]
    element_region_bindings: dict[StrictStr, StrictStr] = {}
    canonical_sha256: StrictStr

    @field_validator(
        "program_sha256",
        "content_atom_set_sha256",
        "semantic_content_model_sha256",
        "page_brief_sha256",
        "asset_manifest_sha256",
        "family_tokens_sha256",
        "canonical_sha256",
    )
    @classmethod
    def validate_provenance_hash(cls, value: str, info) -> str:
        return _validate_hash(value, info.field_name)

    @field_validator("page_brief_set_sha256", "visual_direction_plan_sha256")
    @classmethod
    def validate_optional_provenance_hash(cls, value: str, info) -> str:
        return _validate_hash(value, info.field_name)

    @field_validator("compiler_version")
    @classmethod
    def validate_compiler_version(cls, value: str) -> str:
        if value != CANONICAL_COMPILER_VERSION_V4:
            raise ValueError("v4 compiler version is not canonical")
        return value

    @field_validator("text_wrap_policy")
    @classmethod
    def validate_wrap_policy(cls, value: str) -> str:
        if value != CANONICAL_TEXT_WRAP_POLICY_V4:
            raise ValueError("v4 text wrap policy is not canonical")
        return value

    @field_validator("accessibility_ink")
    @classmethod
    def validate_accessibility_ink(cls, value: str) -> str:
        if value != CANONICAL_ACCESSIBILITY_INK_V4:
            raise ValueError("v4 accessibility ink is not canonical")
        return value

    @field_validator("contrast_policy_version")
    @classmethod
    def validate_contrast_policy(cls, value: str) -> str:
        if value != CANONICAL_CONTRAST_POLICY_VERSION_V4:
            raise ValueError("v4 contrast policy is not canonical")
        return value

    @field_validator("candidate_id")
    @classmethod
    def validate_candidate_id(cls, value: str) -> str:
        return _validate_identifier(value, "candidate_id")

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        return _validate_identifier(value, "run_id")

    @field_validator("font_sha256_by_role")
    @classmethod
    def validate_font_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        expected_roles = {"display", "heading", "body", "caption"}
        if set(value) != expected_roles:
            raise ValueError("compiler provenance must bind all canonical font roles")
        for role, digest in value.items():
            _validate_hash(digest, f"font_sha256_by_role[{role}]")
        return value

    @field_validator("text_measurement_evidence")
    @classmethod
    def validate_text_evidence(cls, value: dict[str, TextMeasurementEvidenceV4]):
        checked = {
            key: TextMeasurementEvidenceV4.model_validate(item.model_dump(mode="python"))
            for key, item in value.items()
        }
        if any(key != item.fragment_ref for key, item in checked.items()):
            raise ValueError("text measurement evidence keys must match fragment refs")
        return checked

    @field_validator("asset_binding_evidence")
    @classmethod
    def validate_asset_evidence(cls, value: dict[str, AssetBindingEvidenceV4]):
        checked = {
            key: AssetBindingEvidenceV4.model_validate(item.model_dump(mode="python"))
            for key, item in value.items()
        }
        if any(key != item.directive_id for key, item in checked.items()):
            raise ValueError("asset binding evidence keys must match directive IDs")
        return checked

    @field_validator("region_geometry_evidence")
    @classmethod
    def validate_region_evidence(cls, value: dict[str, RegionGeometryEvidenceV4]):
        checked = {
            key: RegionGeometryEvidenceV4.model_validate(item.model_dump(mode="python"))
            for key, item in value.items()
        }
        if any(key != item.region_id for key, item in checked.items()):
            raise ValueError("region geometry evidence keys must match region IDs")
        return checked

    @field_validator("element_region_bindings")
    @classmethod
    def validate_element_region_bindings(cls, value: dict[str, str]):
        checked: dict[str, str] = {}
        for element_id, region_id in value.items():
            checked[_validate_identifier(element_id, "element_id")] = _validate_identifier(
                region_id,
                "region_id",
            )
        return checked

    @field_serializer("font_sha256_by_role")
    def serialize_font_hashes(self, value):
        return deep_thaw(value)

    @field_serializer("text_measurement_evidence")
    def serialize_text_evidence(self, value):
        return deep_thaw(value)

    @field_serializer("asset_binding_evidence")
    def serialize_asset_evidence(self, value):
        return deep_thaw(value)

    @field_serializer("region_geometry_evidence")
    def serialize_region_evidence(self, value):
        return deep_thaw(value)

    @field_serializer("element_region_bindings")
    def serialize_element_region_bindings(self, value):
        return deep_thaw(value)

    @model_validator(mode="after")
    def validate_provenance(self) -> "CompilerProvenanceV4":
        if self.template_family not in {"pink_red", "deep_teal", "soft_pink", "coral_impact", "green_catalog", "white_quote"}:
            raise ValueError("compiler provenance family is not canonical")
        if self.canvas_width != 1080 or self.canvas_height != 1440:
            raise ValueError("v4 compiler provenance canvas must be exactly 1080x1440")
        if self.safe_margin_px != 80:
            raise ValueError("v4 compiler provenance safe margin is fixed at 80px")
        if self.min_body_font_px < 24 or self.min_display_font_px < 32:
            raise ValueError("compiler provenance minimum font floors are below policy")
        try:
            from src.visual_design.v4.tokens import get_family_tokens
            from src.visual_design.v4.typography import CANONICAL_FONT_SHA256_V4

            tokens = get_family_tokens(self.template_family)
            current_fonts = {
                role: CANONICAL_FONT_SHA256_V4[getattr(tokens.font_roles, role)]
                for role in ("display", "heading", "body", "caption")
            }
        except Exception:
            raise ValueError("current canonical font registry is unavailable") from None
        if dict(self.font_sha256_by_role) != current_fonts:
            raise ValueError("compiler provenance font hashes do not match current registry")
        for key, evidence in self.text_measurement_evidence.items():
            if self.font_sha256_by_role[evidence.font_role] != evidence.font_sha256:
                raise ValueError("text measurement evidence font hash is not provenance-bound")
        object.__setattr__(
            self,
            "font_sha256_by_role",
            deep_freeze(self.font_sha256_by_role),
        )
        object.__setattr__(self, "text_measurement_evidence", deep_freeze(self.text_measurement_evidence))
        object.__setattr__(self, "asset_binding_evidence", deep_freeze(self.asset_binding_evidence))
        object.__setattr__(self, "region_geometry_evidence", deep_freeze(self.region_geometry_evidence))
        object.__setattr__(self, "element_region_bindings", deep_freeze(self.element_region_bindings))
        expected = canonical_sha256_v4(
            self.model_dump(
                mode="json",
                exclude={"canonical_sha256"},
            )
        )
        if self.canonical_sha256 != expected:
            raise ValueError("compiler provenance canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))


class CompiledPageV4(_FrozenLayoutV4):
    """One immutable page seam between the v4 compiler and renderer."""

    page_id: StrictStr = Field(min_length=1)
    sequence: StrictInt = Field(ge=1)
    layout_program: LayoutProgramV4
    scene: PageScene
    compiler_provenance: CompilerProvenanceV4
    canonical_sha256: StrictStr

    @field_validator("canonical_sha256")
    @classmethod
    def validate_compiled_page_hash(cls, value: str) -> str:
        return _validate_hash(value, "canonical_sha256")

    @model_validator(mode="after")
    def validate_compiled_page(self) -> "CompiledPageV4":
        self.layout_program.validate_integrity()
        self.compiler_provenance.validate_integrity()
        if self.layout_program.page_id != self.page_id:
            raise ValueError("compiled page ID does not match layout program")
        if self.layout_program.grammar_id != self.compiler_provenance.grammar_id:
            raise ValueError("compiled page grammar does not match compiler provenance")
        if self.layout_program.canonical_sha256 != self.compiler_provenance.program_sha256:
            raise ValueError("compiler provenance is bound to a different layout program")
        try:
            PageScene.model_validate(self.scene.model_dump(mode="python"))
        except Exception:
            raise ValueError("compiled page scene is stale or invalid") from None
        if self.scene.page_id != self.page_id or self.scene.sequence != self.sequence:
            raise ValueError("compiled page scene identity does not match page identity")
        if self.compiler_provenance.template_family != self.layout_program.template_family:
            raise ValueError("compiler provenance family does not match layout program")
        if self.compiler_provenance.family_tokens_sha256 != self.layout_program.family_tokens_sha256:
            raise ValueError("compiler provenance family token hash does not match layout program")
        if self.compiler_provenance.page_brief_sha256 != self.layout_program.page_brief_sha256:
            raise ValueError("compiler provenance page brief hash does not match layout program")
        expected_region_ids = tuple(region.region_id for region in self.layout_program.regions)
        if set(self.compiler_provenance.region_geometry_evidence) != set(expected_region_ids):
            raise ValueError("compiler provenance region geometry evidence is incomplete")
        for region in self.layout_program.regions:
            evidence = self.compiler_provenance.region_geometry_evidence[region.region_id]
            if evidence.role != region.role or evidence.order != region.order:
                raise ValueError("compiler provenance region geometry identity does not match program")

        bindings = self.compiler_provenance.element_region_bindings
        scene_element_ids = tuple(element.element_id for element in self.scene.elements)
        if set(bindings) != set(scene_element_ids):
            raise ValueError("compiled page element region bindings are incomplete")
        region_evidence = self.compiler_provenance.region_geometry_evidence

        def _safe_number(value: object) -> bool:
            return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))

        def _safe_box(element) -> tuple[float, float, float, float]:
            box = element.box
            values = (box.x, box.y, box.width, box.height)
            if not all(_safe_number(value) for value in values) or box.width <= 0 or box.height <= 0:
                raise ValueError("compiled page contains non-finite or non-positive geometry")
            margin = self.compiler_provenance.safe_margin_px
            if (
                box.x < margin
                or box.y < margin
                or box.x + box.width > self.compiler_provenance.canvas_width - margin
                or box.y + box.height > self.compiler_provenance.canvas_height - margin
            ):
                raise ValueError("compiled page geometry exceeds compiler safe margin")
            return float(box.x), float(box.y), float(box.width), float(box.height)

        # Keep the adapter's complete reserved boxes separate from the measured
        # glyph ink bounds.  The reserved box is the geometry contract for the
        # renderer and must never be replaced by a smaller painted rectangle:
        # doing so lets a rehashed scene hide two colliding layout lanes when
        # their glyphs happen to be narrow.
        reserved_boxes: list[
            tuple[str, tuple[float, float, float, float], tuple[str, ...]]
        ] = []
        painted_boxes: list[
            tuple[str, tuple[float, float, float, float], tuple[str, ...]]
        ] = []
        element_ids = [element.element_id for element in self.scene.elements]
        if len(element_ids) != len(set(element_ids)):
            raise ValueError("compiled page scene element IDs must be unique")
        text_refs: list[str] = []
        image_refs: list[str] = []
        for element in self.scene.elements:
            bound_region_id = bindings.get(element.element_id)
            if bound_region_id is None or bound_region_id not in region_evidence:
                raise ValueError("compiled page element has no canonical region binding")
            bound_region = region_evidence[bound_region_id]

            def _inside_region(bounds: tuple[float, float, float, float]) -> bool:
                left, top, right, bottom = bounds
                return (
                    left >= bound_region.x
                    and top >= bound_region.y
                    and right <= bound_region.x + bound_region.width
                    and bottom <= bound_region.y + bound_region.height
                )

            if isinstance(element, LineElement):
                for endpoint in (element.start, element.end):
                    if (
                        len(endpoint) != 2
                        or not all(_safe_number(value) for value in endpoint)
                        or endpoint[0] < self.compiler_provenance.safe_margin_px
                        or endpoint[1] < self.compiler_provenance.safe_margin_px
                        or endpoint[0] > self.compiler_provenance.canvas_width - self.compiler_provenance.safe_margin_px
                        or endpoint[1] > self.compiler_provenance.canvas_height - self.compiler_provenance.safe_margin_px
                    ):
                        raise ValueError("compiled page line endpoint exceeds compiler safe margin")
                if not _inside_region(
                    (
                        min(element.start[0], element.end[0]),
                        min(element.start[1], element.end[1]),
                        max(element.start[0], element.end[0]),
                        max(element.start[1], element.end[1]),
                    )
                ):
                    raise ValueError("compiled page line endpoints exceed bound region")
                if not _safe_number(element.width) or element.width <= 0:
                    raise ValueError("compiled page line width is non-finite or non-positive")
                continue
            box = _safe_box(element)
            if not _inside_region((box[0], box[1], box[0] + box[2], box[1] + box[3])):
                raise ValueError("compiled page element box exceeds bound region")
            reserved_boxes.append((element.element_id, box, tuple(element.intentional_overlap_with)))
            if isinstance(element, TextElement):
                text_refs.append(element.content_ref)
                floor = (
                    self.compiler_provenance.min_display_font_px
                    if element.style.font_role in {"display", "heading"}
                    else self.compiler_provenance.min_body_font_px
                )
                if element.style.font_size < floor:
                    raise ValueError("compiled page text font size is below provenance floor")
                evidence = self.compiler_provenance.text_measurement_evidence.get(element.content_ref)
                if evidence is None:
                    raise ValueError("compiled page text has no measurement evidence")
                if evidence.fragment_ref != element.content_ref:
                    raise ValueError("compiled page text fragment does not match measurement evidence")
                if evidence.font_role != element.style.font_role:
                    raise ValueError("compiled page text role does not match measurement evidence")
                if abs(evidence.font_size_px - element.style.font_size) > 1e-6:
                    raise ValueError("compiled page text size does not match measurement evidence")
                if abs(evidence.line_height - element.style.line_height) > 1e-6:
                    raise ValueError("compiled page text line height does not match measurement evidence")
                if abs(evidence.max_width_px - box[2]) > 1e-6:
                    raise ValueError("compiled page text max width does not match reserved box")
                if (
                    abs(evidence.reserved_box_x_px - box[0]) > 1e-6
                    or abs(evidence.reserved_box_y_px - box[1]) > 1e-6
                    or abs(evidence.reserved_box_width_px - box[2]) > 1e-6
                    or abs(evidence.reserved_box_height_px - box[3]) > 1e-6
                ):
                    raise ValueError("compiled page text reserved box does not match scene box")
                margin = self.compiler_provenance.safe_margin_px
                content_left = box[0] + evidence.content_inset_left_px
                content_top = box[1] + evidence.content_inset_top_px
                content_right = box[0] + box[2] - evidence.content_inset_right_px
                content_bottom = box[1] + box[3] - evidence.content_inset_bottom_px
                content_origin_x = box[0] + evidence.content_inset_left_px
                content_origin_y = box[1] + evidence.content_inset_top_px
                glyph_left = content_origin_x + evidence.painted_offset_x_px + evidence.painted_left_px
                glyph_top = content_origin_y + evidence.painted_offset_y_px + evidence.painted_top_px
                glyph_right = content_origin_x + evidence.painted_offset_x_px + evidence.painted_right_px
                glyph_bottom = content_origin_y + evidence.painted_offset_y_px + evidence.painted_bottom_px
                if (
                    content_left < box[0]
                    or content_top < box[1]
                    or content_right < content_left
                    or content_bottom < content_top
                    or content_right > box[0] + box[2]
                    or content_bottom > box[1] + box[3]
                    or content_origin_x > content_right
                    or content_origin_y > content_bottom
                    or glyph_left < box[0]
                    or glyph_top < box[1]
                    or glyph_right > box[0] + box[2]
                    or glyph_bottom > box[1] + box[3]
                ):
                    raise ValueError("compiled page painted text exceeds reserved box inset")
                if (
                    glyph_left < margin
                    or glyph_top < margin
                    or glyph_right > self.compiler_provenance.canvas_width - margin
                    or glyph_bottom > self.compiler_provenance.canvas_height - margin
                ):
                    raise ValueError("compiled page glyph ink exceeds compiler safe margin")
                if not _inside_region((glyph_left, glyph_top, glyph_right, glyph_bottom)):
                    raise ValueError("compiled page painted text exceeds bound region")
                painted_boxes.append(
                    (
                    element.element_id,
                    (glyph_left, glyph_top, glyph_right - glyph_left, glyph_bottom - glyph_top),
                    tuple(element.intentional_overlap_with),
                    )
                )
                try:
                    from src.visual_design.v4.tokens import get_family_tokens
                    from src.visual_design.v4.typography import CANONICAL_FONT_NOMINAL_WEIGHTS_V4

                    family_tokens = get_family_tokens(
                        self.compiler_provenance.template_family,
                    )
                    font_label = getattr(family_tokens.font_roles, element.style.font_role)
                    nominal_weight = CANONICAL_FONT_NOMINAL_WEIGHTS_V4[font_label]
                except Exception:
                    raise ValueError("compiled page canonical font registry is unavailable") from None
                if element.style.weight != nominal_weight:
                    raise ValueError("compiled page text weight does not match measured font face")
                if evidence.font_nominal_weight != nominal_weight:
                    raise ValueError("compiled page text evidence weight does not match measured font face")
            elif isinstance(element, ImageElement):
                image_refs.append(element.asset_ref)
        expected_text_refs = tuple(item.fragment_ref for item in self.layout_program.fragment_placements)
        if tuple(text_refs) != expected_text_refs or len(text_refs) != len(set(text_refs)):
            raise ValueError("compiled page text refs do not exactly match layout program placements")
        expected_directives = tuple(item.directive_id for item in self.layout_program.asset_placements)
        evidence = self.compiler_provenance.asset_binding_evidence
        if set(evidence) != set(expected_directives):
            raise ValueError("compiled page asset binding evidence is incomplete")
        if len(image_refs) != len(set(image_refs)) or len(image_refs) != len(expected_directives):
            raise ValueError("compiled page asset placements are not exact-once")
        placement_by_directive = {
            placement.directive_id: placement
            for placement in self.layout_program.asset_placements
        }
        image_by_ref = {
            element.asset_ref: element
            for element in self.scene.elements
            if isinstance(element, ImageElement)
        }
        # Re-derive the opaque reference from durable evidence so a caller
        # cannot rehash a page after swapping the byte digest underneath an
        # otherwise matching image reference.
        from src.visual_design.v4.compiler import opaque_asset_ref_v4

        for directive_id, asset_ref in zip(expected_directives, image_refs):
            binding = evidence[directive_id]
            if binding.asset_ref != asset_ref:
                raise ValueError("compiled page asset evidence does not match scene assets")
            image = image_by_ref.get(asset_ref)
            if image is None or binding.region_id != bindings.get(image.element_id):
                raise ValueError("compiled page asset evidence region binding is stale")
            if binding.page_id != self.page_id:
                raise ValueError("compiled page asset evidence page binding is stale")
            if binding.region_id != placement_by_directive[directive_id].region_id:
                raise ValueError("compiled page asset region does not match directive placement")
            expected_asset_ref = opaque_asset_ref_v4(
                candidate_id=self.compiler_provenance.candidate_id,
                revision=self.compiler_provenance.revision,
                page_id=self.page_id,
                directive_id=directive_id,
                asset_sha256=binding.asset_sha256,
            )
            if binding.asset_ref != expected_asset_ref:
                raise ValueError("compiled page opaque asset reference is not evidence-bound")
            if binding.box_ratio <= 0 or binding.crop_factor < 1:
                raise ValueError("compiled page asset geometry evidence is invalid")
        def _intersects(
            left_box: tuple[float, float, float, float],
            right_box: tuple[float, float, float, float],
        ) -> bool:
            return (
                left_box[0] < right_box[0] + right_box[2]
                and left_box[0] + left_box[2] > right_box[0]
                and left_box[1] < right_box[1] + right_box[3]
                and left_box[1] + left_box[3] > right_box[1]
            )

        def _check_overlaps(
            boxes: list[tuple[str, tuple[float, float, float, float], tuple[str, ...]]],
            error_message: str,
        ) -> None:
            for left_index, (left_id, left_box, left_allowed) in enumerate(boxes):
                for right_id, right_box, right_allowed in boxes[left_index + 1 :]:
                    intersects = _intersects(left_box, right_box)
                    if intersects and right_id not in left_allowed and left_id not in right_allowed:
                        raise ValueError(error_message)

        # Reserved geometry is authoritative and is checked independently of
        # painted ink.  Painted bounds get their own pairwise check below.
        _check_overlaps(reserved_boxes, "compiled page contains an unintended element overlap")
        _check_overlaps(painted_boxes, "compiled page contains an unintended painted text overlap")

        # A painted text bound is already proven to be inside its own reserved
        # box above.  Check it against every other reserved element as well;
        # this makes the painted geometry participate in the same overlap
        # policy without comparing a text element with its own box.
        for painted_id, painted_box, painted_allowed in painted_boxes:
            for reserved_id, reserved_box, reserved_allowed in reserved_boxes:
                if painted_id == reserved_id:
                    continue
                intersects = (
                    _intersects(painted_box, reserved_box)
                )
                if (
                    intersects
                    and reserved_id not in painted_allowed
                    and painted_id not in reserved_allowed
                ):
                    raise ValueError("compiled page contains an unintended painted text overlap")
        payload = self.model_dump(mode="json", exclude={"canonical_sha256"})
        expected = canonical_sha256_v4(payload)
        if self.canonical_sha256 != expected:
            raise ValueError("compiled page canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))

    @property
    def program(self) -> LayoutProgramV4:
        return self.layout_program

    @property
    def page_scene(self) -> PageScene:
        return self.scene

    @property
    def provenance(self) -> CompilerProvenanceV4:
        return self.compiler_provenance


class CarouselDesignPlanV4(_FrozenLayoutV4):
    """Hash-bound ordered v4 compiled pages for the renderer seam."""

    content_atom_set_sha256: StrictStr
    semantic_content_model_sha256: StrictStr
    page_brief_set_sha256: StrictStr
    asset_manifest_sha256: StrictStr
    family_tokens_sha256: StrictStr
    candidate_id: StrictStr
    revision: StrictInt = Field(ge=0)
    run_id: StrictStr
    visual_direction_plan_sha256: StrictStr
    pages: tuple[CompiledPageV4, ...] = Field(min_length=5, max_length=18)
    canonical_sha256: StrictStr

    @field_validator(
        "content_atom_set_sha256",
        "semantic_content_model_sha256",
        "page_brief_set_sha256",
        "visual_direction_plan_sha256",
        "asset_manifest_sha256",
        "family_tokens_sha256",
        "canonical_sha256",
    )
    @classmethod
    def validate_plan_hashes(cls, value: str, info) -> str:
        if value is None:
            return value
        return _validate_hash(value, info.field_name)

    @field_validator("candidate_id")
    @classmethod
    def validate_plan_candidate(cls, value: str) -> str:
        return _validate_identifier(value, "candidate_id")

    @field_validator("run_id")
    @classmethod
    def validate_plan_run(cls, value: str) -> str:
        return _validate_identifier(value, "run_id")

    @model_validator(mode="after")
    def validate_plan_identity_and_hash(self) -> "CarouselDesignPlanV4":
        for page in self.pages:
            page.validate_integrity()
        page_ids = [page.page_id for page in self.pages]
        if len(page_ids) != len(set(page_ids)):
            raise ValueError("v4 design plan page IDs must be unique")
        if [page.sequence for page in self.pages] != list(range(1, len(self.pages) + 1)):
            raise ValueError("v4 design plan page sequences must be contiguous from 1")
        if any(page.compiler_provenance.candidate_id != self.candidate_id for page in self.pages):
            raise ValueError("v4 design plan pages mix candidate identities")
        if any(page.compiler_provenance.revision != self.revision for page in self.pages):
            raise ValueError("v4 design plan pages mix revisions")
        if any(page.compiler_provenance.run_id != self.run_id for page in self.pages):
            raise ValueError("v4 design plan pages mix run identities")
        if any(
            page.compiler_provenance.visual_direction_plan_sha256
            != self.visual_direction_plan_sha256
            for page in self.pages
        ):
            raise ValueError("v4 design plan pages mix visual direction plans")
        for page in self.pages:
            provenance = page.compiler_provenance
            if provenance.content_atom_set_sha256 != self.content_atom_set_sha256:
                raise ValueError("v4 design plan content atom hash is not page-bound")
            if provenance.semantic_content_model_sha256 != self.semantic_content_model_sha256:
                raise ValueError("v4 design plan semantic hash is not page-bound")
            if provenance.page_brief_set_sha256 != self.page_brief_set_sha256:
                raise ValueError("v4 design plan page brief set hash is not page-bound")
            if provenance.asset_manifest_sha256 != self.asset_manifest_sha256:
                raise ValueError("v4 design plan asset manifest hash is not page-bound")
            if provenance.family_tokens_sha256 != self.family_tokens_sha256:
                raise ValueError("v4 design plan family token hash is not page-bound")
        program_families = {
            page.layout_program.family_tokens_sha256 for page in self.pages
        }
        if program_families != {self.family_tokens_sha256}:
            raise ValueError("v4 design plan family token hash is not shared by every page")
        expected = canonical_sha256_v4(
            self.model_dump(mode="json", exclude={"canonical_sha256"})
        )
        if self.canonical_sha256 != expected:
            raise ValueError("v4 design plan canonical sha256 does not match payload")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.model_dump(mode="python"))

    @property
    def page_count(self) -> int:
        return len(self.pages)


# Friendly aliases keep the isolated contract discoverable while the suffixed
# names remain the durable implementation names.
CompilerProvenance = CompilerProvenanceV4
CompiledPage = CompiledPageV4
CarouselDesignPlan = CarouselDesignPlanV4


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
    "CarouselDesignPlan",
    "CarouselDesignPlanV4",
    "CANONICAL_CONTENT_INSET_POLICY_V4",
    "canonical_text_measurement_payload_v4",
    "canonical_text_measurement_sha256_v4",
    "CompiledPage",
    "CompiledPageV4",
    "AssetBindingEvidenceV4",
    "CompilerProvenance",
    "CompilerProvenanceV4",
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
    "RegionGeometryEvidenceV4",
    "TypographyRolesV4",
    "TextMeasurementEvidenceV4",
]
