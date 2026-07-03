from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

SourceType = Literal["public_health", "academic", "professional"]


class EvidenceItem(BaseModel):
    claim: str
    summary: str
    source_title: str
    source_url: HttpUrl
    source_type: SourceType


class EvidenceBrief(BaseModel):
    topic_id: str
    items: list[EvidenceItem] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
