"""The v4 workflow state schema.

An independent TypedDict (never a subclass of the v3 ``AgentState``): the v4
visual chain stores different contract types under some of the same channel
names (``content_atom_set`` is the v4 atom model here), and LangGraph drops
any key absent from the schema from a node's return patch — so every channel
any v4 node may write MUST be declared below.  The shared content chain's
channels are declared with the same names and types the v3 schema uses.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Literal, NotRequired, Optional, TypedDict

from src.creator_profile import CreatorProfile
from src.domain import ContentPolicy, DomainContext, DomainName
from src.evidence.models import EvidenceBrief
from src.schemas.agent_state import (
    AngleStrategy,
    CreativeBrief,
    DecisionOutput,
    DraftItem,
    DraftTitles,
    EvidenceBrief as _EvidenceBrief,  # noqa: F401 - re-export guard
    HashTagInput,
    HashTagOutput,
    NarrativePlan,
    NoveltyCheckResults,
    OutlineItem,
    R1Output,
    R2Output,
    ScoreResult,
    TitleWinner,
    TopicGenerationTrace,
    TopicItem,
    TopicSignal,
)
from src.schemas.assets import AssetManifest, AssetResolutionResult
from src.schemas.content_lock import ContentLock
from src.schemas.v4.content import ContentAtomSetV4
from src.schemas.v4.critique import CarouselAestheticEvaluationV4
from src.schemas.v4.direction import (
    CarouselNarrativeV4,
    PageBriefSetV4,
    VisualDirectionPlanV4,
)
from src.schemas.v4.layout import CarouselDesignPlanV4, FamilyTokensV4
from src.schemas.v4.publishing import (
    FinalPolicyAttestationV4,
    ShadowManifestV4,
)
from src.schemas.v4.quality import DesignPlanQAResultV4
from src.schemas.v4.rendering import RenderManifestV4, RenderQAResultV4
from src.schemas.v4.revision import (
    NormalizedFailureV4,
    RevisionEventV4,
    RevisionRequestV4,
)
from src.schemas.v4.review import (
    HumanReviewDecisionReferenceV4,
    HumanReviewDecisionV4,
    HumanReviewRouteContextV4,
    HumanReviewRouteEvidenceV4,
    ReviewWorkspaceReferenceV4,
)
from src.schemas.v4.semantic import SemanticContentModelV4
from src.visual_runtime.artifact_identity import ArtifactPaths


class AgentStateV4(TypedDict, total=False):
    # --- shared content chain (identical channel names/types as v3) ---
    trends_num: int
    interactive: Optional[bool]
    creator_profile: Optional[CreatorProfile]
    domain: Optional[DomainName]
    subdomain: Optional[str]
    focus_keyword: Optional[str]
    focus_keyword_cli_present: bool
    domain_context: Optional[DomainContext]
    content_policy: Optional[ContentPolicy]
    memory_context: Optional[dict]
    evidence_briefs: dict[str, EvidenceBrief]
    topic_signals: List[TopicSignal]
    creative_briefs: List[CreativeBrief]
    topic_generation_trace: Optional[TopicGenerationTrace]
    topic_candidates: List[TopicItem]
    topic_generation_degraded_reason: Optional[str]
    final_policy_issues: list[dict]
    trends: List[TopicItem]
    angles: List[AngleStrategy]
    novelty_check_results: NoveltyCheckResults
    scores: List[ScoreResult]
    outlines: List[OutlineItem]
    drafts: List[DraftItem]
    title_options: List[DraftTitles]
    title_winner: TitleWinner
    selected_narrative_plan: Optional[NarrativePlan]
    current_node: Optional[str]
    decision_output: DecisionOutput
    r1_output: R1Output
    r2_output: R2Output
    final_content: HashTagInput
    hashtags: HashTagOutput
    run_output_dir: Optional[str]
    publish_package: dict
    pending_human_publish_patch: Optional[dict]
    data_writed: Optional[bool]
    _now_for_test: Optional[datetime]
    _today_for_test: Optional[date]

    # --- v4 orchestration identity (set at run start, never switched) ---
    run_id: str
    run_mode: Literal["production", "shadow"]
    source_run_id: Optional[str]
    candidate_id: str
    revision_id: str
    parent_revision_id: Optional[str]
    revision: int
    artifact_paths: Optional[ArtifactPaths]
    artifact_paths_v4: Optional[ArtifactPaths]

    # --- v4 content boundary ---
    visible_copy_projection: Optional[Any]
    visible_copy_projection_v4: Optional[Any]
    content_atom_set: Optional[ContentAtomSetV4]
    content_atom_set_v4: Optional[ContentAtomSetV4]
    atom_set: Optional[ContentAtomSetV4]
    content_atomization_route: Literal["content_lock_builder", "r2_compliance"]
    content_atomization_issues: list[str]
    content_lock: Optional[ContentLock]
    content_lock_v4: Optional[ContentLock]

    # --- v4 semantic boundary (Q0) ---
    semantic_content_model: Optional[SemanticContentModelV4]
    semantic_content_model_v4: Optional[SemanticContentModelV4]
    semantic_model: Optional[SemanticContentModelV4]
    semantic_qa_result: Optional[Any]
    semantic_qa: Optional[Any]
    semantic_route: Optional[str]

    # --- v4 authoring boundary (Q1) ---
    narrative: Optional[CarouselNarrativeV4]
    carousel_narrative: Optional[CarouselNarrativeV4]
    carousel_narrative_v4: Optional[CarouselNarrativeV4]
    page_brief_set: Optional[PageBriefSetV4]
    page_brief_set_v4: Optional[PageBriefSetV4]
    page_briefs: Optional[PageBriefSetV4]
    visual_direction_plan: Optional[VisualDirectionPlanV4]
    authoring_qa_result: Optional[Any]
    authoring_qa: Optional[Any]
    authoring_route: Optional[str]

    # --- v4 asset boundary ---
    asset_manifest: Optional[AssetManifest]
    asset_manifest_v4: Optional[AssetManifest]
    assets: Optional[AssetManifest]
    asset_resolution_result: Optional[AssetResolutionResult]
    asset_resolution_result_v4: Optional[AssetResolutionResult]
    asset_transaction_evidence: Optional[Any]
    unresolved_optional_assets: Optional[list[dict]]
    asset_resolver_route: Optional[str]

    # --- v4 composition/layout/design (Q2) ---
    layout_programs: Optional[tuple]
    family_tokens: Optional[FamilyTokensV4]
    carousel_design_plan: Optional[CarouselDesignPlanV4]
    carousel_design_plan_v4: Optional[CarouselDesignPlanV4]
    design_plan_qa_result: Optional[DesignPlanQAResultV4]
    design_plan_qa_result_v4: Optional[DesignPlanQAResultV4]
    design_metrics_qa_result: Optional[DesignPlanQAResultV4]
    asset_transaction_paths: Optional[ArtifactPaths]

    # --- v4 render boundary (Q3) ---
    render_manifest: Optional[RenderManifestV4]
    render_manifest_v4: Optional[RenderManifestV4]
    render_route: Optional[str]
    render_qa_result: Optional[RenderQAResultV4]
    render_qa_result_v4: Optional[RenderQAResultV4]

    # --- v4 critic boundary (Q4) ---
    visual_critique: Optional[CarouselAestheticEvaluationV4]
    visual_critique_v4: Optional[CarouselAestheticEvaluationV4]
    critic_route: Optional[str]

    # --- v4 typed revision boundary ---
    normalized_failures_v4: Optional[tuple[NormalizedFailureV4, ...]]
    revision_request_v4: Optional[RevisionRequestV4]
    revision_request: Optional[Any]
    revision_history_v4: Optional[tuple[RevisionEventV4, ...]]
    revision_invalidation_v4: Optional[Any]
    prior_revision_id: Optional[str]
    revision_route: Optional[str]

    # --- v4 human review boundary ---
    review_workspace: Optional[Any]
    review_workspace_v4: Optional[Any]
    review_workspace_reference: Optional[ReviewWorkspaceReferenceV4]
    review_workspace_reference_v4: Optional[ReviewWorkspaceReferenceV4]
    previous_review_workspace_v4: Optional[Any]
    human_review_decision: Optional[HumanReviewDecisionV4]
    human_review_decision_v4: Optional[HumanReviewDecisionV4]
    human_review_decision_reference: Optional[HumanReviewDecisionReferenceV4]
    human_review_decision_reference_v4: Optional[HumanReviewDecisionReferenceV4]
    human_review_route_context_v4: Optional[HumanReviewRouteContextV4]
    human_review_route_evidence_v4: Optional[HumanReviewRouteEvidenceV4]
    human_review_history_v4: Optional[HumanReviewDecisionReferenceV4]
    human_review_terminal_decision_v4: Optional[HumanReviewDecisionV4]
    human_review_terminal_reference_v4: Optional[HumanReviewDecisionReferenceV4]
    human_review_revision_request_v4: Optional[RevisionRequestV4]
    review_status: Optional[str]
    review_feedback: Optional[str]
    review_round: Optional[int]
    review_route: Optional[str]
    visual_aesthetic_override: Optional[bool]
    r2_input_v4: Optional[dict]

    # --- v4 final guard and terminal writers ---
    final_policy_attestation: Optional[dict]
    final_policy_attestation_v4: Optional[FinalPolicyAttestationV4]
    final_policy_guard_passed_v4: Optional[bool]
    shadow_bundle_path: Optional[str]
    shadow_manifest_v4: Optional[ShadowManifestV4]

    # --- routing channels consumed by conditional edges ---
    route: Optional[str]
    visual_route: Optional[str]


__all__ = ["AgentStateV4"]
