"""Blind, two-pass evaluator adapter for the isolated v4 Q4 contract."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Mapping

from src.schemas.v4.critique import (
    AestheticPageEvaluationV4,
    AestheticPagePassV4,
    AestheticSetPassV4,
    AestheticIssueV4,
    CarouselAestheticEvaluationV4,
    SetAestheticEvaluationV4,
)
from src.visual_ai.protocols import InvocationPolicy, InvocationRequest

_PROMPT = (Path(__file__).resolve().parents[1] / "prompts/base/v4_aesthetic_critic.txt").read_text(encoding="utf-8").strip()
_PASS = Literal["page", "set"]


def build_aesthetic_request(
    *,
    run_id: str,
    run_mode: Literal["production", "shadow"],
    candidate_id: str,
    revision_id: str,
    page_ids: tuple[str, ...],
    page_roles: tuple[str, ...],
    page_duties: tuple[str, ...],
    image_bytes: tuple[bytes, ...],
    image_mime_types: tuple[str, ...],
    pass_kind: _PASS,
    pass_one_observations: tuple[AestheticPageEvaluationV4, ...] = (),
    parent_revision_id: str | None = None,
    source_bindings: Mapping[str, str] | None = None,
) -> InvocationRequest:
    """Make a payload deliberately blind to authoring/revision/private state."""
    if len(page_ids) != len(page_roles) or len(page_ids) != len(page_duties):
        raise ValueError("aesthetic request pages, roles and duties must align")
    if len(page_ids) != len(image_bytes) or len(page_ids) != len(image_mime_types):
        raise ValueError("aesthetic request images must align with manifest pages")
    if pass_kind not in ("page", "set"):
        raise ValueError("aesthetic request pass kind is invalid")
    if pass_kind == "page" and pass_one_observations:
        raise ValueError("page pass cannot receive prior observations")
    if pass_kind == "set" and tuple(item.page_id for item in pass_one_observations) != page_ids:
        raise ValueError("set pass must consume complete ordered page observations")
    payload: dict[str, Any] = {
        "evaluator_prompt": _PROMPT,
        "pass_kind": pass_kind,
        "pages": tuple(
            {"page_id": page_id, "role": role, "duty": duty}
            for page_id, role, duty in zip(page_ids, page_roles, page_duties, strict=True)
        ),
        "image_mime_types": image_mime_types,
    }
    # Hashes identify the immutable review subject without supplying prompts,
    # provenance, local paths, or any visible-copy payload to the evaluator.
    if source_bindings is not None:
        required = {
            "render_manifest_sha256", "render_qa_result_sha256",
            "page_brief_set_sha256", "semantic_content_model_sha256",
        }
        if set(source_bindings) != required or any(type(value) is not str or len(value) != 64 for value in source_bindings.values()):
            raise ValueError("aesthetic request source bindings must be exact sha256 values")
        payload["source_bindings"] = dict(source_bindings)
    if pass_kind == "set":
        payload["page_observations"] = tuple(
            item.model_dump(mode="json") for item in pass_one_observations
        )
    return InvocationRequest(
        run_id=run_id,
        run_mode=run_mode,
        candidate_id=candidate_id,
        revision_id=revision_id,
        parent_revision_id=parent_revision_id,
        node="v4_aesthetic_critic",
        page_ids=page_ids,
        operation_kind=f"aesthetic_{pass_kind}_evaluation",
        payload=payload,
        image_inputs=image_bytes,
    )


def evaluate_aesthetics(
    *,
    gateway: Any,
    run_id: str,
    run_mode: Literal["production", "shadow"],
    candidate_id: str,
    revision_id: str,
    page_ids: tuple[str, ...],
    page_roles: tuple[str, ...],
    page_duties: tuple[str, ...],
    image_bytes: tuple[bytes, ...],
    image_mime_types: tuple[str, ...],
    render_manifest_sha256: str,
    render_qa_result_sha256: str,
    page_brief_set_sha256: str,
    semantic_content_model_sha256: str,
    authoring_model_identity: str | None,
    evaluator_model_identity: str | None,
    parent_revision_id: str | None = None,
    policy: InvocationPolicy | None = None,
) -> CarouselAestheticEvaluationV4:
    """Call the shared gateway twice; aggregation is wholly local."""
    if gateway is None or not callable(getattr(gateway, "evaluate_images", None)):
        raise ValueError("aesthetic evaluator requires an injected VisualLLMGateway")
    page_request = build_aesthetic_request(
        run_id=run_id, run_mode=run_mode, candidate_id=candidate_id, revision_id=revision_id,
        parent_revision_id=parent_revision_id, page_ids=page_ids, page_roles=page_roles,
        page_duties=page_duties, image_bytes=image_bytes, image_mime_types=image_mime_types,
        pass_kind="page", source_bindings={
            "render_manifest_sha256": render_manifest_sha256,
            "render_qa_result_sha256": render_qa_result_sha256,
            "page_brief_set_sha256": page_brief_set_sha256,
            "semantic_content_model_sha256": semantic_content_model_sha256,
        },
    )
    pages_result = gateway.evaluate_images(page_request, AestheticPagePassV4) if policy is None else gateway.evaluate_images(page_request, AestheticPagePassV4, policy)
    if type(pages_result) is not AestheticPagePassV4:
        raise ValueError("aesthetic evaluator returned an invalid page pass")
    pages = tuple(
        AestheticPageEvaluationV4.create(
            page_id=page.page_id,
            hierarchy=page.hierarchy, readability=page.readability, composition=page.composition,
            whitespace=page.whitespace, visual_focus=page.visual_focus,
            asset_integration=page.asset_integration,
            issues=tuple(AestheticIssueV4.create(
                severity=issue.severity, dimension=issue.dimension, page_ids=issue.page_ids,
                evidence=issue.evidence,
            ) for issue in page.issues),
        )
        for page in pages_result.pages
    )
    if tuple(page.page_id for page in pages) != page_ids:
        raise ValueError("aesthetic page pass must cover manifest pages exactly once in order")
    set_request = build_aesthetic_request(
        run_id=run_id, run_mode=run_mode, candidate_id=candidate_id, revision_id=revision_id,
        parent_revision_id=parent_revision_id, page_ids=page_ids, page_roles=page_roles,
        page_duties=page_duties, image_bytes=image_bytes, image_mime_types=image_mime_types,
        pass_kind="set", pass_one_observations=pages, source_bindings={
            "render_manifest_sha256": render_manifest_sha256,
            "render_qa_result_sha256": render_qa_result_sha256,
            "page_brief_set_sha256": page_brief_set_sha256,
            "semantic_content_model_sha256": semantic_content_model_sha256,
        },
    )
    set_result = gateway.evaluate_images(set_request, AestheticSetPassV4) if policy is None else gateway.evaluate_images(set_request, AestheticSetPassV4, policy)
    if type(set_result) is not AestheticSetPassV4:
        raise ValueError("aesthetic evaluator returned an invalid set pass")
    set_draft = set_result.set_evaluation
    set_evaluation = SetAestheticEvaluationV4.create(
        rhythm=set_draft.rhythm, repetition=set_draft.repetition,
        family_consistency=set_draft.family_consistency,
        cover_body_consistency=set_draft.cover_body_consistency,
        issues=tuple(AestheticIssueV4.create(
            severity=issue.severity, dimension=issue.dimension, page_ids=issue.page_ids,
            evidence=issue.evidence,
        ) for issue in set_draft.issues),
    )
    return CarouselAestheticEvaluationV4.create(
        render_manifest_sha256=render_manifest_sha256,
        render_qa_result_sha256=render_qa_result_sha256,
        page_brief_set_sha256=page_brief_set_sha256,
        semantic_content_model_sha256=semantic_content_model_sha256,
        authoring_model_identity=authoring_model_identity,
        evaluator_model_identity=evaluator_model_identity,
        pages=pages,
        set_evaluation=set_evaluation,
    )


__all__ = ["build_aesthetic_request", "evaluate_aesthetics"]
