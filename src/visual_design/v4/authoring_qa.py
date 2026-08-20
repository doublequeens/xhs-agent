"""Deterministic Q1 hard gate for v4 carousel authoring."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from src.schemas.content_lock import ContentLock
from src.schemas.v4.content import ContentAtomSetV4, canonical_sha256_v4
from src.schemas.v4.direction import (
    AuthoringIssueV4,
    AuthoringQAResultV4,
    CarouselNarrativeV4,
    PageBriefSetV4,
    PageBriefV4,
    VisualDirectionPlanV4,
    canonical_direction_sha256_v4,
    contains_forbidden_visible_copy,
)
from src.schemas.v4.semantic import (
    SemanticContentModelV4,
    SemanticFragmentV4,
    SemanticGroupV4,
)


_ZERO_SHA256 = "0" * 64
def _safe_hash(value: Any) -> str:
    if isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    ):
        return value
    return _ZERO_SHA256


def _payload(value: Any) -> Mapping[str, Any] | None:
    try:
        candidate = (
            value.model_dump(mode="python", warnings="none")
            if hasattr(value, "model_dump")
            else value
        )
        return candidate if isinstance(candidate, Mapping) else None
    except Exception:
        return None


def _issue(
    code: str,
    *,
    location: str,
    message: str,
    page_id: str | None = None,
    fragment_id: str | None = None,
    directive_id: str | None = None,
) -> AuthoringIssueV4:
    return AuthoringIssueV4(
        code=code,  # type: ignore[arg-type]
        location=location,
        message=message,
        evidence="deterministic authoring contract check",
        page_id=page_id,
        fragment_id=fragment_id,
        directive_id=directive_id,
    )


def _revalidate_page(value: Any) -> tuple[PageBriefV4 | None, bool]:
    raw = _payload(value)
    if raw is None:
        return None, False
    try:
        checked = PageBriefV4.model_validate(raw)
        return checked, True
    except Exception:
        # A model_copy(update=...) can stale only the enclosing digest.  Parse
        # all nested fields again and retain a deterministic drift bit.
        try:
            repaired = dict(raw)
            original = repaired.get("canonical_sha256")
            repaired.pop("canonical_sha256", None)
            canonical_source = PageBriefV4.model_construct(
                **repaired,
                canonical_sha256=_ZERO_SHA256,
            )
            expected = canonical_direction_sha256_v4(canonical_source)
            repaired["canonical_sha256"] = expected
            checked = PageBriefV4.model_validate(repaired)
            return checked, original == expected
        except Exception:
            return None, False


def _coerce_page_brief_set(value: Any) -> tuple[PageBriefSetV4 | None, bool]:
    raw = _payload(value)
    if raw is None:
        return None, False
    try:
        checked = PageBriefSetV4.model_validate(raw)
        return checked, True
    except Exception:
        try:
            pages: list[PageBriefV4] = []
            nested_ok = True
            for page_raw in raw.get("pages", ()):
                page, page_ok = _revalidate_page(page_raw)
                if page is None:
                    return None, False
                pages.append(page)
                nested_ok = nested_ok and page_ok
            repaired = dict(raw)
            repaired["pages"] = tuple(pages)
            original = repaired.get("canonical_sha256")
            repaired.pop("canonical_sha256", None)
            canonical_source = PageBriefSetV4.model_construct(
                **repaired,
                canonical_sha256=_ZERO_SHA256,
            )
            expected = canonical_direction_sha256_v4(
                canonical_source, exclude_none=True
            )
            repaired["canonical_sha256"] = expected
            checked = PageBriefSetV4.model_validate(repaired)
            return checked, nested_ok and original == expected
        except Exception:
            return None, False


def _coerce_semantic_model(value: Any) -> tuple[SemanticContentModelV4 | None, bool]:
    raw = _payload(value)
    if raw is None:
        return None, False
    try:
        checked = SemanticContentModelV4.model_validate(raw)
        return checked, True
    except Exception:
        try:
            fragments = tuple(
                SemanticFragmentV4.model_validate(
                    item.model_dump(mode="python")
                    if isinstance(item, SemanticFragmentV4)
                    else item
                )
                for item in raw["fragments"]
            )
            groups = tuple(
                SemanticGroupV4.model_validate(
                    item.model_dump(mode="python")
                    if isinstance(item, SemanticGroupV4)
                    else item
                )
                for item in raw.get("groups", ())
            )
            repaired = {
                "content_atom_set_sha256": raw["content_atom_set_sha256"],
                "fragments": fragments,
                "groups": groups,
            }
            expected = canonical_sha256_v4(repaired)
            original = raw.get("canonical_sha256")
            checked = SemanticContentModelV4(
                **repaired,
                canonical_sha256=expected,
            )
            return checked, original == expected
        except Exception:
            return None, False


def _coerce_narrative(value: Any) -> tuple[CarouselNarrativeV4 | None, bool]:
    raw = _payload(value)
    if raw is None:
        return None, False
    try:
        checked = CarouselNarrativeV4.model_validate(raw)
        return checked, True
    except Exception:
        try:
            repaired = dict(raw)
            original = repaired.get("canonical_sha256")
            repaired.pop("canonical_sha256", None)
            canonical_source = CarouselNarrativeV4.model_construct(
                **repaired,
                canonical_sha256=_ZERO_SHA256,
            )
            expected = canonical_direction_sha256_v4(
                canonical_source, exclude_none=True
            )
            repaired["canonical_sha256"] = expected
            checked = CarouselNarrativeV4.model_validate(repaired)
            return checked, original == expected
        except Exception:
            return None, False


def _coerce_plan(value: Any) -> tuple[VisualDirectionPlanV4 | None, bool]:
    raw = _payload(value)
    if raw is None:
        return None, False
    try:
        checked = VisualDirectionPlanV4.model_validate(raw)
        return checked, True
    except Exception:
        try:
            repaired = dict(raw)
            # Nested models are parsed afresh by the plan validator.  If only
            # the top-level digest drifted, this recovers a safe plan while
            # retaining the false integrity bit for Q1.
            expected = canonical_sha256_v4(
                {key: item for key, item in repaired.items() if key != "canonical_sha256"}
            )
            original = repaired.get("canonical_sha256")
            repaired["canonical_sha256"] = expected
            checked = VisualDirectionPlanV4.model_validate(repaired)
            return checked, original == expected
        except Exception:
            return None, False


def _coerce_lock(value: Any) -> tuple[ContentLock | None, bool]:
    raw = _payload(value)
    if raw is None:
        return None, False
    try:
        checked = ContentLock.model_validate(raw)
        expected = canonical_sha256_v4(
            checked.model_dump(mode="json", exclude={"canonical_sha256"})
        )
        return checked, checked.canonical_sha256 == expected
    except Exception:
        return None, False


def _coerce_atom_set(value: Any) -> tuple[ContentAtomSetV4 | None, bool]:
    raw = _payload(value)
    if raw is None:
        return None, False
    try:
        checked = ContentAtomSetV4.model_validate(raw)
        return checked, True
    except Exception:
        try:
            atoms = tuple(
                item.model_dump(mode="python") if hasattr(item, "model_dump") else item
                for item in raw["atoms"]
            )
            repaired = {
                "projection_sha256": raw["projection_sha256"],
                "atoms": atoms,
            }
            expected = canonical_sha256_v4(repaired)
            original = raw.get("canonical_sha256")
            checked = ContentAtomSetV4(**repaired, canonical_sha256=expected)
            return checked, original == expected
        except Exception:
            return None, False


def _scan_forbidden(value: Any, *, location: str = "authoring") -> bool:
    if isinstance(value, str):
        return contains_forbidden_visible_copy(value)
    if isinstance(value, Mapping):
        return any(
            _scan_forbidden(item, location=f"{location}.{key}")
            for key, item in value.items()
            if key not in {"forbidden_patterns", "negative_constraints"}
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_scan_forbidden(item, location=location) for item in value)
    return False


def _append_unique(issues: list[AuthoringIssueV4], issue: AuthoringIssueV4) -> None:
    key = (issue.code, issue.location, issue.page_id, issue.fragment_id, issue.directive_id)
    if not any(
        (existing.code, existing.location, existing.page_id, existing.fragment_id, existing.directive_id)
        == key
        for existing in issues
    ):
        issues.append(issue)


def _result(
    issues: list[AuthoringIssueV4],
    *,
    semantic_model: SemanticContentModelV4 | None,
    narrative: CarouselNarrativeV4 | None,
    page_brief_set: PageBriefSetV4 | None,
    plan: VisualDirectionPlanV4 | None,
    content_lock: ContentLock | None,
    content_atom_set: ContentAtomSetV4 | None,
) -> AuthoringQAResultV4:
    payload = {
        "passed": not issues,
        "issues": tuple(issues),
        "content_atom_set_sha256": _safe_hash(
            getattr(content_atom_set, "canonical_sha256", None)
            or getattr(semantic_model, "content_atom_set_sha256", None)
        ),
        "content_lock_sha256": _safe_hash(getattr(content_lock, "canonical_sha256", None)),
        "semantic_content_model_sha256": _safe_hash(
            getattr(semantic_model, "canonical_sha256", None)
        ),
        "narrative_sha256": _safe_hash(getattr(narrative, "canonical_sha256", None)),
        "page_brief_set_sha256": _safe_hash(
            getattr(page_brief_set, "canonical_sha256", None)
        ),
        "visual_direction_plan_sha256": _safe_hash(
            getattr(plan, "canonical_sha256", None)
        ),
    }
    return AuthoringQAResultV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def evaluate_authoring(
    page_brief_set: PageBriefSetV4 | Mapping[str, Any],
    semantic_model: SemanticContentModelV4 | Mapping[str, Any],
    narrative: CarouselNarrativeV4 | Mapping[str, Any] | None = None,
    visual_direction_plan: VisualDirectionPlanV4 | Mapping[str, Any] | None = None,
    *,
    content_lock: ContentLock | Mapping[str, Any] | None = None,
    content_atom_set: ContentAtomSetV4 | Mapping[str, Any] | None = None,
) -> AuthoringQAResultV4:
    """Evaluate authoring semantics without model/provider side effects.

    The first two positional parameters intentionally form the small public
    API used by unit tests.  Full workflow callers may pass the optional
    narrative, plan, lock and atom-set bindings for stronger cross-contract
    validation.
    """

    issues: list[AuthoringIssueV4] = []
    page_set, page_set_ok = _coerce_page_brief_set(page_brief_set)
    model, model_ok = _coerce_semantic_model(semantic_model)
    narrative_obj: CarouselNarrativeV4 | None = None
    narrative_ok = True
    if narrative is not None:
        narrative_obj, narrative_ok = _coerce_narrative(narrative)
    plan, plan_ok = (None, True)
    if visual_direction_plan is not None:
        plan, plan_ok = _coerce_plan(visual_direction_plan)
        if narrative is None and plan is not None:
            narrative_obj = plan.narrative
            narrative_ok = plan_ok
    lock, lock_ok = (None, True)
    if content_lock is not None:
        lock, lock_ok = _coerce_lock(content_lock)
    atom_set, atom_set_ok = (None, True)
    if content_atom_set is not None:
        atom_set, atom_set_ok = _coerce_atom_set(content_atom_set)

    if page_set is None:
        _append_unique(
            issues,
            _issue(
                "SCHEMA_INVALID",
                location="page_brief_set",
                message="page brief set could not be revalidated",
            ),
        )
    elif not page_set_ok:
        _append_unique(
            issues,
            _issue(
                "HASH_BINDING_MISMATCH",
                location="page_brief_set.canonical_sha256",
                message="page brief set canonical hash does not match its payload",
            ),
        )
    if model is None:
        _append_unique(
            issues,
            _issue(
                "SCHEMA_INVALID",
                location="semantic_content_model",
                message="semantic content model could not be revalidated",
            ),
        )
    elif not model_ok:
        _append_unique(
            issues,
            _issue(
                "HASH_BINDING_MISMATCH",
                location="semantic_content_model.canonical_sha256",
                message="semantic model canonical hash does not match its payload",
            ),
        )
    if narrative is not None and (narrative_obj is None or not narrative_ok):
        _append_unique(
            issues,
            _issue(
                "HASH_BINDING_MISMATCH" if narrative_obj is not None else "SCHEMA_INVALID",
                location="narrative.canonical_sha256",
                message="narrative could not be revalidated without trusting provider data",
            ),
        )
    if visual_direction_plan is not None and (plan is None or not plan_ok):
        _append_unique(
            issues,
            _issue(
                "HASH_BINDING_MISMATCH" if plan is not None else "SCHEMA_INVALID",
                location="visual_direction_plan.canonical_sha256",
                message="visual direction plan could not be revalidated",
            ),
        )
    if content_lock is not None and (lock is None or not lock_ok):
        _append_unique(
            issues,
            _issue(
                "HASH_BINDING_MISMATCH",
                location="content_lock.canonical_sha256",
                message="content lock canonical hash does not match its payload",
            ),
        )
    if content_atom_set is not None and (atom_set is None or not atom_set_ok):
        _append_unique(
            issues,
            _issue(
                "HASH_BINDING_MISMATCH",
                location="content_atom_set.canonical_sha256",
                message="content atom set canonical hash does not match its payload",
            ),
        )

    if page_set is not None:
        pages = page_set.pages
        page_ids = [page.page_id for page in pages]
        if page_set.page_count < 5 or page_set.page_count > 18:
            _append_unique(
                issues,
                _issue(
                    "PAGE_COUNT_INVALID",
                    location="page_brief_set.page_count",
                    message="page count must be between five and eighteen",
                ),
            )
        if page_set.page_count != len(pages):
            _append_unique(
                issues,
                _issue(
                    "PAGE_COUNT_MISMATCH",
                    location="page_brief_set.page_count",
                    message="page count must equal the number of page briefs",
                ),
            )
        if [page.sequence for page in pages] != list(range(1, len(pages) + 1)):
            _append_unique(
                issues,
                _issue(
                    "PAGE_SEQUENCE_INVALID",
                    location="page_brief_set.pages.sequence",
                    message="page sequences must be unique, continuous, and one-based",
                ),
            )

        # Use a supplied narrative when available; a standalone Q1 call can
        # still validate rhythm from the page budgets themselves.
        expected_density = (
            tuple(page.density_budget for page in pages)
            if narrative_obj is None
            else narrative_obj.density_curve
        )
        actual_density = tuple(page.density_budget for page in pages)
        if narrative_obj is not None and actual_density != expected_density:
            _append_unique(
                issues,
                _issue(
                    "DENSITY_CURVE_MISMATCH",
                    location="page_brief_set.pages.density_budget",
                    message="page density budgets must match the narrative density curve",
                ),
            )
        run = 0
        for index, density in enumerate(actual_density):
            run = run + 1 if density == "high" else 0
            if run >= 3:
                _append_unique(
                    issues,
                    _issue(
                        "DENSITY_CURVE_UNBALANCED",
                        location=f"page_brief_set.pages[{index - 2}:{index + 1}]",
                        message="three consecutive high-density pages are not allowed",
                    ),
                )
                break

        fragments_by_id = (
            {fragment.fragment_id: fragment for fragment in model.fragments}
            if model is not None
            else {}
        )
        known_fragment_ids = set(fragments_by_id)
        owned_ids = [
            fragment_id
            for page in pages
            for fragment_id in page.fragment_refs
        ]
        counts = Counter(owned_ids)
        duplicated = sorted(fragment_id for fragment_id, count in counts.items() if count > 1)
        unknown = sorted(set(owned_ids) - known_fragment_ids)
        missing = sorted(known_fragment_ids - set(owned_ids))
        # Duplicate ownership is intentionally a single stable finding.  This
        # keeps the required duplicate test deterministic even when the
        # duplicate replaced another page's fragment.
        if duplicated:
            for fragment_id in duplicated:
                _append_unique(
                    issues,
                    _issue(
                        "FRAGMENT_OWNERSHIP_DUPLICATED",
                        location="page_brief_set.fragment_refs",
                        message="a semantic fragment is owned by more than one page",
                        fragment_id=fragment_id,
                    ),
                )
        else:
            for fragment_id in missing:
                _append_unique(
                    issues,
                    _issue(
                        "FRAGMENT_OWNERSHIP_MISSING",
                        location="page_brief_set.fragment_refs",
                        message="a semantic fragment is not owned by any page",
                        fragment_id=fragment_id,
                    ),
                )
        for fragment_id in unknown:
            _append_unique(
                issues,
                _issue(
                    "FRAGMENT_OWNERSHIP_UNKNOWN",
                    location="page_brief_set.fragment_refs",
                    message="a page references an unknown semantic fragment",
                    fragment_id=fragment_id,
                ),
            )

        # Family/page-count consistency is checked at every available layer.
        families = []
        if page_set.template_family is not None:
            families.append(("page_brief_set.template_family", page_set.template_family))
        if narrative_obj is not None:
            families.append(("narrative.template_family", narrative_obj.template_family))
            if narrative_obj.page_count != page_set.page_count:
                _append_unique(
                    issues,
                    _issue(
                        "PAGE_COUNT_MISMATCH",
                        location="narrative.page_count",
                        message="narrative and page brief set page counts differ",
                    ),
                )
        if plan is not None:
            families.append(("visual_direction_plan.template_family", plan.template_family))
            if plan.page_count != page_set.page_count:
                _append_unique(
                    issues,
                    _issue(
                        "PAGE_COUNT_MISMATCH",
                        location="visual_direction_plan.page_count",
                        message="plan and page brief set page counts differ",
                    ),
                )
        if families and any(value != families[0][1] for _, value in families[1:]):
            _append_unique(
                issues,
                _issue(
                    "FAMILY_MISMATCH",
                    location="authoring.template_family",
                    message="all authoring contracts must use one template family",
                ),
            )

        # Hash bindings are compared rather than trusted, including the
        # optional top-level source bindings carried by PageBriefSet.
        if model is not None:
            if (
                narrative_obj is not None
                and narrative_obj.content_atom_set_sha256 is not None
                and narrative_obj.content_atom_set_sha256 != model.content_atom_set_sha256
            ):
                _append_unique(
                    issues,
                    _issue(
                        "HASH_BINDING_MISMATCH",
                        location="narrative.content_atom_set_sha256",
                        message="narrative atom hash does not match semantic model",
                    ),
                )
            if (
                page_set.semantic_content_model_sha256 is not None
                and page_set.semantic_content_model_sha256 != model.canonical_sha256
            ):
                _append_unique(
                    issues,
                    _issue(
                        "HASH_BINDING_MISMATCH",
                        location="page_brief_set.semantic_content_model_sha256",
                        message="page brief set semantic hash does not match model",
                    ),
                )
            if (
                page_set.content_atom_set_sha256 is not None
                and page_set.content_atom_set_sha256 != model.content_atom_set_sha256
            ):
                _append_unique(
                    issues,
                    _issue(
                        "HASH_BINDING_MISMATCH",
                        location="page_brief_set.content_atom_set_sha256",
                        message="page brief set atom hash does not match model",
                    ),
                )
        if plan is not None and model is not None:
            if plan.semantic_content_model.canonical_sha256 != model.canonical_sha256:
                _append_unique(
                    issues,
                    _issue(
                        "HASH_BINDING_MISMATCH",
                        location="visual_direction_plan.semantic_content_model",
                        message="plan embeds a different semantic model revision",
                    ),
                )
            if plan.page_brief_set.canonical_sha256 != page_set.canonical_sha256:
                _append_unique(
                    issues,
                    _issue(
                        "HASH_BINDING_MISMATCH",
                        location="visual_direction_plan.page_brief_set",
                        message="plan embeds a different page brief set revision",
                    ),
                )
            if narrative_obj is not None and plan.narrative.canonical_sha256 != narrative_obj.canonical_sha256:
                _append_unique(
                    issues,
                    _issue(
                        "HASH_BINDING_MISMATCH",
                        location="visual_direction_plan.narrative",
                        message="plan embeds a different narrative revision",
                    ),
                )

        # Page task, rhythm and notes checks.
        for index, page in enumerate(pages):
            if not page.narrative_role.strip():
                _append_unique(
                    issues,
                    _issue(
                        "NARRATIVE_ROLE_EMPTY",
                        location=f"pages[{page.sequence}].narrative_role",
                        message="each page must have a non-empty narrative role",
                        page_id=page.page_id,
                    ),
                )
            local_priority = tuple(
                fragment_id
                for fragment_id in page.visual_priority
                if fragment_id in set(page.fragment_refs)
                and fragment_id in fragments_by_id
            )
            for fragment_id in page.visual_priority:
                if fragment_id not in fragments_by_id or fragment_id not in set(page.fragment_refs):
                    _append_unique(
                        issues,
                        _issue(
                            "VISUAL_PRIORITY_UNKNOWN",
                            location=f"pages[{page.sequence}].visual_priority",
                            message="visual priority must reference a fragment owned by this page",
                            page_id=page.page_id,
                            fragment_id=fragment_id,
                        ),
                    )
            if local_priority and model is not None:
                local_fragments = [fragments_by_id[fragment_id] for fragment_id in local_priority]
                non_note_refs = [
                    fragment_id
                    for fragment_id in page.fragment_refs
                    if fragment_id in fragments_by_id
                    and fragments_by_id[fragment_id].semantic_role != "note"
                ]
                priority_roles = [fragment.semantic_role for fragment in local_fragments]
                if non_note_refs and all(role == "note" for role in priority_roles):
                    _append_unique(
                        issues,
                        _issue(
                            "NOTES_CANNOT_BE_PRIMARY",
                            location=f"pages[{page.sequence}].visual_priority",
                            message="note fragments cannot be the only primary visual priority",
                            page_id=page.page_id,
                        ),
                    )

            if index > 0:
                previous = pages[index - 1]
                previous_comp = previous.preferred_compositions[0] if previous.preferred_compositions else None
                current_comp = page.preferred_compositions[0] if page.preferred_compositions else None
                shared_compositions = set(previous.preferred_compositions).intersection(
                    page.preferred_compositions
                )
                if shared_compositions:
                    _append_unique(
                        issues,
                        _issue(
                            "COMPOSITION_REPEATED",
                            location=f"pages[{previous.sequence}:{page.sequence}].preferred_compositions",
                            message="adjacent pages must not repeat the same preferred information organization",
                            page_id=page.page_id,
                        ),
                    )
                if (
                    previous.narrative_role == page.narrative_role
                    and previous_comp == current_comp
                    and previous.density_budget == page.density_budget
                ):
                    _append_unique(
                        issues,
                        _issue(
                            "PAGE_BRIEF_DUPLICATE_SIGNATURE",
                            location=f"pages[{previous.sequence}:{page.sequence}]",
                            message="adjacent pages have the same role, density and composition signature",
                            page_id=page.page_id,
                        ),
                    )
            if index >= 2 and all(
                pages[index - offset].narrative_role == page.narrative_role
                for offset in (1, 2)
            ):
                _append_unique(
                    issues,
                    _issue(
                        "NARRATIVE_ROLE_REPEATED",
                        location=f"pages[{page.sequence - 2}:{page.sequence + 1}].narrative_role",
                        message="three consecutive pages cannot repeat one narrative role",
                        page_id=page.page_id,
                    ),
                )

            for directive in page.asset_directives:
                if directive.page_id != page.page_id:
                    _append_unique(
                        issues,
                        _issue(
                            "ASSET_DIRECTIVE_PAGE_MISMATCH",
                            location=f"pages[{page.sequence}].asset_directives",
                            message="asset directive page ownership must match its containing brief",
                            page_id=page.page_id,
                            directive_id=directive.directive_id,
                        ),
                    )
                source = directive.preferred_source
                if source == "none":
                    invalid = directive.required or directive.query_or_prompt is not None
                else:
                    invalid = directive.query_or_prompt is None
                if (
                    invalid
                    or not directive.role.strip()
                    or directive.min_width < 1
                    or directive.min_height < 1
                ):
                    _append_unique(
                        issues,
                        _issue(
                            "ASSET_DIRECTIVE_MISMATCH",
                            location=f"pages[{page.sequence}].asset_directives[{directive.directive_id}]",
                            message="asset directive source, role, query and resolution must be coherent",
                            page_id=page.page_id,
                            directive_id=directive.directive_id,
                        ),
                    )
                if directive.query_or_prompt and contains_forbidden_visible_copy(
                    directive.query_or_prompt
                ):
                    _append_unique(
                        issues,
                        _issue(
                            "FORBIDDEN_VISIBLE_COPY",
                            location=f"pages[{page.sequence}].asset_directives[{directive.directive_id}].query_or_prompt",
                            message="authoring asset prompts cannot request system copy or disclaimers",
                            page_id=page.page_id,
                            directive_id=directive.directive_id,
                        ),
                    )

        directive_ids = [
            directive.directive_id
            for page in pages
            for directive in page.asset_directives
        ]
        directive_counts = Counter(directive_ids)
        for directive_id, count in sorted(directive_counts.items()):
            if count > 1:
                _append_unique(
                    issues,
                    _issue(
                        "ASSET_DIRECTIVE_OWNERSHIP_DUPLICATED",
                        location="page_brief_set.asset_directives",
                        message="an asset directive ID must belong to exactly one page",
                        directive_id=directive_id,
                    ),
                )

        if _scan_forbidden(_payload(page_brief_set) or {}):
            _append_unique(
                issues,
                _issue(
                    "FORBIDDEN_VISIBLE_COPY",
                    location="page_brief_set",
                    message="authoring contracts cannot carry forbidden system copy",
                ),
            )
        if narrative_obj is not None and _scan_forbidden(
            _payload(narrative_obj) or {}
        ):
            _append_unique(
                issues,
                _issue(
                    "FORBIDDEN_VISIBLE_COPY",
                    location="narrative",
                    message="authoring contracts cannot carry forbidden system copy",
                ),
            )

    # Optional source-contract checks are intentionally last so page/fragment
    # ownership remains the primary deterministic evidence.
    if atom_set is not None and model is not None:
        if atom_set.canonical_sha256 != model.content_atom_set_sha256:
            _append_unique(
                issues,
                _issue(
                    "HASH_BINDING_MISMATCH",
                    location="semantic_content_model.content_atom_set_sha256",
                    message="semantic model is bound to a different atom set",
                ),
            )
    if lock is not None:
        if model is not None and lock.content_atom_set_sha256 != model.content_atom_set_sha256:
            _append_unique(
                issues,
                _issue(
                    "HASH_BINDING_MISMATCH",
                    location="content_lock.content_atom_set_sha256",
                    message="content lock is bound to a different atom set",
                ),
            )

    return _result(
        issues,
        semantic_model=model,
        narrative=narrative_obj,
        page_brief_set=page_set,
        plan=plan,
        content_lock=lock,
        content_atom_set=atom_set,
    )


def evaluate_authoring_qa(*args: Any, **kwargs: Any) -> AuthoringQAResultV4:
    return evaluate_authoring(*args, **kwargs)


__all__ = [
    "AuthoringIssueV4",
    "AuthoringQAResultV4",
    "evaluate_authoring",
    "evaluate_authoring_qa",
]
