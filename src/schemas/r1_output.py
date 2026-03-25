from pydantic import BaseModel
from typing import List

class R1Scores(BaseModel):
    clarity_score: float
    save_value_score: float
    readability_score: float
    authenticity_score: float
    promise_alignment_score: float

class RevisionMeta(BaseModel):
    revision_id: str
    round: int
    diff_summary: List[str]
    next_actions: List[str]

class R1Output(BaseModel):
    draft_id: str
    revised_title: str
    revised_md: str
    scores: R1Scores
    revision_meta: RevisionMeta
    fixed_issues: List[str]
    remaining_risks: List[str]
    editor_notes: List[str]
    should_run_R1_again: bool
    topic_id: str
    topic_name: str
    angle_id: str
    angle_name: str
    target_group: str
    core_pain: str