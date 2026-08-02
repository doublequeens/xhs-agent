from typing import Literal

from pydantic import Field, model_validator

from .visual_style import Sha256, StrictModel


Score = int
ImageRelevanceScore = int | Literal["not_applicable"]


class VisualCritiqueIssue(StrictModel):
    rule: str = Field(min_length=1)
    message: str = Field(min_length=1)
    revision_instruction: str = Field(min_length=1)
    page_id: str | None = None
    element_id: str | None = None

    @model_validator(mode="after")
    def require_issue_location(self):
        if self.page_id is None and self.element_id is None:
            raise ValueError("visual critique issue must identify page or element")
        return self


class VisualCritique(StrictModel):
    content_atom_set_sha256: Sha256
    direction_plan_sha256: Sha256
    design_plan_sha256: Sha256
    render_manifest_sha256: Sha256
    passed: bool
    revision_round: int = Field(ge=0, le=2)
    contains_images: bool
    overall: Score = Field(ge=0, le=100)
    hierarchy: Score = Field(ge=0, le=100)
    legibility: Score = Field(ge=0, le=100)
    composition: Score = Field(ge=0, le=100)
    family_consistency: Score = Field(ge=0, le=100)
    page_variation: Score = Field(ge=0, le=100)
    page_rhythm: Score = Field(ge=0, le=100)
    color: Score = Field(ge=0, le=100)
    spacing: Score = Field(ge=0, le=100)
    image_relevance: ImageRelevanceScore
    issues: tuple[VisualCritiqueIssue, ...] = ()
    revision_instructions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_image_relevance(self):
        if not self.contains_images and self.image_relevance != "not_applicable":
            raise ValueError(
                "text-only critique must mark image relevance not_applicable"
            )
        if self.contains_images and self.image_relevance == "not_applicable":
            raise ValueError("critique with images requires an image relevance score")
        return self

    @model_validator(mode="after")
    def validate_passed_state(self):
        thresholds_met = (
            self.overall >= 80
            and self.hierarchy >= 70
            and self.family_consistency >= 75
            and self.page_rhythm >= 70
            and (
                self.image_relevance == "not_applicable"
                or self.image_relevance >= 70
            )
        )
        if self.passed and (not thresholds_met or self.issues):
            raise ValueError("passing visual critique must meet thresholds without issues")
        if not self.passed and not self.revision_instructions:
            raise ValueError("failing visual critique requires revision instructions")
        return self
