from datetime import date, datetime
from typing import TypedDict, List, Optional

from memory.memory_manager import XHSMemoryManager
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
from .visual_director import ImageScriptList
from .image_sourcing import ImageCandidates
from .image_qa import FinalImages
from .topic_signal import CreativeBrief, TopicGenerationTrace, TopicSignal

class AgentState(TypedDict):
    trends_num: int
    interactive: Optional[bool]
    domain: Optional[DomainName]
    subdomain: Optional[str]
    focus_keyword: Optional[str]
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
    current_node: Optional[str]
    decision_output: DecisionOutput
    r1_output: R1Output
    r2_output: R2Output
    final_content: HashTagInput
    hashtags: HashTagOutput
    image_scripts: ImageScriptList
    image_candidates: ImageCandidates
    final_images: FinalImages
    publish_package: dict
    review_status: Optional[str]
    review_feedback: Optional[str]
    review_round: Optional[int]
    review_route: Optional[str]
    pending_human_publish_patch: Optional[dict]
    pending_human_replace_storyboards: Optional[bool]
    data_writed: Optional[bool]
    # Test-injection hooks only: nodes fall back to real now()/today() when
    # these are absent. Never set in production initial_state.
    _now_for_test: Optional[datetime]
    _today_for_test: Optional[date]
