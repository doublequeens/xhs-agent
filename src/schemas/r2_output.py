from pydantic import BaseModel
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
    issues: List[R2ComplianceIssue]
    required_fixes: List[R2FixTask]
    suggested_fixes: List[R2FixTask]

class R2Output(BaseModel):
    content_snapshot: R2ContentSnapShoot
    compliance_audit: R2ComplianceAudit
    revision_meta: RevisionMeta