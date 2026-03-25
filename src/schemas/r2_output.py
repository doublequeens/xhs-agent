from pydantic import BaseModel
from typing import List
from .r1_output import RevisionMeta

class R2ContentSnapShoot(BaseModel):
    draft_id: str
    title: str
    md: str
    topic_id: str
    topic_name: str
    angle_id: str
    angle_name: str
    target_group: str
    core_pain: str

class R2ComplianceIssue(BaseModel):
    type: str
    description: str
    severity: str
    evidence_quote: str
    location_hint: str

class R2RequiredFix(BaseModel):
    fix_id: str
    severity: str
    location_hint: str
    instruction: str
    before: str
    after_suggestion: str

class R2SuggestedFix(BaseModel):
    fix_id: str
    location_hint: str
    instruction: str
    before: str
    after_suggestion: str

class R2ComplianceAudit(BaseModel):
    compliance_status: str
    issues: List[R2ComplianceIssue]
    required_fixes: List[R2RequiredFix]
    suggested_fixes: List[R2SuggestedFix]
    notes_for_editor: List[str]

class R2Decision(BaseModel):
    should_block_publish: bool
    should_send_back_to_R1: bool
    recommended_next_node: str
    decision_reason: List[str]
    
class R2Output(BaseModel):
    content_snapshot: R2ContentSnapShoot
    compliance_audit: R2ComplianceAudit
    revision_meta: RevisionMeta