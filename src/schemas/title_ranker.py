from pydantic import BaseModel
from typing import List

class TitleScore(BaseModel):
    click_score: float
    save_score: float
    readability_score: float
    authenticity_score: float
    compliance_score: float
    promise_alignment_score: float

class TitleRankItem(BaseModel):
    draft_id: str
    title_id: str
    total_score: float
    scores: TitleScore
    strategy_tags: List[str]
    reason: str
    best_title_for_this_draft: str
    best_cover_copy_for_this_draft: str
    title_risk_notes: List[str]
    must_fix_if_selected: List[str]

class Recommendation(BaseModel):
    rec_id: str
    instruction: str
    severity: str
    location_hint: str
    rationale: str
    
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
    topic_name: str
    angle_id: str
    angle_name: str
    target_group: str
    core_pain: str

class TitleRankResult(BaseModel):
    ranking: List[TitleRankItem]
    winner: TitleWinner

class R1Input(BaseModel):
    winner: TitleWinner
    winner_scores: TitleScore