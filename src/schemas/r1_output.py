from pydantic import BaseModel
from typing import List
from .decision import RevisionMeta

class R1Scores(BaseModel):
    clarity_score: float
    save_value_score: float
    readability_score: float
    authenticity_score: float
    promise_alignment_score: float

class TaskReport(BaseModel):
    completed_task_ids: List[str]
    skipped_task_ids: List[str]
    notes: List[str]

class R1Output(BaseModel):
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
    scores: R1Scores
    revision_meta: RevisionMeta
    task_report: TaskReport
    remaining_risks: List[str]
    editor_notes: List[str]
    should_run_R1_again: bool
