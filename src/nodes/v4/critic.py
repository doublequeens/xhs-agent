"""Isolated v4 Q4 visual critic; it cannot weaken Q0--Q3."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.schemas.assets import AssetManifest
from src.schemas.content_atoms import canonical_sha256 as canonical_sha256_v3
from src.schemas.content_lock import ContentLock
from src.schemas.v4.content import ContentAtomSetV4
from src.schemas.v4.critique import CarouselAestheticEvaluationV4
from src.schemas.v4.direction import PageBriefSetV4, VisualDirectionPlanV4
from src.schemas.v4.layout import CarouselDesignPlanV4, FamilyTokensV4
from src.schemas.v4.quality import DesignPlanQAResultV4
from src.schemas.v4.rendering import RenderManifestV4, RenderQAResultV4
from src.schemas.v4.revision import FailureFingerprintV4, NormalizedFailureV4
from src.schemas.v4.semantic import SemanticContentModelV4
from src.visual_ai.aesthetic_evaluator import evaluate_aesthetics
from src.visual_design.v4.render_qa import evaluate_v4_render
from src.visual_design.v4.tokens import get_family_tokens
from src.visual_runtime.artifact_identity import ArtifactIdentity, ArtifactPaths, read_verified_artifact, resolve_artifact_paths


def _value(state: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in state and state[name] is not None:
            return state[name]
    return None


def _identity(state: Mapping[str, Any], key: str) -> str:
    value = state.get(key)
    if type(value) is not str or not value.strip():
        raise ValueError(f"v4 aesthetic critic requires {key}")
    return value


def _checked(value: Any, model: type, name: str):
    from src.schemas.v4.content import canonical_json_v4
    import warnings

    if not isinstance(value, model) and not isinstance(value, Mapping):
        raise ValueError(f"v4 aesthetic critic requires exact {name}")
    try:
        # LangGraph checkpoints rebuild pydantic contracts either as plain
        # mappings (unregistered) or model_construct instances with nested
        # dicts/lists (registered), so identity or python-mode revalidation
        # would spuriously reject serialized state.  Revalidate through the
        # canonical JSON boundary instead — and return the rebuilt instance
        # so downstream attribute access never sees degraded forms.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            payload = value.model_dump(mode="json") if isinstance(value, model) else dict(value)
        return model.model_validate_json(canonical_json_v4(payload).encode("utf-8"))
    except Exception:
        raise ValueError(f"v4 aesthetic critic received invalid {name}") from None


def _q3_sources(state: Mapping[str, Any]) -> dict[str, Any]:
    sources = {
        "render_manifest": _value(state, "render_manifest_v4", "render_manifest"),
        "render_qa_result": _value(state, "render_qa_result_v4", "render_qa_result"),
        "carousel_design_plan": _value(state, "carousel_design_plan_v4", "carousel_design_plan"),
        "design_plan_qa_result": _value(state, "design_plan_qa_result_v4", "design_plan_qa_result"),
        "content_atom_set": _value(state, "content_atom_set", "atom_set"),
        "content_lock": _value(state, "content_lock"),
        "semantic_content_model": _value(state, "semantic_content_model", "semantic_model"),
        "page_brief_set": _value(state, "page_brief_set", "page_briefs"),
        "visual_direction_plan": _value(state, "visual_direction_plan"),
        "asset_manifest": _value(state, "asset_manifest", "assets"),
        "family_tokens": _value(state, "family_tokens"),
        "artifact_paths": _value(state, "artifact_paths", "asset_transaction_paths"),
    }
    expected = {
        "render_manifest": RenderManifestV4, "render_qa_result": RenderQAResultV4,
        "carousel_design_plan": CarouselDesignPlanV4, "design_plan_qa_result": DesignPlanQAResultV4,
        "content_atom_set": ContentAtomSetV4, "content_lock": ContentLock,
        "semantic_content_model": SemanticContentModelV4, "page_brief_set": PageBriefSetV4,
        "visual_direction_plan": VisualDirectionPlanV4, "asset_manifest": AssetManifest,
    }
    for name, model in expected.items():
        sources[name] = _checked(sources[name], model, name)
    paths = sources["artifact_paths"]
    if paths is not None and (
        type(paths) is not ArtifactPaths
        or not isinstance(paths.trusted_base_identity, tuple)
    ):
        # Checkpoints degrade the paths dataclass to a mapping (or rebuild it
        # with tuple fields as lists); rehydrate it through the same strict
        # rebuild the review loader uses.
        from src.review.v4_checkpoint import V4ReviewCheckpointError, _rehydrate_paths

        try:
            paths = _rehydrate_paths(paths)
        except V4ReviewCheckpointError as error:
            raise ValueError("v4 aesthetic critic artifact paths are stale") from error
        sources["artifact_paths"] = paths
    if type(sources["artifact_paths"]) is not ArtifactPaths:
        raise ValueError("v4 aesthetic critic requires exact artifact_paths")
    paths = sources["artifact_paths"]
    manifest = sources["render_manifest"]
    expected_paths = resolve_artifact_paths(paths.base_root, ArtifactIdentity(manifest.run_id, manifest.candidate_id, manifest.revision_id))
    if any(getattr(paths, field) != getattr(expected_paths, field) for field in ("base_root", "identity", "run_root", "candidate_root", "revision_root", "asset_root", "render_root", "review_root", "artifact_root", "trusted_base_identity")):
        raise ValueError("v4 aesthetic critic received aliased artifact paths")
    family = sources["family_tokens"]
    if isinstance(family, str):
        family_hash = get_family_tokens(family).canonical_sha256
    elif type(family) is FamilyTokensV4:
        family.validate_integrity()
        family_hash = family.canonical_sha256
    else:
        raise ValueError("v4 aesthetic critic requires canonical family tokens")
    q3 = sources["render_qa_result"]
    plan = sources["carousel_design_plan"]
    direction = sources["visual_direction_plan"]
    expected_bindings = {
        "render_manifest_sha256": manifest.canonical_sha256,
        "design_plan_sha256": plan.canonical_sha256,
        "design_plan_qa_sha256": sources["design_plan_qa_result"].canonical_sha256,
        "content_atom_set_sha256": sources["content_atom_set"].canonical_sha256,
        "content_lock_sha256": sources["content_lock"].canonical_sha256,
        "semantic_content_model_sha256": sources["semantic_content_model"].canonical_sha256,
        "narrative_sha256": direction.narrative_sha256,
        "page_brief_set_sha256": sources["page_brief_set"].canonical_sha256,
        "visual_direction_plan_sha256": direction.canonical_sha256,
        "asset_manifest_sha256": canonical_sha256_v3(sources["asset_manifest"]),
        "family_tokens_sha256": family_hash,
    }
    if not q3.passed or any(getattr(q3, field) != value for field, value in expected_bindings.items()):
        raise ValueError("v4 aesthetic critic requires a fresh passed Q3 result")
    if manifest.artifact_identity != q3.artifact_identity or manifest.artifact_identity.run_id != plan.run_id or manifest.artifact_identity.candidate_id != plan.candidate_id or manifest.artifact_identity.revision_id != f"revision-{plan.revision}":
        raise ValueError("v4 aesthetic critic received mixed Q3 identity")
    if (manifest.page_ids != tuple(page.page_id for page in sources["page_brief_set"].pages)):
        raise ValueError("v4 aesthetic critic manifest and page briefs differ")
    # Re-evaluate Q3 from the descriptor-safe bytes; a forged/rehashed passed
    # result cannot cross this boundary merely by fixing its outer digest.
    try:
        recomputed = evaluate_v4_render(
            render_manifest=manifest, design_plan=plan, design_plan_qa_result=sources["design_plan_qa_result"],
            content_atom_set=sources["content_atom_set"], content_lock=sources["content_lock"],
            semantic_content_model=sources["semantic_content_model"], page_brief_set=sources["page_brief_set"],
            visual_direction_plan=direction, asset_manifest=sources["asset_manifest"], family_tokens=family,
            artifact_paths=paths,
        )
    except Exception:
        raise ValueError("v4 aesthetic critic could not independently revalidate Q3") from None
    if recomputed != q3 or not recomputed.passed:
        raise ValueError("v4 aesthetic critic rejected stale or forged Q3 evidence")
    return sources


def _model_identity(gateway: Any, state: Mapping[str, Any]) -> tuple[str | None, str | None]:
    # No current v4 durable authoring attestation carries a model identity.
    # State is untrusted workflow input, so it cannot promote independence.
    authoring = None
    configured = getattr(getattr(gateway, "provider_config", None), "model", None)
    evaluator = configured if type(configured) is str else None
    return authoring, evaluator


def _page_duties(direction: VisualDirectionPlanV4, page_set: PageBriefSetV4) -> tuple[str, ...]:
    tasks = {beat.beat_id: beat.task for beat in direction.narrative.beats}
    try:
        return tuple(tasks[page.beat_ref] for page in page_set.pages)
    except KeyError:
        raise ValueError("v4 aesthetic critic page brief beat binding is stale") from None


def aesthetic_critic_node(state: Mapping[str, Any], *, gateway: Any | None = None, policy=None) -> dict[str, Any]:
    """Evaluate only an intact passed Q3 revision, then choose review/revision."""
    if not isinstance(state, Mapping):
        raise ValueError("v4 aesthetic critic requires state mapping")
    sources = _q3_sources(state)
    gateway = gateway if gateway is not None else state.get("visual_llm_gateway")
    run_id, run_mode, candidate_id, revision_id = (_identity(state, key) for key in ("run_id", "run_mode", "candidate_id", "revision_id"))
    if run_mode not in ("production", "shadow"):
        raise ValueError("v4 aesthetic critic run_mode is invalid")
    if (run_id, candidate_id, revision_id) != (sources["render_manifest"].run_id, sources["render_manifest"].candidate_id, sources["render_manifest"].revision_id):
        raise ValueError("v4 aesthetic critic state identity is stale")
    manifest, page_set = sources["render_manifest"], sources["page_brief_set"]
    images = tuple(read_verified_artifact(sources["artifact_paths"].revision_root / page.path, page.sha256, containment_root=sources["artifact_paths"].render_root) for page in manifest.pages)
    author, evaluator = _model_identity(gateway, state)
    critique = evaluate_aesthetics(
        gateway=gateway, run_id=run_id, run_mode=run_mode, candidate_id=candidate_id, revision_id=revision_id,
        parent_revision_id=state.get("parent_revision_id"), page_ids=manifest.page_ids,
        page_roles=tuple(page.narrative_role for page in page_set.pages),
        page_duties=_page_duties(sources["visual_direction_plan"], page_set), image_bytes=images,
        image_mime_types=("image/png",) * len(images), render_manifest_sha256=manifest.canonical_sha256,
        render_qa_result_sha256=sources["render_qa_result"].canonical_sha256,
        page_brief_set_sha256=page_set.canonical_sha256,
        semantic_content_model_sha256=sources["semantic_content_model"].canonical_sha256,
        authoring_model_identity=author, evaluator_model_identity=evaluator, policy=policy,
    )
    if critique.passed:
        route, failures = "human_review", ()
    else:
        issue_pages = tuple(
            page_id for page in critique.pages for issue in page.issues
            if issue.severity == "critical" for page_id in issue.page_ids
        ) or tuple(
            page.page_id for page in critique.pages
            if sum(getattr(page, dimension) < 70 for dimension in (
                "hierarchy", "readability", "composition", "whitespace", "visual_focus", "asset_integration"
            )) >= 2
        ) or tuple(page_id for issue in critique.set_evaluation.issues for page_id in issue.page_ids)
        if critique.set_evaluation.rhythm < 70 or critique.set_evaluation.repetition < 70:
            issue_pages += tuple(page.page_id for page in critique.pages)
        selected = set(issue_pages)
        failures = tuple(
            NormalizedFailureV4.from_fingerprint(FailureFingerprintV4.create(
                node="V4_VISUAL_CRITIC", page_id=page_id, failure_code="AESTHETIC_REVIEW_FAILED", geometry_region=None,
            ))
            for page_id in manifest.page_ids if page_id in selected
        )
        route = "revision"
    return {"visual_critique_v4": critique, "visual_critique": critique, "normalized_failures_v4": failures, "route": route, "visual_route": route, "critic_route": route, "current_node": "V4_VISUAL_CRITIC"}


def route_after_aesthetic_critic(state: Mapping[str, Any]) -> str:
    critique = _value(state, "visual_critique_v4", "visual_critique") if isinstance(state, Mapping) else None
    if type(critique) is not CarouselAestheticEvaluationV4:
        raise ValueError("v4 aesthetic route requires exact critique")
    critique.validate_integrity()
    sources = _q3_sources(state)
    expected = {
        "render_manifest_sha256": sources["render_manifest"].canonical_sha256,
        "render_qa_result_sha256": sources["render_qa_result"].canonical_sha256,
        "page_brief_set_sha256": sources["page_brief_set"].canonical_sha256,
        "semantic_content_model_sha256": sources["semantic_content_model"].canonical_sha256,
    }
    if any(getattr(critique, key) != value for key, value in expected.items()):
        raise ValueError("v4 aesthetic route critique source bindings are stale")
    return "human_review" if critique.passed else "revision"


v4_aesthetic_critic_node = aesthetic_critic_node
__all__ = ["aesthetic_critic_node", "v4_aesthetic_critic_node", "route_after_aesthetic_critic"]
