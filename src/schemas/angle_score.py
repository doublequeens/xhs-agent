from pydantic import BaseModel, Field
from typing import List

class ScoreBreakdown(BaseModel):
    click_potential: int
    save_value: int
    comment_potential: int
    execution_barrier: int
    compliance_risk: int
    
class ScoreResult(BaseModel):
    total_score: int
    breakdown: ScoreBreakdown
    strengths: List[str]
    weaknesses: List[str]
    optimization_suggestions: List[str]
    topic_id: str
    topic: str
    target_group: str
    core_pain: str
    angle_id: str
    angle_name: str
    opening_hook: str
    value_promise: str
    suggested_structure: str