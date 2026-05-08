import string

from pydantic import BaseModel, Field
from typing import List

class MatchedHistoryItem(BaseModel):
    content_id: str
    topic: str
    angle: str
    title: str
    similarity: float 
    created_at: str  = None
    published_at: str  = None
    performance_level: str
    why_similar: str  = None

class MemorySignalResult(BaseModel):
    decision: str
    novelty_score: float
    max_similarity: float
    rejected_by_memory: bool
    similar_to_recent_content: bool
    similar_to_high_performing_pattern: bool
    similar_to_low_performing_pattern: bool
    recommended_for_virality_scorer: bool

class NoveltyCheckResult(BaseModel):
    topic_id: str
    topic: str
    target_group: str
    core_pain: str

    angle_id: str
    angle: str
    opening_hook: str
    value_promise: str
    suggested_structure: str

    decision: str
    novelty_score: float
    max_similarity: float
    matched_history: List[MatchedHistoryItem] = Field(min_length=0, max_length=3, description="与当前内容在向量空间中最相似的历史内容列表，只保留最多前 3 条")
    reason: str
    revision_suggestions: List[str]
    memory_signal: MemorySignalResult

class NoveltyCheckResults(BaseModel):
    novelty_results: List[NoveltyCheckResult]


class NoveltyMatches(BaseModel):
    topic_id: str
    angle_id: str
    matches: List[MatchedHistoryItem]