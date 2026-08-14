from pydantic import BaseModel
from typing import List, Optional

from .narrative import NarrativePlan


class Recommendation(BaseModel):
    rec_id: str
    instruction: str
    severity: str
    location_hint: str
    rationale: str
    before: Optional[str] = None
    after_hint: Optional[str] = None
    
class TitleWinner(BaseModel):
    draft_id: str
    draft_md: str
    best_title: str
    best_title_id: str
    safer_title: str
    safer_title_id: str
    best_cover_copy: str
    why_win: List[str]
    must_fix_if_selected: List[Recommendation]
    optional_improvements: List[Recommendation]
    topic_id: str
    topic: str
    angle_id: str
    angle: str
    target_group: str
    core_pain: str
    narrative_plan: NarrativePlan

