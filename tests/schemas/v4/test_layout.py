from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.schemas.v4.content import canonical_sha256_v4
from src.schemas.v4.layout import (
    CompositionGrammarV4,
    GrammarRegionV4,
    LayoutProgramV4,
)
from src.visual_design.v4.tokens import get_family_tokens


def test_layout_contracts_are_frozen_and_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        GrammarRegionV4.model_validate(
            {"region_id": "hero", "role": "primary", "x": 1}
        )

    with pytest.raises(ValidationError):
        CompositionGrammarV4.model_validate(
            {
                "grammar_id": "custom",
                "allowed_page_roles": ("body",),
                "allowed_narrative_roles": ("context",),
                "region_roles": (
                    {"region_id": "hero", "role": "primary"},
                ),
                "relationships": (),
                "alignment_axes": (),
                "density_range": {"low": 0.1, "high": 0.8},
                "constraints": (),
                "html": "<section />",
            }
        )


def test_grammar_rejects_dangling_region_relationships() -> None:
    with pytest.raises(ValidationError, match="unknown region"):
        CompositionGrammarV4(
            grammar_id="custom",
            allowed_page_roles=("body",),
            allowed_narrative_roles=("context",),
            region_roles=(GrammarRegionV4(region_id="hero", role="primary"),),
            relationships=(
                {
                    "relationship_id": "hero-to-missing",
                    "kind": "stack",
                    "source_region_id": "hero",
                    "target_region_id": "missing",
                },
            ),
            alignment_axes=({"axis_id": "hero-axis", "orientation": "block", "region_ids": ("hero",)},),
            density_range={"low": 0.1, "high": 0.8},
            constraints=({"constraint_id": "hero-focus", "kind": "single_focus", "region_ids": ("hero",), "axis_ids": ("hero-axis",), "behavior": "preserve_focus"},),
        )


def test_layout_program_revalidates_tampered_canonical_hash() -> None:
    # The concrete program shape is produced by the composition node.  This
    # test deliberately uses a compact valid payload so the schema boundary is
    # independently exercised from the planner.
    payload = {
        "page_id": "page-1",
        "page_brief_sha256": "1" * 64,
        "grammar_id": "editorial_hero",
        "template_family": "pink_red",
        "family_tokens_sha256": get_family_tokens("pink_red").canonical_sha256,
        "carousel_narrative_sha256": "2" * 64,
        "beat_ref": "beat-1",
        "beat_task_kind": "context",
        "regions": (
            {"region_id": "hero", "role": "primary", "order": 0},
        ),
        "fragment_placements": (
                {
                    "fragment_ref": "fragment-1",
                    "region_id": "hero",
                    "order": 0,
                    "alignment_axis_ids": (),
                    "emphasis_rule_ids": (),
                },
        ),
        "asset_placements": (),
        "emphasis_rules": (),
        "alignment_axes": (),
        "density_target": "low",
        "responsive_constraints": (),
    }
    program = LayoutProgramV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )
    tampered = program.model_copy(update={"canonical_sha256": "0" * 64})
    with pytest.raises(ValidationError, match="canonical sha256"):
        tampered.validate_integrity()


def test_family_token_hash_is_required_and_tampering_is_rejected() -> None:
    tokens = get_family_tokens("pink_red")
    payload = tokens.model_dump(mode="python")
    payload["canonical_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="canonical sha256"):
        type(tokens).model_validate(payload)


def test_layout_program_requires_a_current_family_token_hash() -> None:
    tokens = get_family_tokens("pink_red")
    payload = {
        "page_id": "page-1",
        "page_brief_sha256": "1" * 64,
        "grammar_id": "editorial_hero",
        "template_family": "pink_red",
        "family_tokens_sha256": "1" * 64,
        "carousel_narrative_sha256": "2" * 64,
        "beat_ref": "beat-1",
        "beat_task_kind": "context",
        "regions": (
            {"region_id": "hero", "role": "primary", "order": 0},
        ),
        "fragment_placements": (
            {
                "fragment_ref": "fragment-1",
                "region_id": "hero",
                "order": 0,
                "alignment_axis_ids": (),
                "emphasis_rule_ids": (),
            },
        ),
        "asset_placements": (),
        "emphasis_rules": (),
        "alignment_axes": (),
        "density_target": "low",
        "responsive_constraints": (),
    }
    with pytest.raises(ValidationError, match="family token"):
        LayoutProgramV4(
            **payload,
            canonical_sha256=canonical_sha256_v4(payload),
        )
    assert tokens.canonical_sha256 != "1" * 64


def test_layout_program_rejects_duplicate_emphasis_priorities_even_with_valid_hash() -> None:
    payload = {
        "page_id": "page-1",
        "page_brief_sha256": "1" * 64,
        "grammar_id": "editorial_hero",
        "template_family": "pink_red",
        "family_tokens_sha256": get_family_tokens("pink_red").canonical_sha256,
        "carousel_narrative_sha256": "2" * 64,
        "beat_ref": "beat-1",
        "beat_task_kind": "context",
        "regions": (
            {"region_id": "hero", "role": "primary", "order": 0},
        ),
        "fragment_placements": (
            {
                "fragment_ref": "fragment-1",
                "region_id": "hero",
                "order": 0,
                "alignment_axis_ids": (),
                "emphasis_rule_ids": ("rule-a", "rule-b"),
            },
        ),
        "asset_placements": (),
        "emphasis_rules": (
            {
                "rule_id": "rule-a",
                "kind": "primary_focus",
                "target_fragment_refs": ("fragment-1",),
                "priority": 0,
            },
            {
                "rule_id": "rule-b",
                "kind": "secondary_focus",
                "target_fragment_refs": ("fragment-1",),
                "priority": 0,
            },
        ),
        "alignment_axes": (),
        "density_target": "low",
        "responsive_constraints": (),
    }
    with pytest.raises(ValidationError, match="priority"):
        LayoutProgramV4(
            **payload,
            canonical_sha256=canonical_sha256_v4(payload),
        )
