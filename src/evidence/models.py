from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_serializer

SourceType = Literal["public_health", "academic", "professional"]
ProvenanceType = Literal["search_snippet"]


class EvidenceItem(BaseModel):
    claim: str
    summary: str
    source_title: str
    source_url: HttpUrl
    source_type: SourceType
    provenance_type: ProvenanceType = "search_snippet"
    verified: bool = False

    @field_serializer("source_url")
    def serialize_source_url(self, value: HttpUrl) -> str:
        return str(value)


class EvidenceBrief(BaseModel):
    topic_id: str
    items: list[EvidenceItem] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
