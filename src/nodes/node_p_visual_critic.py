"""Multimodal Visual Critic LangGraph node (Task 13).

Inspects the actual rendered carousel page PNGs (+ contact sheet) alongside
the selected family reference images, scores the carousel on eight aesthetic
dimensions plus image relevance, and drives a two-round aesthetic redesign
loop:

* round 0 (first critique) and round 1 (after one redesign) failures route to
  ``design_reviser`` for an automatic redesign;
* round 2 (the third evaluation) is terminal: a failure routes to
  ``human_review`` with ``review_status="visual_needs_attention"`` and no
  further automatic redesign is attempted.

The critic is strictly read-only. It scores and issues revision instructions;
it must never mutate content, atoms, source hashes, assets, or the selected
family. The four source hashes on the returned :class:`VisualCritique` are
re-bound to the actual content/direction/design/render hashes (never trusted
from the model); a mismatch is rejected and retried inside the bounded
``generate_validated`` loop.

Graph wiring (the cutover so ``route_after_visual_critic`` feeds the
design-reviser / human-review loop) is Task 14; this module exports the node
and the route function so ``src/graph.py`` can import both.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value
from src.schemas.content_atoms import ContentAtomSet, canonical_sha256
from src.schemas.render_manifest import RenderManifest
from src.schemas.render_qa import RenderQAResult
from src.schemas.scene_graph import CarouselDesignPlan
from src.schemas.visual_critique import VisualCritique
from src.schemas.visual_director import VisualDirectionPlan
from src.schemas.visual_style import FamilyStyleProfile, TemplateFamily
from src.visual_ai import StructuredVisualModel
from src.visual_design.model_retry import VisualProductionInterrupted, generate_validated
from src.visual_design.style_registry import load_style_registry

_ATOM_SET_KEY = "content_atom_set"
_DIRECTION_KEY = "visual_direction_plan"
_DESIGN_PLAN_KEY = "carousel_design_plan"
_RENDER_MANIFEST_KEY = "render_manifest"
_RENDER_QA_KEY = "render_qa_result"
_ROUND_KEY = "visual_critic_round"

_REVIEW_NEEDS_ATTENTION = "visual_needs_attention"
_TERMINAL_ROUND = 2


def _coerce(state: Mapping[str, Any], key: str, model_type: type, label: str):
    raw = state.get(key)
    if raw is None:
        raise ValueError(f"visual_critic requires {label}")
    if isinstance(raw, model_type):
        return raw
    return model_type.model_validate(raw)


def _render_qa_result(state: Mapping[str, Any]) -> RenderQAResult:
    raw = state.get(_RENDER_QA_KEY)
    if raw is None:
        raise ValueError("visual_critic requires render_qa_result")
    if isinstance(raw, RenderQAResult):
        return raw
    return RenderQAResult.model_validate(raw)


def _revision_round(state: Mapping[str, Any]) -> int:
    """Read the critic round counter from state.

    ``visual_critic_round`` counts how many redesigns have happened before
    this critique (0 = first critique, 1 = after one redesign, 2 = terminal
    third evaluation). It is clamped to the schema's 0..2 range so a
    defensively large counter can never violate the ``VisualCritique``
    contract; the graph loop (Task 14) cannot legitimately call the critic a
    fourth time.
    """
    raw_round = state.get(_ROUND_KEY, 0)
    try:
        round_value = int(raw_round)
    except (TypeError, ValueError) as exc:
        raise ValueError("visual_critic_round must be an integer") from exc
    return max(0, min(round_value, _TERMINAL_ROUND))


def _contains_images(design_plan: CarouselDesignPlan) -> bool:
    return any(
        element.kind == "image"
        for page in design_plan.pages
        for element in page.elements
    )


def _family_profile(
    family: TemplateFamily,
    style_profiles: Mapping[TemplateFamily, FamilyStyleProfile] | None,
) -> FamilyStyleProfile:
    registry = load_style_registry() if style_profiles is None else style_profiles
    profile = registry.get(family)
    if profile is None:
        raise ValueError(f"visual_critic requires style profile for family {family}")
    if profile.family != family:
        raise ValueError("style profile family key must match profile family")
    if not profile.reference_image_paths:
        raise ValueError("family profile requires reference images")
    return profile


def _reference_image_paths(profile: FamilyStyleProfile) -> tuple[Path, ...]:
    paths = tuple(Path(path) for path in profile.reference_image_paths)
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise ValueError(
            "visual_critic reference images do not exist: " + ", ".join(missing)
        )
    return paths


def _rendered_image_paths(render_manifest: RenderManifest) -> tuple[Path, ...]:
    """Assemble the image paths sent to the multimodal model.

    Order: every rendered page PNG (in sequence order), then the contact
    sheet, then the selected family's reference images. Each path is verified
    to exist so a stale manifest cannot hand the model a missing file.
    """
    page_paths = tuple(Path(page.path) for page in render_manifest.pages)
    contact_path = Path(render_manifest.contact_sheet_path)
    image_paths = (*page_paths, contact_path)
    missing = [str(path) for path in image_paths if not path.is_file()]
    if missing:
        raise ValueError(
            "visual_critic rendered images do not exist: " + ", ".join(missing)
        )
    return image_paths


def _critic_prompt(
    state: Mapping[str, Any],
    *,
    atom_set: ContentAtomSet,
    direction: VisualDirectionPlan,
    design_plan: CarouselDesignPlan,
    render_manifest: RenderManifest,
    render_qa: RenderQAResult,
    family_profile: FamilyStyleProfile,
    contains_images: bool,
    revision_round: int,
) -> str:
    base_prompt = compose_prompt_for_state(
        "visual_critic",
        state,
        allow_legacy_beauty_fallback=False,
    )
    context = {
        "carousel": {
            "page_count": len(render_manifest.pages),
            "page_ids": [page.page_id for page in render_manifest.pages],
            "canvas": {"width": 1080, "height": 1440},
        },
        "family": {
            "template_family": direction.template_family,
            "palette": list(family_profile.palette),
            "font_roles": dict(family_profile.font_roles),
            "composition_principles": list(family_profile.composition_principles),
            "whitespace_range": list(family_profile.whitespace_range),
            "density_range": list(family_profile.density_range),
        },
        "render_qa": {
            "passed": render_qa.passed,
            "render_manifest_sha256": render_qa.render_manifest_sha256,
        },
        "contains_images": contains_images,
        "revision_round": revision_round,
        "immutable_hashes": {
            "content_atom_set_sha256": atom_set.canonical_sha256,
            "direction_plan_sha256": canonical_sha256(direction),
            "design_plan_sha256": canonical_sha256(design_plan),
            "render_manifest_sha256": canonical_sha256(render_manifest),
        },
        "image_inventory": {
            "rendered_page_pngs": [page.path for page in render_manifest.pages],
            "contact_sheet_path": render_manifest.contact_sheet_path,
            "family_reference_images": list(family_profile.reference_image_paths),
        },
    }
    return (
        f"{base_prompt}\n\n"
        "【Visual Critic Inputs】\n"
        f"{serialize_prompt_value(context)}"
    )


def _validate_candidate(
    candidate: VisualCritique,
    *,
    expected_content_sha: str,
    expected_direction_sha: str,
    expected_design_sha: str,
    expected_render_sha: str,
    expected_contains_images: bool,
    expected_revision_round: int,
) -> None:
    # Revalidate the complete dump so scripted/future adapters cannot bypass
    # Pydantic invariants by constructing a model without validation.
    validated = VisualCritique.model_validate(candidate.model_dump(mode="python"))

    # Read-only attestation: the critic must echo the four source hashes
    # exactly. A mismatch means the model tried to alter (or failed to bind to)
    # the immutable sources — reject and retry.
    actual_hashes = {
        "content_atom_set_sha256": validated.content_atom_set_sha256,
        "direction_plan_sha256": validated.direction_plan_sha256,
        "design_plan_sha256": validated.design_plan_sha256,
        "render_manifest_sha256": validated.render_manifest_sha256,
    }
    expected_hashes = {
        "content_atom_set_sha256": expected_content_sha,
        "direction_plan_sha256": expected_direction_sha,
        "design_plan_sha256": expected_design_sha,
        "render_manifest_sha256": expected_render_sha,
    }
    for field, expected in expected_hashes.items():
        if actual_hashes[field] != expected:
            raise ValueError(
                f"visual critique {field} must equal the actual source hash; "
                f"critic returned {actual_hashes[field]}, expected {expected}. "
                "The critic is read-only and must echo the immutable hashes."
            )

    # contains_images and revision_round are node-controlled facts, not model
    # decisions. A model that fabricates or hides images, or that advances the
    # round on its own, is rejected and retried.
    if validated.contains_images != expected_contains_images:
        raise ValueError(
            f"visual critique contains_images must be {expected_contains_images}; "
            f"critic returned {validated.contains_images}."
        )
    if validated.revision_round != expected_revision_round:
        raise ValueError(
            f"visual critique revision_round must be {expected_revision_round}; "
            f"critic returned {validated.revision_round}. The round is "
            "node-controlled."
        )


def visual_critic_node(
    state: Mapping[str, Any],
    *,
    model: StructuredVisualModel,
    style_profiles: Mapping[TemplateFamily, FamilyStyleProfile] | None = None,
) -> dict[str, object]:
    """Score a rendered carousel and drive the two-round aesthetic loop."""
    render_qa = _render_qa_result(state)

    # Hard QA gate: render QA already routes failures to the design reviser.
    # Defend in-depth by never invoking the multimodal model on a carousel
    # that failed render QA; surface a clean route back to the reviser.
    if not render_qa.passed:
        return {
            "route": "design_reviser",
            "current_node": "VISUAL_CRITIC",
        }

    atom_set = _coerce(state, _ATOM_SET_KEY, ContentAtomSet, "content_atom_set")
    direction = _coerce(state, _DIRECTION_KEY, VisualDirectionPlan, "visual_direction_plan")
    design_plan = _coerce(state, _DESIGN_PLAN_KEY, CarouselDesignPlan, "carousel_design_plan")
    render_manifest = _coerce(state, _RENDER_MANIFEST_KEY, RenderManifest, "render_manifest")

    revision_round_value = _revision_round(state)
    contains_images_value = _contains_images(design_plan)
    family_profile = _family_profile(direction.template_family, style_profiles)

    image_paths = (
        *_rendered_image_paths(render_manifest),
        *_reference_image_paths(family_profile),
    )

    expected_content_sha = atom_set.canonical_sha256
    expected_direction_sha = canonical_sha256(direction)
    expected_design_sha = canonical_sha256(design_plan)
    expected_render_sha = canonical_sha256(render_manifest)

    prompt = _critic_prompt(
        state,
        atom_set=atom_set,
        direction=direction,
        design_plan=design_plan,
        render_manifest=render_manifest,
        render_qa=render_qa,
        family_profile=family_profile,
        contains_images=contains_images_value,
        revision_round=revision_round_value,
    )

    try:
        critique = generate_validated(
            model,
            prompt=prompt,
            response_model=VisualCritique,
            image_paths=image_paths,
            validate=lambda candidate: _validate_candidate(
                candidate,
                expected_content_sha=expected_content_sha,
                expected_direction_sha=expected_direction_sha,
                expected_design_sha=expected_design_sha,
                expected_render_sha=expected_render_sha,
                expected_contains_images=contains_images_value,
                expected_revision_round=revision_round_value,
            ),
            max_attempts=3,
        )
    except VisualProductionInterrupted as exc:
        raise VisualProductionInterrupted(
            stage="visual_critic",
            errors=exc.errors,
            raw_outputs=exc.raw_outputs,
        ) from exc

    result: dict[str, object] = {
        "visual_critique": critique,
        "current_node": "VISUAL_CRITIC",
        # Advance the round counter so the next critique (after a redesign)
        # reflects one more pass. The stamped revision_round on this critique
        # is the pre-increment value (0, 1, or 2).
        _ROUND_KEY: revision_round_value + 1,
    }

    # A failed terminal critique routes to Human Review; flag it so reviewers
    # can see the carousel needs visual attention. Passed critiques also route
    # to Human Review but do not carry the needs-attention flag.
    if not critique.passed and critique.revision_round >= _TERMINAL_ROUND:
        result["review_status"] = _REVIEW_NEEDS_ATTENTION

    return result


def route_after_visual_critic(
    state: Mapping[str, Any],
) -> Literal["design_reviser", "human_review"]:
    critique = state["visual_critique"]
    if critique.passed:
        return "human_review"
    if critique.revision_round < 2:
        return "design_reviser"
    return "human_review"


__all__ = [
    "route_after_visual_critic",
    "visual_critic_node",
]
