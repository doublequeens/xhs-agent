from datetime import date, datetime
from typing import Any, TypedDict, List, NotRequired, Optional, Literal

from memory.memory_manager import XHSMemoryManager
from src.creator_profile import CreatorProfile
from src.domain import ContentPolicy, DomainContext, DomainName
from src.evidence.models import EvidenceBrief
from .topic import TopicItem
from .angle import AngleStrategy
from .novelty_guard import NoveltyCheckResults
from .virality_score import ScoreResult
from .outline import OutlineItem
from .draft import DraftItem
from .title import DraftTitles
from .r1_output import R1Output
from .r2_output import R2Output
from .title_ranker import TitleWinner
from .decision import DecisionOutput, HashTagInput
from .hashtag import HashTagOutput
from .render_qa import RenderQAResult
from .topic_signal import CreativeBrief, TopicGenerationTrace, TopicSignal
from .assets import AssetManifest
from .render_manifest import RenderManifest
from .content_atoms import ContentAtomSet
from .scene_graph import CarouselDesignPlan
from .design_qa import DesignPlanQAResult
from .visual_critique import VisualCritique
from .visual_director import VisualDirectionPlan
from .narrative import NarrativePlan

class AgentState(TypedDict):
    trends_num: int
    interactive: Optional[bool]
    creator_profile: NotRequired[Optional[CreatorProfile]]
    domain: Optional[DomainName]
    subdomain: Optional[str]
    focus_keyword: Optional[str]
    focus_keyword_cli_present: NotRequired[bool]
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
    selected_narrative_plan: NotRequired[Optional[NarrativePlan]]
    current_node: Optional[str]
    decision_output: DecisionOutput
    r1_output: R1Output
    r2_output: R2Output
    final_content: HashTagInput
    hashtags: HashTagOutput
    # --- llm_scene_v3 dynamic visual production state ---
    content_atom_set: NotRequired[Optional[ContentAtomSet]]
    content_atomization_route: NotRequired[Literal["visual_director", "r2_compliance"]]
    content_atomization_issues: NotRequired[list[str]]
    visual_direction_plan: NotRequired[Optional[VisualDirectionPlan]]
    asset_manifest: NotRequired[Optional[AssetManifest]]
    carousel_design_plan: NotRequired[Optional[CarouselDesignPlan]]
    design_plan_qa_result: NotRequired[Optional[DesignPlanQAResult]]
    render_manifest: NotRequired[Optional[RenderManifest]]
    render_qa_result: NotRequired[Optional[RenderQAResult]]
    visual_critique: NotRequired[Optional[VisualCritique]]
    design_revision_round: NotRequired[int]
    visual_revision_round: NotRequired[int]
    unresolved_optional_assets: NotRequired[list[dict]]
    # Transient route-override channel consumed by conditional edges after
    # design_reviser / visual_critic. Nodes always set this (None clears any
    # stale override) so the graph never misroutes on a leftover value.
    visual_route_override: NotRequired[Optional[str]]
    # Per-run directory where the generic scene renderer writes carousel PNGs.
    run_output_dir: NotRequired[Optional[str]]
    publish_package: dict
    review_status: Optional[str]
    review_feedback: Optional[str]
    review_round: Optional[int]
    review_route: Optional[str]
    legacy_editorial_checkpoint: NotRequired[bool]
    editorial_workflow_version: NotRequired[str]
    pending_human_publish_patch: Optional[dict]
    data_writed: Optional[bool]
    # Test-injection hooks only: nodes fall back to real now()/today() when
    # these are absent. Never set in production initial_state.
    _now_for_test: Optional[datetime]
    _today_for_test: Optional[date]
