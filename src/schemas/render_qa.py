from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class RenderQAIssue(BaseModel):
    rule_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    message: str
    location_hint: str
    frame_id: Optional[str] = None


class RenderQAResult(BaseModel):
    passed: bool
    issues: list[RenderQAIssue] = Field(default_factory=list)
    metrics_available: bool = False
    metric_kind: Literal["deterministic_proxy"] = "deterministic_proxy"
    metric_note: str = (
        "Deterministic proxy metrics derived from measured layout, token, and asset "
        "facts; they do not replace human aesthetic review."
    )
    editorial_quality: int | None = Field(default=None, ge=0, le=100)
    beauty_category_fit: int | None = Field(default=None, ge=0, le=100)
    visual_hierarchy: int | None = Field(default=None, ge=0, le=100)
    saveability: int | None = Field(default=None, ge=0, le=100)
    cross_page_consistency: int | None = Field(default=None, ge=0, le=100)
    template_stiffness: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Higher means more measured layout reuse across the carousel.",
    )

    @model_validator(mode="after")
    def require_metrics_only_for_passing_editorial_qa(self):
        values = (
            self.editorial_quality,
            self.beauty_category_fit,
            self.visual_hierarchy,
            self.saveability,
            self.cross_page_consistency,
            self.template_stiffness,
        )
        if self.metrics_available:
            if not self.passed or self.issues or any(value is None for value in values):
                raise ValueError("available proxy metrics require a passing QA result")
        elif any(value is not None for value in values):
            raise ValueError("unavailable proxy metrics must not publish values")
        return self
