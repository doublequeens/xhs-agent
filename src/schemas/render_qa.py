from pydantic import BaseModel, Field


class RenderQAIssue(BaseModel):
    rule_id: str
    message: str
    location_hint: str


class RenderQAResult(BaseModel):
    passed: bool
    issues: list[RenderQAIssue] = Field(default_factory=list)
