from typing import Literal, Optional

from pydantic import BaseModel, Field


class RenderQAIssue(BaseModel):
    rule_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    message: str
    location_hint: str
    frame_id: Optional[str] = None


class RenderQAResult(BaseModel):
    passed: bool
    issues: list[RenderQAIssue] = Field(default_factory=list)
    metric_kind: Literal["deterministic_proxy"] = "deterministic_proxy"
    metric_note: str = (
        "Deterministic proxy metrics derived from measured layout, token, and asset "
        "facts; they do not replace human aesthetic review."
    )
    editorial_quality: int = Field(default=0, ge=0, le=100)
    beauty_category_fit: int = Field(default=0, ge=0, le=100)
    visual_hierarchy: int = Field(default=0, ge=0, le=100)
    saveability: int = Field(default=0, ge=0, le=100)
    cross_page_consistency: int = Field(default=0, ge=0, le=100)
    template_stiffness: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Higher means more measured adjacent layout repetition.",
    )
