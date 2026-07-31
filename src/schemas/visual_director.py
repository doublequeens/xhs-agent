from typing import Literal

from pydantic import Field, model_validator

from .content_atoms import ContentAtomSet, ContentFragment
from .visual_style import FamilyStyleProfile, Sha256, StrictModel, TemplateFamily


class PageDirection(StrictModel):
    page_id: str
    sequence: int = Field(ge=1)
    purpose: str = Field(min_length=1)
    visual_job: str = Field(min_length=1)
    fragment_ids: tuple[str, ...] = Field(min_length=1)
    asset_directive_ids: tuple[str, ...] = ()


class AssetDirective(StrictModel):
    directive_id: str
    page_id: str
    role: Literal[
        "evidence_example", "skin_example", "texture", "object", "decorative"
    ]
    required: bool
    preferred_source: Literal["search", "generate", "either", "none"]
    fallback_source: Literal["search", "generate", "none"]
    query_or_prompt: str | None
    negative_constraints: tuple[str, ...] = ()
    orientation: Literal["portrait", "landscape", "square", "any"]
    min_width: int = Field(ge=1)
    min_height: int = Field(ge=1)


class VisualDirectionPlan(StrictModel):
    template_family: TemplateFamily
    page_count: int = Field(ge=5, le=18)
    content_atom_set_sha256: Sha256
    art_direction: str
    palette: tuple[str, ...]
    typography_direction: dict[str, str]
    motifs: tuple[str, ...]
    content_fragments: tuple[ContentFragment, ...]
    page_sequence: tuple[PageDirection, ...]
    asset_directives: tuple[AssetDirective, ...]
    recent_visual_context: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_plan_structure(self):
        if self.page_count != len(self.page_sequence):
            raise ValueError("page count must match page sequence length")

        page_ids = [page.page_id for page in self.page_sequence]
        if len(page_ids) != len(set(page_ids)):
            raise ValueError("page IDs must be unique")
        if [page.sequence for page in self.page_sequence] != list(
            range(1, self.page_count + 1)
        ):
            raise ValueError("page sequences must be contiguous from 1")

        visual_jobs = [page.visual_job.strip() for page in self.page_sequence]
        if any(not page.fragment_ids for page in self.page_sequence):
            raise ValueError("each page must own at least one content fragment")
        if any(not job for job in visual_jobs):
            raise ValueError("page visual jobs must be non-blank")
        if len(visual_jobs) != len(set(visual_jobs)):
            raise ValueError("page visual jobs must be unique")

        fragment_ids = [fragment.fragment_id for fragment in self.content_fragments]
        if len(fragment_ids) != len(set(fragment_ids)):
            raise ValueError("content fragment IDs must be unique")
        owned_fragment_ids = [
            fragment_id
            for page in self.page_sequence
            for fragment_id in page.fragment_ids
        ]
        if len(owned_fragment_ids) != len(set(owned_fragment_ids)):
            raise ValueError("content fragments must be owned by exactly one page")
        if set(owned_fragment_ids) != set(fragment_ids):
            raise ValueError("page fragments must exactly cover direction fragments")

        directives = {directive.directive_id: directive for directive in self.asset_directives}
        if len(directives) != len(self.asset_directives):
            raise ValueError("asset directive IDs must be unique")
        owned_directive_ids = [
            directive_id
            for page in self.page_sequence
            for directive_id in page.asset_directive_ids
        ]
        if len(owned_directive_ids) != len(set(owned_directive_ids)):
            raise ValueError("asset directives must be owned by exactly one page")
        if set(owned_directive_ids) != set(directives):
            raise ValueError("page asset directives must exactly cover plan directives")
        page_by_directive = {
            directive_id: page.page_id
            for page in self.page_sequence
            for directive_id in page.asset_directive_ids
        }
        if any(
            directive.page_id != page_by_directive[directive.directive_id]
            for directive in self.asset_directives
        ):
            raise ValueError("asset directives must bind to their owning page")
        return self

    def validate_against(
        self,
        content_atom_set: ContentAtomSet,
        family_profile: FamilyStyleProfile,
    ) -> None:
        if self.content_atom_set_sha256 != content_atom_set.canonical_sha256:
            raise ValueError("direction content atom set hash does not match source")
        content_atom_set.validate_complete_fragments(self.content_fragments)

        if self.template_family != family_profile.family:
            raise ValueError("direction family does not match family profile")
        if not set(self.palette).issubset(family_profile.palette):
            raise ValueError("palette must be a subset of family profile")
        if not set(self.motifs).issubset(family_profile.allowed_motifs):
            raise ValueError("motifs must be a subset of family profile")
