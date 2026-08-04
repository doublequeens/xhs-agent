"""Constrained reviser for an approved CarouselDesignPlan."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, Union

from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value
from src.schemas.assets import AssetManifest
from src.schemas.content_atoms import ContentAtomSet, canonical_sha256
from src.schemas.design_qa import DesignIssue, DesignPlanQAResult
from src.schemas.render_qa import RenderIssue, RenderQAResult
from src.schemas.scene_graph import CarouselDesignPlan
from src.schemas.visual_critique import VisualCritique, VisualCritiqueIssue
from src.schemas.visual_director import VisualDirectionPlan
from src.schemas.visual_style import FamilyStyleProfile, StrictModel, TemplateFamily
from src.visual_ai import StructuredVisualModel
from src.visual_design.model_retry import (
    MAX_GENERATION_ATTEMPTS,
    VisualProductionInterrupted,
    generate_validated,
)
from src.visual_design.style_registry import load_style_registry


RevisionIssue = Union[DesignIssue, RenderIssue, VisualCritiqueIssue]


class RevisionRequest(StrictModel):
    source: Literal["design_plan_qa", "render_qa", "visual_critic", "human_review"]
    issues: tuple[RevisionIssue, ...]
    current_revision: int


# Sentinel phrases that indicate family/page-count replanning is required.
# Matched case-insensitively against any free-text field of an issue.
# Family patterns are scoped to intent-bearing phrases so a page-level note
# that merely mentions "family" (e.g. "color drifts from the family palette",
# "improve family consistency") does not burn a visual_director cycle. The
# underscore rule name ``family_consistency`` never matches on its own.
_FAMILY_VERB_BEFORE = re.compile(
    r"\b(?:change|switch|swap|replace|replan|pick|choose|select)\s+"
    r"(?:a\s+|the\s+)?(?:new\s+|different\s+)?family\b",
    re.IGNORECASE,
)
_FAMILY_NEW_OR_DIFFERENT = re.compile(r"\b(?:new|different)\s+family\b", re.IGNORECASE)
_FAMILY_CHANGE_AFTER = re.compile(
    r"\bfamily\s+(?:no\s+longer\s+fits?|does\s+not\s+fit|doesn't\s+fit|"
    r"must\s+change|needs?\s+to\s+change|should\s+change|to\s+change|is\s+wrong)\b",
    re.IGNORECASE,
)
_REPLAN_PATTERNS = (
    _FAMILY_VERB_BEFORE,
    _FAMILY_NEW_OR_DIFFERENT,
    _FAMILY_CHANGE_AFTER,
    re.compile(r"\bpage[\s-]?count\b", re.IGNORECASE),
    re.compile(r"\bpage_count\b", re.IGNORECASE),
    re.compile(r"\badd(?:\s+a)?\s+page\b", re.IGNORECASE),
    re.compile(r"\bremove(?:\s+a)?\s+page\b", re.IGNORECASE),
    re.compile(r"\b(?:drop|insert)\s+(?:a\s+)?page\b", re.IGNORECASE),
    re.compile(r"\breplan\b", re.IGNORECASE),
    re.compile(r"\bcarousel\s+length\b", re.IGNORECASE),
)


def _issue_text(issue: RevisionIssue) -> str:
    parts = [issue.rule, issue.message]
    repair = getattr(issue, "repair_instruction", None)
    if repair:
        parts.append(repair)
    revision = getattr(issue, "revision_instruction", None)
    if revision:
        parts.append(revision)
    return "\n".join(parts)


def _requires_replan(
    issues: tuple[RevisionIssue, ...],
    before: CarouselDesignPlan,
) -> bool:
    known_page_ids = {page.page_id for page in before.pages}
    for issue in issues:
        if issue.page_id is not None and issue.page_id not in known_page_ids:
            return True
        text = _issue_text(issue)
        if any(pattern.search(text) for pattern in _REPLAN_PATTERNS):
            return True
    return False


def _named_page_ids(issues: tuple[RevisionIssue, ...]) -> frozenset[str]:
    return frozenset(
        issue.page_id for issue in issues if issue.page_id is not None
    )


def validate_revision(
    before: CarouselDesignPlan,
    after: CarouselDesignPlan,
) -> None:
    if after.content_atom_set_sha256 != before.content_atom_set_sha256:
        raise ValueError("revision changed content binding")
    if after.asset_manifest_sha256 != before.asset_manifest_sha256:
        raise ValueError("revision changed asset binding")
    if tuple(page.page_id for page in after.pages) != tuple(
        page.page_id for page in before.pages
    ):
        raise ValueError("family or page-sequence changes require visual_director")


def _validate_candidate(
    candidate: CarouselDesignPlan,
    *,
    before: CarouselDesignPlan,
    direction_plan: VisualDirectionPlan,
    atom_set: ContentAtomSet,
    manifest: AssetManifest,
    named_pages: frozenset[str],
    current_revision: int,
) -> None:
    # Revalidate the complete dump so scripted/future adapters cannot bypass
    # Pydantic invariants by constructing a model without validation.
    validated = CarouselDesignPlan.model_validate(candidate.model_dump(mode="python"))
    validate_revision(before, validated)
    # Re-run binding checks so an unapproved asset or stale fragment reference
    # cannot slip through the revision.
    validated.validate_bindings(direction_plan, atom_set, manifest)
    if validated.revision != current_revision + 1:
        raise ValueError(
            f"revision must increment from {current_revision} to "
            f"{current_revision + 1}; got {validated.revision}"
        )
    # Patches may only touch named pages; every other page must stay verbatim.
    before_pages = {page.page_id: page for page in before.pages}
    for after_page in validated.pages:
        if after_page.page_id in named_pages:
            continue
        before_page = before_pages[after_page.page_id]
        if after_page != before_page:
            raise ValueError(
                "revision must not modify pages that the issues do not name: "
                f"{after_page.page_id}"
            )
    # A revision that edits nothing (a pure revision bump) makes no progress
    # toward resolving the QA issues; force the model to actually change at
    # least one page the issues name.
    if named_pages and not any(
        after_page.page_id in named_pages and after_page != before_pages[after_page.page_id]
        for after_page in validated.pages
    ):
        raise ValueError(
            "revision must modify at least one page named by the issues: "
            + ", ".join(sorted(named_pages))
        )


def _design_plan(state: Mapping[str, Any]) -> CarouselDesignPlan:
    raw = state.get("carousel_design_plan")
    if raw is None:
        raise ValueError("design_reviser requires carousel_design_plan")
    if isinstance(raw, CarouselDesignPlan):
        return raw
    return CarouselDesignPlan.model_validate(raw)


def _revision_request_from_state(
    state: Mapping[str, Any],
    design_plan: CarouselDesignPlan,
) -> RevisionRequest:
    """Build a RevisionRequest from the failing QA/critic result in state.

    Production routing never injects ``revision_request`` explicitly: the
    graph routes into ``design_reviser`` from ``design_plan_qa``,
    ``render_qa``, or ``visual_critic``, and the triggering result is already
    in state. Exactly one of those results is the active failure; prefer the
    most downstream failing one (visual_critic > render_qa > design_plan_qa)
    so a stale upstream result is never mistaken for the trigger. In the
    normal loop only one is failing at a time because each gate overwrites
    its own result on every pass.
    """
    visual_critique_raw = state.get("visual_critique")
    if visual_critique_raw is not None:
        critique = (
            visual_critique_raw
            if isinstance(visual_critique_raw, VisualCritique)
            else VisualCritique.model_validate(visual_critique_raw)
        )
        if not critique.passed:
            return RevisionRequest(
                source="visual_critic",
                issues=critique.issues,
                current_revision=design_plan.revision,
            )
    render_qa_raw = state.get("render_qa_result")
    if render_qa_raw is not None:
        render_qa = (
            render_qa_raw
            if isinstance(render_qa_raw, RenderQAResult)
            else RenderQAResult.model_validate(render_qa_raw)
        )
        if not render_qa.passed:
            return RevisionRequest(
                source="render_qa",
                issues=render_qa.issues,
                current_revision=design_plan.revision,
            )
    design_qa_raw = state.get("design_plan_qa_result")
    if design_qa_raw is not None:
        design_qa = (
            design_qa_raw
            if isinstance(design_qa_raw, DesignPlanQAResult)
            else DesignPlanQAResult.model_validate(design_qa_raw)
        )
        if not design_qa.passed:
            return RevisionRequest(
                source="design_plan_qa",
                issues=design_qa.issues,
                current_revision=design_plan.revision,
            )
    raise ValueError(
        "design_reviser cannot build a revision request: no failing "
        "design_plan_qa_result, render_qa_result, or visual_critique in state "
        "and no explicit revision_request was injected"
    )


def _revision_request(
    state: Mapping[str, Any],
    design_plan: CarouselDesignPlan,
) -> RevisionRequest:
    """Resolve the RevisionRequest, falling back to state when unset.

    Unit tests inject ``revision_request`` directly; the production graph does
    not (no node writes it), so when it is absent we assemble one from the
    failing QA/critic result already in state. Without this fallback every
    failure route into the reviser crashes with ValueError.
    """
    raw = state.get("revision_request")
    if raw is None:
        return _revision_request_from_state(state, design_plan)
    if isinstance(raw, RevisionRequest):
        return raw
    return RevisionRequest.model_validate(raw)


def _direction_plan(state: Mapping[str, Any]) -> VisualDirectionPlan:
    raw = state.get("visual_direction_plan")
    if raw is None:
        raise ValueError("design_reviser requires visual_direction_plan")
    if isinstance(raw, VisualDirectionPlan):
        return raw
    return VisualDirectionPlan.model_validate(raw)


def _atom_set(state: Mapping[str, Any]) -> ContentAtomSet:
    raw = state.get("content_atom_set")
    if raw is None:
        raise ValueError("design_reviser requires content_atom_set")
    if isinstance(raw, ContentAtomSet):
        return raw
    return ContentAtomSet.model_validate(raw)


def _manifest(state: Mapping[str, Any]) -> AssetManifest:
    raw_manifest = state.get("asset_manifest")
    if raw_manifest is None:
        raise ValueError("design_reviser requires asset_manifest")
    if isinstance(raw_manifest, AssetManifest):
        return raw_manifest
    return AssetManifest.model_validate(raw_manifest)


def _family_profile(
    family: TemplateFamily,
    style_profiles: Mapping[TemplateFamily, FamilyStyleProfile] | None,
) -> FamilyStyleProfile:
    registry = load_style_registry() if style_profiles is None else style_profiles
    profile = registry.get(family)
    if profile is None:
        raise ValueError(f"design_reviser requires style profile for family {family}")
    return profile


def _reference_image_paths(profile: FamilyStyleProfile) -> tuple[Path, ...]:
    paths = tuple(Path(path) for path in profile.reference_image_paths)
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise ValueError(
            "design_reviser reference images do not exist: " + ", ".join(missing)
        )
    return paths


def _reviser_prompt(
    state: Mapping[str, Any],
    *,
    before: CarouselDesignPlan,
    request: RevisionRequest,
    direction_plan: VisualDirectionPlan,
    atom_set: ContentAtomSet,
    manifest: AssetManifest,
    family_profile: FamilyStyleProfile,
    named_pages: frozenset[str],
) -> str:
    base_prompt = compose_prompt_for_state(
        "design_reviser",
        state,
        allow_legacy_beauty_fallback=False,
    )
    context = {
        "before_plan": before.model_dump(mode="json"),
        "named_pages": sorted(named_pages),
        "revision_request": {
            "source": request.source,
            "current_revision": request.current_revision,
            "issues": [issue.model_dump(mode="json") for issue in request.issues],
        },
        "family_profile": family_profile.model_dump(mode="json"),
        "direction_plan": {
            "template_family": direction_plan.template_family,
            "page_count": direction_plan.page_count,
            "page_ids": [page.page_id for page in direction_plan.page_sequence],
        },
        "approved_asset_ids": [item.asset_id for item in manifest.items],
        "immutable_hashes": {
            "direction_plan_sha256": canonical_sha256(direction_plan),
            "content_atom_set_sha256": atom_set.canonical_sha256,
            "asset_manifest_sha256": canonical_sha256(manifest),
        },
        "next_revision": request.current_revision + 1,
    }
    return (
        f"{base_prompt}\n\n"
        "【Design Reviser Inputs】\n"
        f"{serialize_prompt_value(context)}"
    )


def design_reviser_node(
    state: Mapping[str, Any],
    *,
    model: StructuredVisualModel,
    style_profiles: Mapping[TemplateFamily, FamilyStyleProfile] | None = None,
) -> dict[str, object]:
    """Constrainedly revise a CarouselDesignPlan or signal visual_director."""
    before = _design_plan(state)
    request = _revision_request(state, before)
    direction_plan = _direction_plan(state)
    atom_set = _atom_set(state)
    manifest = _manifest(state)

    if _requires_replan(request.issues, before):
        return {
            "route": "visual_director",
            "current_node": "DESIGN_REVISER",
        }

    family_profile = _family_profile(direction_plan.template_family, style_profiles)
    image_paths = _reference_image_paths(family_profile)
    named_pages = _named_page_ids(request.issues)
    prompt = _reviser_prompt(
        state,
        before=before,
        request=request,
        direction_plan=direction_plan,
        atom_set=atom_set,
        manifest=manifest,
        family_profile=family_profile,
        named_pages=named_pages,
    )

    try:
        revised = generate_validated(
            model,
            prompt=prompt,
            response_model=CarouselDesignPlan,
            image_paths=image_paths,
            validate=lambda candidate: _validate_candidate(
                candidate,
                before=before,
                direction_plan=direction_plan,
                atom_set=atom_set,
                manifest=manifest,
                named_pages=named_pages,
                current_revision=request.current_revision,
            ),
            max_attempts=MAX_GENERATION_ATTEMPTS,
        )
    except VisualProductionInterrupted as exc:
        raise VisualProductionInterrupted(
            stage="design_reviser",
            errors=exc.errors,
            raw_outputs=exc.raw_outputs,
        ) from exc

    return {
        "carousel_design_plan": revised,
        "current_node": "DESIGN_REVISER",
    }


__all__ = [
    "RevisionRequest",
    "design_reviser_node",
    "validate_revision",
]
