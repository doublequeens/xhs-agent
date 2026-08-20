"""Gateway-backed semantic modeling node and Q0 route boundary."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.schemas.content_lock import ContentLock
from src.schemas.v4.content import ContentAtomSetV4, VisibleCopyProjectionV4, canonical_sha256_v4
from src.schemas.v4.semantic import (
    SemanticContentModelV4,
    SemanticFragmentV4,
    SemanticGroupV4,
    SemanticModelingDraftV4,
    SemanticQAResultV4,
)
from src.visual_ai.protocols import InvocationPolicy, InvocationRequest
from src.visual_design.v4.semantic_qa import evaluate_semantic_model


_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "base" / "v4_semantic_modeling.txt"
_CURRENT_NODE = "V4_SEMANTIC_MODELING"
_NEXT_ROUTE = "visual_authoring"
_FAIL_ROUTE = "semantic_modeling"


def _required_identity(state: Mapping[str, Any], field_name: str) -> str:
    value = state.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"semantic_modeling requires non-empty state.{field_name}")
    return value


def _coerce(value: Any, model_type: type[Any], field_name: str) -> Any:
    if isinstance(value, model_type):
        try:
            # ``model_copy(update=...)`` bypasses Pydantic validators.  Always
            # cross the persisted-contract boundary through a fresh payload.
            value = value.model_dump(mode="python")
        except Exception as exc:
            raise ValueError(f"semantic_modeling persisted {field_name} is invalid") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"semantic_modeling requires persisted {field_name}")
    try:
        checked = model_type.model_validate(value)
        if model_type is ContentLock:
            expected = canonical_sha256_v4(
                checked.model_dump(mode="json", exclude={"canonical_sha256"})
            )
            if checked.canonical_sha256 != expected:
                raise ValueError("content lock canonical hash does not match payload")
        return checked
    except Exception as exc:
        raise ValueError(f"semantic_modeling persisted {field_name} is invalid") from exc


def _revalidate_draft(value: Any) -> SemanticModelingDraftV4:
    try:
        payload = value.model_dump(mode="python") if isinstance(value, SemanticModelingDraftV4) else value
        return SemanticModelingDraftV4.model_validate(payload)
    except Exception as exc:
        raise ValueError("semantic_modeling gateway draft is invalid") from exc


def _load_prompt() -> str:
    prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    if not prompt.strip():
        raise ValueError("v4 semantic modeling prompt must not be empty")
    return prompt


def _request_payload(
    atom_set: ContentAtomSetV4,
    lock: ContentLock,
    projection: VisibleCopyProjectionV4 | None,
) -> dict[str, Any]:
    # Only persisted content and safe hashes cross the gateway boundary.  No
    # provider credentials, absolute paths, or prior provider responses are
    # included in this payload.
    atoms = tuple(
        {
            "atom_id": atom.atom_id,
            "text": atom.text,
            "role": atom.role,
            "source_unit_id": atom.source_unit_id,
        }
        for atom in atom_set.atoms
    )
    table_groups = ()
    if projection is not None:
        table_groups = tuple(
            {
                "group_id": group.group_id,
                "rows": group.rows,
                "unit_ids": group.unit_ids,
            }
            for group in projection.table_groups
        )
    return {
        "prompt": _load_prompt(),
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "content_lock_sha256": lock.canonical_sha256,
        "atoms": atoms,
        "table_groups": table_groups,
        "constraints": {
            "exact_text_source": "persisted_atom_slice_only",
            "slice_indexing": "unicode_codepoint_zero_based_half_open",
            "must_cover_every_atom": True,
            "allow_visible_text_output": False,
            "allow_pagination": False,
            "allow_visual_decisions": False,
        },
    }


def _local_slice(atom_set: ContentAtomSetV4, source_atom_id: str, start: int, end: int) -> str:
    atom = next((item for item in atom_set.atoms if item.atom_id == source_atom_id), None)
    if atom is None:
        return ""
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(atom.text):
        return ""
    return atom.text[start:end]


def _build_model(
    atom_set: ContentAtomSetV4,
    draft: SemanticModelingDraftV4,
) -> SemanticContentModelV4:
    fragments = tuple(
        SemanticFragmentV4(
            fragment_id=fragment.fragment_id,
            source_atom_id=fragment.source_atom_id,
            start=fragment.start,
            end=fragment.end,
            exact_text=_local_slice(
                atom_set,
                fragment.source_atom_id,
                fragment.start,
                fragment.end,
            ),
            semantic_role=fragment.semantic_role,
            parent_fragment_id=fragment.parent_fragment_id,
            sequence_index=fragment.sequence_index,
        )
        for fragment in draft.fragments
    )
    groups = tuple(
        SemanticGroupV4(
            group_id=group.group_id,
            group_kind=group.group_kind,
            fragment_ids=group.fragment_ids,
            ordering=group.ordering,
        )
        for group in draft.groups
    )
    payload = {
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "fragments": fragments,
        "groups": groups,
    }
    return SemanticContentModelV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def semantic_modeling_node(
    state: Mapping[str, Any],
    *,
    gateway: Any | None = None,
    policy: InvocationPolicy | None = None,
) -> dict[str, Any]:
    """Derive semantic references through the injected Task 5 gateway.

    The node performs no retry, timeout, fallback, or provider invocation of
    its own.  Any exception from the gateway propagates to the caller.
    """

    if not isinstance(state, Mapping):
        raise ValueError("semantic_modeling requires state")
    run_id = _required_identity(state, "run_id")
    run_mode = _required_identity(state, "run_mode")
    candidate_id = _required_identity(state, "candidate_id")
    revision_id = _required_identity(state, "revision_id")
    parent_revision_id = state.get("parent_revision_id")
    if parent_revision_id is not None and (
        not isinstance(parent_revision_id, str) or not parent_revision_id.strip()
    ):
        raise ValueError("semantic_modeling state.parent_revision_id must be a non-empty string or None")

    atom_set = _coerce(state.get("content_atom_set"), ContentAtomSetV4, "content_atom_set")
    lock = _coerce(state.get("content_lock"), ContentLock, "content_lock")
    projection_value = state.get("visible_copy_projection")
    projection = (
        _coerce(projection_value, VisibleCopyProjectionV4, "visible_copy_projection")
        if projection_value is not None
        else None
    )
    if projection is None and any(
        atom.role in {"table_header", "table_cell"} for atom in atom_set.atoms
    ):
        raise ValueError(
            "semantic_modeling requires persisted visible_copy_projection for table content"
        )
    if lock.content_atom_set_sha256 != atom_set.canonical_sha256:
        raise ValueError("semantic_modeling content_lock is bound to a different content_atom_set")
    if projection is not None:
        try:
            atom_set.validate_projection(projection)
        except Exception as exc:
            raise ValueError("semantic_modeling persisted content projection is invalid") from exc

    gateway = gateway if gateway is not None else state.get("visual_llm_gateway")
    if gateway is None or not callable(getattr(gateway, "invoke_structured", None)):
        raise ValueError("semantic_modeling requires an injected VisualLLMGateway")

    request = InvocationRequest(
        run_id=run_id,
        run_mode=run_mode,
        candidate_id=candidate_id,
        revision_id=revision_id,
        parent_revision_id=parent_revision_id,
        node="semantic_modeling",
        page_ids=("content",),
        operation_kind="semantic_modeling",
        payload=_request_payload(atom_set, lock, projection),
    )

    # Do not catch this call: gateway failures are terminal for this node and
    # must not be hidden by a synthetic passed result or local retry.
    if policy is None:
        draft = gateway.invoke_structured(request, SemanticModelingDraftV4)
    else:
        draft = gateway.invoke_structured(request, SemanticModelingDraftV4, policy)
    draft = _revalidate_draft(draft)

    model = _build_model(atom_set, draft)
    qa_result = evaluate_semantic_model(
        atom_set,
        model,
        content_lock=lock,
        projection=projection,
    )
    route = _NEXT_ROUTE if qa_result.passed else _FAIL_ROUTE
    return {
        "content_atom_set": atom_set,
        "content_lock": lock,
        "visible_copy_projection": projection,
        "semantic_content_model": model,
        "semantic_model": model,
        "semantic_qa_result": qa_result,
        "semantic_route": route,
        "current_node": _CURRENT_NODE,
    }


def route_after_semantic_qa(state: Mapping[str, Any]) -> str:
    """Route only a fresh, current-contract Q0 result into authoring.

    A self-consistent result from an older atom/model revision is not enough:
    route validation recomputes Q0 over the contracts in the current state and
    compares the persisted result byte-for-byte at the model level.
    """

    try:
        if not isinstance(state, Mapping):
            return _FAIL_ROUTE
        atom_set = _coerce(state.get("content_atom_set"), ContentAtomSetV4, "content_atom_set")
        lock = _coerce(state.get("content_lock"), ContentLock, "content_lock")
        model_value = state.get("semantic_content_model", state.get("semantic_model"))
        model = _coerce(model_value, SemanticContentModelV4, "semantic_content_model")
        projection_value = state.get("visible_copy_projection")
        projection = (
            _coerce(projection_value, VisibleCopyProjectionV4, "visible_copy_projection")
            if projection_value is not None
            else None
        )
        if projection is None and any(
            atom.role in {"table_header", "table_cell"} for atom in atom_set.atoms
        ):
            return _FAIL_ROUTE
        if lock.content_atom_set_sha256 != atom_set.canonical_sha256:
            return _FAIL_ROUTE
        if projection is not None:
            atom_set.validate_projection(projection)

        persisted_value = state.get("semantic_qa_result")
        if isinstance(persisted_value, SemanticQAResultV4):
            persisted_payload = persisted_value.model_dump(mode="python")
        elif isinstance(persisted_value, Mapping):
            persisted_payload = persisted_value
        else:
            return _FAIL_ROUTE
        persisted = SemanticQAResultV4.model_validate(persisted_payload)
        fresh = evaluate_semantic_model(
            atom_set,
            model,
            content_lock=lock,
            projection=projection,
        )
        if not fresh.passed or persisted != fresh:
            return _FAIL_ROUTE
        return _NEXT_ROUTE
    except Exception:
        return _FAIL_ROUTE


__all__ = ["route_after_semantic_qa", "semantic_modeling_node"]
