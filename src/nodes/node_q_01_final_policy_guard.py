"""Final Policy Guard for the ``llm_scene_v3`` path (Task 15).

Hard-gates on every QA / hash / asset-security / R2 / ContentLock attestation
after the unified Human Review. It may accept an *aesthetic* override (a
human-overridden ``visual_needs_attention`` critique) but NEVER a hard-QA
override: a failed design-plan QA, render QA, content-hash binding, asset
security, R2 or ContentLock attestation cannot be force-approved.

The guard is side-effect-free and returns the complete issue list; routing is
``route_after_final_guard`` (``human_review`` if any issue, else
``content_writer``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from src.domain import find_policy_violations
from src.schemas import AgentState
from src.schemas.content_atoms import canonical_sha256
from src.schemas.content_lock import ContentLock
from src.utils import _value


_URL_PATTERN = re.compile(r"https?://[^\s，。！？、；：)\]}>\"']+")

# Textual publish-package fields locked into ContentLock (the visible source
# copy). ``first_screen_promise`` is sourced from the content contract.
_LOCK_TEXT_FIELDS = (
    "focus_keyword",
    "topic",
    "topic_id",
    "angle",
    "angle_id",
    "target_group",
    "core_pain",
    "title",
    "cover_copy",
    "content",
)


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return " ".join(str(item) for item in value if item is not None)
    return str(value)


def _artifact_issue(rule_id: str, message: str, location: str) -> dict:
    return {
        "rule_id": rule_id,
        "matched_text": location,
        "message": message,
        "location": location,
    }


def _required_field_issues(publish_package: Mapping[str, Any]) -> list[dict]:
    issues: list[dict] = []
    for field_name in _LOCK_TEXT_FIELDS:
        value = publish_package.get(field_name)
        if not (isinstance(value, str) and value.strip()):
            issues.append(
                _artifact_issue(
                    "missing_required_field",
                    f"Missing or invalid required publish_package field: {field_name}",
                    f"publish_package.{field_name}",
                )
            )
    hashtags = publish_package.get("hashtags")
    hashtags_valid = (
        isinstance(hashtags, (list, tuple))
        and bool(hashtags)
        and all(isinstance(item, str) and item.strip() for item in hashtags)
    )
    if not hashtags_valid:
        issues.append(
            _artifact_issue(
                "missing_required_field",
                "Missing or invalid required publish_package field: hashtags",
                "publish_package.hashtags",
            )
        )
    return issues


def _content_lock_payload(
    publish_package: Mapping[str, Any], atom_sha: str | None
) -> dict[str, Any]:
    contract = publish_package.get("content_contract")
    first_screen_promise = (
        _value(contract, "first_screen_promise")
        or publish_package.get("first_screen_promise")
        or ""
    )
    return {
        "focus_keyword": publish_package.get("focus_keyword"),
        "topic": publish_package.get("topic"),
        "topic_id": publish_package.get("topic_id"),
        "angle": publish_package.get("angle"),
        "angle_id": publish_package.get("angle_id"),
        "target_group": publish_package.get("target_group"),
        "core_pain": publish_package.get("core_pain"),
        "title": publish_package.get("title"),
        "cover_copy": publish_package.get("cover_copy"),
        "first_screen_promise": first_screen_promise,
        "content": publish_package.get("content"),
        "hashtags": list(publish_package.get("hashtags") or []),
        "content_atom_set_sha256": atom_sha,
    }


def _content_lock_issues(
    publish_package: Mapping[str, Any], atom_sha: str | None
) -> list[dict]:
    """Validate a ContentLock can be built from the package + atom-set hash.

    This is the structural content-lock attestation: the locked visible source
    copy plus the atom-set hash that binds the dynamic visual chain. If any
    required field is missing/blank or the constructed lock fails Pydantic
    validation (incl. the atom-set hash shape), the guard rejects.
    """
    payload = _content_lock_payload(publish_package, atom_sha)
    missing = [
        field_name
        for field_name in (*_LOCK_TEXT_FIELDS, "first_screen_promise")
        if not (isinstance(payload[field_name], str) and payload[field_name].strip())
    ]
    if not payload["hashtags"]:
        missing.append("hashtags")
    if not atom_sha:
        missing.append("content_atom_set_sha256")
    if missing:
        return [
            _artifact_issue(
                "content_lock_invalid",
                "ContentLock cannot be built: missing " + ", ".join(missing),
                "content_lock",
            )
        ]
    canonical = canonical_sha256(payload)
    try:
        ContentLock.model_validate({**payload, "canonical_sha256": canonical})
    except (TypeError, ValueError):
        return [
            _artifact_issue(
                "content_lock_invalid",
                "ContentLock failed validation against the locked content + atom-set hash.",
                "content_lock",
            )
        ]
    return []


def _required_directive_ids(direction_plan: Any) -> set[str]:
    if direction_plan is None:
        return set()
    directives = _value(direction_plan, "asset_directives", ()) or ()
    required: set[str] = set()
    for directive in directives:
        if _value(directive, "required") is True:
            directive_id = _value(directive, "directive_id")
            if directive_id:
                required.add(str(directive_id))
    return required


def _attestation_issues(state: Mapping[str, Any]) -> list[dict]:
    issues: list[dict] = []

    # Human approval gate.
    if state.get("review_status") != "approved":
        issues.append(
            _artifact_issue(
                "human_review_not_approved",
                "Final Policy Guard requires explicit human approval.",
                "review_status",
            )
        )

    # Content atom set + structural content-lock binding across the visual chain.
    atom_set = state.get("content_atom_set")
    atom_sha = _value(atom_set, "canonical_sha256")
    if atom_set is None or not atom_sha:
        issues.append(
            _artifact_issue(
                "content_atom_set_missing",
                "Final Policy Guard requires a persisted content atom set.",
                "content_atom_set",
            )
        )
        atom_sha = atom_sha or None
    if atom_sha:
        for state_key in (
            "visual_direction_plan",
            "carousel_design_plan",
            "render_manifest",
            "visual_critique",
        ):
            artifact = state.get(state_key)
            if artifact is None:
                continue
            if _value(artifact, "content_atom_set_sha256") != atom_sha:
                issues.append(
                    _artifact_issue(
                        "content_lock_binding_mismatch",
                        "content_atom_set_sha256 must bind consistently across the visual chain.",
                        state_key,
                    )
                )
                break

    # Hard QA: design-plan QA (never overridable).
    design_qa = state.get("design_plan_qa_result")
    if design_qa is None:
        issues.append(
            _artifact_issue(
                "design_plan_qa_missing",
                "Final Policy Guard requires a persisted design-plan QA result.",
                "design_plan_qa_result",
            )
        )
    elif _value(design_qa, "passed") is not True:
        issues.append(
            _artifact_issue(
                "design_plan_qa_not_passed",
                "Design-plan QA must pass; a hard-QA failure cannot be overridden.",
                "design_plan_qa_result.passed",
            )
        )

    # Hard QA: render QA (never overridable).
    render_qa = state.get("render_qa_result")
    if render_qa is None:
        issues.append(
            _artifact_issue(
                "render_qa_missing",
                "Final Policy Guard requires a persisted render-QA result.",
                "render_qa_result",
            )
        )
    elif _value(render_qa, "passed") is not True:
        issues.append(
            _artifact_issue(
                "render_qa_not_passed",
                "Render QA must pass; a hard-QA failure cannot be overridden.",
                "render_qa_result.passed",
            )
        )

    # Asset security: no rejected asset, every required directive covered.
    asset_manifest = state.get("asset_manifest")
    items = (
        list(_value(asset_manifest, "items", ()) or ())
        if asset_manifest is not None
        else []
    )
    for item in items:
        if _value(item, "security_status") == "rejected":
            issues.append(
                _artifact_issue(
                    "asset_security_rejected",
                    "A security-rejected asset cannot pass Final Policy Guard.",
                    "asset_manifest.items",
                )
            )
            break
    covered = {
        str(_value(item, "directive_id"))
        for item in items
        if _value(item, "directive_id")
        and _value(item, "security_status") != "rejected"
    }
    missing_required = sorted(_required_directive_ids(state.get("visual_direction_plan")) - covered)
    if missing_required:
        issues.append(
            _artifact_issue(
                "required_asset_unresolved",
                "Every required asset directive must be resolved by an approved asset: "
                + ", ".join(missing_required),
                "asset_manifest.items",
            )
        )

    # R2 compliance attestation.
    r2_output = state.get("r2_output")
    if r2_output is None:
        issues.append(
            _artifact_issue(
                "r2_compliance_missing",
                "Final Policy Guard requires an R2 compliance result.",
                "r2_output",
            )
        )
    else:
        audit = _value(r2_output, "compliance_audit")
        if _value(audit, "block_publish") is True:
            issues.append(
                _artifact_issue(
                    "r2_compliance_blocked",
                    "R2 compliance must not block publish.",
                    "r2_output.compliance_audit.block_publish",
                )
            )

    # ContentLock attestation (build + validate).
    publish_package = state.get("publish_package") or {}
    issues.extend(_content_lock_issues(publish_package, atom_sha))

    # Aesthetic override rule: a failed critique needs an explicit override.
    # This is the ONLY gate an aesthetic override can satisfy.
    critique = state.get("visual_critique")
    if critique is not None and _value(critique, "passed") is not True:
        if state.get("visual_aesthetic_override") is not True:
            issues.append(
                _artifact_issue(
                    "visual_critique_not_overridden",
                    "A failed visual critique requires an explicit human aesthetic override.",
                    "visual_critique.passed",
                )
            )

    return issues


def _policy_issues(publish_package: Mapping[str, Any]) -> list[dict]:
    combined_text = _URL_PATTERN.sub(
        "",
        "\n".join(
            [
                _coerce_text(publish_package.get("title")),
                _coerce_text(publish_package.get("content")),
                _coerce_text(publish_package.get("cover_copy")),
                _coerce_text(publish_package.get("hashtags")),
            ]
        ),
    )
    return [
        issue.model_copy(update={"location": "publish_package"}).model_dump(mode="json")
        for issue in find_policy_violations(combined_text)
    ]


def validate_final_policy(state: AgentState) -> list[dict]:
    """Return the complete, side-effect-free Final Guard issue list for ``state``."""
    publish_package = state.get("publish_package")
    if publish_package is None:
        raise ValueError("validate_final_policy requires `publish_package` in state.")

    issues = _required_field_issues(publish_package)
    issues.extend(_attestation_issues(state))
    issues.extend(_policy_issues(publish_package))
    return issues


def final_policy_guard_node(state: AgentState) -> AgentState:
    issues = validate_final_policy(state)
    return {
        "final_policy_issues": issues,
        "current_node": "FINAL_POLICY_GUARD",
    }


def route_after_final_guard(state: AgentState) -> str:
    issues = state.get("final_policy_issues") or []
    return "human_review" if issues else "content_writer"
