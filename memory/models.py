from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ContentRecord:
    content_id: str
    topic: str
    created_at: str

    status: str = "generated"
    platform: str = "xiaohongshu"

    reviewed_at: Optional[str] = None
    published_at: Optional[str] = None

    post_id: Optional[str] = None
    url: Optional[str] = None

    topic_id: Optional[str] = None
    angle_id: Optional[str] = None
    angle: Optional[str] = None
    domain: Optional[str] = None
    subdomain: Optional[str] = None
    content_intent: Optional[str] = None
    profile_version: Optional[str] = None
    risk_level: Optional[str] = None

    target_group: Optional[str] = None
    core_pain: Optional[str] = None

    title: Optional[str] = None
    cover_copy: Optional[str] = None

    content: Optional[str] = None
    hashtags: list[str] = field(default_factory=list)

    content_format: Optional[str] = None
    visual_style: Optional[str] = None
    card_count: Optional[int] = None
    storyboards: list[str] = field(default_factory=list)

    image_paths: list[str] = field(default_factory=list)

    strategy_tags: list[str] = field(default_factory=list)
    compliance_status: Optional[str] = None

    embedding_text: Optional[str] = None

    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricsRecord:
    content_id: str

    views: int = 0
    likes: int = 0
    saves: int = 0
    comments: int = 0
    shares: int = 0
    followers_gained: int = 0

    like_rate: float = 0
    save_rate: float = 0
    comment_rate: float = 0
    share_rate: float = 0
    engagement_rate: float = 0

    performance_level: str = "unknown"
    updated_at: Optional[str] = None


@dataclass
class MemoryContext:
    recent_contents: list[dict[str, Any]]
    recent_topics_to_avoid: list[str]
    recent_angles_to_avoid: list[str]
    high_performing_patterns: list[dict[str, Any]]
    low_performing_patterns: list[dict[str, Any]]
    recent_hashtags: list[str]
