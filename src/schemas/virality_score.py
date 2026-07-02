from pydantic import BaseModel, Field
from typing import List

class ScoreBreakdown(BaseModel):
    click_potential: int
    save_value: int
    comment_potential: int
    execution_barrier: int
    compliance_safety: int
    memory_fit_score: float
    
class ScoreResult(BaseModel):
    total_score: float
    breakdown: ScoreBreakdown
    strengths: List[str]
    weaknesses: List[str]
    optimization_suggestions: List[str]
    absorbed_memory_suggestions: List[str]
    memory_decision: str
    novelty_score: float
    max_similarity: float
    topic_id: str
    topic: str
    angle_id: str
    angle: str
    target_group: str
    core_pain: str
    opening_hook: str
    value_promise: str
    suggested_structure: str