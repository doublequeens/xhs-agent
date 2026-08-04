"""LLM-directed page designer producing a structured CarouselDesignPlan."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value
from src.schemas.assets import AssetManifest
from src.schemas.content_atoms import ContentAtomSet, ContentFragment, canonical_sha256
from src.schemas.scene_graph import CarouselDesignPlan
from src.schemas.visual_director import VisualDirectionPlan
from src.schemas.visual_style import FamilyStyleProfile, TemplateFamily
from src.visual_ai import StructuredVisualModel
from src.visual_design.model_retry import (
    MAX_GENERATION_ATTEMPTS,
    VisualProductionInterrupted,
    generate_validated,
)
from src.visual_design.style_registry import load_style_registry


def _direction_plan(state: Mapping[str, Any]) -> VisualDirectionPlan:
    raw = state.get("visual_direction_plan")
    if raw is None:
        raise ValueError("page_designer requires visual_direction_plan")
    if isinstance(raw, VisualDirectionPlan):
        return raw
    if isinstance(raw, Mapping):
        return VisualDirectionPlan.model_validate(raw)
    return VisualDirectionPlan.model_validate(raw)


def _atom_set(state: Mapping[str, Any]) -> ContentAtomSet:
    raw = state.get("content_atom_set")
    if raw is None:
        raise ValueError("page_designer requires content_atom_set")
    if isinstance(raw, ContentAtomSet):
        return raw
    return ContentAtomSet.model_validate(raw)


def _manifest(state: Mapping[str, Any]) -> AssetManifest:
    raw_manifest = state.get("asset_manifest")
    if raw_manifest is None:
        raise ValueError("page_designer requires asset_manifest")
    if isinstance(raw_manifest, AssetManifest):
        return raw_manifest
    return AssetManifest.model_validate(raw_manifest)


def _unresolved_optional_pages(state: Mapping[str, Any]) -> tuple[str, ...]:
    raw_unresolved = state.get("unresolved_optional_assets", ())
    pages: list[str] = []
    for item in raw_unresolved:
        page_id = item.get("page_id") if isinstance(item, Mapping) else getattr(item, "page_id", None)
        directive_id = (
            item.get("directive_id")
            if isinstance(item, Mapping)
            else getattr(item, "directive_id", None)
        )
        if page_id:
            pages.append(f"{page_id} ({directive_id})")
    return tuple(pages)


def _family_profile(
    family: TemplateFamily,
    style_profiles: Mapping[TemplateFamily, FamilyStyleProfile] | None,
) -> FamilyStyleProfile:
    registry = load_style_registry() if style_profiles is None else style_profiles
    profile = registry.get(family)
    if profile is None:
        raise ValueError(f"page_designer requires style profile for family {family}")
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
            "page_designer reference images do not exist: " + ", ".join(missing)
        )
    return paths


def _fragment_index(
    direction_plan: VisualDirectionPlan,
) -> dict[str, ContentFragment]:
    return {
        fragment.fragment_id: fragment for fragment in direction_plan.content_fragments
    }


def _designer_prompt(
    state: Mapping[str, Any],
    *,
    direction_plan: VisualDirectionPlan,
    atom_set: ContentAtomSet,
    manifest: AssetManifest,
    family_profile: FamilyStyleProfile,
    unresolved_pages: tuple[str, ...],
) -> str:
    base_prompt = compose_prompt_for_state(
        "page_designer",
        state,
        allow_legacy_beauty_fallback=False,
    )
    fragments_by_id = _fragment_index(direction_plan)
    resolved_fragments = [
        {
            "page_id": page.page_id,
            "sequence": page.sequence,
            "purpose": page.purpose,
            "visual_job": page.visual_job,
            "fragment_ids": list(page.fragment_ids),
            "fragment_text_by_id": {
                fragment_id: fragments_by_id[fragment_id].text
                for fragment_id in page.fragment_ids
                if fragment_id in fragments_by_id
            },
            "asset_directive_ids": list(page.asset_directive_ids),
        }
        for page in direction_plan.page_sequence
    ]
    approved_assets = [
        {
            "asset_id": item.asset_id,
            "directive_id": item.directive_id,
            "page_id": item.page_id,
            "width": item.width,
            "height": item.height,
            "crop_guidance": item.crop_guidance,
            "subject_focal_point": list(item.subject_focal_point),
        }
        for item in manifest.items
    ]
    context = {
        "canvas": {"width": 1080, "height": 1440},
        "family_profile": family_profile.model_dump(mode="json"),
        "approved_assets": approved_assets,
        "page_fragments": resolved_fragments,
        "unresolved_optional_pages": list(unresolved_pages),
        "immutable_hashes": {
            "direction_plan_sha256": _direction_sha(direction_plan),
            "content_atom_set_sha256": atom_set.canonical_sha256,
            "asset_manifest_sha256": _manifest_sha(manifest),
        },
    }
    return (
        f"{base_prompt}\n\n"
        "【Page Designer Inputs】\n"
        f"{serialize_prompt_value(context)}"
    )


def _direction_sha(direction_plan: VisualDirectionPlan) -> str:
    return canonical_sha256(direction_plan)


def _manifest_sha(manifest: AssetManifest) -> str:
    return canonical_sha256(manifest)


def _validate_candidate(
    candidate: CarouselDesignPlan,
    *,
    direction_plan: VisualDirectionPlan,
    atom_set: ContentAtomSet,
    manifest: AssetManifest,
) -> None:
    # Revalidate the complete dump so scripted/future adapters cannot bypass
    # Pydantic invariants by constructing a model without validation.
    validated = CarouselDesignPlan.model_validate(candidate.model_dump(mode="python"))
    validated.validate_bindings(direction_plan, atom_set, manifest)


def page_designer_node(
    state: Mapping[str, Any],
    *,
    model: StructuredVisualModel,
    style_profiles: Mapping[TemplateFamily, FamilyStyleProfile] | None = None,
) -> dict[str, object]:
    """Produce one validated CarouselDesignPlan through a three-attempt boundary."""
    direction_plan = _direction_plan(state)
    atom_set = _atom_set(state)
    manifest = _manifest(state)
    family_profile = _family_profile(direction_plan.template_family, style_profiles)
    image_paths = _reference_image_paths(family_profile)
    unresolved_pages = _unresolved_optional_pages(state)
    prompt = _designer_prompt(
        state,
        direction_plan=direction_plan,
        atom_set=atom_set,
        manifest=manifest,
        family_profile=family_profile,
        unresolved_pages=unresolved_pages,
    )

    try:
        plan = generate_validated(
            model,
            prompt=prompt,
            response_model=CarouselDesignPlan,
            image_paths=image_paths,
            validate=lambda candidate: _validate_candidate(
                candidate,
                direction_plan=direction_plan,
                atom_set=atom_set,
                manifest=manifest,
            ),
            max_attempts=MAX_GENERATION_ATTEMPTS,
        )
    except VisualProductionInterrupted as exc:
        raise VisualProductionInterrupted(
            stage="page_designer",
            errors=exc.errors,
            raw_outputs=exc.raw_outputs,
        ) from exc

    return {
        "carousel_design_plan": plan,
        "current_node": "PAGE_DESIGNER",
    }


__all__ = ["page_designer_node"]
