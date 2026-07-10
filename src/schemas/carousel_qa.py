from typing import Optional

from pydantic import BaseModel, Field


class CarouselQAIssue(BaseModel):
    rule_id: str
    message: str
    location_hint: str
    frame_id: Optional[str] = None
    before: Optional[str] = None
    after_hint: Optional[str] = None


class CarouselQAResult(BaseModel):
    passed: bool
    issues: list[CarouselQAIssue] = Field(default_factory=list)
