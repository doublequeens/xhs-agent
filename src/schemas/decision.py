from pydantic import BaseModel, field_validator
from typing import List, Optional, Any

class SingleTask(BaseModel):
    task_id: str
    source: str
    instruction: str
    severity: str
    location_hint: str
    rationale: str
    before: Optional[str] = None
    after_hint: Optional[str] = None

class EditorialTasks(BaseModel):
    mandatory: List[SingleTask]
    optional: List[SingleTask]
    
class ContentCandidate(BaseModel):
    draft_id: str
    draft_md: str
    best_title: Optional[str] = None
    best_title_id: Optional[str] = None
    safer_title: Optional[str] = None
    safer_title_id: Optional[str] = None
    best_cover_copy: str
    why_win: Optional[List[str]] = None
    topic_id: str
    topic_name: str
    angle_id: str
    angle_name: str
    target_group: str
    core_pain: str

class RevisionMeta(BaseModel):
    revision_id: str
    round: int
    diff_summary: List[str]
    next_actions: List[str]

class DecisionTrace(BaseModel):
    source_node: str
    why_this_route: List[str]
    
class R1Input(BaseModel):
    content_candidate: ContentCandidate
    editorial_tasks: EditorialTasks
    revision_meta: RevisionMeta
    decision_trace: DecisionTrace

class R2ContentSnapShoot(BaseModel):
    draft_id: str
    revised_title: str
    revised_md: str
    topic_id: str
    topic_name: str
    angle_id: str
    angle_name: str
    target_group: str
    core_pain: str
    best_cover_copy: str

class R2Input(BaseModel):
    content_snapshot: R2ContentSnapShoot
    revision_meta: RevisionMeta
    decision_trace: DecisionTrace

class HashTagInput(BaseModel):
    final_title: str
    final_md: str
    topic_name: str
    angle_name: str
    target_group: str
    core_pain: str
    best_cover_copy: str

class NormalizedInput(BaseModel):
    r1_input: Optional[R1Input] = None
    r2_input: Optional[R2Input] = None
    hashtag_input: Optional[HashTagInput] = None

    @field_validator('r1_input', 'r2_input', 'hashtag_input', mode='before')
    @classmethod
    def empty_dict_to_none(cls, v: Any) -> Optional[Any]:
        """Converts an empty dictionary to None before validation."""
        if v == {}:
            return None
        return v

class DecisionOutput(BaseModel):
    next_node: str
    normalized_input: NormalizedInput