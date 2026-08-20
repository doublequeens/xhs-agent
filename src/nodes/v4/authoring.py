"""Gateway-backed v4 authoring node and the Q1 route boundary."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.schemas.content_lock import ContentLock
from src.schemas.v4.content import (
    ContentAtomSetV4,
    VisibleCopyProjectionV4,
    canonical_sha256_v4,
)
from src.schemas.v4.direction import (
    AssetDirectiveV4,
    AssetDirectiveCandidateV4,
    AuthoringIssueV4,
    AuthoringQAResultV4,
    CarouselNarrativeDraftV4,
    CarouselNarrativeV4,
    PageBriefDraftV4,
    PageBriefCandidateV4,
    PageBriefSetDraftV4,
    PageBriefSetCandidateV4,
    PageBriefSetV4,
    PageBriefV4,
    VisualAuthoringDraftV4,
    VisualDirectionPlanV4,
)
from src.schemas.v4.semantic import SemanticContentModelV4, SemanticQAResultV4
from src.visual_ai.protocols import InvocationPolicy, InvocationRequest
from src.visual_design.v4.authoring_qa import evaluate_authoring
from src.nodes.v4.semantic import route_after_semantic_qa


_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "base" / "v4_visual_authoring.txt"
_CURRENT_NODE = "V4_VISUAL_AUTHORING"
_NEXT_ROUTE = "asset_resolver"
_FAIL_ROUTE = "visual_authoring"


def _required_identity(state: Mapping[str, Any], field_name: str) -> str:
    value = state.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"visual_authoring requires non-empty state.{field_name}")
    return value


def _coerce(value: Any, model_type: type[Any], field_name: str) -> Any:
    raw = value.model_dump(mode="python") if isinstance(value, model_type) else value
    if not isinstance(raw, Mapping):
        raise ValueError(f"visual_authoring requires persisted {field_name}")
    try:
        checked = model_type.model_validate(raw)
    except Exception as exc:
        raise ValueError(f"visual_authoring persisted {field_name} is invalid") from exc
    if model_type is ContentLock:
        expected = canonical_sha256_v4(
            checked.model_dump(mode="json", exclude={"canonical_sha256"})
        )
        if checked.canonical_sha256 != expected:
            raise ValueError(f"visual_authoring persisted {field_name} hash is invalid")
    return checked


def _load_prompt() -> str:
    prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    if not prompt.strip():
        raise ValueError("v4 visual authoring prompt must not be empty")
    return prompt


def _revalidate_draft(value: Any) -> VisualAuthoringDraftV4:
    try:
        raw = value.model_dump(mode="python") if isinstance(value, VisualAuthoringDraftV4) else value
        return VisualAuthoringDraftV4.model_validate(raw)
    except Exception as exc:
        raise ValueError("visual_authoring gateway draft is invalid") from exc


def _revalidate_q0(state: Mapping[str, Any]) -> tuple[
    ContentAtomSetV4,
    ContentLock,
    VisibleCopyProjectionV4 | None,
    SemanticContentModelV4,
    SemanticQAResultV4,
]:
    """Revalidate all persisted Q0 inputs and reject stale passed results."""

    atom_set = _coerce(state.get("content_atom_set"), ContentAtomSetV4, "content_atom_set")
    lock = _coerce(state.get("content_lock"), ContentLock, "content_lock")
    projection_value = state.get("visible_copy_projection")
    projection = (
        _coerce(projection_value, VisibleCopyProjectionV4, "visible_copy_projection")
        if projection_value is not None
        else None
    )
    try:
        atom_set.validate_integrity()
        if projection is not None:
            atom_set.validate_projection(projection)
    except Exception as exc:
        raise ValueError("visual_authoring persisted content projection is invalid") from exc
    if lock.content_atom_set_sha256 != atom_set.canonical_sha256:
        raise ValueError("visual_authoring content_lock is bound to a different atom set")
    if projection is None and any(
        atom.role in {"table_header", "table_cell"} for atom in atom_set.atoms
    ):
        raise ValueError("visual_authoring requires visible_copy_projection for table content")

    model_value = state.get("semantic_content_model", state.get("semantic_model"))
    model = _coerce(model_value, SemanticContentModelV4, "semantic_content_model")
    persisted_value = state.get("semantic_qa_result")
    if isinstance(persisted_value, SemanticQAResultV4):
        persisted = SemanticQAResultV4.model_validate(persisted_value.model_dump(mode="python"))
    elif isinstance(persisted_value, Mapping):
        persisted = SemanticQAResultV4.model_validate(persisted_value)
    else:
        raise ValueError("visual_authoring requires persisted semantic_qa_result")

    # Task 7's route helper recomputes Q0 from the current persisted contracts.
    # A stale passed result therefore cannot unlock the gateway.
    q0_state = dict(state)
    q0_state["semantic_content_model"] = model
    q0_state["semantic_qa_result"] = persisted
    if route_after_semantic_qa(q0_state) != "visual_authoring":
        raise ValueError("visual_authoring requires a fresh passed semantic QA result")
    return atom_set, lock, projection, model, persisted


def _request_payload(
    atom_set: ContentAtomSetV4,
    lock: ContentLock,
    model: SemanticContentModelV4,
) -> dict[str, Any]:
    # Fragment metadata is enough to choose page tasks.  Exact visible text is
    # intentionally not sent as an output field and is reconstructed locally
    # only by the earlier semantic boundary.
    fragments = tuple(
        {
            "fragment_id": fragment.fragment_id,
            "source_atom_id": fragment.source_atom_id,
            "semantic_role": fragment.semantic_role,
            "sequence_index": fragment.sequence_index,
            "parent_fragment_id": fragment.parent_fragment_id,
        }
        for fragment in model.fragments
    )
    return {
        "prompt": _load_prompt(),
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "content_lock_sha256": lock.canonical_sha256,
        "semantic_content_model_sha256": model.canonical_sha256,
        "fragments": fragments,
        "constraints": {
            "allow_visible_text_output": False,
            "allow_fragment_text_output": False,
            "allow_coordinates": False,
            "allow_pixel_boxes": False,
            "allow_html_css_dom": False,
            "fragment_reference_mode": "opaque_ids_only",
            "page_count_range": "5..18",
            "one_template_family": True,
        },
    }


def _asset_candidate_from_draft(value: Any) -> AssetDirectiveCandidateV4:
    draft = value if isinstance(value, dict) else value.model_dump(mode="python")
    return AssetDirectiveCandidateV4.model_validate(draft)


def _asset_from_candidate(value: AssetDirectiveCandidateV4) -> AssetDirectiveV4:
    payload = value.model_dump(mode="python")
    # Resolution is an asset safety contract, not provider-controlled layout.
    payload.update(min_width=1080, min_height=1440, resolution=(1080, 1440))
    return AssetDirectiveV4.model_validate(payload)


def _derive_narrative(
    draft: CarouselNarrativeDraftV4,
    *,
    atom_set: ContentAtomSetV4,
) -> CarouselNarrativeV4:
    payload = draft.model_dump(mode="python")
    payload["content_atom_set_sha256"] = atom_set.canonical_sha256
    canonical_payload = dict(payload)
    return CarouselNarrativeV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(canonical_payload),
    )


def _derive_page_candidate(value: PageBriefDraftV4) -> PageBriefCandidateV4:
    payload = value.model_dump(mode="python")
    payload["asset_directives"] = tuple(
        _asset_candidate_from_draft(item) for item in value.asset_directives
    )
    return PageBriefCandidateV4.model_validate(payload)


def _derive_page_brief(value: PageBriefCandidateV4) -> PageBriefV4:
    payload = value.model_dump(mode="python")
    payload["asset_directives"] = tuple(
        _asset_from_candidate(item) for item in value.asset_directives
    )
    return PageBriefV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def _derive_page_brief_set_candidate(
    draft: PageBriefSetDraftV4,
    *,
    narrative: CarouselNarrativeV4,
    semantic_model: SemanticContentModelV4,
    atom_set: ContentAtomSetV4,
) -> PageBriefSetCandidateV4:
    pages = tuple(_derive_page_candidate(page) for page in draft.pages)
    return PageBriefSetCandidateV4(
        page_count=narrative.page_count,
        pages=pages,
        template_family=narrative.template_family,
        content_atom_set_sha256=atom_set.canonical_sha256,
        semantic_content_model_sha256=semantic_model.canonical_sha256,
    )


def _derive_page_brief_set(
    candidate: PageBriefSetCandidateV4,
    *,
    narrative: CarouselNarrativeV4,
    semantic_model: SemanticContentModelV4,
    atom_set: ContentAtomSetV4,
) -> PageBriefSetV4:
    pages = tuple(_derive_page_brief(page) for page in candidate.pages)
    payload = {
        "page_count": narrative.page_count,
        "pages": pages,
        "template_family": narrative.template_family,
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "semantic_content_model_sha256": semantic_model.canonical_sha256,
    }
    return PageBriefSetV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(
            {key: value for key, value in payload.items() if value is not None}
        ),
    )


def _derive_plan(
    *,
    semantic_model: SemanticContentModelV4,
    atom_set: ContentAtomSetV4,
    narrative: CarouselNarrativeV4,
    page_brief_set: PageBriefSetV4,
) -> VisualDirectionPlanV4:
    payload = {
        "semantic_content_model": semantic_model,
        "narrative": narrative,
        "page_brief_set": page_brief_set,
        "template_family": narrative.template_family,
        "page_count": narrative.page_count,
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "semantic_content_model_sha256": semantic_model.canonical_sha256,
        "narrative_sha256": narrative.canonical_sha256,
        "page_brief_set_sha256": page_brief_set.canonical_sha256,
    }
    return VisualDirectionPlanV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def _failed_qa(
    *,
    atom_set: ContentAtomSetV4,
    lock: ContentLock,
    semantic_model: SemanticContentModelV4,
    narrative: CarouselNarrativeV4 | None = None,
    candidate: PageBriefSetCandidateV4 | None = None,
    location: str = "provider_draft",
) -> AuthoringQAResultV4:
    issue = AuthoringIssueV4(
        code="SCHEMA_INVALID",
        location=location,
        message="visual authoring candidate failed local contract preflight",
        evidence="sanitized local schema diagnostic",
    )
    payload = {
        "passed": False,
        "issues": (issue,),
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "content_lock_sha256": lock.canonical_sha256,
        "semantic_content_model_sha256": semantic_model.canonical_sha256,
        "narrative_sha256": getattr(narrative, "canonical_sha256", "0" * 64),
        "page_brief_set_sha256": "0" * 64,
        "visual_direction_plan_sha256": "0" * 64,
        "candidate_sha256": getattr(candidate, "candidate_sha256", "0" * 64),
    }
    return AuthoringQAResultV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def _node_result(
    *,
    atom_set: ContentAtomSetV4,
    lock: ContentLock,
    semantic_model: SemanticContentModelV4,
    q0: SemanticQAResultV4,
    narrative: CarouselNarrativeV4 | None,
    page_brief_set: PageBriefSetV4 | None,
    plan: VisualDirectionPlanV4 | None,
    qa_result: AuthoringQAResultV4,
) -> dict[str, Any]:
    route = _NEXT_ROUTE if qa_result.passed else _FAIL_ROUTE
    return {
        "content_atom_set": atom_set,
        "content_lock": lock,
        "semantic_content_model": semantic_model,
        "semantic_model": semantic_model,
        "semantic_qa_result": q0,
        "narrative": narrative,
        "carousel_narrative": narrative,
        "page_brief_set": page_brief_set,
        "page_briefs": page_brief_set,
        "visual_direction_plan": plan,
        "authoring_qa_result": qa_result,
        "authoring_route": route,
        "visual_route": route,
        "route": route,
        "current_node": _CURRENT_NODE,
    }


def visual_authoring_node(
    state: Mapping[str, Any],
    *,
    gateway: Any | None = None,
    policy: InvocationPolicy | None = None,
) -> dict[str, Any]:
    """Produce semantic narrative/page briefs through one injected gateway call."""

    if not isinstance(state, Mapping):
        raise ValueError("visual_authoring requires state")
    run_id = _required_identity(state, "run_id")
    run_mode = _required_identity(state, "run_mode")
    candidate_id = _required_identity(state, "candidate_id")
    revision_id = _required_identity(state, "revision_id")
    parent_revision_id = state.get("parent_revision_id")
    if parent_revision_id is not None and (
        not isinstance(parent_revision_id, str) or not parent_revision_id.strip()
    ):
        raise ValueError("visual_authoring state.parent_revision_id must be non-empty or None")

    atom_set, lock, _projection, semantic_model, _q0 = _revalidate_q0(state)
    gateway = gateway if gateway is not None else state.get("visual_llm_gateway")
    if gateway is None or not callable(getattr(gateway, "invoke_structured", None)):
        raise ValueError("visual_authoring requires an injected VisualLLMGateway")

    request = InvocationRequest(
        run_id=run_id,
        run_mode=run_mode,
        candidate_id=candidate_id,
        revision_id=revision_id,
        parent_revision_id=parent_revision_id,
        node="visual_authoring",
        # Before any page exists, this stable sentinel keeps request identity
        # non-empty and independent of untrusted provider output.
        page_ids=("carousel",),
        operation_kind="visual_authoring",
        payload=_request_payload(atom_set, lock, semantic_model),
    )

    # Gateway failures intentionally propagate.  This node owns no retry,
    # timeout, provider selection or fallback policy of its own.
    if policy is None:
        draft_value = gateway.invoke_structured(request, VisualAuthoringDraftV4)
    else:
        draft_value = gateway.invoke_structured(request, VisualAuthoringDraftV4, policy)
    try:
        draft = _revalidate_draft(draft_value)
        narrative = _derive_narrative(draft.narrative, atom_set=atom_set)
        candidate = _derive_page_brief_set_candidate(
            draft.page_brief_set,
            narrative=narrative,
            semantic_model=semantic_model,
            atom_set=atom_set,
        )
    except Exception:
        # A successfully invoked provider can still return a malformed
        # semantic candidate.  Return a sanitized hard-gate result instead of
        # allowing a durable-construction ValidationError to escape.
        qa_result = _failed_qa(
            atom_set=atom_set,
            lock=lock,
            semantic_model=semantic_model,
        )
        return _node_result(
            atom_set=atom_set,
            lock=lock,
            semantic_model=semantic_model,
            q0=_q0,
            narrative=None,
            page_brief_set=None,
            plan=None,
            qa_result=qa_result,
        )

    # Q1 evaluates the relaxed candidate first.  Only a passing candidate is
    # converted into the strict durable page-brief and plan contracts.
    candidate_qa = evaluate_authoring(
        candidate,
        semantic_model,
        narrative,
        content_lock=lock,
        content_atom_set=atom_set,
    )
    if not candidate_qa.passed:
        return _node_result(
            atom_set=atom_set,
            lock=lock,
            semantic_model=semantic_model,
            q0=_q0,
            narrative=narrative,
            page_brief_set=None,
            plan=None,
            qa_result=candidate_qa,
        )

    try:
        page_brief_set = _derive_page_brief_set(
            candidate,
            narrative=narrative,
            semantic_model=semantic_model,
            atom_set=atom_set,
        )
        plan = _derive_plan(
            semantic_model=semantic_model,
            atom_set=atom_set,
            narrative=narrative,
            page_brief_set=page_brief_set,
        )
    except Exception:
        qa_result = _failed_qa(
            atom_set=atom_set,
            lock=lock,
            semantic_model=semantic_model,
            narrative=narrative,
            candidate=candidate,
            location="durable_contract",
        )
        return _node_result(
            atom_set=atom_set,
            lock=lock,
            semantic_model=semantic_model,
            q0=_q0,
            narrative=narrative,
            page_brief_set=None,
            plan=None,
            qa_result=qa_result,
        )

    qa_result = evaluate_authoring(
        page_brief_set,
        semantic_model,
        narrative,
        plan,
        content_lock=lock,
        content_atom_set=atom_set,
    )
    return _node_result(
        atom_set=atom_set,
        lock=lock,
        semantic_model=semantic_model,
        q0=_q0,
        narrative=narrative,
        page_brief_set=page_brief_set,
        plan=plan,
        qa_result=qa_result,
    )


def route_after_authoring_qa(state: Mapping[str, Any]) -> str:
    """Recompute Q0/Q1 and route only a fresh, hash-equal passed result."""

    try:
        if not isinstance(state, Mapping):
            return _FAIL_ROUTE
        atom_set, lock, _projection, model, _q0 = _revalidate_q0(state)
        narrative_value = state.get("narrative", state.get("carousel_narrative"))
        narrative = _coerce(narrative_value, CarouselNarrativeV4, "narrative")
        page_set = _coerce(
            state.get("page_brief_set", state.get("page_briefs")),
            PageBriefSetV4,
            "page_brief_set",
        )
        plan = _coerce(
            state.get("visual_direction_plan"), VisualDirectionPlanV4, "visual_direction_plan"
        )
        fresh = evaluate_authoring(
            page_set,
            model,
            narrative,
            plan,
            content_lock=lock,
            content_atom_set=atom_set,
        )
        persisted_value = state.get("authoring_qa_result")
        persisted = (
            AuthoringQAResultV4.model_validate(persisted_value.model_dump(mode="python"))
            if isinstance(persisted_value, AuthoringQAResultV4)
            else AuthoringQAResultV4.model_validate(persisted_value)
        )
        if not fresh.passed or persisted != fresh:
            return _FAIL_ROUTE
        return _NEXT_ROUTE
    except Exception:
        return _FAIL_ROUTE


# Explicit aliases keep the v4 node discoverable to graph wiring and tests.
authoring_node = visual_authoring_node
v4_visual_authoring_node = visual_authoring_node
route_after_visual_authoring_qa = route_after_authoring_qa


__all__ = [
    "authoring_node",
    "route_after_authoring_qa",
    "route_after_visual_authoring_qa",
    "v4_visual_authoring_node",
    "visual_authoring_node",
]
