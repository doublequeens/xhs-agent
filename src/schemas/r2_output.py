from pydantic import BaseModel, Field
from typing import List
from .decision import RevisionMeta, R2ContentSnapShoot

class R2ComplianceIssue(BaseModel):
    type: str
    description: str
    severity: str
    evidence_quote: str
    location_hint: str
    
class R2FixTask(BaseModel):
    fix_id: str
    location_hint: str
    instruction: str
    before: str
    after_suggestion: str

class R2ComplianceAudit(BaseModel):
    compliance_status: str
    issues: List[R2ComplianceIssue] = Field(default_factory=list)
    required_fixes: List[R2FixTask] = Field(default_factory=list)
    suggested_fixes: List[R2FixTask] = Field(default_factory=list)
    block_publish: bool = False
    matched_policy_rules: List[str] = Field(default_factory=list)
    unresolved_claims: List[str] = Field(default_factory=list)

class R2Output(BaseModel):
    content_snapshot: R2ContentSnapShoot
    compliance_audit: R2ComplianceAudit
    revision_meta: RevisionMeta
