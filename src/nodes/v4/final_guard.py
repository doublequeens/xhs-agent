"""Isolated v4 Final Guard: recompute the reviewed terminal state.

The guard re-opens the append-only decision record, the externally authorized
review workspace and every current source contract/page/contact/asset byte
through the Task 16B public verifier, then emits a strict
``FinalPolicyAttestationV4`` embedding the complete reviewed decision.  Hard
QA can never be overridden here: an aesthetic override is honored only when it
is the exact reviewed terminal action, and every other action fails closed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.nodes.v4.human_review import _coerce_inputs, _coerce_workspace
from src.review.v4_decisions import (
    HumanReviewDecisionError,
    verify_human_review_decision,
)
from src.review.v4_workspace import ReviewWorkspaceInputsV4, ReviewWorkspaceV4
from src.schemas.v4.publishing import FinalPolicyAttestationV4
from src.schemas.v4.review import (
    HumanReviewDecisionReferenceV4,
    HumanReviewDecisionV4,
)


class V4FinalGuardError(RuntimeError):
    """The terminal v4 state failed the recomputed Final Guard."""


@dataclass(frozen=True)
class V4FinalGuardResult:
    """Everything publication needs from one recomputed terminal state."""

    attestation: FinalPolicyAttestationV4
    decision: HumanReviewDecisionV4
    reference: HumanReviewDecisionReferenceV4
    workspace: ReviewWorkspaceV4
    inputs: ReviewWorkspaceInputsV4


def _exact(value: Any, model: type, label: str):
    if type(value) is not model:
        raise V4FinalGuardError(f"v4 Final Guard requires an exact {label}")
    return value


def verify_v4_final_policy(state: Mapping[str, Any]) -> V4FinalGuardResult:
    """Recompute the full reviewed terminal state before any publication."""

    if not isinstance(state, Mapping):
        raise V4FinalGuardError("v4 Final Guard requires a state mapping")
    inputs = _coerce_inputs(state)
    workspace = _coerce_workspace(state, inputs)
    decision = _exact(
        state.get("human_review_decision_v4"),
        HumanReviewDecisionV4,
        "terminal HumanReviewDecisionV4",
    )
    reference = _exact(
        state.get("human_review_decision_reference_v4"),
        HumanReviewDecisionReferenceV4,
        "terminal HumanReviewDecisionReferenceV4",
    )
    current_package = state.get("publish_package")
    try:
        # The strongest public seam: reopens the append-only record, the
        # anchored workspace, fresh Q0-Q3 recomputation and every bound byte.
        checked = verify_human_review_decision(
            decision,
            reference,
            workspace,
            inputs,
            current_package=current_package,
        )
    except HumanReviewDecisionError as error:
        raise V4FinalGuardError(
            "v4 Final Guard failed the recomputed review boundary"
        ) from error
    if checked.action not in {"APPROVE", "AESTHETIC_OVERRIDE"}:
        raise V4FinalGuardError(
            "v4 Final Guard requires a terminal approval action; "
            f"got {checked.action}"
        )
    attestation = FinalPolicyAttestationV4.create(
        passed=True,
        run_id=checked.run_id,
        candidate_id=checked.candidate_id,
        revision_id=checked.revision_id,
        decision_id=checked.decision_id,
        action=checked.action,
        aesthetic_override=checked.action == "AESTHETIC_OVERRIDE",
        review_status="approved",
        decision_canonical_sha256=checked.canonical_sha256,
        decision_raw_sha256=reference.decision_raw_sha256,
        decision_reference_canonical_sha256=reference.canonical_sha256,
        workspace_reference_canonical_sha256=workspace.reference.canonical_sha256,
        human_review_decision=checked.model_dump(mode="json"),
    )
    return V4FinalGuardResult(
        attestation=attestation,
        decision=checked,
        reference=reference,
        workspace=workspace,
        inputs=inputs,
    )


def final_policy_guard_v4_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the recomputed Final Guard to one approved terminal state."""

    result = verify_v4_final_policy(state)
    return {
        "current_node": "V4_FINAL_GUARD",
        "review_status": "approved",
        "final_policy_issues": [],
        "final_policy_attestation": dict(
            result.attestation.model_dump(mode="json")
        ),
        "final_policy_attestation_v4": result.attestation,
        "final_policy_guard_passed_v4": True,
    }


v4_final_policy_guard_node = final_policy_guard_v4_node


__all__ = [
    "V4FinalGuardError",
    "V4FinalGuardResult",
    "final_policy_guard_v4_node",
    "verify_v4_final_policy",
    "v4_final_policy_guard_node",
]
