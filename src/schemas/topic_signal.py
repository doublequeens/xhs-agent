from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.domain.models import ContentIntent, DomainName


SignalType = Literal[
    "seasonal",
    "calendar",
    "weather",
    "creator_center",
    "historical_pattern",
    "weekday_rhythm",
    "evergreen_context",
]
SignalRiskLevel = Literal["low", "medium", "high"]


class TopicSignal(BaseModel):
    signal_id: str
    source: str
    signal_type: SignalType
    signal_name: str
    normalized_signal: str
    domain: DomainName
    subdomain: str
    why_now: str
    domain_translation: str
    risk_level: SignalRiskLevel
    avoid_topics: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    active_from: date
    expires_at: date
    collected_at: datetime
    source_url: str | None = None
    raw_title: str | None = None
    metadata: dict = Field(default_factory=dict)


class CreativeSeed(BaseModel):
    signal_type: SignalType
    signal_name: str
    why_now: str
    domain_translation: str
    evergreen_pain: str
    timely_framing: str


class CreativeBrief(BaseModel):
    brief_id: str
    signal: TopicSignal
    audience: str
    pain: str
    content_intent: ContentIntent
    contrast_frame: str
    historical_pattern_hint: str | None = None


class TopicGenerationTrace(BaseModel):
    run_id: str
    domain: DomainName
    subdomain: str
    trends_num: int = Field(gt=0)
    signals_used: list[str]
    creative_briefs_sampled: list[str]
    generated_candidates_count: int = Field(ge=0)
    filtered_candidates_count: int = Field(ge=0)
    final_trends: list[str]
    diversity_metrics: dict
    degraded_reason: str | None = None
    created_at: datetime
