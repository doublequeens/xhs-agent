from pydantic import Field, model_validator

from .visual_style import Sha256, StrictModel


class DesignIssue(StrictModel):
    rule: str = Field(min_length=1)
    message: str = Field(min_length=1)
    repair_instruction: str = Field(min_length=1)
    page_id: str | None = None
    element_id: str | None = None
    atom_id: str | None = None

    @model_validator(mode="after")
    def require_issue_location(self):
        if self.page_id is None and self.element_id is None and self.atom_id is None:
            raise ValueError("design issue must identify page, element, or atom")
        return self


class DesignPlanQAResult(StrictModel):
    passed: bool
    issues: tuple[DesignIssue, ...] = ()
    design_plan_sha256: Sha256
    content_coverage_attestation: bool
    family_attestation: bool
    asset_binding_attestation: bool

    @model_validator(mode="after")
    def validate_passed_state(self):
        attestations = (
            self.content_coverage_attestation,
            self.family_attestation,
            self.asset_binding_attestation,
        )
        if self.passed and (self.issues or not all(attestations)):
            raise ValueError("passing design QA requires no issues and all attestations")
        if not self.passed and not self.issues:
            raise ValueError("failing design QA requires at least one issue")
        return self
